"""Execute frozen replay contracts; never infer a contract from a strategy label."""

from dataclasses import fields
from hashlib import sha256
import json
from math import isfinite
from types import SimpleNamespace

from app.services.executable_strategy import (
    ExecutableStrategySpec,
    StrategySignalEvaluator,
)
from app.services.forex_contracts import (
    AgentMarketInput,
    ForexDirection,
    ForexStrategyEvidence,
    PriceActionOutput,
    pair_config,
)
from app.services.market_clock import utc_naive
from app.services.market_bar_clock import available_at

PRICE_FEATURE_SCHEMA_HASH = sha256(
    json.dumps(
        {
            "version": "forex-ohlcv-v1",
            "prices": "quote_currency_per_base_currency",
            "volume": "provider_reported_only",
            "clock": "eligible_completed_bars_utc",
        },
        sort_keys=True,
    ).encode()
).hexdigest()
TIMEFRAME_MINUTES = {"1h": 60, "15m": 15, "5m": 5, "1m": 1}


def validated_spec(
    strategy: ForexStrategyEvidence,
) -> tuple[ExecutableStrategySpec | None, str | None]:
    payload = strategy.executable_strategy
    if not isinstance(payload, dict) or not payload:
        return None, "EXECUTABLE_SPEC_UNAVAILABLE"
    if any(field.name not in payload for field in fields(ExecutableStrategySpec)):
        return None, "EXECUTABLE_SPEC_INVALID"
    try:
        # No coercion of fractional integers, bools, NaN, or missing parameters
        # into a different executable contract.
        for name in ("lookback", "atr_period", "maximum_holding_bars"):
            if type(payload[name]) is not int:
                raise ValueError("integer parameter required")
        for name in (
            "minimum_relative_volume",
            "higher_timeframe_min_trend",
            "stop_atr_multiple",
            "minimum_stop_percent",
            "target_r_multiple",
            "trailing_atr_multiple",
        ):
            if (
                isinstance(payload[name], bool)
                or not isinstance(payload[name], (int, float))
                or not isfinite(payload[name])
            ):
                raise ValueError("finite numeric parameter required")
        spec = ExecutableStrategySpec.from_payload(payload)
        if (
            spec.execution_timeframe not in TIMEFRAME_MINUTES
            or set(spec.required_timeframes) - TIMEFRAME_MINUTES.keys()
        ):
            raise ValueError("unsupported Forex timeframe")
        if len(set(spec.required_timeframes)) != len(spec.required_timeframes):
            raise ValueError("duplicate timeframe")
    except (TypeError, ValueError, OverflowError):
        return None, "EXECUTABLE_SPEC_INVALID"
    if (
        strategy.strategy_fingerprint != spec.fingerprint
        or payload.get("strategy_fingerprint") != spec.fingerprint
    ):
        return None, "STRATEGY_FINGERPRINT_MISMATCH"
    if strategy.required_feature_schema_hash != PRICE_FEATURE_SCHEMA_HASH:
        return None, "FEATURE_SCHEMA_MISMATCH"
    if strategy.holding_horizon_bars != spec.maximum_holding_bars:
        return None, "HOLDING_HORIZON_MISMATCH"
    return spec, None


