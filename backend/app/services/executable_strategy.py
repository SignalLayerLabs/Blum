from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from statistics import mean
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "executable-strategy-v1"
SUPPORTED_ENTRY_RULES = {
    "breakout_close",
    "trend_continuation",
    "mean_reversion_deviation",
    "pullback_to_mean",
}
SUPPORTED_TIMEFRAMES = {"1d", "1h", "15m", "5m", "1m"}


@dataclass(frozen=True)
class ExecutableStrategySpec:
    schema_version: str
    family: str
    setup_type: str
    required_timeframes: tuple[str, ...]
    execution_timeframe: str
    entry_rule: str
    lookback: int
    minimum_relative_volume: float
    higher_timeframe_min_trend: float
    atr_period: int
    stop_atr_multiple: float
    minimum_stop_percent: float
    target_r_multiple: float
    trailing_atr_multiple: float
    maximum_holding_bars: int
    regime_filter: str = "all"
    market_filter: str = "all"

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported strategy schema: {self.schema_version}")
        if self.entry_rule not in SUPPORTED_ENTRY_RULES:
            raise ValueError(f"unsupported entry rule: {self.entry_rule}")
        if not self.required_timeframes or set(self.required_timeframes) - SUPPORTED_TIMEFRAMES:
            raise ValueError("unsupported or empty timeframe stack")
        if self.execution_timeframe not in self.required_timeframes:
            raise ValueError("execution timeframe must be included in required timeframes")
        if not 2 <= self.lookback <= 250:
            raise ValueError("lookback must be between 2 and 250")
        if not 2 <= self.atr_period <= 100:
            raise ValueError("ATR period must be between 2 and 100")
        if not 0.0 <= self.minimum_relative_volume <= 20.0:
            raise ValueError("minimum relative volume is outside supported bounds")
        if not 0.1 <= self.stop_atr_multiple <= 10.0:
            raise ValueError("stop ATR multiple is outside supported bounds")
        if not 0.0 <= self.minimum_stop_percent <= 0.25:
            raise ValueError("minimum stop percent is outside supported bounds")
        if not 0.1 <= self.target_r_multiple <= 20.0:
            raise ValueError("target R multiple is outside supported bounds")
        if not 0.1 <= self.trailing_atr_multiple <= 10.0:
            raise ValueError("trailing ATR multiple is outside supported bounds")
        if not 1 <= self.maximum_holding_bars <= 2_000:
            raise ValueError("maximum holding bars is outside supported bounds")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ExecutableStrategySpec":
        return cls(
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            family=str(payload.get("family") or "unclassified"),
            setup_type=str(payload.get("setup_type") or "unknown"),
            required_timeframes=tuple(str(value) for value in payload.get("required_timeframes") or ("1d",)),
            execution_timeframe=str(payload.get("execution_timeframe") or (payload.get("required_timeframes") or ["1d"])[-1]),
            entry_rule=str(payload.get("entry_rule") or "breakout_close"),
            lookback=int(payload.get("lookback", 10)),
            minimum_relative_volume=float(payload.get("minimum_relative_volume", 0.0)),
            higher_timeframe_min_trend=float(payload.get("higher_timeframe_min_trend", 0.0)),
            atr_period=int(payload.get("atr_period", 14)),
            stop_atr_multiple=float(payload.get("stop_atr_multiple", 1.0)),
            minimum_stop_percent=float(payload.get("minimum_stop_percent", 0.01)),
            target_r_multiple=float(payload.get("target_r_multiple", 2.0)),
            trailing_atr_multiple=float(payload.get("trailing_atr_multiple", 1.2)),
            maximum_holding_bars=int(payload.get("maximum_holding_bars", 20)),
            regime_filter=str(payload.get("regime_filter") or "all"),
            market_filter=str(payload.get("market_filter") or "all"),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_timeframes"] = list(self.required_timeframes)
        payload["strategy_fingerprint"] = self.fingerprint
        return payload

    @property
    def fingerprint(self) -> str:
        payload = asdict(self)
        payload["required_timeframes"] = list(self.required_timeframes)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StrategySignalEvaluation:
    status: str
    reason_code: str
    decision_timestamp: datetime | None
    relative_volume: float
    atr: float
    regime: str
    higher_timeframe_trends: dict[str, float]
    evidence: dict[str, Any]


@dataclass(frozen=True)
class TradeGeometry:
    entry_price: float
    stop_price: float
    target_price: float
    trailing_stop: float
    risk_distance: float
    atr: float


class StrategySignalEvaluator:
    """Evaluate a frozen strategy using only bars available at ``as_of``."""

    def evaluate(
        self,
        spec: ExecutableStrategySpec,
        bars_by_timeframe: Mapping[str, Sequence[Any]],
        *,
        as_of: datetime,
        market: str | None = None,
    ) -> StrategySignalEvaluation:
        histories = {
            timeframe: tuple(
                row
                for row in bars_by_timeframe.get(timeframe, ())
                if getattr(row, "bar_timestamp", as_of) <= as_of
            )
            for timeframe in spec.required_timeframes
        }
        execution = histories.get(spec.execution_timeframe, ())
        decision_timestamp = getattr(execution[-1], "bar_timestamp", None) if execution else None
        minimum_execution_rows = max(spec.lookback + 1, spec.atr_period + 1)
        missing = [
            timeframe
            for timeframe in spec.required_timeframes
            if len(histories.get(timeframe, ())) < (minimum_execution_rows if timeframe == spec.execution_timeframe else 2)
        ]
        if missing:
            return self._result(
                "blocked",
                "INSUFFICIENT_POINT_IN_TIME_CONTEXT",
                decision_timestamp,
                regime="insufficient_data",
                evidence={"missing_timeframes": missing},
            )

        market_filter = spec.market_filter.removesuffix("_only").upper()
        if spec.market_filter != "all" and market and normalize_market(market) != normalize_market(market_filter):
            return self._result(
                "blocked",
                "MARKET_FILTER_MISMATCH",
                decision_timestamp,
                regime="unknown",
                evidence={"required_market": market_filter, "observed_market": market},
            )

        regime_history = histories.get("1d") or execution
        regime = market_regime(regime_history)
        expected_regime = spec.regime_filter.removesuffix("_only")
        if spec.regime_filter != "all" and regime != expected_regime:
            return self._result(
                "blocked",
                "REGIME_FILTER_MISMATCH",
                decision_timestamp,
                regime=regime,
                evidence={"required_regime": expected_regime},
            )

        trends = {
            timeframe: trend_return(history)
            for timeframe, history in histories.items()
            if timeframe != spec.execution_timeframe
        }
        contradictions = [
            timeframe
            for timeframe, trend in trends.items()
            if trend < spec.higher_timeframe_min_trend
        ]
        if contradictions:
            return self._result(
                "blocked",
                "HIGHER_TIMEFRAME_CONTRADICTION",
                decision_timestamp,
                regime=regime,
                trends=trends,
                evidence={"contradicting_timeframes": contradictions},
            )

        current = execution[-1]
        prior = execution[-(spec.lookback + 1) : -1]
        prior_volumes = [float(getattr(row, "volume", 0.0) or 0.0) for row in prior]
        average_volume = mean(prior_volumes) if prior_volumes else 0.0
        current_volume = float(getattr(current, "volume", 0.0) or 0.0)
        relative_volume = current_volume / average_volume if average_volume > 0 else 0.0
        atr = average_true_range(execution, spec.atr_period)
        evidence = {
            "strategy_fingerprint": spec.fingerprint,
            "as_of": as_of.isoformat(),
            "feature_bar_timestamps": [getattr(row, "bar_timestamp").isoformat() for row in prior],
            "current_bar_timestamp": decision_timestamp.isoformat() if decision_timestamp else None,
            "relative_volume": relative_volume,
            "higher_timeframe_trends": trends,
        }
        if relative_volume < spec.minimum_relative_volume:
            return self._result(
                "waiting",
                "RELATIVE_VOLUME_BELOW_THRESHOLD",
                decision_timestamp,
                relative_volume=relative_volume,
                atr=atr,
                regime=regime,
                trends=trends,
                evidence=evidence,
            )

        close = float(current.close)
        if spec.entry_rule == "breakout_close":
            # The existing BLUM breakout contract is close-to-close. Keeping the
            # reference explicit preserves replay compatibility while sharing the
            # exact same trigger with paper-forward evaluation.
            triggered = close > max(float(row.close) for row in prior)
        elif spec.entry_rule == "trend_continuation":
            prior_closes = [float(row.close) for row in prior]
            moving_average = mean(prior_closes)
            triggered = close > moving_average and close > float(prior[-1].close) and prior_closes[-1] > prior_closes[0]
        elif spec.entry_rule == "mean_reversion_deviation":
            prior_closes = [float(row.close) for row in prior]
            moving_average = mean(prior_closes)
            variance = mean([(value - moving_average) ** 2 for value in prior_closes])
            deviation = variance**0.5
            triggered = close < moving_average - max(deviation, moving_average * 0.01)
        else:
            prior_closes = [float(row.close) for row in prior]
            moving_average = mean(prior_closes)
            triggered = prior_closes[-1] > prior_closes[0] and moving_average * 0.97 <= close <= moving_average * 1.01
        if not triggered:
            return self._result(
                "waiting",
                "ENTRY_NOT_TRIGGERED",
                decision_timestamp,
                relative_volume=relative_volume,
                atr=atr,
                regime=regime,
                trends=trends,
                evidence=evidence,
            )
        return self._result(
            "triggered",
            "ENTRY_TRIGGERED",
            decision_timestamp,
            relative_volume=relative_volume,
            atr=atr,
            regime=regime,
            trends=trends,
            evidence=evidence,
        )

    def geometry(
        self,
        spec: ExecutableStrategySpec,
        *,
        entry_price: float,
        execution_history: Sequence[Any],
    ) -> TradeGeometry:
        if entry_price <= 0:
            raise ValueError("entry price must be positive")
        atr = average_true_range(execution_history, spec.atr_period)
        risk_distance = max(atr * spec.stop_atr_multiple, entry_price * spec.minimum_stop_percent)
        return TradeGeometry(
            entry_price=entry_price,
            stop_price=entry_price - risk_distance,
            target_price=entry_price + risk_distance * spec.target_r_multiple,
            trailing_stop=entry_price - atr * spec.trailing_atr_multiple,
            risk_distance=risk_distance,
            atr=atr,
        )

    @staticmethod
    def _result(
        status: str,
        reason_code: str,
        decision_timestamp: datetime | None,
        *,
        relative_volume: float = 0.0,
        atr: float = 0.0,
        regime: str,
        trends: dict[str, float] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> StrategySignalEvaluation:
        return StrategySignalEvaluation(
            status=status,
            reason_code=reason_code,
            decision_timestamp=decision_timestamp,
            relative_volume=relative_volume,
            atr=atr,
            regime=regime,
            higher_timeframe_trends=trends or {},
            evidence=evidence or {},
        )


def canonical_strategy_spec(setup_type: str) -> ExecutableStrategySpec:
    definitions = {
        "intraday_breakout": {
            "family": "intraday_scalping",
            "required_timeframes": ["1d", "15m", "5m", "1m"],
            "execution_timeframe": "1m",
            "entry_rule": "breakout_close",
            "lookback": 10,
            "minimum_relative_volume": 0.0,
            "minimum_stop_percent": 0.01,
            "maximum_holding_bars": 20,
        },
        "intraday_trend": {
            "family": "intraday_scalping",
            "required_timeframes": ["1d", "15m", "5m", "1m"],
            "execution_timeframe": "5m",
            "entry_rule": "trend_continuation",
            "lookback": 10,
            "minimum_relative_volume": 0.0,
            "minimum_stop_percent": 0.01,
            "maximum_holding_bars": 20,
        },
        "mean_reversion": {
            "family": "mean_reversion",
            "required_timeframes": ["15m", "5m"],
            "execution_timeframe": "5m",
            "entry_rule": "mean_reversion_deviation",
            "lookback": 10,
            "minimum_relative_volume": 0.0,
            "minimum_stop_percent": 0.01,
            "maximum_holding_bars": 20,
        },
        "pullback": {
            "family": "pullback",
            "required_timeframes": ["1d", "15m"],
            "execution_timeframe": "15m",
            "entry_rule": "pullback_to_mean",
            "lookback": 10,
            "minimum_relative_volume": 0.0,
            "minimum_stop_percent": 0.01,
            "maximum_holding_bars": 20,
        },
        "swing_breakout": {
            "family": "breakout",
            "required_timeframes": ["1d"],
            "execution_timeframe": "1d",
            "entry_rule": "breakout_close",
            "lookback": 10,
            "minimum_relative_volume": 0.0,
            "minimum_stop_percent": 0.01,
            "maximum_holding_bars": 20,
        },
    }
    if setup_type not in definitions:
        raise ValueError(f"unsupported setup type: {setup_type}")
    return ExecutableStrategySpec.from_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "setup_type": setup_type,
            "atr_period": 14,
            "stop_atr_multiple": 1.0,
            "target_r_multiple": 2.0,
            "trailing_atr_multiple": 1.2,
            "higher_timeframe_min_trend": 0.0,
            "regime_filter": "all",
            "market_filter": "all",
            **definitions[setup_type],
        }
    )


