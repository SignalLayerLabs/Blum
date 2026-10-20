from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
import logging
from math import ceil
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    ForexDecision,
    ForexLearningEvidence,
    ForexContextualMemory,
    ForexPolicyState,
    ForexPosition,
    ForexStrategyReadiness,
    ForexTraderCycle,
    ForexTraderRuntimeState,
    LiveForwardPaperGame,
    ReplayMarketBar,
)
from app.services.forex_agents import (
    BlumForexContrarianRiskAgent,
    BlumForexMacroAgent,
    BlumForexMarketContextAgent,
    BlumForexPriceActionAgent,
    BlumForexScalpingExpertAgent,
    serialize_agent_outputs,
)
from app.services.forex_broker import BlumForexBrokerProfileService
from app.services.forex_contracts import (
    AgentMarketInput,
    EvaluationOutcome,
    ForexDirection,
    ForexOrderRequest,
    ForexQuote,
    ForexReadiness,
    ForexStrategyEvidence,
    pair_config,
)
from app.services.forex_execution import BlumForexExecutionSimulator
from app.services.forex_learning import BlumForexLearningEngine
from app.services.forex_reinforcement import ForexReinforcementPolicyService
from app.services.financial_model_council import FinancialModelCouncil
from app.services.forex_risk import BlumForexPortfolioRiskEngine, ForexPortfolioState
from app.services.promoted_strategy_registry import BlumPromotedStrategyRegistry
from app.services.replay_data import MultiProviderReplayDataService
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.trading_ml.finrlx import FinRLXQuantEngine
from app.services.trading_ml.finrlx_overlay import FinRLXDecisionOverlay
from app.services.trading_ml.inference import TradingMLInferenceService, advice_payload
from app.services.trading_ml.forex_history import ForexHistoricalKnowledgeService
from app.core.config import get_settings


logger = logging.getLogger(__name__)


class BlumForexPositionManagerAgent:
    """Manages only persisted Forex paper positions against observed quotes."""

    def __init__(self) -> None:
        self.execution = BlumForexExecutionSimulator()
        self.brokers = BlumForexBrokerProfileService()
        self.learning = BlumForexLearningEngine()
        self.reinforcement = ForexReinforcementPolicyService()
        self.model_council = FinancialModelCouncil()

    def manage(self, db: Session, quotes: dict[str, ForexQuote], *, now: datetime) -> dict:
        updated, closed = 0, []
        positions = db.scalars(select(ForexPosition).where(ForexPosition.status.in_(["OPEN", "SETTLEMENT_PENDING"])).order_by(ForexPosition.id).limit(20)).all()
        for position in positions:
            if (position.contract_json or {}).get("accounting_version") == "forex-cashflow-v2":
                from app.services.forex_cash_accounting import ForexCashAccounting
                if position.contract_json.get('account_id'):
                    margin_state = ForexCashAccounting().margin_state(db, account_id=position.contract_json['account_id'], quotes=quotes, broker=self.brokers.get(), now=now)
                    from copy import deepcopy
                    contract = deepcopy(position.contract_json)
                    contract['margin_state'] = margin_state
                    if margin_state['breached']:
                        contract['accounting']['exit_reason'] = 'MARGIN_STOP_OUT'
                    position.contract_json = contract
                result = ForexCashAccounting().manage(position, quotes, self.brokers.get(), self.execution, now=now)
                game = db.scalar(select(LiveForwardPaperGame).where(LiveForwardPaperGame.game_id == position.contract_json['account_id']).with_for_update()) if position.contract_json.get('account_id') else db.scalar(select(LiveForwardPaperGame).where(LiveForwardPaperGame.status == "active").order_by(desc(LiveForwardPaperGame.started_at)).limit(1).with_for_update())
                if game and (game.configuration or {}).get("account_currency", "EUR") == position.contract_json.get("account_currency"):
                    game.current_capital += result["cash_delta"]
                    game.cash += result["cash_delta"] + (result["margin_released"] if (position.contract_json.get('accounting') or {}).get('entry_cash_posted') else 0)
                    game.realized_pl += result["cash_delta"]
                    game.exposure = max(0.0, game.exposure-result["margin_released"])
                    if result["exited_now"]:
                        game.open_positions = max(0, game.open_positions-1)
                    game.updated_at = now
                if result["completed"]:
                    self._record_closed_outcome(db, position, position.contract_json, position.closed_at, position.exit_price)
                    closed.append(position.position_uid)
                updated += 1
                continue
            quote = quotes.get(position.pair)
            if quote is None or quote.timestamp > now or (now - quote.timestamp).total_seconds() > 180:
                continue
            current = quote.bid if position.direction == "LONG" else quote.ask
            position.current_price = current
            position.last_managed_at = now
            signed_move = (current - position.entry_price) * (1 if position.direction == "LONG" else -1)
            position.mfe = max(position.mfe, signed_move)
            position.mae = min(position.mae, signed_move)
            contract = dict(position.contract_json or {})
            request = ForexOrderRequest(
                position.pair,
                ForexDirection(position.direction),
                "MARKET",
                position.quantity_lots,
                current,
                position.stop_price,
                position.target_price,
                session=str(contract.get("session") or "UNKNOWN"),
                liquidity_score=float(contract.get("liquidity_score") or 0.5),
                volatility_score=float(contract.get("volatility_score") or 0.5),
                event_impact=str(contract.get("event_impact") or "LOW_IMPACT"),
            )
            broker = self.brokers.get(contract.get("broker_profile", "paper_eu_30x"))
            valuation_fill = self.execution.close(request, quote, broker, reason="VALUATION", now=now)
            config = pair_config(position.pair)
            account_fx_rate = float(contract.get("account_fx_rate") or 1.0)
            mid = (quote.bid + quote.ask) / 2
            gross_pips = ((mid - float(contract.get("entry") or position.entry_price)) * (1 if position.direction == "LONG" else -1)) / config.pip_size
            unrealized_gross = gross_pips * config.pip_value_per_standard_lot * position.quantity_lots * account_fx_rate
            unrealized_net = (
                unrealized_gross
                - position.spread_cost
                - position.slippage_cost
                - position.commission
                - valuation_fill.total_cost
                + position.swap_accrued
            )
            initial_risk = abs(position.entry_price - position.stop_price) / config.pip_size * config.pip_value_per_standard_lot * position.quantity_lots * account_fx_rate
            contract["valuation"] = {
                "timestamp": now.isoformat(),
                "bid": quote.bid,
                "ask": quote.ask,
                "unrealized_gross_pnl": unrealized_gross,
                "unrealized_net_pnl": unrealized_net,
                "current_r": unrealized_net / initial_risk if initial_risk else None,
                "spread_impact": valuation_fill.spread_cost,
                "strategy_valid": True,
                "regime_valid": None,
                "source": quote.source,
            }
            position.contract_json = contract
            reason = None
            if position.direction == "LONG":
                reason = "STOP_HIT" if quote.bid <= position.stop_price else "TARGET_HIT" if quote.bid >= position.target_price else None
            else:
                reason = "STOP_HIT" if quote.ask >= position.stop_price else "TARGET_HIT" if quote.ask <= position.target_price else None
            accrued_nights = int(contract.get("swap_nights_accrued") or 0)
            elapsed_nights = max(0, (now.date() - position.opened_at.date()).days)
            if elapsed_nights > accrued_nights:
                for offset in range(accrued_nights, elapsed_nights):
                    weekday = (position.opened_at + timedelta(days=offset + 1)).weekday()
                    position.swap_accrued += self.execution.accrue_swap(request, broker, nights=1, weekday=weekday)
                contract["swap_nights_accrued"] = elapsed_nights
                position.contract_json = contract
            max_minutes = int(contract.get("expected_holding_minutes") or 30)
            if reason is None and (now - position.opened_at).total_seconds() >= max_minutes * 60:
                reason = "TIME_STOP"
            if reason:
                fill = self.execution.close(request, quote, broker, reason=reason, now=now)
                if fill.status not in {"FILLED", "PARTIALLY_FILLED"} or fill.fill_price is None or fill.filled_quantity_lots <= 0:
                    contract["last_exit_attempt"] = {"at":now.isoformat(), **_jsonable(asdict(fill))}
                    position.contract_json = contract
                    updated += 1
                    continue
                position.status = "CLOSED"
                position.closed_at = now
                position.exit_price = fill.fill_price
                position.exit_reason = reason
                theoretical_entry = float(contract.get("entry") or position.entry_price)
                theoretical_exit = (quote.bid + quote.ask) / 2
                gross_pips = ((theoretical_exit - theoretical_entry) * (1 if position.direction == "LONG" else -1)) / config.pip_size
                account_fx_rate = float(contract.get("account_fx_rate") or 1.0)
                position.gross_pnl = gross_pips * config.pip_value_per_standard_lot * position.quantity_lots * account_fx_rate
                position.spread_cost += fill.spread_cost
                position.slippage_cost += fill.slippage_cost
                position.commission += fill.commission
                position.net_pnl = position.gross_pnl - position.spread_cost - position.slippage_cost - position.commission + position.swap_accrued
                risk = abs(position.entry_price - position.stop_price) / config.pip_size * config.pip_value_per_standard_lot * position.quantity_lots
                position.realized_r = position.net_pnl / risk if risk else None
                self._record_closed_outcome(db, position, contract, now, current)
                game = db.scalar(select(LiveForwardPaperGame).where(LiveForwardPaperGame.status == "active").order_by(desc(LiveForwardPaperGame.started_at)).limit(1))
                if game:
                    game.current_capital += position.net_pnl
                    game.cash += position.net_pnl
                    game.realized_pl += position.net_pnl
                    game.exposure = max(0.0, game.exposure - position.margin_used)
                    game.open_positions = max(0, game.open_positions - 1)
                    game.updated_at = now
                closed.append(position.position_uid)
            updated += 1
        db.flush()
        return {"positions_updated": updated, "trades_closed": len(closed), "closed_position_ids": closed}


    def _record_closed_outcome(self, db, position, contract, now, current):
        contract = dict(contract)
        outcome = "WIN" if position.net_pnl > 0 else "LOSS" if position.net_pnl < 0 else "BREAKEVEN"
        benchmark_excess = self._benchmark_excess(db, position, now, current)
        evidence = self.learning.record_outcome(db, decision_id=position.decision_id, outcome=outcome, payload={
            "position_id": position.id, "strategy_id": position.strategy_id, "pair": position.pair,
            "direction": position.direction, "expected_result": contract.get("expected_r"),
            "realized_result": position.realized_r, "benchmark_excess": benchmark_excess,
            "likely_cause": position.exit_reason, "evidence_strength": 0.8,
            "session": contract.get("session"), "regime": contract.get("regime"),
            "setup_family": contract.get("setup_family"),
            "timeframe_stack": ["1h", "15m", "5m", "1m"],
            "news_state": contract.get("event_impact"),
            "spread_model": "quoted_or_broker_dynamic_v1",
            "slippage_model": "broker_base_x_liquidity_x_volatility_x_event_v1",
            "holding_model": "strategy_contract_time_stop_v1",
            "risk_gate_accuracy": "TO_BE_EVALUATED",
            "evidence_lane": contract.get("evidence_lane"),
            "certified_for_copy_readiness": bool(contract.get("certified_for_copy_readiness", False)),
        })
        if evidence is not None:
            policy_update = self.reinforcement.observe(db, evidence)
            reward = (evidence.payload_json or {}).get("reinforcement_reward_r")
            model_evaluation = (
                self.model_council.evaluate_outcome(
                    db,
                    decision_id=position.decision_id,
                    reward_r=float(reward),
                )
                if reward is not None
                else {"votes_evaluated": 0}
            )
            contract["learning_update"] = {
                "evidence_id": evidence.id,
                "policy": policy_update,
                "model_council": model_evaluation,
            }
            position.contract_json = contract
            self.learning.refresh_readiness(
                db,
                ForexStrategyEvidence(
                    strategy_id=position.strategy_id,
                    readiness=ForexReadiness.PAPER_TRADE_ELIGIBLE,
                    sample_size=int(contract.get("strategy_sample_size") or 0),
                    net_expectancy_r=float(contract.get("expected_r") or 0.0),
                    replay_forward_decay=_number(contract.get("replay_forward_decay")),
                    currency_concentration=_number(contract.get("currency_concentration")),
                ),
            )

    @staticmethod
    def _benchmark_excess(db: Session, position: ForexPosition, now: datetime, current_price: float) -> float | None:
        benchmark = db.scalar(select(Asset).where(Asset.ticker == "UUP"))
        if benchmark is None:
            return None
        start = db.scalar(select(ReplayMarketBar).where(ReplayMarketBar.asset_id == benchmark.id, ReplayMarketBar.timeframe == "1m", ReplayMarketBar.bar_timestamp >= position.opened_at, ReplayMarketBar.bar_timestamp <= now).order_by(ReplayMarketBar.bar_timestamp).limit(1))
        end = db.scalar(select(ReplayMarketBar).where(ReplayMarketBar.asset_id == benchmark.id, ReplayMarketBar.timeframe == "1m", ReplayMarketBar.bar_timestamp <= now).order_by(desc(ReplayMarketBar.bar_timestamp)).limit(1))
        if start is None or end is None or start.close <= 0:
            return None
        asset_return = (current_price / position.entry_price - 1.0) * (1 if position.direction == "LONG" else -1)
        benchmark_return = end.close / start.close - 1.0
        return asset_return - benchmark_return


