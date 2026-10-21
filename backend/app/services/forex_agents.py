from __future__ import annotations

from dataclasses import asdict
from math import sqrt

from app.services.forex_contracts import (
    AgentMarketInput,
    ForexDirection,
    ForexStrategyEvidence,
    ForexTradeProposal,
    MacroOutput,
    MarketContextOutput,
    PriceActionOutput,
    RiskObjectionOutput,
    pair_config,
)
from app.services.forex_broker import BlumForexBrokerProfileService
from app.core.config import get_settings


def _trend(values: tuple[float, ...], lookback: int = 10) -> ForexDirection:
    if len(values) < lookback + 1:
        return ForexDirection.ABSTAIN
    change = values[-1] - values[-lookback]
    threshold = max(abs(values[-1]) * 0.00005, 1e-9)
    if change > threshold:
        return ForexDirection.LONG
    if change < -threshold:
        return ForexDirection.SHORT
    return ForexDirection.WATCH


class BlumForexMarketContextAgent:
    def analyze(self, market: AgentMarketInput) -> MarketContextOutput:
        blockers = tuple(market.blockers())
        direction = _trend(market.frames["1h"].closes) if "1h" in market.frames else ForexDirection.ABSTAIN
        active_macro = (market.macro_event_impact,) if market.macro_event_impact != "LOW_IMPACT" else ()
        return MarketContextOutput(
            regime="trend" if direction in {ForexDirection.LONG, ForexDirection.SHORT} else "range",
            directional_bias=direction,
            volatility_state="expanding" if market.volatility_score >= 0.6 else "normal",
            session_state=market.session,
            liquidity_state="sufficient" if market.liquidity_score >= 0.5 else "low",
            data_quality=min((frame.quality_score for frame in market.frames.values()), default=0.0),
            active_macro_risks=active_macro,
            confidence=0.8 if not blockers else 0.0,
            blockers=blockers,
        )


class BlumForexPriceActionAgent:
    def analyze(self, market: AgentMarketInput) -> PriceActionOutput:
        config = pair_config(market.pair)
        directions = [_trend(market.frames[key].closes) for key in ("15m", "5m", "1m") if key in market.frames]
        direction = directions[0] if directions and all(item == directions[0] for item in directions) else ForexDirection.WATCH
        entry = (market.quote.bid + market.quote.ask) / 2
        stop_pips = 5.0
        target_pips = 10.0
        sign = 1 if direction == ForexDirection.LONG else -1
        stop = entry - sign * stop_pips * config.pip_size
        target = entry + sign * target_pips * config.pip_size
        return PriceActionOutput(
            setup_family="momentum_breakout" if direction in {ForexDirection.LONG, ForexDirection.SHORT} else "avoid_no_edge",
            direction=direction,
            setup_quality=0.82 if direction in {ForexDirection.LONG, ForexDirection.SHORT} else 0.2,
            trigger="1m close confirms aligned 15m/5m structure",
            entry_zone=(market.quote.bid, market.quote.ask),
            stop_level=stop,
            target_levels=(target, entry + sign * 15 * config.pip_size),
            invalidation="1m close through the structural stop",
            expected_holding_minutes=30,
            expected_gross_pips=target_pips,
            technical_evidence=tuple(f"{key}_aligned" for key in ("15m", "5m", "1m") if key in market.frames),
            confidence=0.82 if direction in {ForexDirection.LONG, ForexDirection.SHORT} else 0.2,
        )


class BlumForexMacroAgent:
    def analyze(self, market: AgentMarketInput) -> MacroOutput:
        blocked = False
        if market.macro_event_impact == "HIGH_IMPACT":
            settings = get_settings()
            if market.macro_event_timestamp is None:
                blocked = True
            else:
                minutes_to_event = (market.macro_event_timestamp - market.as_of).total_seconds() / 60.0
                blocked = -max(0, settings.forex_news_block_after_minutes) <= minutes_to_event <= max(
                    0,
                    settings.forex_news_block_before_minutes,
                )
        information = market.information_context
        if information and (information.asset_key != market.pair or information.decision_at != market.as_of):
            raise ValueError("Forex information context must match the exact pair and decision clock")
        features = information.features if information else {}
        delta = features.get("policy_differential_change_bps")
        score = float(delta) if delta is not None else 0.0
        macro_bias = ForexDirection.LONG if score > 0 else ForexDirection.SHORT if score < 0 else ForexDirection.WATCH
        calendar = information.calendar_state if information else "UNKNOWN"
        blocked = blocked or calendar == "KNOWN_EVENT_WINDOW"
        return MacroOutput(
            macro_bias=macro_bias,
            event_risk=market.macro_event_impact,
            news_window_status="BLOCKED" if blocked else "CLEAR" if calendar == "KNOWN_CLEAR" else "UNKNOWN",
            cross_asset_confirmation="UNAVAILABLE",
            cross_asset_divergence=None,
            confidence=.5 if delta is not None else 0.0,
            veto_reason="NEWS_WINDOW_BLOCKED" if blocked else None,
        )