def average_true_range(history: Sequence[Any], period: int) -> float:
    rows = list(history)[-max(2, period + 1) :]
    if len(rows) < 2:
        return 0.0
    ranges: list[float] = []
    for previous, current in zip(rows, rows[1:]):
        high = float(getattr(current, "high", current.close) or current.close)
        low = float(getattr(current, "low", current.close) or current.close)
        previous_close = float(previous.close)
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return max(0.000001, mean(ranges))


def trend_return(history: Sequence[Any]) -> float:
    rows = list(history)
    if len(rows) < 2 or float(rows[0].close) == 0:
        return 0.0
    return float(rows[-1].close) / float(rows[0].close) - 1.0


def market_regime(history: Sequence[Any]) -> str:
    change = trend_return(list(history)[-20:])
    if change > 0.03:
        return "trend_up"
    if change < -0.03:
        return "trend_down"
    return "range_bound"


def normalize_market(value: str) -> str:
    key = str(value or "").strip().upper()
    return {
        "US": "USA",
        "UNITED STATES": "USA",
        "NASDAQ": "USA",
        "NYSE": "USA",
        "EUROPE": "EUROPE",
        "ITALY": "EUROPE",
        "GERMANY": "EUROPE",
        "FRANCE": "EUROPE",
        "SPAIN": "EUROPE",
        "NETHERLANDS": "EUROPE",
        "UNITED KINGDOM": "EUROPE",
        "UK": "EUROPE",
    }.get(key, key)