class BlumForexTraderCore:
    """Only authoritative analysis-to-paper-order orchestrator for Forex."""

    def __init__(
        self,
        *,
        historical_knowledge_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.context = BlumForexMarketContextAgent()
        self.price_action = BlumForexPriceActionAgent()
        self.macro = BlumForexMacroAgent()
        self.scalper = BlumForexScalpingExpertAgent()
        self.contrarian = BlumForexContrarianRiskAgent()
        self.risk = BlumForexPortfolioRiskEngine()
        self.execution = BlumForexExecutionSimulator()
        self.brokers = BlumForexBrokerProfileService()
        self.learning = BlumForexLearningEngine()
        self.model_council = FinancialModelCouncil()
        self.manager = BlumForexPositionManagerAgent()
        self.supervised_advisor = TradingMLInferenceService()
        self.quant_advisor = FinRLXQuantEngine()
        self.quant_overlay = FinRLXDecisionOverlay()
        settings = get_settings()
        self.historical_knowledge = ForexHistoricalKnowledgeService(
            historical_knowledge_path
            or Path(settings.trading_ml_artifact_root)
            / "forex_historical_knowledge.json"
        )

    def evaluate_input(self, market: AgentMarketInput, *, strategy: ForexStrategyEvidence) -> EvaluationOutcome:
        context = self.context.analyze(market)
        price_action = self.price_action.analyze(market)
        macro = self.macro.analyze(market)
        proposal = self.scalper.propose(market, context, price_action, macro, strategy)
        historical = self.historical_knowledge.advise(
            pair=market.pair,
            closes=market.frames.get("1h").closes if market.frames.get("1h") else (),
        )
        if historical.status == "AVAILABLE":
            historical_payload = _jsonable(asdict(historical))
            adjustment = historical.confidence_adjustment
            proposal = replace(
                proposal,
                confidence=max(0.0, min(1.0, proposal.confidence + adjustment)),
                supporting_evidence=(
                    (*proposal.supporting_evidence, historical.explanation[0])
                    if adjustment > 0
                    else proposal.supporting_evidence
                ),
                conflicting_evidence=(
                    (*proposal.conflicting_evidence, historical.explanation[0])
                    if adjustment < 0
                    else proposal.conflicting_evidence
                ),
                confidence_components={
                    **dict(proposal.confidence_components or {}),
                    "historical_knowledge_adjustment": adjustment * 100.0,
                },
                knowledge_context={
                    **dict(proposal.knowledge_context or {}),
                    "historical_forex": historical_payload,
                },
            )
        objections = self.contrarian.challenge(market, proposal, context, macro, strategy)
        proposal = replace(
            proposal,
            actionability_status="BLOCKED" if objections.veto else "ACTIONABLE",
        )
        outputs = serialize_agent_outputs(context=context, price_action=price_action, macro=macro, contrarian=objections)
        return EvaluationOutcome(not objections.veto, proposal, objections.objections, _jsonable(outputs))

    def run_cycle(
        self,
        db: Session,
        *,
        inputs: list[AgentMarketInput],
        strategies: dict[str, ForexStrategyEvidence],
        now: datetime | None = None,
        cycle_key: str | None = None,
        trigger: str = "scheduled",
    ) -> dict:
        now = now or datetime.utcnow()
        cycle_key = cycle_key or f"{now.strftime('%Y%m%d%H%M')}:{trigger}"
        existing = db.scalar(select(ForexTraderCycle).where(ForexTraderCycle.cycle_key == cycle_key))
        if existing:
            if existing.status == "RUNNING" and now - existing.started_at > timedelta(seconds=60):
                existing.status = "DEGRADED"
                existing.completed_at = now
                existing.blockers = list(dict.fromkeys([*(existing.blockers or []), "RECOVERED_INTERRUPTED_CYCLE"]))
                existing.next_action = "Interrupted cycle quarantined; the scheduler may start a new minute without duplicating decisions."
                db.commit()
            return self._cycle_payload(existing, idempotent=True)
        started = time.perf_counter()
        configuration = {"risk_percent": 0.5, "daily_loss_limit": 2.0, "max_positions": 4, "broker": "paper_eu_30x"}
        cycle = ForexTraderCycle(
            cycle_uid=f"fx-cycle-{uuid4().hex}", cycle_key=cycle_key, status="RUNNING",
            session=inputs[0].session if inputs else None, started_at=now,
            pairs_scanned=[item.pair for item in inputs], configuration_hash=_hash(configuration),
            data_coverage_hash=_hash([item.data_hash() for item in inputs]), code_commit=_commit(),
        )
        db.add(cycle)
        db.flush()
        quotes = {item.pair: item.quote for item in inputs}
        managed = self.manager.manage(db, quotes, now=now)
        from app.services.forex_order_lifecycle import ForexOrderLifecycle
        advanced = ForexOrderLifecycle(brokers=self.brokers, execution=self.execution).process_batch(db, quotes=quotes, as_of=now)
        approved, rejected, orders, fills, learning_events, blockers = [], [], [], [], [], []
        fills.extend({"order_uid": item["order_uid"], "new_fills": item["new_fills"]} for item in advanced if item["new_fills"])
        agent_outputs = {}
        for market in inputs:
            strategy = strategies.get(market.pair)
            if strategy is None:
                strategy = ForexStrategyEvidence("unavailable", readiness=_training_level(), sample_size=0, net_expectancy_r=0.0)
            evaluation = self.evaluate_input(market, strategy=strategy)
            agent_outputs[market.pair] = evaluation.agent_outputs
            if not evaluation.approved and self._recent_equivalent_rejection(
                db,
                market=market,
                strategy=strategy,
                evaluation=evaluation,
                now=now,
            ):
                rejected.append({
                    "pair": market.pair,
                    "blockers": list(evaluation.blockers),
                    "deduplicated": True,
                })
                blockers.extend(evaluation.blockers)
                continue
            decision_uid = f"{cycle.cycle_uid}:{market.pair}:{strategy.strategy_id}"
            decision = ForexDecision(
                decision_uid=decision_uid, cycle_id=cycle.id, pair=market.pair, strategy_id=strategy.strategy_id,
                status="APPROVED" if evaluation.approved else "REJECTED", direction=evaluation.proposal.direction.value,
                decision_timestamp=now, blockers=list(evaluation.blockers), proposal_json=_jsonable(asdict(evaluation.proposal)),
                input_snapshot=self._input_snapshot(market),
            )
            db.add(decision)
            db.flush()
            context_output = evaluation.agent_outputs.get("context", {})
            price_output = evaluation.agent_outputs.get("price_action", {})
            ml_features = self._supervised_features(market, evaluation)
            supervised = self.supervised_advisor.advise(
                db,
                market_family="forex",
                features=ml_features,
                baseline_output={
                    "approved": evaluation.approved,
                    "confidence": evaluation.proposal.confidence,
                    "blockers": list(evaluation.blockers),
                    "expected_r": evaluation.proposal.expected_r,
                },
                deterministic_blockers=evaluation.blockers,
                source_object_type="forex_decision",
                source_object_id=str(decision.id),
                persist=True,
                decision_timestamp=now,
                asset_key=market.pair,
                setup_type=evaluation.proposal.setup_family,
                regime=str(context_output.get("regime") or "unknown"),
            )
            supervised_payload = advice_payload(supervised)
            bandit_delta = (
                float(evaluation.proposal.knowledge_context.get("confidence_adjustment") or 0.0)
                if evaluation.proposal.knowledge_context.get("status") in {"CONTEXT_ELIGIBLE", "POLICY_ELIGIBLE"}
                else 0.0
            )
            supervised_fraction = supervised.confidence_adjustment / 100.0
            remaining = max(0.0, 0.10 - abs(bandit_delta))
            applied_supervised_fraction = max(-remaining, min(remaining, supervised_fraction))
            if evaluation.blockers:
                applied_supervised_fraction = 0.0
            if supervised.veto_recommended and evaluation.approved:
                new_blockers = tuple(dict.fromkeys([*evaluation.blockers, "SUPERVISED_MODEL_NEGATIVE_EDGE"]))
                evaluation = replace(
                    evaluation,
                    approved=False,
                    blockers=new_blockers,
                    proposal=replace(
                        evaluation.proposal,
                        confidence=max(0.0, evaluation.proposal.confidence + applied_supervised_fraction),
                        actionability_status="BLOCKED",
                        reason_to_abstain="Validated supervised model indicates negative net edge.",
                        knowledge_context={
                            **dict(evaluation.proposal.knowledge_context or {}),
                            "supervised_model": supervised_payload,
                        },
                    ),
                )
            else:
                evaluation = replace(
                    evaluation,
                    proposal=replace(
                        evaluation.proposal,
                        confidence=max(0.0, min(1.0, evaluation.proposal.confidence + applied_supervised_fraction)),
                        knowledge_context={
                            **dict(evaluation.proposal.knowledge_context or {}),
                            "supervised_model": {
                                **supervised_payload,
                                "applied_confidence_adjustment": round(applied_supervised_fraction * 100.0, 4),
                                "combined_contextual_adjustment_points": round(
                                    (bandit_delta + applied_supervised_fraction) * 100.0,
                                    4,
                                ),
                            },
                        },
                    ),
                )
            decision.status = "APPROVED" if evaluation.approved else "REJECTED"
            decision.blockers = list(evaluation.blockers)
            decision.proposal_json = _jsonable(asdict(evaluation.proposal))
            quant_proposal = self.quant_advisor.propose(
                market_family="forex",
                features=ml_features,
                context={
                    "pair": market.pair,
                    "session": market.session,
                    "regime": context_output.get("regime"),
                    "setup_type": evaluation.proposal.setup_family,
                    "spread": market.quote.ask - market.quote.bid,
                    "decision_timestamp": now.isoformat(),
                },
                deterministic_blockers=evaluation.blockers,
            )
            quant_payload = quant_proposal.to_payload()
            quant_overlay = self.quant_overlay.evaluate(
                baseline_direction=evaluation.proposal.direction.value,
                baseline_confidence=evaluation.proposal.confidence,
                proposal=quant_proposal,
                deterministic_blockers=evaluation.blockers,
            )
            if quant_overlay.applied:
                overlay_blockers = tuple(evaluation.blockers)
                if quant_overlay.require_confirmation:
                    overlay_blockers = tuple(
                        dict.fromkeys([*overlay_blockers, "FINRLX_CONFIRMATION_REQUIRED"])
                    )
                evaluation = replace(
                    evaluation,
                    approved=evaluation.approved and not quant_overlay.require_confirmation,
                    blockers=overlay_blockers,
                    proposal=replace(
                        evaluation.proposal,
                        confidence=max(
                            0.0,
                            min(
                                1.0,
                                evaluation.proposal.confidence
                                + quant_overlay.confidence_adjustment,
                            ),
                        ),
                        actionability_status=(
                            "BLOCKED"
                            if quant_overlay.require_confirmation
                            else evaluation.proposal.actionability_status
                        ),
                        knowledge_context={
                            **dict(evaluation.proposal.knowledge_context or {}),
                            "finrlx_overlay": quant_overlay.to_payload(),
                        },
                    ),
                )
            quant_payload["decision_overlay"] = quant_overlay.to_payload()
            decision.status = "APPROVED" if evaluation.approved else "REJECTED"
            decision.blockers = list(evaluation.blockers)
            decision.proposal_json = _jsonable(asdict(evaluation.proposal))
            model_review = self.model_council.review_forex_decision(
                db,
                decision_id=decision.id,
                ticker=market.pair,
                evidence={
                    "approved": evaluation.approved,
                    "confidence": evaluation.proposal.confidence,
                    "blockers": list(evaluation.blockers),
                    "expected_net_pips": evaluation.proposal.expected_net_pips,
                    "context_direction": context_output.get("directional_bias"),
                    "price_direction": price_output.get("direction"),
                    "session": market.session,
                    "regime": context_output.get("regime"),
                    "setup_family": evaluation.proposal.setup_family,
                },
            )
            decision.proposal_json = {
                **dict(decision.proposal_json or {}),
                "model_council": model_review,
                "supervised_model": supervised_payload,
                "finrlx_quant": quant_payload,
            }
            if not evaluation.approved:
                from app.services.alpha_desk import AlphaCallRegistry
                AlphaCallRegistry().register(db, decision)
                rejected.append({"pair": market.pair, "blockers": list(evaluation.blockers)})
                blockers.extend(evaluation.blockers)
                continue
            state = self._portfolio_state(db, candidate_pair=market.pair)
            risk = self.risk.evaluate(evaluation.proposal, state, self.brokers.get(), quotes=quotes, now=now)
            decision.risk_json = _jsonable(asdict(risk))
            if not risk.decision.startswith("APPROVE"):
                decision.status = "REJECTED"
                decision.blockers = list(risk.blockers)
                from app.services.alpha_desk import AlphaCallRegistry
                AlphaCallRegistry().register(db, decision)
                rejected.append({"pair": market.pair, "blockers": list(risk.blockers)})
                blockers.extend(risk.blockers)
                evidence = self.learning.record_outcome(db, decision_id=decision.id, outcome="RISK_BLOCK_CORRECT", payload={
                    "strategy_id": strategy.strategy_id, "pair": market.pair, "session": market.session,
                    "regime": evaluation.agent_outputs.get("context", {}).get("regime"),
                    "setup_family": evaluation.proposal.setup_family,
                    "likely_cause": risk.decision,
                    "risk_gate_accuracy": "PROCESS_COMPLIANT_NOT_YET_OUTCOME_EVALUATED",
                })
                if evidence:
                    learning_events.append(evidence.outcome)
                continue
            from app.services.alpha_desk import AlphaCallRegistry
            decision.proposal_json = {**decision.proposal_json, 'strategy_readiness': strategy.readiness.value,
                'strategy_sample_size': strategy.sample_size, 'evidence_lane': strategy.evidence_lane,
                'certified_for_copy_readiness': strategy.certified_for_copy_readiness,
                'replay_forward_decay': strategy.replay_forward_decay, 'currency_concentration': strategy.currency_concentration}
            AlphaCallRegistry().register(db, decision)
            request = ForexOrderRequest.from_proposal(
                evaluation.proposal,
                quantity_lots=risk.quantity_lots,
                market=market,
            )
            from app.services.forex_order_lifecycle import ForexOrderLifecycle
            pending_order = ForexOrderLifecycle(brokers=self.brokers, execution=self.execution).submit(
                db, decision_id=decision.id, order=request,
                expires_at=now + timedelta(minutes=max(1, min(5, evaluation.proposal.expected_holding_minutes))))
            decision.status = "SUBMITTED"
            decision.execution_json = {"order_uid": pending_order.order_uid, "status": "SUBMITTED", "filled_quantity_lots": 0.0}
            approved.append({"pair": market.pair, "decision_uid": decision_uid})
            orders.append({"decision_uid": decision_uid, "status": "SUBMITTED"})
        cycle.status = "COMPLETED"
        cycle.completed_at = datetime.utcnow()
        cycle.duration_ms = (time.perf_counter() - started) * 1000
        cycle.agent_outputs = agent_outputs
        cycle.candidates_json = approved + rejected
        cycle.approved_candidates = approved
        cycle.rejected_candidates = rejected
        cycle.orders_json = orders
        cycle.fills_json = fills
        cycle.position_updates = [managed]
        cycle.closed_trades = managed["closed_position_ids"]
        cycle.blockers = list(dict.fromkeys(blockers))
        cycle.learning_events = learning_events
        cycle.next_action = self._next_action(approved, rejected, managed)
        for strategy in {item.strategy_id: item for item in strategies.values()}.values():
            self.learning.refresh_readiness(db, strategy)
        db.commit()
        return self._cycle_payload(cycle)

    @staticmethod
    def _portfolio_state(db: Session, *, candidate_pair: str | None = None) -> ForexPortfolioState:
        rows = db.scalars(select(ForexPosition).where(ForexPosition.status == "OPEN").limit(5)).all()
        payload = tuple({"pair": row.pair, "direction": row.direction,
            "notional": float((row.contract_json.get('accounting') or {}).get('entry_notional_account') or row.current_price * row.quantity_lots * 100_000)
                * float((row.contract_json.get('accounting') or {}).get('remaining_quantity_lots', row.quantity_lots)) / row.quantity_lots}
            for row in rows if row.quantity_lots > 0)
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        daily = db.scalar(select(func.coalesce(func.sum(ForexPosition.net_pnl), 0.0)).where(ForexPosition.status == "CLOSED", ForexPosition.closed_at >= today)) or 0.0
        margin = sum(row.margin_used for row in rows)
        game = db.scalar(select(LiveForwardPaperGame).where(LiveForwardPaperGame.status == "active").order_by(desc(LiveForwardPaperGame.started_at)).limit(1))
        from app.models import ForexPendingOrder
        pending = []
        if game:
            for order in db.scalars(select(ForexPendingOrder).where(ForexPendingOrder.account_id == game.game_id, ForexPendingOrder.status.in_(['SUBMITTED', 'PARTIALLY_FILLED']))):
                decision = db.get(ForexDecision, order.decision_id)
                reservation = float(decision.risk_json.get('margin_required') or 0) * order.remaining_lots / order.requested_lots
                margin += reservation
                pending.append({'pair': order.pair, 'direction': order.payload['side'], 'notional': reservation * 30})
        equity = float(game.current_capital) if game else 0.0
        drawdown = (
            max(0.0, (float(game.starting_capital) - equity) / float(game.starting_capital) * 100.0)
            if game and game.starting_capital > 0
            else 0.0
        )
        correlations = BlumForexTraderCore._pair_correlations(db, candidate_pair, rows) if candidate_pair else {}
        return ForexPortfolioState(
            equity=max(0.0, equity),
            daily_realized_pnl=float(daily),
            open_positions=payload,
            used_margin=margin,
            drawdown_percent=drawdown,
            pair_correlations=correlations,
            pending_orders=tuple(pending),
        )

    @staticmethod
    def _supervised_features(market: AgentMarketInput, evaluation: EvaluationOutcome) -> dict:
        proposal = evaluation.proposal
        context = evaluation.agent_outputs.get("context") or {}
        price = evaluation.agent_outputs.get("price_action") or {}
        quote = market.quote
        spread = max(0.0, quote.ask - quote.bid)
        return {
            "aggregate_score": proposal.confidence * 100.0,
            "confidence": proposal.confidence * 100.0,
            "trend_score": _number(context.get("trend_score") or context.get("confidence")),
            "momentum_score": _number(price.get("momentum_score") or price.get("confidence")),
            "volume_score": None,
            "volatility_score": market.volatility_score * 100.0,
            "support_resistance_score": _number(price.get("setup_quality")),
            "sentiment_score": None,
            "narrative_score": None,
            "fundamental_score": None,
            "regime_score": _number(context.get("confidence")),
            "expected_gross_r": proposal.expected_gross_pips,
            "expected_net_r": proposal.expected_r,
            "expected_cost": proposal.expected_cost_pips,
            "stop_distance": abs(proposal.entry - proposal.stop),
            "target_distance": abs(proposal.target - proposal.entry),
            "data_quality_score": min(frame.quality_score for frame in market.frames.values()) if market.frames else 0.0,
            "liquidity_score": market.liquidity_score,
            "spread": spread,
            "slippage": None,
            "volatility": market.volatility_score,
            "recent_return": None,
            "multi_timeframe_trend": _number(context.get("multi_timeframe_alignment")),
            "contextual_bandit_adjustment": _number(proposal.knowledge_context.get("confidence_adjustment")),
            "contextual_bandit_sample_size": _number(proposal.knowledge_context.get("sample_size")),
            "market_family": "forex",
            "setup_type": proposal.setup_family,
            "regime": str(context.get("regime") or "unknown"),
            "session": market.session,
            "direction": proposal.direction.value,
            "timeframe": "1m_5m_15m_1h",
            "sector_or_currency_family": market.pair[:3] + "/" + market.pair[3:],
        }

    @staticmethod
    def _pair_correlations(db: Session, candidate_pair: str, positions: list[ForexPosition]) -> dict[str, float]:
        candidate_asset = db.scalar(select(Asset).where(Asset.ticker == candidate_pair).limit(1))
        if candidate_asset is None or not positions:
            return {}
        candidate_closes = BlumForexTraderCore._recent_closes(db, candidate_asset.id)
        if len(candidate_closes) < 10:
            return {}
        values = []
        for position in positions[:4]:
            asset = db.scalar(select(Asset).where(Asset.ticker == position.pair).limit(1))
            if asset is None:
                continue
            correlation = _return_correlation(candidate_closes, BlumForexTraderCore._recent_closes(db, asset.id))
            if correlation is not None:
                values.append(abs(correlation))
        return {candidate_pair: max(values)} if values else {}

    @staticmethod
    def _recent_closes(db: Session, asset_id: int) -> list[float]:
        rows = db.scalars(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == asset_id, ReplayMarketBar.timeframe == "5m")
            .order_by(desc(ReplayMarketBar.bar_timestamp))
            .limit(60)
        ).all()
        return [float(row.close) for row in reversed(rows)]

    @staticmethod
    def _input_snapshot(market: AgentMarketInput) -> dict:
        return {
            "pair": market.pair, "as_of": market.as_of.isoformat(), "session": market.session,
            "macro_event_impact": market.macro_event_impact,
            "macro_event_timestamp": market.macro_event_timestamp.isoformat() if market.macro_event_timestamp else None,
            "liquidity_score": market.liquidity_score,
            "volatility_score": market.volatility_score,
            "macro_payload": _jsonable(market.macro_payload),
            "quote": _jsonable(asdict(market.quote)), "data_hash": market.data_hash(),
            "timeframes": {key: {"market_timestamp": value.market_timestamp.isoformat(), "acquired_at": value.acquired_at.isoformat(), "provider": value.provider, "quality_score": value.quality_score, "missing_intervals": list(value.missing_intervals), "adjustment_status": value.adjustment_status, "opens": list(value.opens), "highs": list(value.highs), "lows": list(value.lows), "closes": list(value.closes)} for key, value in market.frames.items()},
        }

    @staticmethod
    def _rejection_outcome(blockers: tuple[str, ...]) -> str:
        if "SPREAD_TOO_WIDE" in blockers or "NO_NET_EDGE" in blockers:
            return "EDGE_DESTROYED_BY_COSTS"
        if "STALE_DATA" in blockers or "TIMEFRAME_UNAVAILABLE" in blockers:
            return "DATA_BLOCKED"
        if "NEWS_WINDOW_BLOCKED" in blockers:
            return "NEWS_BLOCK_CORRECT"
        return "CORRECT_NO_TRADE"

    @staticmethod
    def _recent_equivalent_rejection(
        db: Session,
        *,
        market: AgentMarketInput,
        strategy: ForexStrategyEvidence,
        evaluation: EvaluationOutcome,
        now: datetime,
    ) -> bool:
        latest = db.scalar(
            select(ForexDecision)
            .where(
                ForexDecision.pair == market.pair,
                ForexDecision.strategy_id == strategy.strategy_id,
                ForexDecision.status == "REJECTED",
                ForexDecision.decision_timestamp >= now - timedelta(minutes=15),
                ForexDecision.decision_timestamp <= now,
            )
            .order_by(desc(ForexDecision.decision_timestamp), desc(ForexDecision.id))
            .limit(1)
        )
        if latest is None:
            return False
        return (
            tuple(latest.blockers or ()) == tuple(evaluation.blockers)
            and str(latest.direction or "") == evaluation.proposal.direction.value
        )

    @staticmethod
    def _next_action(approved, rejected, managed) -> str:
        if approved:
            return "Manage open paper positions against fresh 1m bid/ask evidence."
        if managed["positions_updated"]:
            return "Continue monitoring existing positions; no new eligible setup was approved."
        if rejected:
            return f"Wait and rescan; latest rejection: {rejected[0]['blockers'][0] if rejected[0]['blockers'] else 'NO_EDGE'}."
        return "Acquire strict 1H/15m/5m/1m Forex evidence before the next scan."

    @staticmethod
    def _cycle_payload(cycle: ForexTraderCycle, *, idempotent: bool = False) -> dict:
        return {
            "cycle_id": cycle.cycle_uid, "status": cycle.status, "idempotent": idempotent,
            "pairs_scanned": len(cycle.pairs_scanned or []), "positions_updated": sum(int(item.get("positions_updated") or 0) for item in (cycle.position_updates or [])),
            "setups_found": len(cycle.candidates_json or []), "candidates_approved": len(cycle.approved_candidates or []),
            "candidates_rejected": len(cycle.rejected_candidates or []), "trades_opened": len(cycle.fills_json or []),
            "trades_closed": len(cycle.closed_trades or []), "blockers": cycle.blockers or [],
            "learning_events": cycle.learning_events or [], "runtime_ms": cycle.duration_ms, "next_action": cycle.next_action,
        }


