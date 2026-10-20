from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from app.services.intraday_contracts import (
    INTRADAY_BLOCKED,
    INTRADAY_DATA_BLOCKED,
    INTRADAY_TRADE_CANDIDATE,
    INTRADAY_WATCHLIST,
    IntradayDataBundle,
    IntradayDecision,
    IntradayPositionSize,
    PromotedIntradayStrategy,
)
from app.services.replay_execution import ReplayExecutionModel, ReplayPositionSizer
from app.services.executable_strategy import ExecutableStrategySpec, StrategySignalEvaluator


@dataclass(frozen=True)
class IntradayPortfolioState:
    capital: float
    open_tickers: frozenset[str] = frozenset()
    positions_by_market: dict[str, int] = field(default_factory=dict)
    positions_by_desk: dict[str, int] = field(default_factory=dict)
    positions_by_asset_class: dict[str, int] = field(default_factory=dict)
    total_open_positions: int = 0
    total_risk_percent: float = 0.0


class BlumIntradayOpportunityEngine:
    def __init__(
        self,
        *,
        min_expected_move_bps: float = 12.0,
        max_spread_to_target_ratio: float = 0.25,
        min_liquidity_score: float = 35.0,
        max_open_positions: int = 5,
        max_positions_per_market: int = 3,
        max_positions_per_desk: int = 2,
        max_positions_per_asset_class: int = 3,
        max_total_risk_percent: float = 5.0,
        min_volatility_bps: float = 1.0,
    ):
        self.min_expected_move_bps = float(min_expected_move_bps)
        self.max_spread_to_target_ratio = float(max_spread_to_target_ratio)
        self.min_liquidity_score = float(min_liquidity_score)
        self.max_open_positions = int(max_open_positions)
        self.max_positions_per_market = int(max_positions_per_market)
        self.max_positions_per_desk = int(max_positions_per_desk)
        self.max_positions_per_asset_class = int(max_positions_per_asset_class)
        self.max_total_risk_percent = float(max_total_risk_percent)
        self.min_volatility_bps = float(min_volatility_bps)
        self.cost_model = ReplayExecutionModel()
        self.sizer = ReplayPositionSizer(max_risk_fraction=0.01)
        self.signal_evaluator = StrategySignalEvaluator()

    def evaluate(
        self,
        *,
        strategy: PromotedIntradayStrategy,
        data: IntradayDataBundle,
        portfolio: IntradayPortfolioState,
        desk: str,
        benchmark_ticker: str,
        asset_type: str = "Stock",
    ) -> IntradayDecision:
        base = dict(
            ticker=data.ticker,
            market=data.market,
            desk=desk,
            benchmark_ticker=benchmark_ticker,
            strategy_id=strategy.strategy_id,
            validation_id=strategy.validation_id,
            setup_type=strategy.setup_type,
            decision_timestamp=data.as_of,
        )
        if not data.ready:
            return IntradayDecision(INTRADAY_DATA_BLOCKED, data.blockers[0] if data.blockers else "DATA_BLOCKED", "Strict timeframe data is incomplete or stale.", **base)
        ticker = data.ticker.upper()
        if ticker in portfolio.open_tickers:
            return IntradayDecision(INTRADAY_BLOCKED, "TICKER_CONCENTRATION", "One intraday position per ticker is already open.", **base)
        if portfolio.total_open_positions >= self.max_open_positions:
            return IntradayDecision(INTRADAY_BLOCKED, "MAX_OPEN_POSITIONS", "Portfolio open-position limit reached.", **base)
        if portfolio.positions_by_market.get(data.market, 0) >= self.max_positions_per_market:
            return IntradayDecision(INTRADAY_BLOCKED, "MARKET_CONCENTRATION", "Market concentration limit reached.", **base)
        if portfolio.positions_by_desk.get(desk, 0) >= self.max_positions_per_desk:
            return IntradayDecision(INTRADAY_BLOCKED, "DESK_CONCENTRATION", "Desk concentration limit reached.", **base)
        if portfolio.positions_by_asset_class.get(asset_type, 0) >= self.max_positions_per_asset_class:
            return IntradayDecision(INTRADAY_BLOCKED, "ASSET_CLASS_CONCENTRATION", "Asset-class concentration limit reached.", **base)
        if portfolio.total_risk_percent >= self.max_total_risk_percent:
            return IntradayDecision(INTRADAY_BLOCKED, "TOTAL_RISK_LIMIT", "Portfolio paper-risk limit reached.", **base)

        spec = ExecutableStrategySpec.from_payload(strategy.executable_strategy)
        signal = self.signal_evaluator.evaluate(
            spec,
            data.bars,
            as_of=data.as_of,
            market=data.market,
        )
        regime = signal.regime
        if signal.status == "blocked":
            return IntradayDecision(
                INTRADAY_BLOCKED,
                signal.reason_code,
                "Current point-in-time evidence contradicts the validated strategy contract.",
                regime=regime,
                evidence={"strategy_fingerprint": spec.fingerprint, "signal_evidence": signal.evidence},
                **base,
            )
        if signal.status != "triggered":
            return IntradayDecision(
                INTRADAY_WATCHLIST,
                signal.reason_code,
                "The validated strategy exists, but its exact entry condition has not triggered.",
                regime=regime,
                evidence={"strategy_fingerprint": spec.fingerprint, "signal_evidence": signal.evidence},
                **base,
            )

        execution_bars = data.bars[spec.execution_timeframe]
        latest = execution_bars[-1]
        entry = float(latest.close)
        geometry = self.signal_evaluator.geometry(spec, entry_price=entry, execution_history=execution_bars)
        atr = geometry.atr
        volatility_bps = atr / entry * 10_000
        if volatility_bps < self.min_volatility_bps:
            return IntradayDecision(INTRADAY_BLOCKED, "VOLATILITY_TOO_LOW", "Observed one-minute volatility is too low for costs and execution risk.", volatility_bps=volatility_bps, regime=regime, **base)
        trigger = data.bars["1m"]
        volumes = [float(row.volume or 0.0) for row in trigger[-20:]]
        asset_type_key = str(asset_type or "").lower()
        is_forex = asset_type_key in {"forex", "fx", "currency"} or str(data.market or "").upper() in {"FOREX", "FX"}
        if is_forex and not any(volume > 0 for volume in volumes):
            liquidity_score = max(35.0, min(85.0, min(data.quality_scores.values())))
            liquidity_method = "major_fx_quote_continuity_proxy"
        else:
            latest_volume = volumes[-1]
            average_volume = max(1.0, mean(volumes))
            liquidity_score = max(0.0, min(100.0, 55.0 + (latest_volume / average_volume - 1.0) * 30.0))
            liquidity_method = "reported_relative_volume"
        if liquidity_score < self.min_liquidity_score:
            return IntradayDecision(INTRADAY_BLOCKED, "LIQUIDITY_TOO_LOW", "Observed one-minute liquidity is below the configured threshold.", liquidity_score=liquidity_score, volatility_bps=volatility_bps, regime=regime, **base)

        from app.services.market_clock import MarketClock
        session = MarketClock().session(data.market, data.as_of)
        if session != "regular":
            return IntradayDecision(INTRADAY_BLOCKED, "SESSION_NOT_ALLOWED", "The current timestamp is outside the permitted regular session.", liquidity_score=liquidity_score, volatility_bps=volatility_bps, regime=regime, session=session, **base)

        cost = self.cost_model.profile(market=data.market, asset_type=asset_type, liquidity_score=liquidity_score, session=session)
        stop = geometry.stop_price
        target = geometry.target_price
        expected_move_bps = (target - entry) / entry * 10_000
        net_expectancy_bps = expected_move_bps - cost.total_round_trip_bps
        costs = cost.to_dict()
        if expected_move_bps < self.min_expected_move_bps:
            return IntradayDecision(INTRADAY_BLOCKED, "EXPECTED_MOVE_TOO_SMALL", "Expected move is below the configured minimum.", entry_price=entry, stop_price=stop, target_price=target, expected_move_bps=expected_move_bps, net_expectancy_bps=net_expectancy_bps, liquidity_score=liquidity_score, volatility_bps=volatility_bps, regime=regime, session=session, costs=costs, **base)
        if net_expectancy_bps <= 0:
            return IntradayDecision(INTRADAY_BLOCKED, "COSTS_KILL_EDGE", "Round-trip costs eliminate expected edge.", entry_price=entry, stop_price=stop, target_price=target, expected_move_bps=expected_move_bps, net_expectancy_bps=net_expectancy_bps, liquidity_score=liquidity_score, volatility_bps=volatility_bps, regime=regime, session=session, costs=costs, **base)
        if cost.spread_bps / max(expected_move_bps, 0.01) > self.max_spread_to_target_ratio:
            return IntradayDecision(INTRADAY_BLOCKED, "SPREAD_TOO_WIDE", "Estimated spread is too large relative to the target.", costs=costs, **base)

        confidence = min(95.0, strategy.walk_forward_score)
        expectancy_r = strategy.metrics.get("expectancy_r")
        if expectancy_r is None:
            expectancy_r = strategy.metrics.get("net_expectancy_r")
        edge_score = min(100.0, 50.0 + float(expectancy_r or 0.0) * 100.0)
        if confidence < strategy.minimum_confidence or edge_score < strategy.minimum_edge_score:
            return IntradayDecision(INTRADAY_BLOCKED, "QUANT_EDGE_BELOW_THRESHOLD", "Promoted strategy does not meet current confidence or Quant Edge threshold.", confidence=confidence, edge_score=edge_score, regime=regime, session=session, costs=costs, **base)
        size = self.sizer.size(
            capital=portfolio.capital,
            entry=entry,
            stop=stop,
            atr=atr,
            liquidity_score=liquidity_score,
            confidence=confidence,
            edge_score=edge_score,
            data_quality=min(data.quality_scores.values()),
            regime_alignment=80.0,
        )
        if size.units <= 0:
            return IntradayDecision(INTRADAY_BLOCKED, size.blocker or "SIZING_BLOCKED", "Dynamic position sizing rejected the setup.", **base)
        evidence_lane = str(strategy.metrics.get("evidence_lane") or "certified_paper")
        risk_multiplier = max(0.05, min(1.0, float(strategy.metrics.get("paper_risk_multiplier") or 1.0)))
        sizing = IntradayPositionSize(
            round(size.units * risk_multiplier, 6),
            round(size.notional * risk_multiplier, 4),
            round(size.risk_amount * risk_multiplier, 4),
            round(size.risk_fraction * 100.0 * risk_multiplier, 6),
            f"Volatility, liquidity, confidence, edge, regime, data quality and stop distance; {evidence_lane} risk multiplier {risk_multiplier:.2f}.",
        )
        return IntradayDecision(
            INTRADAY_TRADE_CANDIDATE,
            "APPROVED",
            "Promoted strategy passed strict multi-timeframe, cost, liquidity, session and concentration gates.",
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            trailing_stop=geometry.trailing_stop,
            confidence=confidence,
            edge_score=edge_score,
            expected_move_bps=expected_move_bps,
            net_expectancy_bps=net_expectancy_bps,
            liquidity_score=liquidity_score,
            volatility_bps=volatility_bps,
            regime=regime,
            session=session,
            costs=costs,
            sizing=sizing,
            evidence={
                "timeframes": list(strategy.timeframe_stack),
                "strategy_fingerprint": spec.fingerprint,
                "executable_strategy": spec.to_payload(),
                "signal_evidence": signal.evidence,
                "maximum_holding_minutes": spec.maximum_holding_bars * timeframe_minutes(spec.execution_timeframe),
                "data_timestamps": {key: value.isoformat() if value else None for key, value in data.latest_timestamps.items()},
                "data_quality_scores": dict(data.quality_scores),
                "evidence_lane": evidence_lane,
                "paper_risk_multiplier": risk_multiplier,
                "certified_for_copy_readiness": bool(strategy.metrics.get("certified_for_copy_readiness", evidence_lane == "certified_paper")),
                "liquidity_method": liquidity_method,
            },
            **base,
        )


def session_name(market: str, utc_hour: int) -> str:
    key = str(market or "").upper()
    if key in {"FOREX", "FX", "CURRENCY"}:
        return "regular"
    if key in {"USA", "US", "UNITED STATES"}:
        return "regular" if 13 <= utc_hour <= 20 else "closed"
    if key in {"ITALY", "GERMANY", "FRANCE", "EUROPE"}:
        return "regular" if 7 <= utc_hour <= 16 else "closed"
    return "closed"


def timeframe_minutes(timeframe: str) -> int:
    return {"1m": 1, "5m": 5, "15m": 15, "1d": 1_440}.get(timeframe, 1)
