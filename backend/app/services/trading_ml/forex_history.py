"""Leakage-safe external Forex history ingestion and bounded knowledge lookup."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import fmean
from typing import Iterable

import polars as pl

from app.services.forex_contracts import pair_config

from .contracts import TradingMLExample


KAGGLE_FOREX_SOURCE_ID = (
    "kaggle:jeleeladekunlefijabi:"
    "forex-trading-dataset-with-ema-rsi-and-atr"
)
KAGGLE_FOREX_SOURCE_URL = (
    "https://www.kaggle.com/datasets/jeleeladekunlefijabi/"
    "forex-trading-dataset-with-ema-rsi-and-atr"
)
FOREX_HISTORY_TRANSFORM_VERSION = "blum-forex-daily-quality-v2"


def bundled_forex_history_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "data"
        / "forex"
        / "Forex_sample_dataset.csv"
    )


@dataclass(frozen=True)
class ForexHistoricalBundle:
    examples: tuple[TradingMLExample, ...]
    knowledge: dict
    provenance: dict


@dataclass(frozen=True)
class ForexHistoricalAdvice:
    status: str
    confidence_adjustment: float
    sample_size: int
    hit_rate: float | None
    mean_net_r: float | None
    pattern: str | None
    source_sha256: str | None
    correlated_pairs: tuple[dict[str, float | str], ...]
    explanation: tuple[str, ...]


@dataclass(frozen=True)
class _Bar:
    timestamp: datetime
    pair: str
    opened: float
    high: float
    low: float
    close: float


class ForexHistoricalDatasetService:
    """Convert licensed daily OHLC into causal, cost-adjusted research examples."""

    def __init__(
        self,
        *,
        source_path: str | Path,
        source_url: str,
        license_name: str,
        source_version: str,
        horizon_bars: int = 1,
        minimum_warmup_bars: int = 50,
        sample_weight: float = 0.25,
        max_rows: int = 250_000,
    ) -> None:
        if horizon_bars < 1:
            raise ValueError("horizon_bars must be positive")
        if minimum_warmup_bars < 50:
            raise ValueError("minimum_warmup_bars must preserve EMA50 warmup")
        if not 0 < sample_weight <= 0.5:
            raise ValueError("external research sample_weight must be in (0, 0.5]")
        self.source_path = Path(source_path)
        self.source_url = source_url
        self.license_name = license_name
        self.source_version = source_version
        self.horizon_bars = horizon_bars
        self.minimum_warmup_bars = minimum_warmup_bars
        self.sample_weight = sample_weight
        self.max_rows = max_rows

    def prepare(self) -> ForexHistoricalBundle:
        source_bytes = self.source_path.read_bytes()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        frame = pl.read_csv(
            self.source_path,
            n_rows=self.max_rows,
            columns=["Timestamp", "Pair", "Rate", "High", "Low", "Close"],
        )
        bars_by_pair, quality = self._bars(frame)
        examples = self._examples(bars_by_pair, source_sha256)
        provenance = {
            "source_id": (
                f"{KAGGLE_FOREX_SOURCE_ID}:dataset-v{self.source_version}:"
                f"{FOREX_HISTORY_TRANSFORM_VERSION}"
            ),
            "source_url": self.source_url,
            "source_version": self.source_version,
            "license": self.license_name,
            "source_sha256": source_sha256,
            "rows_read": frame.height,
            "daily_bars_created": sum(len(rows) for rows in bars_by_pair.values()),
            **quality,
            "examples_created": len(examples),
            "pairs": sorted(bars_by_pair),
            "timeframe": "1d",
            "horizon_bars": self.horizon_bars,
            "sample_weight": self.sample_weight,
            "indicator_policy": "recomputed_from_ohlc_trailing_only",
            "label_policy": "next_bar_open_to_horizon_close_after_decision",
            "gap_policy": "No example spans a gap over four calendar days in its EMA50 window or label path.",
            "transformation_version": FOREX_HISTORY_TRANSFORM_VERSION,
            "evidence_lane": "external_historical_replay",
            "paper_authority": False,
        }
        return ForexHistoricalBundle(
            examples=examples,
            knowledge=_build_knowledge(examples, provenance),
            provenance=provenance,
        )

    @staticmethod
    def write_knowledge(bundle: ForexHistoricalBundle, target: str | Path) -> None:
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        payload = {
            "format": "blum_forex_historical_knowledge_v1",
            "created_at": datetime.now(UTC).isoformat(),
            "provenance": bundle.provenance,
            **bundle.knowledge,
        }
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, destination)

    @staticmethod
    def _bars(
        frame: pl.DataFrame,
    ) -> tuple[dict[str, tuple[_Bar, ...]], dict]:
        required = {"Timestamp", "Pair", "Rate", "High", "Low", "Close"}
        if not required.issubset(frame.columns):
            missing = sorted(required.difference(frame.columns))
            raise ValueError(f"Forex history is missing required columns: {missing}")
        bars: dict[tuple[str, datetime], _Bar] = {}
        counts: dict[tuple[str, datetime], int] = defaultdict(int)
        conflicts: set[tuple[str, datetime]] = set()
        duplicate_rows = 0
        for row in frame.iter_rows(named=True):
            pair = _canonical_pair(str(row["Pair"]))
            stamp = _parse_timestamp(str(row["Timestamp"]))
            key = (pair, stamp)
            counts[key] += 1
            values = tuple(float(row[name]) for name in ("Rate", "High", "Low", "Close"))
            if not all(math.isfinite(value) and value > 0 for value in values):
                raise ValueError(f"invalid OHLC row: {pair} {stamp.isoformat()}")
            opened, high, low, close = values
            if high < max(opened, close) or low > min(opened, close):
                raise ValueError(f"inconsistent OHLC row: {pair} {stamp.isoformat()}")
            previous = bars.get(key)
            if previous is None:
                bars[key] = _Bar(stamp, pair, opened, high, low, close)
            else:
                duplicate_rows += 1
                if values != (previous.opened, previous.high, previous.low, previous.close):
                    conflicts.add(key)
        buckets: dict[str, list[_Bar]] = defaultdict(list)
        weekend_rows = 0
        for key, bar in bars.items():
            if key in conflicts:
                continue
            if bar.timestamp.weekday() >= 5:
                weekend_rows += counts[key]
                continue
            buckets[bar.pair].append(bar)
        accepted = {
            pair: tuple(sorted(rows, key=lambda item: item.timestamp))
            for pair, rows in buckets.items()
        }
        return accepted, {
            "duplicate_rows_observed": duplicate_rows,
            "conflicting_groups_quarantined": len(conflicts),
            "conflicting_rows_quarantined": sum(counts[key] for key in conflicts),
            "weekend_rows_quarantined": weekend_rows,
            "accepted_keys": [{"pair": bar.pair, "date": bar.timestamp.date().isoformat()}
                              for rows in accepted.values() for bar in rows][:1000],
            "accepted_keys_truncated": sum(map(len, accepted.values())) > 1000,
            "duplicate_policy": "Identical OHLC deduplicated; every conflicting group quarantined, never aggregated.",
        }

    def _examples(
        self,
        bars_by_pair: dict[str, tuple[_Bar, ...]],
        source_sha256: str,
    ) -> tuple[TradingMLExample, ...]:
        result: list[TradingMLExample] = []
        future_returns = _future_returns(bars_by_pair, self.horizon_bars)
        for pair, bars in sorted(bars_by_pair.items()):
            indicators = _causal_indicators(bars)
            config = pair_config(pair)
            for index in range(
                self.minimum_warmup_bars,
                len(bars) - self.horizon_bars,
            ):
                current = bars[index]
                entry_bar = bars[index + 1]
                outcome_bar = bars[index + self.horizon_bars]
                window = bars[index - self.minimum_warmup_bars:index + self.horizon_bars + 1]
                if any(right.timestamp - left.timestamp > timedelta(days=4)
                       for left, right in zip(window, window[1:])):
                    continue
                state = indicators[index]
                setup_type, direction = _decision_rule(state)
                side = 1.0 if direction == "LONG" else -1.0
                risk_distance = max(state["atr"] * 1.5, config.pip_size * 5.0)
                round_trip_cost = config.pip_size * _round_trip_cost_pips(pair)
                gross_return = side * (outcome_bar.close - entry_bar.opened)
                realized_net_r = (gross_return - round_trip_cost) / risk_distance
                pair_return = side * (
                    outcome_bar.close / entry_bar.opened - 1.0
                )
                benchmark = future_returns.get(outcome_bar.timestamp, ())
                benchmark_return = fmean(benchmark) if benchmark else 0.0
                features = _feature_payload(
                    pair=pair,
                    setup_type=setup_type,
                    direction=direction,
                    state=state,
                    risk_distance=risk_distance,
                    cost=round_trip_cost,
                )
                result.append(
                    TradingMLExample(
                        source_object_type="external_forex_history",
                        source_object_id=(
                            f"{self.source_version}:{FOREX_HISTORY_TRANSFORM_VERSION}:{pair}:"
                            f"{current.timestamp.date().isoformat()}:h{self.horizon_bars}"
                        ),
                        market_family="forex",
                        evidence_lane="external_historical_replay",
                        decision_timestamp=current.timestamp,
                        outcome_timestamp=outcome_bar.timestamp,
                        asset_key=pair,
                        setup_type=setup_type,
                        regime=str(state["regime"]),
                        features=features,
                        realized_net_r=float(realized_net_r),
                        label_positive_r=int(realized_net_r > 0),
                        benchmark_excess=float(pair_return - benchmark_return),
                        sample_weight=self.sample_weight,
                    )
                )
        return tuple(sorted(result, key=lambda item: (item.decision_timestamp, item.asset_key)))


class ForexHistoricalKnowledgeService:
    """Read-only lookup for bounded historical context during live paper decisions."""

    def __init__(self, artifact_path: str | Path) -> None:
        self.artifact_path = Path(artifact_path)

    def advise(self, *, pair: str, closes: tuple[float, ...]) -> ForexHistoricalAdvice:
        if not self.artifact_path.is_file():
            return _neutral_advice("Historical Forex knowledge artifact is unavailable.")
        try:
            payload = json.loads(self.artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _neutral_advice("Historical Forex knowledge artifact is unreadable.")
        if payload.get("format") != "blum_forex_historical_knowledge_v1":
            return _neutral_advice("Historical Forex knowledge artifact format is unsupported.")
        if (payload.get("provenance") or {}).get("transformation_version") != FOREX_HISTORY_TRANSFORM_VERSION:
            return _neutral_advice("Historical Forex knowledge predates the current data-quality audit.")
        pattern = _live_pattern(closes)
        canonical_pair = _canonical_pair(pair)
        pair_key = f"{canonical_pair}|{pattern}"
        stats = (payload.get("pair_patterns") or {}).get(pair_key)
        if (
            not isinstance(stats, dict)
            or int(stats.get("validation_sample_size") or 0) < 10
        ):
            stats = (payload.get("global_patterns") or {}).get(pattern)
        validation_sample_size = int(
            (stats or {}).get("validation_sample_size") or 0
        )
        if not isinstance(stats, dict) or validation_sample_size < 10:
            return _neutral_advice(
                f"No sufficiently sampled historical pattern exists for {pattern}.",
                pattern=pattern,
            )
        hit_rate = float(stats["validation_hit_rate"])
        mean_net_r = float(stats["validation_mean_net_r"])
        direction_consistent = bool(stats.get("direction_consistent"))
        adjustment = (
            max(
                -0.03,
                min(
                    0.03,
                    (hit_rate - 0.5) * 0.08 + math.tanh(mean_net_r) * 0.01,
                ),
            )
            if direction_consistent
            else 0.0
        )
        source_sha256 = str(
            (payload.get("provenance") or {}).get("source_sha256") or ""
        ) or None
        correlations = (
            (payload.get("correlation_matrix") or {}).get(canonical_pair) or {}
        )
        correlated_pairs = tuple(
            {
                "pair": str(other_pair),
                "correlation": float(correlation),
            }
            for other_pair, correlation in sorted(
                correlations.items(),
                key=lambda item: abs(float(item[1])),
                reverse=True,
            )[:3]
        )
        correlation_note = (
            f"Strongest trailing relationship: {correlated_pairs[0]['pair']} "
            f"({float(correlated_pairs[0]['correlation']):+.2f})."
            if correlated_pairs
            else "No cross-pair relationship has enough aligned history."
        )
        return ForexHistoricalAdvice(
            status="AVAILABLE",
            confidence_adjustment=adjustment,
            sample_size=validation_sample_size,
            hit_rate=hit_rate,
            mean_net_r=mean_net_r,
            pattern=pattern,
            source_sha256=source_sha256,
            correlated_pairs=correlated_pairs,
            explanation=(
                f"Chronological holdout {pattern} n={validation_sample_size}; "
                f"hit rate={hit_rate:.1%}.",
                correlation_note,
                (
                    "Train/holdout direction is consistent; research-only confidence "
                    "impact is capped at +/-3 percentage points."
                    if direction_consistent
                    else "Train/holdout direction is unstable; confidence impact is frozen."
                ),
            ),
        )


def _canonical_pair(value: str) -> str:
    return pair_config(value.strip().upper().replace("/", "")).ticker


def _parse_timestamp(value: str) -> datetime:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            # BLUM persistence currently uses naive UTC consistently.
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"unsupported Forex timestamp: {value}")


def _causal_indicators(bars: tuple[_Bar, ...]) -> tuple[dict[str, float | str], ...]:
    ema10 = bars[0].close
    ema50 = bars[0].close
    alpha10 = 2.0 / 11.0
    alpha50 = 2.0 / 51.0
    gains: deque[float] = deque(maxlen=14)
    losses: deque[float] = deque(maxlen=14)
    true_ranges: deque[float] = deque(maxlen=14)
    closes: deque[float] = deque(maxlen=20)
    returns: deque[float] = deque(maxlen=20)
    output: list[dict[str, float | str]] = []
    previous_close = bars[0].close
    for index, bar in enumerate(bars):
        change = bar.close - previous_close if index else 0.0
        gains.append(max(0.0, change))
        losses.append(max(0.0, -change))
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )
        if index:
            returns.append(bar.close / previous_close - 1.0)
        closes.append(bar.close)
        ema10 = alpha10 * bar.close + (1.0 - alpha10) * ema10
        ema50 = alpha50 * bar.close + (1.0 - alpha50) * ema50
        average_gain = fmean(gains) if gains else 0.0
        average_loss = fmean(losses) if losses else 0.0
        rsi = (
            100.0
            if average_loss == 0 and average_gain > 0
            else 50.0
            if average_loss == 0
            else 100.0 - 100.0 / (1.0 + average_gain / average_loss)
        )
        atr = fmean(true_ranges)
        volatility = _stddev(returns)
        regime = (
            "trend_up"
            if ema10 > ema50 * 1.0005
            else "trend_down"
            if ema10 < ema50 * 0.9995
            else "range"
        )
        output.append(
            {
                "ema10": ema10,
                "ema50": ema50,
                "rsi": rsi,
                "atr": atr,
                "volatility": volatility,
                "support": min(closes),
                "resistance": max(closes),
                "recent_return": returns[-1] if returns else 0.0,
                "regime": regime,
            }
        )
        previous_close = bar.close
    return tuple(output)


def _decision_rule(state: dict[str, float | str]) -> tuple[str, str]:
    rsi = float(state["rsi"])
    if rsi >= 70.0:
        return "mean_reversion", "SHORT"
    if rsi <= 30.0:
        return "mean_reversion", "LONG"
    return (
        "trend_following",
        "LONG" if state["regime"] == "trend_up" else "SHORT",
    )


def _feature_payload(
    *,
    pair: str,
    setup_type: str,
    direction: str,
    state: dict[str, float | str],
    risk_distance: float,
    cost: float,
) -> dict[str, float | str | None]:
    ema10 = float(state["ema10"])
    ema50 = float(state["ema50"])
    atr = float(state["atr"])
    rsi = float(state["rsi"])
    trend = max(-1.0, min(1.0, (ema10 - ema50) / max(atr, 1e-12)))
    momentum = max(-1.0, min(1.0, (rsi - 50.0) / 50.0))
    support_distance = abs(ema10 - float(state["support"]))
    resistance_distance = abs(float(state["resistance"]) - ema10)
    setup_quality = 1.0 - min(1.0, min(support_distance, resistance_distance) / max(atr * 3, 1e-12))
    confidence = min(80.0, 50.0 + abs(trend) * 15.0 + abs(momentum) * 10.0)
    config = pair_config(pair)
    return {
        "aggregate_score": confidence,
        "confidence": confidence,
        "trend_score": trend,
        "momentum_score": momentum,
        "volume_score": None,
        "volatility_score": min(100.0, float(state["volatility"]) * 10_000.0),
        "support_resistance_score": setup_quality,
        "sentiment_score": None,
        "narrative_score": None,
        "fundamental_score": None,
        "regime_score": abs(trend),
        "expected_gross_r": 1.5,
        "expected_net_r": max(-1.0, 1.5 - cost / max(risk_distance, 1e-12)),
        "expected_cost": cost,
        "stop_distance": risk_distance,
        "target_distance": risk_distance * 1.5,
        "data_quality_score": 0.8,
        "liquidity_score": 0.8,
        "spread": config.pip_size * (_round_trip_cost_pips(pair) * 0.5),
        "slippage": config.pip_size * 0.2,
        "volatility": float(state["volatility"]),
        "recent_return": float(state["recent_return"]),
        "multi_timeframe_trend": trend,
        "contextual_bandit_adjustment": 0.0,
        "contextual_bandit_sample_size": 0.0,
        "market_family": "forex",
        "setup_type": setup_type,
        "regime": str(state["regime"]),
        "session": "DAILY",
        "direction": direction,
        "timeframe": "1d",
        "sector_or_currency_family": f"{config.base_currency}/{config.quote_currency}",
    }


def _round_trip_cost_pips(pair: str) -> float:
    return {
        "EURUSD=X": 1.6,
        "GBPUSD=X": 2.0,
        "USDJPY=X": 1.8,
    }.get(pair, 2.2)


def _future_returns(
    bars_by_pair: dict[str, tuple[_Bar, ...]],
    horizon_bars: int,
) -> dict[datetime, tuple[float, ...]]:
    values: dict[datetime, list[float]] = defaultdict(list)
    for bars in bars_by_pair.values():
        for index in range(len(bars) - horizon_bars):
            window = bars[index:index + horizon_bars + 1]
            if any(right.timestamp - left.timestamp > timedelta(days=4)
                   for left, right in zip(window, window[1:])):
                continue
            entry = bars[index + 1].opened
            exit_price = bars[index + horizon_bars].close
            if entry > 0:
                values[bars[index + horizon_bars].timestamp].append(exit_price / entry - 1.0)
    return {stamp: tuple(rows) for stamp, rows in values.items()}


def _build_knowledge(
    examples: Iterable[TradingMLExample],
    provenance: dict,
) -> dict:
    global_rows: dict[str, list[TradingMLExample]] = defaultdict(list)
    pair_rows: dict[str, list[TradingMLExample]] = defaultdict(list)
    for example in examples:
        pattern = f"{example.setup_type}|{example.regime}"
        global_rows[pattern].append(example)
        pair_rows[f"{example.asset_key}|{pattern}"].append(example)
    return {
        "global_patterns": {
            key: _pattern_stats(rows) for key, rows in sorted(global_rows.items())
        },
        "pair_patterns": {
            key: _pattern_stats(rows) for key, rows in sorted(pair_rows.items())
        },
        "correlation_matrix": _correlation_matrix(examples),
        "source_sha256": provenance["source_sha256"],
    }


def _pattern_stats(rows: list[TradingMLExample]) -> dict:
    ordered = sorted(
        rows,
        key=lambda row: (row.decision_timestamp, row.asset_key),
    )
    split = (
        max(1, min(len(ordered) - 1, int(len(ordered) * 0.7)))
        if len(ordered) > 1
        else 1
    )
    training = ordered[:split]
    validation = ordered[split:]
    training_mean = fmean(row.realized_net_r for row in training)
    validation_mean = (
        fmean(row.realized_net_r for row in validation)
        if validation
        else None
    )
    return {
        "sample_size": len(ordered),
        "training_sample_size": len(training),
        "validation_sample_size": len(validation),
        "training_hit_rate": sum(row.label_positive_r for row in training)
        / len(training),
        "validation_hit_rate": (
            sum(row.label_positive_r for row in validation) / len(validation)
            if validation
            else None
        ),
        "training_mean_net_r": training_mean,
        "validation_mean_net_r": validation_mean,
        "direction_consistent": (
            validation_mean is not None
            and (
                training_mean == 0.0
                or validation_mean == 0.0
                or (training_mean > 0) == (validation_mean > 0)
            )
        ),
        "mean_benchmark_excess": fmean(
            row.benchmark_excess or 0.0 for row in ordered
        ),
    }


def _live_pattern(closes: tuple[float, ...]) -> str:
    if len(closes) < 20 or any(not math.isfinite(value) or value <= 0 for value in closes):
        return "insufficient"
    synthetic = tuple(
        _Bar(
            timestamp=datetime(2000, 1, 1, tzinfo=UTC),
            pair="EURUSD=X",
            opened=value,
            high=value,
            low=value,
            close=value,
        )
        for value in closes
    )
    state = _causal_indicators(synthetic)[-1]
    setup_type, _ = _decision_rule(state)
    return f"{setup_type}|{state['regime']}"


def _neutral_advice(
    explanation: str,
    *,
    pattern: str | None = None,
) -> ForexHistoricalAdvice:
    return ForexHistoricalAdvice(
        status="UNAVAILABLE",
        confidence_adjustment=0.0,
        sample_size=0,
        hit_rate=None,
        mean_net_r=None,
        pattern=pattern,
        source_sha256=None,
        correlated_pairs=(),
        explanation=(explanation,),
    )


def _stddev(values: Iterable[float]) -> float:
    rows = tuple(values)
    if len(rows) < 2:
        return 0.0
    mean = fmean(rows)
    return math.sqrt(sum((value - mean) ** 2 for value in rows) / len(rows))


def _correlation_matrix(
    examples: Iterable[TradingMLExample],
) -> dict[str, dict[str, float]]:
    returns: dict[str, dict[datetime, float]] = defaultdict(dict)
    for example in examples:
        value = example.features.get("recent_return")
        if value is not None:
            returns[example.asset_key][example.decision_timestamp] = float(value)
    matrix: dict[str, dict[str, float]] = defaultdict(dict)
    pairs = sorted(returns)
    for left_index, left in enumerate(pairs):
        for right in pairs[left_index + 1 :]:
            common = sorted(set(returns[left]).intersection(returns[right]))
            if len(common) < 20:
                continue
            correlation = _pearson(
                tuple(returns[left][stamp] for stamp in common),
                tuple(returns[right][stamp] for stamp in common),
            )
            if correlation is None:
                continue
            matrix[left][right] = round(correlation, 6)
            matrix[right][left] = round(correlation, 6)
    return {pair: dict(rows) for pair, rows in sorted(matrix.items())}


def _pearson(left: tuple[float, ...], right: tuple[float, ...]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = fmean(left)
    right_mean = fmean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    if left_scale == 0 or right_scale == 0:
        return None
    return numerator / (left_scale * right_scale)