class ForexTraderSnapshotService:
    """Bounded, read-only projection. It never runs a cycle or writes state."""

    def read(self, db: Session, *, now: datetime | None = None) -> dict:
        now = now or datetime.utcnow()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        latest = db.scalar(select(ForexTraderCycle).order_by(desc(ForexTraderCycle.started_at), desc(ForexTraderCycle.id)).limit(1))
        current = db.scalar(
            select(ForexTraderCycle)
            .where(ForexTraderCycle.status == "RUNNING")
            .order_by(desc(ForexTraderCycle.started_at))
            .limit(1)
        )
        productive = db.scalar(select(ForexTraderCycle).where(ForexTraderCycle.approved_candidates != []).order_by(desc(ForexTraderCycle.started_at)).limit(1))
        runtime = db.scalar(select(ForexTraderRuntimeState).where(ForexTraderRuntimeState.runtime_key == "default").limit(1))
        today_cycles = db.scalars(
            select(ForexTraderCycle)
            .where(ForexTraderCycle.started_at >= day_start)
            .order_by(desc(ForexTraderCycle.started_at))
            .limit(1500)
        ).all()
        open_rows = db.scalars(select(ForexPosition).where(ForexPosition.status == "OPEN").order_by(desc(ForexPosition.opened_at)).limit(10)).all()
        closed_rows = db.scalars(select(ForexPosition).where(ForexPosition.status == "CLOSED", ForexPosition.closed_at >= day_start).order_by(desc(ForexPosition.closed_at)).limit(250)).all()
        readiness = db.scalars(select(ForexStrategyReadiness).order_by(desc(ForexStrategyReadiness.updated_at)).limit(50)).all()
        game = db.scalar(select(LiveForwardPaperGame).where(LiveForwardPaperGame.status == "active").order_by(desc(LiveForwardPaperGame.started_at)).limit(1))
        exposure = BlumForexPortfolioRiskEngine().currency_exposure(tuple(
            {"pair": row.pair, "direction": row.direction, "notional": row.current_price * row.quantity_lots * 100_000}
            for row in open_rows
        ))
        gross_exposure = sum(abs(value) for value in exposure.values())
        correlated_exposure = max((abs(value) for value in exposure.values()), default=0.0) / gross_exposure if gross_exposure else None
        daily_net_pnl = sum(row.net_pnl for row in closed_rows)
        reference_equity = float(game.current_capital) if game else None
        daily_loss_usage = (
            abs(min(0.0, daily_net_pnl)) / reference_equity * 100.0
            if reference_equity and reference_equity > 0
            else None
        )
        current_drawdown = (
            max(0.0, (float(game.starting_capital) - float(game.current_capital)) / float(game.starting_capital) * 100.0)
            if game and game.starting_capital > 0
            else None
        )
        blocker = None
        if not open_rows:
            if latest and latest.blockers:
                blocker = f"No open Forex paper trade: {latest.blockers[0]}."
            elif latest:
                blocker = "No open Forex paper trade: the latest cycle found no eligible positive-net-edge setup."
            else:
                blocker = "No Forex cycle has completed; strict 1H/15m/5m/1m evidence is not available yet."
        return {
            "trader_status": runtime.desired_state if runtime else "STARTING",
            "scheduler_status": runtime.scheduler_status if runtime else "STARTING",
            "current_cycle": self._brief(current),
            "last_completed_cycle": self._brief(latest),
            "last_productive_cycle": self._brief(productive),
            "current_session": latest.session if latest else None,
            "pairs_monitored": latest.pairs_scanned if latest else [],
            "pairs_blocked": latest.rejected_candidates if latest else [],
            "data_freshness": latest.completed_at.isoformat() if latest and latest.completed_at else None,
            "setups_found_today": sum(len(row.candidates_json or []) for row in today_cycles),
            "candidates_approved_today": sum(len(row.approved_candidates or []) for row in today_cycles),
            "candidates_rejected_today": sum(len(row.rejected_candidates or []) for row in today_cycles),
            "paper_orders_today": sum(len(row.orders_json or []) for row in today_cycles),
            "fills_today": sum(len(row.fills_json or []) for row in today_cycles),
            "open_positions": [self._position(row) for row in open_rows],
            "closed_positions_today": [self._position(row) for row in closed_rows],
            "gross_pnl": sum(row.gross_pnl for row in closed_rows) if closed_rows else None,
            "net_pnl": sum(row.net_pnl for row in closed_rows) if closed_rows else None,
            "spread_cost": sum(row.spread_cost for row in closed_rows) if closed_rows else None,
            "slippage_cost": sum(row.slippage_cost for row in closed_rows) if closed_rows else None,
            "commissions": sum(row.commission for row in closed_rows) if closed_rows else None,
            "swap": sum(row.swap_accrued for row in closed_rows) if closed_rows else None,
            "current_drawdown": current_drawdown,
            "daily_loss_usage": daily_loss_usage,
            "margin_usage": sum(row.margin_used for row in open_rows) if open_rows else None,
            "exposure_by_currency": exposure,
            "correlated_exposure": correlated_exposure,
            "strategies_in_training": sum(row.readiness_level == "TRAINING_SIGNAL" for row in readiness),
            "paper_eligible_strategies": sum(row.readiness_level == "PAPER_TRADE_ELIGIBLE" for row in readiness),
            "alpha_eligible_strategies": sum(row.readiness_level == "ALPHA_SIGNAL_ELIGIBLE" for row in readiness),
            "valid_no_trade_decisions": db.scalar(
                select(func.count(ForexLearningEvidence.id)).where(
                    ForexLearningEvidence.outcome.in_(["CORRECT_NO_TRADE", "EDGE_DESTROYED_BY_COSTS", "NEWS_BLOCK_CORRECT", "RISK_BLOCK_CORRECT"]),
                    ForexLearningEvidence.realized_result.is_not(None),
                )
            ) or 0,
            "exact_reason_if_no_trade_is_open": blocker,
            "active_blockers": latest.blockers if latest else ["NO_COMPLETED_CYCLE"],
            "next_action": latest.next_action if latest else "Wait for the background Forex scheduler; GET does not start trading work.",
            "evidence_policy": "Paper-only, point-in-time, no real broker and no fabricated fills or alpha.",
        }

    def publish(self, db: Session, *, now: datetime | None = None) -> dict:
        payload = self.read(db, now=now)
        snapshot = DashboardSnapshotService().write(
            db, "forex_trader_summary", payload,
            source_modules={"producer": "BlumForexTradingScheduler", "policy": "stored_projection_only"},
            ttl_seconds=180,
        )
        # Keep the product journal current after the authoritative Forex worker.
        from app.services.unified_paper_trading import UnifiedPaperTradingProjectionService

        try:
            UnifiedPaperTradingProjectionService().publish(db)
        except Exception:
            db.rollback()
            logger.exception("unified_paper_trading_snapshot_failed source=forex_trader")
        return snapshot

    def latest(self, db: Session) -> dict:
        snapshot = DashboardSnapshotService().latest(db, "forex_trader_summary")
        if snapshot.get("payload") is None:
            return {
                "status": "INITIALIZING", "snapshot_status": "missing",
                "exact_reason_if_no_trade_is_open": "No Forex trader snapshot has been produced yet.",
                "next_action": "The autonomous background scheduler will produce the snapshot; GET does not start work.",
                "data_freshness": None,
            }
        return {
            **snapshot["payload"], "snapshot_status": snapshot["status"],
            "snapshot_created_at": snapshot.get("created_at"), "snapshot_is_stale": snapshot.get("is_stale"),
            "snapshot_warnings": snapshot.get("warnings") or [],
        }

    @staticmethod
    def _brief(row):
        return None if row is None else {"cycle_id": row.cycle_uid, "status": row.status, "started_at": row.started_at.isoformat(), "completed_at": row.completed_at.isoformat() if row.completed_at else None}

    @staticmethod
    def _position(row):
        return {"position_id": row.position_uid, "pair": row.pair, "direction": row.direction, "status": row.status, "entry_price": row.entry_price, "current_price": row.current_price, "stop": row.stop_price, "target": row.target_price, "quantity_lots": row.quantity_lots, "net_pnl": row.net_pnl, "opened_at": row.opened_at.isoformat(), "closed_at": row.closed_at.isoformat() if row.closed_at else None}