class BlumForexScalpingExpertAgent:
    def propose(
        self,
        market: AgentMarketInput,
        context: MarketContextOutput,
        price_action: PriceActionOutput,
        macro: MacroOutput,
        strategy: ForexStrategyEvidence,
    ) -> ForexTradeProposal:
        config = pair_config(market.pair)
        spread_pips = (market.quote.ask - market.quote.bid) / config.pip_size
        broker = BlumForexBrokerProfileService().get()
        slippage_pips = broker.slippage_pips * (
            1.0
            + max(0.0, 0.75 - market.liquidity_score) * 2.0
            + max(0.0, market.volatility_score - 0.5) * 1.5
        )
        if market.macro_event_impact == "MEDIUM_IMPACT":
            slippage_pips *= 1.5
        elif market.macro_event_impact == "HIGH_IMPACT":
            slippage_pips *= 3.0
        commission_pips = max(
            broker.minimum_commission,
            broker.commission_per_lot_round_trip * 0.01,
        ) / max(config.pip_value_per_standard_lot * 0.01, 1e-9)
        expected_costs = spread_pips + 2 * slippage_pips + commission_pips
        net = price_action.expected_gross_pips - expected_costs
        canonical = bool(price_action.strategy_fingerprint and price_action.executable_strategy)
        aligned = price_action.direction in {ForexDirection.LONG, ForexDirection.SHORT} and (
            canonical or price_action.direction == context.directional_bias
        )
        eligible = strategy.readiness in {strategy.readiness.PAPER_TRADE_ELIGIBLE, strategy.readiness.ALPHA_SIGNAL_ELIGIBLE}
        direction = price_action.direction if aligned and eligible and net > 0 and not price_action.blockers else ForexDirection.ABSTAIN
        setup_confidence = max(0.0, min(1.0, price_action.confidence))
        timeframe_confidence = 1.0 if aligned else 0.2
        data_confidence = max(0.0, min(1.0, context.confidence))
        expectancy_confidence = max(0.0, min(1.0, strategy.net_expectancy_r + 0.55))
        sample_weight = max(0.0, min(1.0, strategy.sample_size / 300.0))
        strategy_confidence = 0.35 + sample_weight * (expectancy_confidence - 0.35)
        execution_confidence = max(
            0.0,
            min(1.0, net / max(price_action.expected_gross_pips, 1e-9)),
        )
        knowledge_context = _matching_contextual_memory(
            strategy.contextual_memory,
            session=market.session,
            regime=context.regime,
            setup_family=price_action.setup_family,
            direction=price_action.direction.value,
        )
        memory_adjustment = (
            max(-0.08, min(0.08, float(knowledge_context.get("confidence_adjustment") or 0.0)))
            if knowledge_context.get("status") in {"CONTEXT_ELIGIBLE", "POLICY_ELIGIBLE"}
            else 0.0
        )
        decision_confidence = max(0.0, min(1.0, (
            setup_confidence * 0.30
            + timeframe_confidence * 0.20
            + data_confidence * 0.20
            + strategy_confidence * 0.20
            + execution_confidence * 0.10
            + memory_adjustment
        )))
        confidence_components = {
            "setup_confidence": round(setup_confidence * 100.0, 6),
            "timeframe_confidence": round(timeframe_confidence * 100.0, 6),
            "data_confidence": round(data_confidence * 100.0, 6),
            "strategy_confidence": round(strategy_confidence * 100.0, 6),
            "execution_confidence": round(execution_confidence * 100.0, 6),
            "decision_confidence": round(decision_confidence * 100.0, 6),
            "strategy_sample_size": float(strategy.sample_size),
            "contextual_memory_adjustment": round(memory_adjustment * 100.0, 6),
        }
        return ForexTradeProposal(
            pair=market.pair,
            direction=direction,
            strategy_id=strategy.strategy_id,
            setup_family=price_action.setup_family,
            entry=(market.quote.bid + market.quote.ask) / 2,
            stop=price_action.stop_level,
            target=price_action.target_levels[0],
            secondary_target=price_action.target_levels[1] if len(price_action.target_levels) > 1 else None,
            invalidation=price_action.invalidation,
            expected_holding_minutes=price_action.expected_holding_minutes,
            expected_gross_pips=price_action.expected_gross_pips,
            expected_cost_pips=expected_costs,
            expected_net_pips=net,
            expected_r=net / max(abs((market.quote.bid + market.quote.ask) / 2 - price_action.stop_level) / config.pip_size, 1e-9),
            confidence=decision_confidence,
            supporting_evidence=price_action.technical_evidence,
            conflicting_evidence=tuple(item for item in (macro.veto_reason,) if item),
            reason_to_trade="Aligned multi-timeframe setup with positive expected net edge" if direction != ForexDirection.ABSTAIN else None,
            reason_to_abstain=None if direction != ForexDirection.ABSTAIN else "No aligned, eligible positive-net-edge setup",
            confidence_components=confidence_components,
            actionability_status="PROPOSED" if direction != ForexDirection.ABSTAIN else "TRAINING_ONLY",
            knowledge_context=knowledge_context,
            evidence_lane=strategy.evidence_lane,
            certified_for_copy_readiness=bool(
                strategy.certified_for_copy_readiness and canonical and not price_action.blockers
                and price_action.strategy_fingerprint == strategy.strategy_fingerprint
            ),
            strategy_fingerprint=price_action.strategy_fingerprint,
            executable_strategy=dict(price_action.executable_strategy),
            execution_timeframe=price_action.execution_timeframe,
            maximum_holding_bars=price_action.maximum_holding_bars,
            trailing_stop=price_action.trailing_stop,
            feature_schema_hash=price_action.feature_schema_hash,
        )