class ForexStrategySignal:
    def evaluate(
        self, market: AgentMarketInput, *, strategy: ForexStrategyEvidence
    ) -> PriceActionOutput:
        spec, error = validated_spec(strategy)
        if error:
            return self._blocked(market, error)
        histories = {}
        as_of = utc_naive(market.as_of)
        for timeframe in spec.required_timeframes:
            frame = market.frames.get(timeframe)
            if frame is None:
                return self._blocked(market, "TIMEFRAME_UNAVAILABLE")
            if (
                utc_naive(frame.acquired_at) > as_of
                or utc_naive(frame.market_timestamp) > as_of
            ):
                return self._blocked(market, "FUTURE_DATA_DETECTED")
            size = len(frame.closes)
            if not size or len(frame.bar_timestamps) != size:
                return self._blocked(market, "BAR_PROVENANCE_UNAVAILABLE")
            if len({len(frame.opens), len(frame.highs), len(frame.lows), size}) != 1:
                return self._blocked(market, "INVALID_OHLC_CONTEXT")
            stamps = tuple(utc_naive(stamp) for stamp in frame.bar_timestamps)
            if stamps != tuple(sorted(set(stamps))) or stamps[-1] != utc_naive(
                frame.market_timestamp
            ):
                return self._blocked(market, "INVALID_BAR_CLOCKS")
            if any(available_at(stamp, timeframe, "FOREX") > as_of for stamp in stamps):
                return self._blocked(market, "BAR_NOT_AVAILABLE")
            rows = []
            for index, stamp in enumerate(stamps):
                values = (
                    frame.opens[index],
                    frame.highs[index],
                    frame.lows[index],
                    frame.closes[index],
                )
                if any(
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not isfinite(v)
                    or v <= 0
                    for v in values
                ):
                    return self._blocked(market, "INVALID_OHLC_CONTEXT")
                opened, high, low, close = values
                if low > min(opened, close) or high < max(opened, close) or low > high:
                    return self._blocked(market, "INVALID_OHLC_CONTEXT")
                volume = frame.volumes[index] if len(frame.volumes) == size else None
                if volume is None and spec.minimum_relative_volume > 0:
                    return self._blocked(market, "VOLUME_UNAVAILABLE")
                if volume is not None and (
                    isinstance(volume, bool)
                    or not isinstance(volume, (int, float))
                    or not isfinite(volume)
                    or volume < 0
                ):
                    return self._blocked(market, "VOLUME_UNAVAILABLE")
                rows.append(
                    SimpleNamespace(
                        bar_timestamp=stamp,
                        open=opened,
                        high=high,
                        low=low,
                        close=close,
                        volume=volume,
                    )
                )
            histories[timeframe] = tuple(rows)
        evaluator = StrategySignalEvaluator()
        signal = evaluator.evaluate(spec, histories, as_of=as_of, market="FOREX")
        midpoint = (market.quote.bid + market.quote.ask) / 2
        geometry = evaluator.geometry(
            spec,
            entry_price=midpoint,
            execution_history=histories[spec.execution_timeframe],
        )
        if (
            not isfinite(geometry.risk_distance)
            or geometry.risk_distance <= 0
            or geometry.stop_price <= 0
        ):
            return self._blocked(market, "INVALID_TRADE_GEOMETRY")
        return PriceActionOutput(
            setup_family=spec.setup_type,
            direction=(
                ForexDirection.LONG
                if signal.status == "triggered"
                else ForexDirection.WATCH
            ),
            setup_quality=0.82 if signal.status == "triggered" else 0.0,
            trigger=signal.reason_code,
            entry_zone=(market.quote.bid, market.quote.ask),
            stop_level=geometry.stop_price,
            target_levels=(geometry.target_price,),
            invalidation="Frozen executable strategy stop or holding-bar limit",
            expected_holding_minutes=spec.maximum_holding_bars
            * TIMEFRAME_MINUTES[spec.execution_timeframe],
            expected_gross_pips=abs(geometry.target_price - midpoint)
            / pair_config(market.pair).pip_size,
            technical_evidence=(spec.entry_rule, signal.reason_code, spec.fingerprint),
            confidence=0.82 if signal.status == "triggered" else 0.0,
            blockers=(signal.reason_code,) if signal.status == "blocked" else (),
            strategy_fingerprint=spec.fingerprint,
            executable_strategy=spec.to_payload(),
            execution_timeframe=spec.execution_timeframe,
            maximum_holding_bars=spec.maximum_holding_bars,
            trailing_stop=geometry.trailing_stop,
            feature_schema_hash=PRICE_FEATURE_SCHEMA_HASH,
        )

    @staticmethod
    def _blocked(market, reason):
        mid = (market.quote.bid + market.quote.ask) / 2
        return PriceActionOutput(
            setup_family="unavailable",
            direction=ForexDirection.ABSTAIN,
            setup_quality=0.0,
            trigger=reason,
            entry_zone=(market.quote.bid, market.quote.ask),
            stop_level=mid,
            target_levels=(mid,),
            invalidation=reason,
            expected_holding_minutes=0,
            expected_gross_pips=0.0,
            technical_evidence=(),
            confidence=0.0,
            blockers=(reason,),
        )