class ForexMarketInputRepository:
    """Builds strict point-in-time inputs from already persisted Forex bars."""

    def load(self, db: Session, *, now: datetime, limit: int = 12) -> tuple[list[AgentMarketInput], list[dict]]:
        tickers = [item.ticker for item in pair_config.all()]
        assets = db.scalars(
            select(Asset).where(Asset.ticker.in_(tickers), Asset.is_active.is_(True)).order_by(Asset.id).limit(limit)
        ).all()
        output, blockers = [], []
        broker_profiles = BlumForexBrokerProfileService()
        session = forex_session(now)
        for asset in assets:
            frames = {}
            for timeframe in ("1h", "15m", "5m", "1m"):
                rows = db.scalars(
                    select(ReplayMarketBar)
                    .where(ReplayMarketBar.asset_id == asset.id, ReplayMarketBar.timeframe == timeframe, ReplayMarketBar.bar_timestamp <= now)
                    .order_by(desc(ReplayMarketBar.bar_timestamp)).limit(40)
                ).all()
                from app.services.market_clock import eligible_bar
                rows = [row for row in rows if eligible_bar(row, decision_at=None, as_of=now, mode='context')]
                if not rows:
                    continue
                rows = list(reversed(rows))
                from app.services.forex_contracts import MarketFrame
                frames[timeframe] = MarketFrame(
                    timeframe=timeframe, market_timestamp=rows[-1].bar_timestamp,
                    acquired_at=rows[-1].acquired_at, provider=rows[-1].provider,
                    opens=tuple(float(row.open if row.open is not None else row.close) for row in rows),
                    highs=tuple(float(row.high if row.high is not None else row.close) for row in rows),
                    lows=tuple(float(row.low if row.low is not None else row.close) for row in rows),
                    closes=tuple(float(row.close) for row in rows),
                    quality_score=min(float(row.data_quality_score or 0.0) for row in rows),
                    missing_intervals=tuple((rows[-1].source_metadata or {}).get("missing_intervals") or []),
                    adjustment_status=str((rows[-1].source_metadata or {}).get("adjustment_status") or "RAW"),
                )
            if "1m" not in frames:
                blockers.append({"pair": asset.ticker, "reason": "TIMEFRAME_UNAVAILABLE", "missing": [key for key in ("1h", "15m", "5m", "1m") if key not in frames]})
                continue
            metadata = dict(rows[-1].source_metadata or {}) if rows else {}
            bid, ask = _number(metadata.get("bid")), _number(metadata.get("ask"))
            if bid is None or ask is None or ask <= bid:
                mid = frames["1m"].closes[-1]
                estimated_pips = broker_profiles.estimate_spread_pips(
                    asset.ticker,
                    session=session,
                    liquidity_score=float(metadata.get("liquidity_score") or 0.75),
                    volatility_score=float(metadata.get("volatility_score") or 0.5),
                    event_impact=str(metadata.get("macro_event_impact") or "UNKNOWN"),
                )
                spread = estimated_pips * pair_config(asset.ticker).pip_size
                bid, ask, source = mid - spread / 2, mid + spread / 2, "ESTIMATED:broker_profile"
            else:
                source = str(metadata.get("quote_provider") or rows[-1].provider)
            output.append(AgentMarketInput(
                pair=asset.ticker, as_of=now, frames=frames,
                quote=ForexQuote(bid=bid, ask=ask, timestamp=frames["1m"].market_timestamp, source=source),
                session=session, macro_event_impact=str(metadata.get("macro_event_impact") or "UNKNOWN"),
                macro_event_timestamp=_datetime_value(metadata.get("macro_event_timestamp")),
                liquidity_score=float(metadata.get("liquidity_score") or 0.75),
                volatility_score=float(metadata.get("volatility_score") or 0.5),
                macro_payload={
                    key: metadata[key]
                    for key in (
                        "rate_differential_change",
                        "inflation_surprise",
                        "employment_surprise",
                        "dxy_change",
                        "yield_differential_change",
                        "risk_appetite_change",
                        "cross_asset_confirmation",
                        "cross_asset_divergence",
                    )
                    if key in metadata
                },
            ))
        return output, blockers