class BlumForexContrarianRiskAgent:
    def challenge(
        self,
        market: AgentMarketInput,
        proposal: ForexTradeProposal,
        context: MarketContextOutput,
        macro: MacroOutput,
        strategy: ForexStrategyEvidence,
    ) -> RiskObjectionOutput:
        objections = list(context.blockers)
        config = pair_config(market.pair)
        spread_pips = (market.quote.ask - market.quote.bid) / config.pip_size
        if market.session not in {"LONDON", "LONDON_NEW_YORK_OVERLAP", "NEW_YORK"}:
            objections.append("SESSION_NOT_ALLOWED")
        if context.liquidity_state != "sufficient":
            objections.append("LIQUIDITY_TOO_LOW")
        if macro.veto_reason and not strategy.is_news_strategy:
            objections.append(macro.veto_reason)
        if spread_pips > min(3.0, proposal.expected_gross_pips * 0.25):
            objections.append("SPREAD_TOO_WIDE")
        if proposal.expected_cost_pips - spread_pips >= proposal.expected_gross_pips:
            objections.append("SLIPPAGE_KILLS_EDGE")
        if proposal.expected_net_pips <= 0:
            objections.append("NO_NET_EDGE")
        if proposal.direction == ForexDirection.ABSTAIN:
            objections.append("NO_NET_EDGE")
        if strategy.readiness not in {strategy.readiness.PAPER_TRADE_ELIGIBLE, strategy.readiness.ALPHA_SIGNAL_ELIGIBLE}:
            objections.append("STRATEGY_NOT_READY")
        if (
            proposal.knowledge_context.get("status") == "POLICY_ELIGIBLE"
            and float(proposal.knowledge_context.get("confidence_adjustment") or 0.0) <= -0.03
        ):
            objections.append("POLICY_NEGATIVE_EDGE")
        unique = tuple(dict.fromkeys(objections))
        return RiskObjectionOutput(
            objections=unique,
            severity="HIGH" if unique else "LOW",
            risk_reduction=1.0 if unique else 0.0,
            veto=bool(unique),
            veto_reason=unique[0] if unique else None,
        )


