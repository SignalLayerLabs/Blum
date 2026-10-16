"""Pinned daily-bar research; reconstructed features, never production fills."""

from collections import defaultdict
from datetime import datetime, time, timezone
from hashlib import sha256
import math
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

import polars as pl

from .contracts import TradingMLExample

TRANSFORM_VERSION = "daily-next-session-v2"
RESEARCH_LANE = "external_daily_bar_research"
_NEW_YORK = ZoneInfo("America/New_York")
_CORE_COLUMNS = [
    "symbol",
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "close_adj",
    "volume",
    "timeframe",
]


def load_pinned_daily_bars(path: str | Path, *, expected_sha256: str) -> list[dict]:
    """Local files only; revision/hash acceptance and use rights belong to the caller."""
    path = Path(path)
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if len(expected_sha256) != 64 or digest.hexdigest() != expected_sha256:
        raise ValueError("DAILY_SOURCE_SHA256_MISMATCH")
    # Never read publisher indicators, templated prompts, macro proxies or targets.
    return pl.read_parquet(path, columns=_CORE_COLUMNS).to_dicts()


def _available_at(day) -> datetime:
    # Deliberately later than even a regular 16:00 close; this is a declared
    # conservative assumption, not a historical vendor arrival-time receipt.
    return (
        datetime.combine(day, time(18), _NEW_YORK)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def _split(day) -> str:
    if day.year <= 2023:
        return "train"
    return "validation" if day.year == 2024 else "test"


def examples_from_daily_bars(
    rows,
    *,
    source_id: str,
    split: str,
    cost_bps: float = 10,
    sample_weight: float = 0.15,
) -> tuple[TradingMLExample, ...]:
    """One LONG next-open/close hypothesis per day, with prior-close ATR risk.

    These modeled, cost-stressed research returns are not executable fill data,
    dividend total returns, an historical investable universe, or forward alpha.
    Known past adjustment changes and >25% past close discontinuities exclude
    a feature window. Future returns never determine decision eligibility.
    Splits follow outcome dates; no training label can cross into validation.
    """
    if split not in {"train", "validation", "test"} or not source_id.strip():
        raise ValueError("Daily research requires a source identity and a valid split")
    if not math.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("Daily research cost must be finite and non-negative")
    if not math.isfinite(sample_weight) or not 0 < sample_weight <= 1:
        raise ValueError("Daily research weight must be in (0, 1]")
    grouped = defaultdict(list)
    seen = set()
    for row in rows:
        day = row["datetime"].date()
        symbol = str(row["symbol"])
        identity = symbol, day
        if identity in seen:
            raise ValueError("DAILY_DUPLICATE_BAR")
        seen.add(identity)
        opening, high, low, close, adjusted, volume = (
            float(row[k])
            for k in ("open", "high", "low", "close", "close_adj", "volume")
        )
        if (
            row.get("timeframe") != "1day"
            or not all(
                math.isfinite(v) for v in (opening, high, low, close, adjusted, volume)
            )
            or min(opening, high, low, close, adjusted) <= 0
            or volume < 0
            or high < max(opening, close)
            or low > min(opening, close)
            or low > high
        ):
            raise ValueError("DAILY_INVALID_OHLC")
        grouped[symbol].append((day, opening, high, low, close, adjusted, volume))
    examples = []
    for symbol, series in sorted(grouped.items()):
        series.sort()
        for index in range(21, len(series) - 1):
            current, following = series[index], series[index + 1]
            if _split(following[0]) != split:
                continue
            window = series[index - 21 : index + 1]
            # Exclude uncertain action intervals rather than manufacture an
            # adjusted OHLC history from a restated adjusted-close column.
            ratios = [bar[5] / bar[4] for bar in window]
            if any(abs(b / a - 1) > 1e-6 for a, b in zip(ratios, ratios[1:])):
                continue
            if any(abs(b[4] / a[4] - 1) > 0.25 for a, b in zip(window, window[1:])):
                continue
            if (following[0] - current[0]).days > 7:
                continue
            previous = series[index - 20 : index + 1]
            closes = [bar[4] for bar in previous]
            returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
            atr = statistics.fmean(
                max(b[2] - b[3], abs(b[2] - a[4]), abs(b[3] - a[4]))
                for a, b in zip(
                    series[index - 14 : index], series[index - 13 : index + 1]
                )
            )
            if atr <= 0:
                continue
            recent = closes[-1] / closes[-6] - 1
            trend = closes[-1] / statistics.fmean(closes) - 1
            vol = statistics.pstdev(returns)
            volume_mean = statistics.fmean(bar[6] for bar in previous)
            # Relative ATR fixes the risk unit at decision time while the
            # hypothetical next-session return uses same-session price units.
            # A split between sessions must not rescale either risk or features.
            risk_fraction = atr / current[4]
            cost = cost_bps / 10000 / risk_fraction
            net_r = (following[4] / following[1] - 1) / risk_fraction - cost
            regime = (
                "uptrend" if trend > 0.01 else "downtrend" if trend < -0.01 else "range"
            )
            features = {
                "trend_score": max(0, min(100, 50 + trend * 1000)),
                "momentum_score": max(0, min(100, 50 + recent * 1000)),
                "volume_score": (
                    min(100, 50 * current[6] / volume_mean) if volume_mean else 0
                ),
                "volatility_score": max(0, 100 - vol * 2000),
                "expected_cost": cost_bps / 10000 * current[4] / atr,
                "stop_distance": atr / current[4],
                "volatility": vol,
                "recent_return": recent,
                "multi_timeframe_trend": trend,
                "market_family": "equity",
                "setup_type": "daily_bar_research",
                "regime": regime,
                "session": "next_regular",
                "direction": "LONG",
                "timeframe": "1day",
                "sector_or_currency_family": None,
            }
            examples.append(
                TradingMLExample(
                    source_object_type="external_daily_bar_research",
                    source_object_id=f"{source_id}:{TRANSFORM_VERSION}:{symbol}:{current[0]}:cost={cost_bps:g}",
                    market_family="equity",
                    evidence_lane=RESEARCH_LANE,
                    decision_timestamp=_available_at(current[0]),
                    outcome_timestamp=_available_at(following[0]),
                    asset_key=symbol,
                    setup_type="daily_bar_research",
                    regime=regime,
                    features=features,
                    realized_net_r=net_r,
                    label_positive_r=int(net_r > 0),
                    benchmark_excess=None,
                    sample_weight=sample_weight,
                )
            )
    return tuple(
        sorted(examples, key=lambda row: (row.decision_timestamp, row.asset_key))
    )