class ForexMarketDataRefreshService:
    """Refreshes one rotating pair's strict stack per cycle within a bounded budget."""

    def __init__(self) -> None:
        self.data = MultiProviderReplayDataService()

    def refresh(self, db: Session, *, now: datetime) -> dict:
        settings = get_settings()
        tickers = [item.ticker for item in pair_config.all()]
        assets = db.scalars(select(Asset).where(Asset.ticker.in_(tickers), Asset.is_active.is_(True)).order_by(Asset.id)).all()
        if not assets:
            return {"status": "DATA_BLOCKED", "refreshed": [], "blockers": ["NO_FOREX_ASSETS"]}
        freshness_budget = max(1, int(settings.forex_trader_freshness_budget_minutes))
        minimum_required = max(1, ceil(len(assets) / freshness_budget))
        count = min(
            len(assets),
            max(1, int(settings.forex_trader_max_pairs_per_cycle)),
            max(int(settings.forex_trader_refresh_pairs_per_cycle), minimum_required),
        )
        latest_rows = db.execute(
            select(ReplayMarketBar.asset_id, func.max(ReplayMarketBar.bar_timestamp))
            .where(
                ReplayMarketBar.asset_id.in_([asset.id for asset in assets]),
                ReplayMarketBar.timeframe == "1m",
            )
            .group_by(ReplayMarketBar.asset_id)
        ).all()
        latest_by_asset = {asset_id: timestamp for asset_id, timestamp in latest_rows}
        selected = sorted(
            assets,
            key=lambda asset: (latest_by_asset.get(asset.id) or datetime.min, asset.id),
        )[:count]
        results = []
        lookbacks = {
            "1h": timedelta(days=30),
            "15m": timedelta(days=10),
            "5m": timedelta(days=5),
            "1m": timedelta(days=2),
        }
        for asset in selected:
            stack = []
            for timeframe, lookback in lookbacks.items():
                coverage = self.data.ensure_coverage(
                    db,
                    asset=asset,
                    timeframe=timeframe,
                    start=now - lookback,
                    end=now,
                )
                stack.append({
                    "timeframe": timeframe,
                    "status": coverage.status,
                    "rows": coverage.rows_available,
                    "provider": coverage.provider,
                    "blockers": coverage.blockers,
                })
            results.append({
                "pair": asset.ticker,
                "status": "READY" if all(row["rows"] for row in stack) else "DATA_BLOCKED",
                "rows": sum(row["rows"] for row in stack),
                "timeframes": stack,
                "blockers": list(dict.fromkeys(code for row in stack for code in row["blockers"])),
            })
        db.commit()
        return {
            "status": "READY" if any(row["status"] == "READY" for row in results) else "DATA_BLOCKED",
            "refreshed": results,
            "blockers": list(dict.fromkeys(code for row in results for code in row["blockers"])),
            "freshness_budget_minutes": freshness_budget,
            "minimum_pairs_required": minimum_required,
            "pairs_selected": [asset.ticker for asset in selected],
        }