def serialize_agent_outputs(**outputs) -> dict:
    return {key: asdict(value) for key, value in outputs.items()}


def _matching_contextual_memory(
    memory: dict,
    *,
    session: str,
    regime: str,
    setup_family: str,
    direction: str | None = None,
) -> dict:
    cells = memory.get("cells") if isinstance(memory, dict) else None
    if not isinstance(cells, list):
        return {"status": "NO_CONTEXT", "confidence_adjustment": 0.0}
    matching = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        stored_session = str(cell.get("session") or "UNKNOWN")
        stored_regime = str(cell.get("regime") or "UNKNOWN")
        stored_setup = _normalized_setup_family(str(cell.get("setup_family") or "UNKNOWN"))
        stored_direction = str(cell.get("direction") or "ALL")
        if (
            stored_session in {session, "UNKNOWN", "ALL"}
            and stored_regime in {regime, "UNKNOWN", "ALL"}
            and stored_setup in {
                _normalized_setup_family(setup_family),
                "UNKNOWN",
                "ALL",
            }
            and (
                stored_direction in {"ALL", "UNKNOWN"}
                or direction is None
                or stored_direction == direction
            )
        ):
            adjustment = max(
                -0.08,
                min(0.08, float(cell.get("confidence_adjustment") or 0.0)),
            )
            sample_size = int(cell.get("sample_size") or 0)
            status = str(cell.get("status") or "")
            minimum = 12 if adjustment < 0 and status == "POLICY_ELIGIBLE" else 30
            if (
                status not in {"CONTEXT_ELIGIBLE", "POLICY_ELIGIBLE"}
                or adjustment == 0.0
                or sample_size < minimum
            ):
                continue
            scope = str(cell.get("policy_scope") or "FULL_CONTEXT")
            specificity = {
                "STRATEGY": 1.0,
                "SETUP": 2.0,
                "REGIME_SETUP": 3.0,
                "FULL_CONTEXT": 4.0,
            }.get(scope, 4.0)
            matching.append(
                {
                    **cell,
                    "policy_scope": scope,
                    "confidence_adjustment": adjustment,
                    "sample_size": sample_size,
                    "resolution_weight": sqrt(sample_size) * specificity,
                }
            )
    if not matching:
        return {"status": "NO_MATCHING_CONTEXT", "confidence_adjustment": 0.0}

    total_weight = sum(float(row["resolution_weight"]) for row in matching)
    adjustment = sum(
        float(row["confidence_adjustment"]) * float(row["resolution_weight"])
        for row in matching
    ) / max(total_weight, 1e-9)
    adjustment = max(-0.08, min(0.08, adjustment))
    causes: dict[str, int] = {}
    for row in matching:
        for cause, count in (row.get("failure_causes") or {}).items():
            causes[str(cause)] = causes.get(str(cause), 0) + int(count or 0)
    dominant_cause = max(causes, key=causes.get) if causes else None
    policy_trace = [
        {
            "memory_id": row.get("memory_id"),
            "policy_scope": row["policy_scope"],
            "sample_size": row["sample_size"],
            "q_value": row.get("q_value", row.get("net_expectancy_r")),
            "confidence_adjustment": row["confidence_adjustment"],
            "resolution_weight": round(float(row["resolution_weight"]), 6),
            "failure_causes": row.get("failure_causes") or {},
        }
        for row in matching
    ]
    return {
        "status": (
            "POLICY_ELIGIBLE"
            if any(row.get("source") == "reinforcement_policy" for row in matching)
            else "CONTEXT_ELIGIBLE"
        ),
        "sample_size": max(row["sample_size"] for row in matching),
        "confidence_adjustment": adjustment,
        "hierarchical_policy_adjustment": adjustment,
        "policy_trace": policy_trace,
        "dominant_failure_cause": dominant_cause,
        "explanation": (
            "Eligible hierarchical policy memory resolved with specificity-weighted backoff."
        ),
    }


def _normalized_setup_family(value: str) -> str:
    aliases = {
        "intraday_breakout": "momentum_breakout",
        "session_breakout": "momentum_breakout",
        "pullback": "pullback_to_trend",
    }
    return aliases.get(value, value)