class ForexStrategyRepository:
    """Read-only bridge from validated strategy evidence into Forex contracts."""

    def load(self, db: Session, pairs: list[str]) -> dict[str, ForexStrategyEvidence]:
        registry = BlumPromotedStrategyRegistry()
        required_stack = ("1h", "15m", "5m", "1m")
        promoted = [row for row in registry.list_eligible(db, market="FOREX", asset_class="Forex") if tuple(row.timeframe_stack) == required_stack]
        experimental = [row for row in registry.list_experimental(db, market="FOREX", asset_class="Forex") if tuple(row.timeframe_stack) == required_stack]
        selected = promoted[0] if promoted else experimental[0] if experimental else None
        if selected is None:
            return {}
        current = db.scalar(select(ForexStrategyReadiness).where(ForexStrategyReadiness.strategy_id == selected.strategy_id))
        if current and current.readiness_level in {"DEGRADED", "SUSPENDED"}:
            return {}
        forward_gate = BlumForexLearningEngine().forward_gate(db, {selected.strategy_id})
        if forward_gate.status == "QUARANTINED":
            return {}
        from app.services.forex_contracts import ForexReadiness
        readiness = ForexReadiness(current.readiness_level) if current and current.readiness_level in {"PAPER_TRADE_ELIGIBLE", "ALPHA_SIGNAL_ELIGIBLE"} else ForexReadiness.PAPER_TRADE_ELIGIBLE
        expectancy = float(selected.metrics.get("net_expectancy_r") or selected.metrics.get("expectancy_r") or 0.0)
        memory_strategy_ids = {
            selected.strategy_id,
            str(selected.metrics.get("strategy_fingerprint") or ""),
            str(selected.executable_strategy.get("strategy_fingerprint") or ""),
        } - {""}
        memory_rows = db.scalars(
            select(ForexContextualMemory)
            .where(ForexContextualMemory.strategy_id.in_(memory_strategy_ids))
            .order_by(desc(ForexContextualMemory.sample_size), desc(ForexContextualMemory.updated_at))
            .limit(48)
        ).all()
        contextual_memory = {
            "cells": self._policy_cells(db, memory_strategy_ids) + [
                {
                    "memory_id": row.id,
                    "source": "contextual_memory",
                    "status": row.evidence_grade,
                    "session": row.session,
                    "regime": row.regime,
                    "setup_family": row.setup_family,
                    "sample_size": row.sample_size,
                    "net_expectancy_r": row.net_expectancy_r,
                    "benchmark_excess": row.benchmark_excess,
                    "confidence_adjustment": row.confidence_adjustment if row.evidence_grade == "CONTEXT_ELIGIBLE" else 0.0,
                    "explanation": row.explanation,
                }
                for row in memory_rows
            ]
        }
        contract = ForexStrategyEvidence(
            strategy_id=selected.strategy_id, readiness=readiness,
            sample_size=int(selected.validated_trade_count), net_expectancy_r=expectancy,
            replay_forward_decay=_number(selected.metrics.get("replay_forward_decay")),
            currency_concentration=_number(selected.metrics.get("currency_concentration")),
            active_blockers=tuple(selected.metrics.get("active_blockers") or ()),
            is_news_strategy=bool(selected.metrics.get("is_news_strategy")), strategy_version=selected.model_version,
            contextual_memory=contextual_memory,
            evidence_lane=str(selected.metrics.get("evidence_lane") or "certified_paper"),
            certified_for_copy_readiness=bool(selected.metrics.get("certified_for_copy_readiness", bool(promoted))),
        )
        return {pair: contract for pair in pairs}

    @staticmethod
    def _policy_cells(db: Session, strategy_ids: set[str]) -> list[dict]:
        if not strategy_ids:
            return []
        rows = db.scalars(
            select(ForexPolicyState)
            .where(ForexPolicyState.strategy_id.in_(strategy_ids))
            .order_by(desc(ForexPolicyState.sample_size), desc(ForexPolicyState.updated_at))
            .limit(48)
        ).all()
        return [
            {
                "memory_id": row.id,
                "source": "reinforcement_policy",
                "policy_scope": (
                    row.policy_key.split("|", 1)[0]
                    if row.policy_key.split("|", 1)[0] in {
                        "STRATEGY",
                        "SETUP",
                        "REGIME_SETUP",
                        "FULL_CONTEXT",
                    }
                    else "FULL_CONTEXT"
                ),
                "status": row.evidence_grade,
                "session": row.session,
                "regime": row.regime,
                "setup_family": row.setup_family,
                "direction": row.direction,
                "sample_size": row.sample_size,
                "q_value": row.q_value,
                "net_expectancy_r": row.q_value,
                "benchmark_excess": None,
                "failure_causes": row.cause_counts_json or {},
                "confidence_adjustment": (
                    row.confidence_adjustment
                    if row.evidence_grade == "POLICY_ELIGIBLE"
                    else 0.0
                ),
                "explanation": (
                    "Contextual paper reward policy; applied only after its confidence interval excludes zero."
                ),
            }
            for row in rows
        ]


class BlumForexTradingScheduler:
    """Persistent, non-overlapping command runner for the bounded Forex core."""

    lock_seconds = 55

    def __init__(self) -> None:
        self.core = BlumForexTraderCore()
        self.market_inputs = ForexMarketInputRepository()
        self.strategies = ForexStrategyRepository()
        self.refresh = ForexMarketDataRefreshService()

    def run_once(self, db: Session, *, now: datetime | None = None, inputs=None, strategies=None, cycle_key: str | None = None) -> dict:
        live_clock = now is None
        now = now or datetime.utcnow()
        FinancialModelCouncil().ensure_registered(db)
        state = self._state(db)
        if state.lock_expires_at and state.lock_expires_at > now and state.current_cycle_key != cycle_key:
            return {"status": "THROTTLED", "blockers": ["CYCLE_ALREADY_RUNNING"], "next_action": "Wait for the bounded cycle lock to expire."}
        state.heartbeat_at = now
        if state.desired_state in {"PAUSED", "EMERGENCY_STOP"}:
            loaded, data_blockers = (
                self.market_inputs.load(db, now=now, limit=get_settings().forex_trader_max_pairs_per_cycle)
                if inputs is None
                else (inputs, [])
            )
            managed = self.core.manager.manage(db, {item.pair: item.quote for item in loaded}, now=now)
            state.scheduler_status = "RISK_PAUSED"
            state.updated_at = now
            db.commit()
            return {"status": "RISK_PAUSED", **managed, "blockers": [state.desired_state], "next_action": "Position monitoring continues; new entries are blocked."}
        key = cycle_key or f"forex:{now.strftime('%Y%m%d%H%M')}"
        state.current_cycle_key = key
        state.lock_expires_at = now + timedelta(seconds=self.lock_seconds)
        state.scheduler_status = "RUNNING"
        db.commit()
        try:
            reinforcement_replay = self.core.manager.reinforcement.replay_pending(db, limit=50)
            data_blockers = []
            if inputs is None:
                refresh_result = self.refresh.refresh(db, now=now)
                # Data acquired during refresh was not available at cycle start.
                # An explicit injected `now` remains a fixed test/replay clock.
                if live_clock:
                    now = datetime.utcnow()
                inputs, data_blockers = self.market_inputs.load(
                    db,
                    now=now,
                    limit=get_settings().forex_trader_max_pairs_per_cycle,
                )
            else:
                refresh_result = {"status": "INJECTED_TEST_DATA", "refreshed": [], "blockers": []}
            if strategies is None:
                strategies = self.strategies.load(db, [item.pair for item in inputs])
            if forex_session(now) not in {"LONDON", "LONDON_NEW_YORK_OVERLAP", "NEW_YORK"}:
                managed = self.core.manager.manage(
                    db,
                    {item.pair: item.quote for item in inputs},
                    now=now,
                )
                from app.services.forex_order_lifecycle import ForexOrderLifecycle
                pending_results = ForexOrderLifecycle(brokers=self.core.brokers, execution=self.core.execution).process_batch(db, quotes={item.pair: item.quote for item in inputs}, as_of=now)
                state = self._state(db)
                state.scheduler_status = "MARKET_SESSION_MONITOR_ONLY"
                state.current_cycle_key = None
                state.lock_expires_at = None
                state.next_run_after = now + timedelta(minutes=1)
                state.heartbeat_at = now
                db.commit()
                ForexTraderSnapshotService().publish(db, now=now)
                return {
                    "status": "MONITOR_ONLY",
                    **managed,
                    "blockers": ["SESSION_NOT_ALLOWED"],
                    "market_refresh": refresh_result,
                    "reinforcement_replay": reinforcement_replay,
                    "next_action": "Monitor open paper positions; defer new entries until a permitted liquid session.",
                }
            result = self.core.run_cycle(db, inputs=inputs, strategies=strategies, now=now, cycle_key=key)
            state = self._state(db)
            state.scheduler_status = "DATA_BLOCKED" if not inputs else "RESEARCH_ONLY" if not strategies else "RUNNING"
            state.current_cycle_key = None
            state.lock_expires_at = None
            state.consecutive_failures = 0
            state.last_error = None
            state.next_run_after = now + timedelta(minutes=1)
            state.heartbeat_at = now
            if data_blockers:
                result["blockers"] = list(result.get("blockers") or []) + data_blockers
                cycle_uid = result.get("cycle_id")
                cycle = db.scalar(select(ForexTraderCycle).where(ForexTraderCycle.cycle_uid == cycle_uid)) if cycle_uid else None
                if cycle:
                    codes = [str(row.get("reason") or row) if isinstance(row, dict) else str(row) for row in data_blockers]
                    cycle.blockers = list(dict.fromkeys([*(cycle.blockers or []), *codes]))
                    cycle.next_action = "Hydrate missing strict Forex timeframes in background; do not substitute data."
                for blocked in data_blockers:
                    row = blocked if isinstance(blocked, dict) else {"reason": str(blocked)}
                    evidence = self.core.learning.record_outcome(
                        db,
                        decision_id=None,
                        outcome="DATA_BLOCKED",
                        payload={
                            "strategy_id": "data-readiness",
                            "pair": row.get("pair") or "unknown",
                            "session": forex_session(now),
                            "timeframe_stack": ["1h", "15m", "5m", "1m"],
                            "likely_cause": row.get("reason") or "TIMEFRAME_UNAVAILABLE",
                            "missing_intervals": row.get("missing") or [],
                            "evidence_strength": 1.0,
                        },
                    )
                    if evidence:
                        result.setdefault("learning_events", []).append(evidence.outcome)
                        if cycle:
                            cycle.learning_events = [*(cycle.learning_events or []), evidence.outcome]
            if now.weekday() >= 5:
                state.scheduler_status = "MARKET_CLOSED"
            result["market_refresh"] = refresh_result
            result["reinforcement_replay"] = reinforcement_replay
            db.commit()
            ForexTraderSnapshotService().publish(db, now=now)
            return result
        except Exception as exc:
            db.rollback()
            state = self._state(db)
            state.scheduler_status = "ERROR"
            state.current_cycle_key = None
            state.lock_expires_at = None
            state.consecutive_failures += 1
            state.last_error = f"{type(exc).__name__}: {exc}"
            state.next_run_after = now + timedelta(minutes=min(15, 2 ** min(state.consecutive_failures, 4)))
            db.commit()
            raise

    def start(self, db: Session) -> dict:
        return self._set(db, "RUNNING", "STARTING")

    def pause(self, db: Session) -> dict:
        return self._set(db, "PAUSED", "RISK_PAUSED")

    def resume(self, db: Session) -> dict:
        return self._set(db, "RUNNING", "STARTING")

    def emergency_stop(self, db: Session) -> dict:
        return self._set(db, "EMERGENCY_STOP", "RISK_PAUSED")

    def _set(self, db: Session, desired: str, status: str) -> dict:
        state = self._state(db)
        state.desired_state = desired
        state.scheduler_status = status
        state.updated_at = datetime.utcnow()
        db.commit()
        return {"desired_state": desired, "scheduler_status": status, "position_monitoring": True}

    @staticmethod
    def _state(db: Session) -> ForexTraderRuntimeState:
        state = db.scalar(select(ForexTraderRuntimeState).where(ForexTraderRuntimeState.runtime_key == "default"))
        if state is None:
            state = ForexTraderRuntimeState(runtime_key="default", desired_state="RUNNING", scheduler_status="STARTING")
            db.add(state)
            db.flush()
        return state


def forex_session(now: datetime) -> str:
    from app.services.market_clock import MarketClock
    return MarketClock().forex_session(now)


def _hash(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _datetime_value(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _commit() -> str | None:
    value = os.environ.get("SPACE_COMMIT_SHA") or os.environ.get("GIT_COMMIT")
    if value:
        return value[:40]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL, timeout=0.2).strip()[:40]
    except Exception:
        return None


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _training_level():
    from app.services.forex_contracts import ForexReadiness
    return ForexReadiness.TRAINING_SIGNAL


def _return_correlation(left: list[float], right: list[float]) -> float | None:
    size = min(len(left), len(right))
    if size < 10:
        return None
    left_returns = [left[index] / left[index - 1] - 1.0 for index in range(len(left) - size + 1, len(left))]
    right_returns = [right[index] / right[index - 1] - 1.0 for index in range(len(right) - size + 1, len(right))]
    if len(left_returns) != len(right_returns) or len(left_returns) < 9:
        return None
    left_mean = sum(left_returns) / len(left_returns)
    right_mean = sum(right_returns) / len(right_returns)
    covariance = sum((a - left_mean) * (b - right_mean) for a, b in zip(left_returns, right_returns))
    left_variance = sum((value - left_mean) ** 2 for value in left_returns)
    right_variance = sum((value - right_mean) ** 2 for value in right_returns)
    denominator = (left_variance * right_variance) ** 0.5
    return covariance / denominator if denominator > 0 else None
