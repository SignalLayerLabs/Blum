from __future__ import annotations

from app.services.market_clock import bar_available_at, eligible_bar

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta
from time import monotonic
from typing import Callable, Iterable
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    FeedbackLoopAudit,
    IntradayPaperRun,
    IntradayNoTradeDecision,
    LearningEvent,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    PaperExecutionOrder,
    ReplayMarketBar,
    SignalPerformance,
    StrategyMemory,
    TradeLearningEvidence,
    TradingGameTrade,
)
from app.services.intraday_contracts import (
    INTRADAY_TRADE_CANDIDATE,
    PAPER_FORWARD_INTRADAY,
    PAPER_FORWARD_INTRADAY_EXPERIMENTAL,
    IntradayDecision,
)
from app.services.intraday_market_data import StrictIntradayDataGateway
from app.services.intraday_opportunity import BlumIntradayOpportunityEngine, IntradayPortfolioState
from app.services.intraday_no_trade_learning import IntradayNoTradeLearningService
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
from app.services.cross_market_orchestrator import enabled_agents, parse_names
from app.services.copy_readiness_evidence import EvidenceTimelineService, strategy_identity
from app.services.forex_intraday_accounting import (
    forex_account_pnl,
    size_forex_intraday_position,
)
from app.services.market_desks import MarketDeskRegistry
from app.services.promoted_strategy_registry import BlumPromotedStrategyRegistry, normalize_market
from app.services.paper_execution_lifecycle import PaperOrderLifecycleService
from app.services.paper_forward_direction import (
    ACCOUNTING_VALID,
    ACCOUNTING_VERSION,
    LONG,
    SHORT,
    directional_excursions,
    exit_reason,
    normalize_side,
    paper_trade_evidence_is_eligible,
    signed_price_change,
    signed_return,
    trade_metrics,
)
from app.services.realistic_execution import ExecutionMarketBar, ExecutionOrderRequest
from app.services.trading_intelligence_lab import ensure_live_trade_game
from app.services.trading_ml.finrlx import FinRLXQuantEngine
from app.services.trading_ml.finrlx_overlay import FinRLXDecisionOverlay


INTRADAY_MODE = "INTRADAY_PAPER_FORWARD"
TERMINAL_STATUSES = {"CLOSED", "EXPIRED", "INVALIDATED"}
settings = get_settings()


class BlumIntradayPaperEngine:
    """Bounded command service for strict, forward-only intraday paper trades."""

    def __init__(
        self,
        *,
        registry: BlumPromotedStrategyRegistry | None = None,
        gateway: StrictIntradayDataGateway | None = None,
        opportunity: BlumIntradayOpportunityEngine | None = None,
        now_provider: Callable[[], datetime] = datetime.utcnow,
        refresh_missing: bool = True,
        max_assets: int | None = None,
        max_runtime_seconds: float | None = None,
        max_holding_minutes: int | None = None,
        account_currency: str | None = None,
        allow_overnight: bool | None = None,
    ):
        self.registry = registry or BlumPromotedStrategyRegistry()
        self.gateway = gateway or StrictIntradayDataGateway(
            refresh_missing=refresh_missing,
            max_one_minute_age=timedelta(minutes=settings.intraday_max_one_minute_age_minutes),
        )
        self.opportunity = opportunity or BlumIntradayOpportunityEngine(
            min_expected_move_bps=settings.intraday_min_expected_move_bps,
            max_spread_to_target_ratio=settings.intraday_max_spread_to_target_ratio,
            min_liquidity_score=settings.intraday_min_liquidity_score,
            max_open_positions=settings.intraday_max_open_positions,
            max_positions_per_market=settings.intraday_max_positions_per_market,
            max_positions_per_desk=settings.intraday_max_positions_per_desk,
            max_positions_per_asset_class=settings.intraday_max_positions_per_asset_class,
            max_total_risk_percent=settings.intraday_max_total_risk_percent,
            min_volatility_bps=settings.intraday_min_volatility_bps,
        )
        self.now_provider = now_provider
        self.max_assets = max(1, int(max_assets if max_assets is not None else settings.intraday_max_assets_per_run))
        self.max_runtime_seconds = max(1.0, float(max_runtime_seconds if max_runtime_seconds is not None else settings.intraday_max_runtime_seconds))
        self.max_holding_minutes = max(1, int(max_holding_minutes if max_holding_minutes is not None else settings.intraday_max_holding_minutes))
        self.account_currency = str(account_currency or settings.paper_execution_account_currency).upper()
        self.allow_overnight = settings.intraday_allow_overnight if allow_overnight is None else bool(allow_overnight)
        self.paper = LiveForwardPaperTradingService()
        self.execution = PaperOrderLifecycleService()
        self.learning = IntradayPaperLearningService()
        self.no_trade_learning = IntradayNoTradeLearningService(evaluation_minutes=settings.intraday_no_trade_evaluation_minutes)
        self.quant_advisor = FinRLXQuantEngine()
        self.quant_overlay = FinRLXDecisionOverlay()
        self._desk_context: dict[int, tuple[str, str]] = {}
        self._discovery_metadata: dict = {}

    def run_once(self, db: Session, *, trigger: str = "manual", assets: Iterable[Asset] | None = None) -> dict:
        if not settings.intraday_paper_enabled:
            return {"status": "DISABLED", "evidence_type": PAPER_FORWARD_INTRADAY, "blockers": ["intraday_paper_disabled"]}
        now = self.now_provider()
        started = monotonic()
        run = IntradayPaperRun(
            run_uid=f"intraday-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            trigger=trigger,
            status="RUNNING",
            started_at=now,
        )
        db.add(run)
        db.flush()
        blockers: list[dict] = []
        decisions: list[dict] = []
        try:
            game = self.paper.active_or_create_live_game(db)
            order_lifecycle = self._manage_pending_orders(db, game=game, now=now)
            trade_lifecycle = self._manage_open_trades(db, game=game, now=now)
            no_trade_lifecycle = self.no_trade_learning.evaluate_due(db, now=now)
            lifecycle = {"orders": order_lifecycle, "positions": trade_lifecycle, "no_trade": no_trade_lifecycle}
            run.trades_opened = order_lifecycle["trades_opened"]
            run.trades_updated = trade_lifecycle["trades_updated"]
            run.trades_closed = trade_lifecycle["trades_closed"]

            selected_assets = list(assets)[: self.max_assets] if assets is not None else self._discover_assets(db)
            if not selected_assets:
                blockers.append({"reason": "NO_DESK_ASSETS_WITH_INTRADAY_DATA", "detail": "No enabled USA/Europe desk asset currently has stored one-minute data."})
            run.assets_checked = 0
            seen_markets: set[str] = set()
            for asset in selected_assets:
                if monotonic() - started >= self.max_runtime_seconds:
                    blockers.append({"ticker": asset.ticker, "reason": "RUNTIME_BUDGET_EXHAUSTED"})
                    break
                market = normalize_market(asset.country or asset.exchange or "")
                seen_markets.add(market)
                run.assets_checked += 1
                strategies = self.registry.list_eligible(db, market=market, asset_class=asset.asset_type or asset.category or "Stock")
                evidence_lane = "certified_paper"
                if not strategies and settings.intraday_experimental_paper_enabled:
                    strategies = self.registry.list_experimental(
                        db,
                        market=market,
                        asset_class=asset.asset_type or asset.category or "Stock",
                    )
                    evidence_lane = "experimental_paper" if strategies else evidence_lane
                if not strategies and settings.intraday_experimental_paper_enabled:
                    strategies = [
                        self.registry.bootstrap_exploration(
                            market=market,
                            asset_class=asset.asset_type
                            or asset.category
                            or "Stock",
                        )
                    ]
                    evidence_lane = "bootstrap_exploration_paper"
                if not strategies:
                    blockers.append({"ticker": asset.ticker, "market": market, "reason": "NO_PROMOTED_INTRADAY_STRATEGY"})
                    continue
                data = self.gateway.load(db, asset=asset, now=now)
                if not data.ready:
                    blockers.append({"ticker": asset.ticker, "market": market, "reason": "INTRADAY_DATA_BLOCKED", "blockers": list(data.blockers)})
                    continue
                for strategy in strategies:
                    portfolio = self._portfolio_state(db, game)
                    desk, benchmark = self._desk_context.get(asset.id, desk_and_benchmark(asset))
                    decision = self.opportunity.evaluate(
                        strategy=strategy,
                        data=data,
                        portfolio=portfolio,
                        desk=desk,
                        benchmark_ticker=benchmark,
                        asset_type=asset.asset_type or "Stock",
                    )
                    decision = self._apply_quant_overlay(asset, decision)
                    decisions.append({**json_safe(decision.to_dict()), "evidence_lane": evidence_lane})
                    if decision.status != INTRADAY_TRADE_CANDIDATE:
                        self._count_rejection(run, decision.reason_code)
                        self.no_trade_learning.record(db, run=run, asset=asset, decision=decision)
                        continue
                    run.candidates_found += 1
                    trade, created = self._open_trade(db, game=game, run=run, asset=asset, decision=decision)
                    if created and trade.status != "DATA_BLOCKED":
                        run.candidates_approved += 1
                    elif created:
                        blockers.append({"ticker": trade.ticker, "reason": "FX_CONVERSION_UNAVAILABLE"})
                    else:
                        blockers.append({"ticker": trade.ticker, "reason": "DUPLICATE_INTRADAY_DECISION"})

            run.markets_checked = len(seen_markets)
            run.status = self._terminal_status(run=run, blockers=blockers, decisions=decisions)
            run.completed_at = now
            run.duration_seconds = round(monotonic() - started, 4)
            run.data_blockers = blockers
            run.summary_json = {
                "decisions": decisions[:50],
                "lifecycle": lifecycle,
                "asset_discovery": self._discovery_metadata,
                "policy": "Strict 1d/15m/5m/1m paper-forward evidence; no timeframe fallback or broker execution.",
            }
            self.paper.refresh_live_game_counts(db, game)
            db.commit()
            try:
                self.paper.publish_snapshot(db)
                db.commit()
            except Exception as snapshot_exc:
                db.rollback()
                blockers.append({"reason": "SNAPSHOT_REFRESH_FAILED", "detail": str(snapshot_exc)})
            return self._serialize_run(run, blockers)
        except Exception as exc:
            db.rollback()
            failed = IntradayPaperRun(
                run_uid=f"intraday-failed-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
                trigger=trigger,
                status="ERROR",
                started_at=now,
                completed_at=self.now_provider(),
                duration_seconds=round(monotonic() - started, 4),
                data_blockers=[{"reason": type(exc).__name__, "detail": str(exc)}],
                summary_json={"error": str(exc)},
            )
            db.add(failed)
            db.commit()
            return self._serialize_run(failed, failed.data_blockers)

    def run_execution_once(self, db: Session, *, trigger: str = "manual") -> dict:
        """Advance only persisted orders and positions; candidate discovery stays independent."""
        if not settings.intraday_paper_enabled:
            return {"status": "DISABLED", "trigger": trigger, "evidence_type": PAPER_FORWARD_INTRADAY}
        game = self.paper.active_or_create_live_game(db)
        now = self.now_provider()
        orders = self._manage_pending_orders(db, game=game, now=now)
        positions = self._manage_open_trades(db, game=game, now=now)
        no_trade = self.no_trade_learning.evaluate_due(db, now=now)
        self.paper.refresh_live_game_counts(db, game)
        db.commit()
        return {
            "status": "COMPLETED",
            "trigger": trigger,
            "evidence_type": PAPER_FORWARD_INTRADAY,
            "orders": orders,
            "positions": positions,
            "no_trade": no_trade,
            "policy": "Execution advances from stored future bars only; candidate discovery is not run.",
        }

    def _discover_assets(self, db: Session) -> list[Asset]:
        agent_types = enabled_agents(parse_names(settings.blum_enabled_market_desk_agents), stale_after_hours=settings.paper_forward_scan_stale_data_max_age_hours)
        discovery = MarketDeskRegistry(agents=agent_types).discover(db)
        ranked: list[Asset] = []
        seen: set[int] = set()
        for agent in discovery.available_agents:
            if agent.agent_name not in {"WallStreetAgent", "SP500Agent", "NasdaqAgent", "DowJonesAgent", "Russell2000Agent", "FTSEMIBAgent", "DAXAgent", "CAC40Agent", "ETFDeskAgent", "ForexDeskAgent"}:
                continue
            for asset in list(getattr(agent, "_eligible_assets", None) or []):
                if asset.id in seen:
                    continue
                seen.add(asset.id)
                self._desk_context[asset.id] = (agent.agent_name, agent.benchmark)
                ranked.append(asset)

        # Daily providers do not consistently expose FX symbols. Let the strict
        # intraday gateway hydrate configured pairs directly; it still blocks
        # candidates unless all four point-in-time timeframes are available.
        if any(agent.agent_name == "ForexDeskAgent" for agent in agent_types):
            forex_assets = db.scalars(
                select(Asset).where(
                    Asset.is_active.is_(True),
                    func.lower(Asset.asset_type).in_(["forex", "fx", "currency"]),
                )
            ).all()
            for asset in forex_assets:
                if asset.id in seen:
                    continue
                seen.add(asset.id)
                self._desk_context[asset.id] = ("ForexDeskAgent", "UUP")
                ranked.append(asset)

        ranked.sort(key=lambda row: (row.ticker.upper(), row.id))
        previous = db.scalar(
            select(IntradayPaperRun)
            .where(IntradayPaperRun.status != "RUNNING")
            .order_by(desc(IntradayPaperRun.id))
            .limit(1)
        )
        previous_discovery = (previous.summary_json or {}).get("asset_discovery") if previous else {}
        cursor_before = (previous_discovery or {}).get("cursor_after")
        start_index = 0
        if cursor_before is not None:
            for index, asset in enumerate(ranked):
                if asset.id == cursor_before:
                    start_index = (index + 1) % max(1, len(ranked))
                    break
        rotated = ranked[start_index:] + ranked[:start_index]
        selected = rotated[: self.max_assets]
        self._discovery_metadata = {
            "policy": "round_robin_stored_market_universe",
            "universe_size": len(ranked),
            "cursor_before": cursor_before,
            "cursor_after": selected[-1].id if selected else cursor_before,
            "selected_tickers": [asset.ticker for asset in selected],
        }
        return selected

    def _apply_quant_overlay(self, asset: Asset, decision: IntradayDecision) -> IntradayDecision:
        """Attach FinRL-X evidence and apply only a validated bounded overlay."""

        if decision.status != INTRADAY_TRADE_CANDIDATE:
            return decision
        is_forex = str(asset.asset_type or "").strip().lower() in {"forex", "fx", "currency"}
        market_family = "forex" if is_forex else "equity"
        costs = decision.costs or {}
        stop_distance = abs(float(decision.entry_price or 0.0) - float(decision.stop_price or 0.0))
        target_distance = abs(float(decision.target_price or 0.0) - float(decision.entry_price or 0.0))
        features = {
            "aggregate_score": decision.edge_score,
            "confidence": decision.confidence,
            "trend_score": decision.edge_score,
            "momentum_score": decision.edge_score,
            "volume_score": decision.liquidity_score,
            "volatility_score": decision.volatility_bps,
            "support_resistance_score": decision.edge_score,
            "sentiment_score": None,
            "narrative_score": None,
            "fundamental_score": None,
            "regime_score": decision.confidence,
            "expected_gross_r": target_distance / max(stop_distance, 1e-9),
            "expected_net_r": decision.net_expectancy_bps / max(decision.expected_move_bps, 1e-6),
            "expected_cost": costs.get("total_round_trip_bps"),
            "stop_distance": stop_distance,
            "target_distance": target_distance,
            "data_quality_score": min((decision.evidence.get("data_quality_scores") or {"minimum": 0.0}).values()),
            "liquidity_score": decision.liquidity_score,
            "spread": costs.get("spread_bps"),
            "slippage": costs.get("slippage_bps"),
            "volatility": decision.volatility_bps,
            "recent_return": None,
            "multi_timeframe_trend": decision.edge_score,
            "contextual_bandit_adjustment": 0.0,
            "contextual_bandit_sample_size": 0.0,
            "market_family": market_family,
            "setup_type": decision.setup_type,
            "regime": decision.regime,
            "session": decision.session,
            "direction": "LONG",
            "timeframe": "1m_5m_15m_1d",
            "sector_or_currency_family": asset.sector or asset.asset_type or "unknown",
        }
        proposal = self.quant_advisor.propose(
            market_family=market_family,
            features=features,
            context={
                "ticker": asset.ticker,
                "timestamp": decision.decision_timestamp.isoformat(),
                "setup_type": decision.setup_type,
                "regime": decision.regime,
            },
        )
        overlay = self.quant_overlay.evaluate(
            baseline_direction="LONG",
            baseline_confidence=decision.confidence / 100.0,
            proposal=proposal,
        )
        evidence = {
            **dict(decision.evidence or {}),
            "finrlx_quant": proposal.to_payload(),
            "finrlx_overlay": overlay.to_payload(),
        }
        if not overlay.applied:
            return replace(decision, evidence=evidence)
        confidence = max(
            0.0,
            min(100.0, decision.confidence + overlay.confidence_adjustment * 100.0),
        )
        if overlay.require_confirmation:
            return replace(
                decision,
                status=INTRADAY_WATCHLIST,
                reason_code="FINRLX_CONFIRMATION_REQUIRED",
                explanation="Validated FinRL-X policy disagrees with the baseline; no order is submitted until confirmation.",
                confidence=confidence,
                evidence=evidence,
            )
        return replace(decision, confidence=confidence, evidence=evidence)

    def _portfolio_state(self, db: Session, game: LiveForwardPaperGame) -> IntradayPortfolioState:
        rows = db.scalars(
            select(LiveForwardPaperTrade).where(
                LiveForwardPaperTrade.game_id == game.id,
                LiveForwardPaperTrade.trading_mode == INTRADAY_MODE,
                LiveForwardPaperTrade.status.in_(["ORDER_SUBMITTED", "PARTIALLY_FILLED", "OPEN"]),
            )
        ).all()
        markets = Counter(row.market or "UNKNOWN" for row in rows)
        desks = Counter(row.desk or "UNKNOWN" for row in rows)
        classes = Counter(row.asset_type or "UNKNOWN" for row in rows)
        return IntradayPortfolioState(
            capital=float(game.current_capital or game.starting_capital or 0.0),
            open_tickers=frozenset(row.ticker.upper() for row in rows),
            positions_by_market=dict(markets),
            positions_by_desk=dict(desks),
            positions_by_asset_class=dict(classes),
            total_open_positions=len(rows),
            total_risk_percent=sum(float(row.risk_percent or 0.0) for row in rows),
        )

    def _open_trade(
        self,
        db: Session,
        *,
        game: LiveForwardPaperGame,
        run: IntradayPaperRun,
        asset: Asset,
        decision: IntradayDecision,
    ) -> tuple[LiveForwardPaperTrade, bool]:
        trigger_timestamp = (decision.evidence.get("data_timestamps") or {}).get("1m") or decision.decision_timestamp.isoformat()
        strategy_fingerprint = str(decision.evidence.get("strategy_fingerprint") or f"validation-{decision.validation_id}")
        duplicate_key = f"intraday:{asset.ticker}:{strategy_fingerprint}:{trigger_timestamp}"
        existing = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.duplicate_key == duplicate_key).limit(1))
        if existing:
            return existing, False

        feedback = self.paper.feedback_metadata(db, ticker=asset.ticker, setup_type=decision.setup_type)
        evidence_lane = str(decision.evidence.get("evidence_lane") or "certified_paper")
        trade_evidence_type = (
            PAPER_FORWARD_INTRADAY
            if evidence_lane == "certified_paper"
            else PAPER_FORWARD_INTRADAY_EXPERIMENTAL
        )
        costs = decision.costs or {}
        observed_entry = float(decision.entry_price or 0.0)
        quantity = float(decision.sizing.quantity if decision.sizing else 0.0)
        is_forex = str(asset.asset_type or "").strip().lower() in {"forex", "fx", "currency"}
        account_fx_rate = point_in_time_fx_rate(
            db,
            asset_currency=asset.currency or "USD",
            account_currency=self.account_currency,
            at=decision.decision_timestamp,
        )
        forex_sizing = None
        risk_amount = float(decision.sizing.risk_amount if decision.sizing else 0.0)
        risk_percent = float(decision.sizing.risk_percent if decision.sizing else 0.0)
        notional_value = float(decision.sizing.notional if decision.sizing else 0.0)
        margin_reserved = notional_value
        if is_forex:
            evidence_multiplier = max(
                0.05,
                min(1.0, float(decision.evidence.get("paper_risk_multiplier") or 1.0)),
            )
            target_risk_fraction = (
                max(0.05, min(1.0, float(decision.confidence or 0.0) / 100.0))
                * max(0.05, min(1.0, float(decision.edge_score or 0.0) / 100.0))
                * 0.01
                * evidence_multiplier
            )
            forex_sizing = size_forex_intraday_position(
                capital_eur=float(game.current_capital or game.starting_capital or 0.0),
                risk_fraction=target_risk_fraction,
                entry_price=observed_entry,
                stop_price=float(decision.stop_price or observed_entry),
                account_fx_rate=account_fx_rate,
            )
            quantity = forex_sizing.quantity_units
            risk_amount = forex_sizing.risk_amount_eur
            risk_percent = forex_sizing.risk_fraction * 100.0
            notional_value = forex_sizing.notional_eur
            margin_reserved = forex_sizing.margin_eur
        liquidity_basis = "otc_quote_capacity" if is_forex else "reported_volume"
        quote_capacity_units = max(quantity * 20.0, quantity) if is_forex else None
        risk_per_share = max(0.0001, observed_entry - float(decision.stop_price or observed_entry))
        trade_side = LONG
        frozen = {
            "evidence_type": trade_evidence_type,
            "trading_mode": INTRADAY_MODE,
            "strategy": {
                "id": decision.strategy_id,
                "validation_id": decision.validation_id,
                "setup_type": decision.setup_type,
                "fingerprint": strategy_fingerprint,
                "executable_strategy": decision.evidence.get("executable_strategy") or {},
            },
            "decision_timestamp": decision.decision_timestamp.isoformat(),
            "direction": trade_side,
            "observed_entry_price": observed_entry,
            "paper_entry_fill": None,
            "stop_price": decision.stop_price,
            "target_price": decision.target_price,
            "costs": costs,
            "execution_liquidity": {
                "basis": liquidity_basis,
                "quote_capacity_units": quote_capacity_units,
                "reported_volume_required": not is_forex,
            },
            "accounting": {
                "model": "forex_margin_account_v1" if is_forex else "cash_equity_account_v1",
                "account_currency": self.account_currency,
                "account_fx_rate": account_fx_rate,
                "quantity_units": quantity,
                "quantity_lots": forex_sizing.quantity_lots if forex_sizing else None,
                "notional_eur": notional_value,
                "margin_reserved_eur": margin_reserved,
                "risk_amount_eur": risk_amount,
            },
            "evidence": decision.evidence,
            "regime": decision.regime,
            "session": decision.session,
            "feedback": feedback,
            "no_future_data_policy": "Only market bars timestamped at or before this decision were used.",
        }
        trade = LiveForwardPaperTrade(
            trade_uid=f"ipf-{decision.decision_timestamp.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            game_id=game.id,
            ticker=asset.ticker.upper(),
            asset_name=asset.name or asset.ticker,
            asset_type=asset.asset_type,
            sector=asset.sector,
            setup_type=decision.setup_type,
            side=trade_side,
            accounting_status=ACCOUNTING_VALID,
            accounting_version=ACCOUNTING_VERSION,
            status="ORDER_SUBMITTED",
            decision_timestamp=decision.decision_timestamp,
            decision_date=decision.decision_timestamp.date(),
            model_version_used=feedback["model_version_used"],
            weights_used=feedback["weights_used"],
            confidence_adjustment=float(feedback.get("confidence_adjustment") or 0.0),
            learning_memory_used=feedback["learning_memory_used"],
            strategy_memory_used=feedback["strategy_memory_used"],
            research_priority_used=feedback["research_priority_used"],
            frozen_decision_payload=frozen,
            trading_mode=INTRADAY_MODE,
            evidence_type=trade_evidence_type,
            promoted_validation_id=decision.validation_id,
            intraday_run_id=run.id,
            market=normalize_market(decision.market),
            desk=decision.desk,
            session_name=decision.session,
            timeframe_stack=["1d", "15m", "5m", "1m"],
            data_timestamps=decision.evidence.get("data_timestamps") or {},
            execution_costs=costs,
            net_expectancy_bps=decision.net_expectancy_bps,
            sizing_reason=decision.sizing.reason if decision.sizing else None,
            actionability_state="active_setup",
            confidence=decision.confidence,
            sniper_score=decision.edge_score,
            benchmark_ticker=decision.benchmark_ticker,
            entry_trigger="Strict 1m trigger after 5m confirmation inside 15m setup and 1d regime.",
            confirmation_condition=(
                "All certified-strategy and strict data gates passed."
                if evidence_lane == "certified_paper"
                else (
                    "Uncertified exploration contract passed strict data, "
                    "trigger, cost, liquidity, risk and execution gates."
                )
            ),
            entry_price=None,
            entry_date=None,
            opened_at=None,
            stop_loss=decision.stop_price,
            invalidation_level=decision.stop_price,
            target_1=decision.target_price,
            target_2=None,
            trailing_stop=decision.trailing_stop,
            position_size=0.0,
            notional_value=None,
            risk_amount=risk_amount,
            risk_percent=risk_percent,
            expected_risk=risk_amount,
            expected_reward=(
                forex_account_pnl(
                    entry_price=observed_entry,
                    exit_price=float(decision.target_price or observed_entry),
                    quantity_units=quantity,
                    account_fx_rate=account_fx_rate,
                    direction=trade_side,
                )
                if is_forex and account_fx_rate
                else quantity * max(0.0, float(decision.target_price or observed_entry) - observed_entry)
            ),
            expected_r_multiple=max(
                0.0,
                signed_price_change(
                    trade_side,
                    observed_entry,
                    float(decision.target_price or observed_entry),
                ),
            )
            / risk_per_share,
            current_price=observed_entry,
            last_managed_bar_at=decision.decision_timestamp,
            duplicate_key=duplicate_key,
            intraday_metadata={
                "observed_entry_price": observed_entry,
                "requested_quantity": quantity,
                "execution_accounted": False,
                "evidence_lane": evidence_lane,
                "certified_for_copy_readiness": evidence_lane == "certified_paper",
                "strategy_fingerprint": strategy_fingerprint,
                "maximum_holding_minutes": int(decision.evidence.get("maximum_holding_minutes") or self.max_holding_minutes),
                "liquidity_basis": liquidity_basis,
                "quote_capacity_units": quote_capacity_units,
                "accounting_model": "forex_margin_account_v1" if is_forex else "cash_equity_account_v1",
                "account_fx_rate": account_fx_rate,
                "quantity_units": quantity if is_forex else None,
                "quantity_lots": forex_sizing.quantity_lots if forex_sizing else None,
                "notional_eur": notional_value,
                "margin_reserved_eur": margin_reserved,
                "risk_amount_eur": risk_amount,
            },
        )
        db.add(trade)
        db.flush()
        self.paper.append_event(
            db,
            trade.id,
            "INTRADAY_TRADE_CANDIDATE",
            (
                "Promoted strategy passed all strict intraday gates."
                if evidence_lane == "certified_paper"
                else "Experimental challenger passed strict intraday gates at reduced paper risk; it is not copy-ready evidence."
            ),
            frozen,
            observed_entry,
        )
        if is_forex and (forex_sizing is None or forex_sizing.blocker):
            trade.status = "DATA_BLOCKED"
            trade.actionability_state = "data_blocked"
            trade.outcome_label = "DATA_INVALID"
            trade.lesson_learned = "Forex candidate was not submitted because point-in-time account-currency conversion was unavailable."
            self.paper.append_event(
                db,
                trade.id,
                "INTRADAY_DATA_BLOCKED",
                trade.lesson_learned,
                {"blocker": forex_sizing.blocker if forex_sizing else "FX_CONVERSION_UNAVAILABLE"},
                observed_entry,
            )
            return trade, True
        request = ExecutionOrderRequest(
            order_key=f"execution:{duplicate_key}",
            ticker=trade.ticker,
            side="SELL_SHORT" if trade.side == SHORT else "BUY",
            order_type="LIMIT",
            decision_timestamp=decision.decision_timestamp,
            theoretical_price=observed_entry,
            quantity=quantity,
            limit_price=observed_entry,
            stop_price=decision.stop_price,
            target_price=decision.target_price,
            max_participation_rate=0.05,
            commission_bps=float(costs.get("commission_bps") or 0.0),
            latency_bars=1,
            currency=asset.currency or "USD",
            account_currency=self.account_currency,
            fx_rate=account_fx_rate,
            fx_spread_bps=settings.paper_execution_fx_spread_bps,
            liquidity_score=decision.liquidity_score,
            liquidity_basis=liquidity_basis,
            quote_capacity_units=quote_capacity_units,
            allowed_sessions=(decision.session,),
        )
        self.execution.submit(
            db,
            request,
            paper_trade_id=trade.id,
            validation_id=decision.validation_id,
            expires_at=decision.decision_timestamp + timedelta(minutes=5),
        )
        return trade, True

    def _manage_pending_orders(self, db: Session, *, game: LiveForwardPaperGame, now: datetime) -> dict:
        orders = db.scalars(
            select(PaperExecutionOrder)
            .where(PaperExecutionOrder.status.in_(["SUBMITTED", "PARTIALLY_FILLED"]))
            .order_by(PaperExecutionOrder.submitted_at, PaperExecutionOrder.id)
            .limit(100)
        ).all()
        processed = opened = expired = new_fills = 0
        for order in orders:
            trade = db.get(LiveForwardPaperTrade, order.paper_trade_id) if order.paper_trade_id else None
            if trade is None or trade.game_id != game.id or trade.trading_mode != INTRADAY_MODE:
                continue
            asset = db.scalar(select(Asset).where(func.upper(Asset.ticker) == trade.ticker.upper()).limit(1))
            if asset is None:
                continue
            stored_bars = db.scalars(
                select(ReplayMarketBar)
                .where(
                    ReplayMarketBar.asset_id == asset.id,
                    ReplayMarketBar.timeframe == "1m",
                    ReplayMarketBar.bar_timestamp > order.decision_timestamp,
                    ReplayMarketBar.bar_timestamp <= now,
                )
                .order_by(ReplayMarketBar.bar_timestamp)
                .limit(100)
            ).all()
            cost_profile = trade.execution_costs or {}
            bars = [execution_bar_from_replay(row, spread_bps=float(cost_profile.get("spread_bps") or 0.0), fallback_session=trade.session_name or "regular") for row in stored_bars]
            result = self.execution.process_order(db, order, bars, now=now)
            processed += 1
            new_fills += int(result.get("new_fills") or 0)
            if result["status"] in {"FILLED", "PARTIALLY_FILLED_EXPIRED"} and not bool((trade.intraday_metadata or {}).get("execution_accounted")):
                self._account_filled_order(db, game=game, trade=trade, order=order)
                opened += 1
            elif result["status"] in {"EXPIRED", "REJECTED"}:
                unfilled_outcome = classify_unfilled_order(
                    theoretical_price=float(order.theoretical_price or 0.0),
                    target_price=float(order.target_price) if order.target_price is not None else None,
                    bars=stored_bars,
                )
                trade.status = "EXPIRED"
                trade.close_reason = "ORDER_NOT_FILLED" if result["status"] == "EXPIRED" else (result.get("rejection_reason") or "ORDER_REJECTED")
                trade.closed_at = now
                trade.exit_date = now.date()
                trade.outcome_label = unfilled_outcome
                trade.lesson_learned = f"Approved signal did not fill; post-decision classification={unfilled_outcome}."
                self.paper.append_event(db, trade.id, "INTRADAY_ORDER_NOT_FILLED", trade.lesson_learned, result, trade.current_price)
                self.learning.apply_closed_trade(db, trade)
                expired += 1
        return {"orders_processed": processed, "new_fills": new_fills, "trades_opened": opened, "orders_expired": expired}

    def _account_filled_order(self, db: Session, *, game: LiveForwardPaperGame, trade: LiveForwardPaperTrade, order: PaperExecutionOrder) -> None:
        metadata = dict(trade.intraday_metadata or {})
        metadata["execution_accounted"] = True
        metadata["execution_order_id"] = order.id
        metadata["theoretical_entry_price"] = order.theoretical_price
        metadata["executed_entry_price"] = order.average_fill_price
        trade.intraday_metadata = metadata
        is_forex = self._is_forex_trade(trade)
        account_fx_rate = float(order.fx_rate or metadata.get("account_fx_rate") or 1.0)
        quote_notional = float(trade.entry_price or 0.0) * float(trade.position_size or 0.0)
        trade.notional_value = quote_notional / account_fx_rate if is_forex else quote_notional
        risk_per_share = abs(
            float(trade.entry_price or 0.0)
            - float(trade.stop_loss or trade.entry_price or 0.0)
        )
        quote_risk = risk_per_share * float(trade.position_size or 0.0)
        trade.risk_amount = quote_risk / account_fx_rate if is_forex else quote_risk
        trade.expected_risk = trade.risk_amount
        reserved_capital = (
            float(metadata.get("margin_reserved_eur") or 0.0)
            if is_forex
            else float(trade.notional_value or 0.0)
        )
        metadata["reserved_capital_eur"] = reserved_capital
        trade.intraday_metadata = metadata
        trade.last_managed_bar_at = trade.opened_at
        self._create_ledger_trade(db, game, trade)
        self.paper.append_event(db, trade.id, "INTRADAY_TRADE_OPENED", "Paper position opened only after a later executable fill.", {"order_id": order.id, "quantity": trade.position_size, "theoretical_price": order.theoretical_price, "executed_price": order.average_fill_price}, trade.entry_price)
        game.cash = max(0.0, float(game.cash or 0.0) - reserved_capital)
        game.exposure = float(game.exposure or 0.0) + reserved_capital
        game.open_positions = int(game.open_positions or 0) + 1
        game.updated_at = trade.opened_at or datetime.utcnow()

    def _create_ledger_trade(self, db: Session, game: LiveForwardPaperGame, trade: LiveForwardPaperTrade) -> None:
        ledger_game = ensure_live_trade_game(db)
        ledger = TradingGameTrade(
            game_id=ledger_game.id,
            mode="live_forward_paper",
            ticker=trade.ticker,
            asset_name=trade.asset_name or trade.ticker,
            asset_type=trade.asset_type,
            sector=trade.sector,
            setup_type=trade.setup_type,
            sniper_score_at_entry=trade.sniper_score,
            confidence_at_entry=trade.confidence,
            actionability_state_at_entry=trade.actionability_state,
            market_regime_at_entry=(trade.frozen_decision_payload or {}).get("regime"),
            benchmark_ticker=trade.benchmark_ticker or game.benchmark_ticker,
            timeframe="1m",
            decision_state="active_setup",
            entry_date=trade.entry_date,
            entry_price=trade.entry_price,
            entry_reason=(
                "Strict promoted intraday setup confirmed."
                if trade.evidence_type == PAPER_FORWARD_INTRADAY
                else "Reduced-risk experimental intraday challenger confirmed; not certified for copy-readiness."
            ),
            entry_trigger=trade.entry_trigger,
            confirmation_condition=trade.confirmation_condition,
            position_size=trade.position_size,
            notional_value=trade.notional_value,
            risk_amount=trade.risk_amount,
            risk_percent=trade.risk_percent,
            stop_loss=trade.stop_loss,
            invalidation_level=trade.invalidation_level,
            initial_target_1=trade.target_1,
            capital_before=game.current_capital,
            capital_after=game.current_capital,
            reproducibility_score=90.0,
            data_quality_score=minimum_quality_from_trade(trade),
            outcome_label="open",
            payload={"paper_forward_trade_id": trade.id, "evidence_type": trade.evidence_type or PAPER_FORWARD_INTRADAY, "frozen_decision_payload": trade.frozen_decision_payload},
        )
        db.add(ledger)
        db.flush()
        trade.ledger_trade_id = ledger.id

    def _manage_open_trades(self, db: Session, *, game: LiveForwardPaperGame, now: datetime) -> dict:
        rows = db.scalars(
            select(LiveForwardPaperTrade).where(
                LiveForwardPaperTrade.game_id == game.id,
                LiveForwardPaperTrade.trading_mode == INTRADAY_MODE,
                LiveForwardPaperTrade.status == "OPEN",
            )
        ).all()
        updated = 0
        closed = 0
        for trade in rows:
            asset = db.scalar(select(Asset).where(func.upper(Asset.ticker) == trade.ticker.upper()).limit(1))
            if not asset:
                continue
            bars = db.scalars(
                select(ReplayMarketBar)
                .where(
                    ReplayMarketBar.asset_id == asset.id,
                    ReplayMarketBar.timeframe == "1m",
                    ReplayMarketBar.bar_timestamp > (trade.last_managed_bar_at or trade.opened_at or trade.decision_timestamp),
                    ReplayMarketBar.bar_timestamp <= now,
                )
                .order_by(ReplayMarketBar.bar_timestamp)
                .limit(500)
            ).all()
            for bar in bars:
                if not eligible_bar(bar, decision_at=trade.opened_at or trade.decision_timestamp, as_of=now, mode='execution'):
                    continue
                updated += 1
                trade.last_managed_bar_at = bar.bar_timestamp
                trade.current_price = float(bar.close)
                trade.holding_minutes = max(0.0, (bar.bar_timestamp - (trade.opened_at or trade.decision_timestamp)).total_seconds() / 60)
                self._update_excursions(trade, bar)
                close_reason, raw_exit = self._exit_for_bar(trade, bar)
                if close_reason:
                    self._close_trade(db, game=game, trade=trade, bar=bar, raw_exit=raw_exit, reason=close_reason)
                    closed += 1
                    self.learning.apply_closed_trade(db, trade)
                    break
                executable_strategy = ((trade.frozen_decision_payload or {}).get("strategy") or {}).get("executable_strategy") or {}
                trailing_multiple = float(executable_strategy.get("trailing_atr_multiple") or 1.2)
                trailing_distance = max(0.0001, float(bar.high) - float(bar.low)) * trailing_multiple
                if normalize_side(trade.side) == SHORT:
                    candidate_trailing = float(bar.close) + trailing_distance
                    trade.trailing_stop = min(
                        float(trade.trailing_stop or candidate_trailing),
                        candidate_trailing,
                    )
                else:
                    trade.trailing_stop = max(
                        float(trade.trailing_stop or 0.0),
                        float(bar.close) - trailing_distance,
                    )
                if self._is_forex_trade(trade):
                    trade.unrealized_pnl = forex_account_pnl(
                        entry_price=float(trade.entry_price or bar.close),
                        exit_price=float(bar.close),
                        quantity_units=float(trade.position_size or 0.0),
                        account_fx_rate=float((trade.intraday_metadata or {}).get("account_fx_rate") or 1.0),
                        direction=trade.side or LONG,
                    )
                else:
                    trade.unrealized_pnl = signed_price_change(
                        trade.side,
                        float(trade.entry_price or bar.close),
                        float(bar.close),
                    ) * float(trade.position_size or 0.0)
                self.paper.append_event(db, trade.id, "INTRADAY_TRADE_UPDATED", "Position marked using a later one-minute bar.", {"bar_timestamp": bar.bar_timestamp.isoformat()}, float(bar.close))
        return {"trades_updated": updated, "trades_closed": closed}

    def _exit_for_bar(self, trade: LiveForwardPaperTrade, bar: ReplayMarketBar) -> tuple[str | None, float | None]:
        low = float(bar.low if bar.low is not None else bar.close)
        high = float(bar.high if bar.high is not None else bar.close)
        side = normalize_side(trade.side)
        stop_probe = high if side == SHORT else low
        target_probe = low if side == SHORT else high
        reason = exit_reason(
            side,
            stop_probe,
            stop=trade.stop_loss,
            invalidation=trade.invalidation_level if trade.stop_loss is None else None,
        )
        if reason:
            stop_level = trade.stop_loss if reason == "STOP_HIT" else trade.invalidation_level
            gap_price = float(bar.open or bar.close)
            executed = max(float(stop_level), gap_price) if side == SHORT else min(float(stop_level), gap_price)
            return reason, executed
        reason = exit_reason(
            side,
            target_probe,
            target_1=trade.target_1,
        )
        if reason:
            return "TARGET_HIT", float(trade.target_1)
        if trade.trailing_stop:
            trailing_hit = (
                high >= float(trade.trailing_stop)
                if side == SHORT
                else low <= float(trade.trailing_stop)
            )
            favorable_trailing = (
                float(trade.trailing_stop) < float(trade.entry_price or 0.0)
                if side == SHORT
                else float(trade.trailing_stop) > float(trade.entry_price or 0.0)
            )
            if trailing_hit and favorable_trailing:
                return "TRAILING_STOP", float(trade.trailing_stop)
        opened_at = trade.opened_at or trade.decision_timestamp
        holding = (bar.bar_timestamp - opened_at).total_seconds() / 60
        if bar.bar_timestamp.date() > opened_at.date() and not self.allow_overnight:
            return "MARKET_CLOSE", float(bar.open or bar.close)
        strategy_holding_minutes = float(
            (trade.intraday_metadata or {}).get("maximum_holding_minutes")
            or self.max_holding_minutes
        )
        if holding >= min(float(self.max_holding_minutes), strategy_holding_minutes):
            return "TIME_STOP", float(bar.close)
        return None, None

    def _close_trade(self, db: Session, *, game: LiveForwardPaperGame, trade: LiveForwardPaperTrade, bar: ReplayMarketBar, raw_exit: float, reason: str) -> None:
        costs = trade.execution_costs or {}
        one_way_bps = float(costs.get("one_way_bps") or 0.0)
        side = normalize_side(trade.side) or LONG
        exit_fill = float(raw_exit) * (
            1 + one_way_bps / 10_000 if side == SHORT else 1 - one_way_bps / 10_000
        )
        quantity = float(trade.position_size or 0.0)
        is_forex = self._is_forex_trade(trade)
        account_fx_rate = float((trade.intraday_metadata or {}).get("account_fx_rate") or 1.0)
        observed_entry = float((trade.intraday_metadata or {}).get("observed_entry_price") or trade.entry_price or 0.0)
        if is_forex:
            gross = forex_account_pnl(
                entry_price=observed_entry,
                exit_price=float(raw_exit),
                quantity_units=quantity,
                account_fx_rate=account_fx_rate,
                direction=side,
            )
            net = forex_account_pnl(
                entry_price=float(trade.entry_price or 0.0),
                exit_price=exit_fill,
                quantity_units=quantity,
                account_fx_rate=account_fx_rate,
                direction=side,
            )
        else:
            gross = signed_price_change(side, observed_entry, float(raw_exit)) * quantity
            net = signed_price_change(side, float(trade.entry_price or 0.0), exit_fill) * quantity
        total_cost = max(0.0, gross - net)
        initial_risk = max(0.0001, float(trade.expected_risk or trade.risk_amount or 0.0001))
        trade.status = "CLOSED"
        trade.close_reason = reason
        trade.exit_price = exit_fill
        trade.exit_date = bar.bar_timestamp.date()
        trade.closed_at = bar.bar_timestamp
        trade.gross_pnl_eur = round(gross, 6)
        trade.net_pnl_eur = round(net, 6)
        unit_pnl = signed_price_change(side, float(trade.entry_price or 0.0), exit_fill)
        trade.pnl_per_share = round(unit_pnl / account_fx_rate if is_forex else unit_pnl, 8)
        trade.pnl_percent = round(
            signed_return(side, float(trade.entry_price or 1.0), exit_fill) * 100,
            6,
        )
        trade.r_multiple = round(net / initial_risk, 6)
        trade.costs_paid = round(total_cost, 6)
        conversion = account_fx_rate if is_forex else 1.0
        trade.spread_cost = round(float(costs.get("spread_bps") or 0.0) / 10_000 * observed_entry * quantity / conversion, 6)
        trade.slippage_cost = round(float(costs.get("slippage_bps") or 0.0) * 2 / 10_000 * observed_entry * quantity / conversion, 6)
        trade.commission_cost = round(float(costs.get("commission_bps") or 0.0) * 2 / 10_000 * observed_entry * quantity / conversion, 6)
        trade.stop_hit = reason == "STOP_HIT"
        trade.invalidation_hit = reason == "INVALIDATION_HIT"
        trade.target_1_hit = reason == "TARGET_HIT"
        trade.outcome_label = "win" if net > 0 else "loss" if net < 0 else "breakeven"
        self._update_benchmark_outcome(db, trade, bar.bar_timestamp)
        trade.lesson_learned = intraday_lesson(trade)
        trade.unrealized_pnl = 0.0
        reserved_capital = float(
            (trade.intraday_metadata or {}).get("reserved_capital_eur")
            or (trade.intraday_metadata or {}).get("margin_reserved_eur")
            or trade.notional_value
            or 0.0
        )
        if is_forex:
            game.cash = float(game.cash or 0.0) + reserved_capital + net
            game.exposure = max(0.0, float(game.exposure or 0.0) - reserved_capital)
        else:
            game.cash = float(game.cash or 0.0) + exit_fill * quantity
            game.exposure = max(0.0, float(game.exposure or 0.0) - float(trade.notional_value or 0.0))
        game.realized_pl = float(game.realized_pl or 0.0) + net
        game.current_capital = float(game.cash or 0.0) + float(game.exposure or 0.0)
        game.open_positions = max(0, int(game.open_positions or 0) - 1)
        game.updated_at = bar.bar_timestamp
        ledger = db.get(TradingGameTrade, trade.ledger_trade_id) if trade.ledger_trade_id else None
        if ledger:
            ledger.exit_date = trade.exit_date
            ledger.exit_price = exit_fill
            ledger.exit_reason = reason
            ledger.holding_days = max(0, (trade.exit_date - trade.entry_date).days) if trade.entry_date else 0
            ledger.gross_pnl_eur = trade.gross_pnl_eur
            ledger.net_pnl_eur = trade.net_pnl_eur
            ledger.pnl_percent = trade.pnl_percent
            ledger.pnl_per_share = trade.pnl_per_share
            ledger.r_multiple = trade.r_multiple
            ledger.outcome_label = trade.outcome_label
            ledger.capital_after = game.current_capital
            ledger.benchmark_return_same_period = trade.benchmark_return_same_period
            ledger.excess_return_vs_benchmark = trade.excess_return_vs_benchmark
        self.paper.append_event(db, trade.id, "INTRADAY_TRADE_CLOSED", f"Intraday paper trade closed: {reason}.", {"bar_timestamp": bar.bar_timestamp.isoformat(), "gross_pnl": gross, "net_pnl": net, "costs_paid": total_cost}, exit_fill)
        self.paper.append_event(db, trade.id, "INTRADAY_OUTCOME_EVALUATED", "Closed intraday outcome evaluated against stored benchmark data when available.", {"r_multiple": trade.r_multiple, "benchmark_return": trade.benchmark_return_same_period, "benchmark_excess": trade.excess_return_vs_benchmark}, exit_fill)

    @staticmethod
    def _is_forex_trade(trade: LiveForwardPaperTrade) -> bool:
        return str(trade.asset_type or "").strip().lower() in {"forex", "fx", "currency"}

    def _update_benchmark_outcome(self, db: Session, trade: LiveForwardPaperTrade, exit_timestamp: datetime) -> None:
        if self._is_forex_trade(trade) and str(trade.benchmark_ticker or "").upper() in {"", "SPY", "CASH", "NO_TRADE"}:
            trade.benchmark_ticker = "CASH"
            trade.benchmark_return_same_period = 0.0
            trade.excess_return_vs_benchmark = round(float(trade.pnl_percent or 0.0), 6)
            return
        benchmark = db.scalar(select(Asset).where(func.upper(Asset.ticker) == str(trade.benchmark_ticker or "").upper()).limit(1))
        if benchmark is None:
            return
        entry_row = db.scalar(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == benchmark.id, ReplayMarketBar.timeframe == "1m", ReplayMarketBar.bar_timestamp <= (trade.opened_at or trade.decision_timestamp))
            .order_by(desc(ReplayMarketBar.bar_timestamp))
            .limit(1)
        )
        exit_row = db.scalar(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == benchmark.id, ReplayMarketBar.timeframe == "1m", ReplayMarketBar.bar_timestamp <= exit_timestamp)
            .order_by(desc(ReplayMarketBar.bar_timestamp))
            .limit(1)
        )
        if entry_row is None or exit_row is None or float(entry_row.close or 0.0) <= 0:
            return
        benchmark_return = (float(exit_row.close) / float(entry_row.close) - 1) * 100
        trade.benchmark_return_same_period = round(benchmark_return, 6)
        trade.excess_return_vs_benchmark = round(float(trade.pnl_percent or 0.0) - benchmark_return, 6)

    @staticmethod
    def _update_excursions(trade: LiveForwardPaperTrade, bar: ReplayMarketBar) -> None:
        entry = float(trade.entry_price or 0.0)
        if entry <= 0:
            return
        high = float(bar.high if bar.high is not None else bar.close)
        low = float(bar.low if bar.low is not None else bar.close)
        mfe, mae = directional_excursions(
            side=trade.side,
            entry_price=entry,
            high_price=high,
            low_price=low,
            current_mfe=float(trade.max_favorable_excursion or 0.0),
            current_mae=float(trade.max_adverse_excursion or 0.0),
            percent=True,
        )
        trade.max_favorable_excursion = mfe
        trade.max_adverse_excursion = mae

    @staticmethod
    def _count_rejection(run: IntradayPaperRun, reason: str) -> None:
        if "COST" in reason or "SPREAD" in reason or "EXPECTED_MOVE" in reason:
            run.rejected_due_to_costs += 1
        elif "CONCENTRATION" in reason or "MAX_OPEN" in reason:
            run.rejected_due_to_concentration += 1
        else:
            run.rejected_due_to_risk += 1

    @staticmethod
    def _terminal_status(*, run: IntradayPaperRun, blockers: list[dict], decisions: list[dict]) -> str:
        blocker_reasons = {str(blocker.get("reason") or "") for blocker in blockers}
        if "RUNTIME_BUDGET_EXHAUSTED" in blocker_reasons:
            return "PAUSED_FOR_RUNTIME"
        if run.trades_opened or run.trades_updated or run.trades_closed:
            return "COMPLETED"
        decision_reasons = {str(decision.get("reason_code") or "") for decision in decisions}
        if decision_reasons and decision_reasons == {"SESSION_NOT_ALLOWED"}:
            return "MARKET_CLOSED"
        if blocker_reasons & {"NO_DESK_ASSETS_WITH_INTRADAY_DATA", "INTRADAY_DATA_BLOCKED"}:
            return "DATA_BLOCKED"
        return "COMPLETED"

    @staticmethod
    def _serialize_run(run: IntradayPaperRun, blockers: list[dict]) -> dict:
        return {
            "status": run.status,
            "run_id": run.run_uid,
            "assets_checked": run.assets_checked,
            "markets_checked": run.markets_checked,
            "candidates_found": run.candidates_found,
            "candidates_approved": run.candidates_approved,
            "trades_opened": run.trades_opened,
            "trades_updated": run.trades_updated,
            "trades_closed": run.trades_closed,
            "rejected_due_to_costs": run.rejected_due_to_costs,
            "rejected_due_to_risk": run.rejected_due_to_risk,
            "rejected_due_to_concentration": run.rejected_due_to_concentration,
            "blockers": blockers,
            "data_blockers": blockers,
            "next_action": "Continue on the next fresh one-minute bar." if run.trades_opened or run.trades_updated else "Resolve recorded blockers; never force activity.",
            "duration_seconds": run.duration_seconds,
            "evidence_type": PAPER_FORWARD_INTRADAY,
        }


class IntradayPaperLearningService:
    """Translate a resolved intraday trade into idempotent forward evidence."""

    def apply_closed_trade(self, db: Session, trade: LiveForwardPaperTrade) -> dict:
        if trade.status not in TERMINAL_STATUSES or trade.closed_at is None:
            return {"status": "not_closed", "trade_id": trade.id}
        if not paper_trade_evidence_is_eligible(trade):
            return {
                "status": "quarantined",
                "trade_id": trade.id,
                "reason": "directional_accounting_not_verified",
            }
        identity = f"intraday_trade:{trade.id}"
        existing = db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.action_taken == identity).limit(1))
        if existing:
            return {"status": "duplicate", "trade_id": trade.id, "evidence_id": existing.id}
        outcome = str(trade.outcome_label or "").upper()
        positive = float(trade.net_pnl_eur or 0.0) > 0 or outcome in {
            "CORRECT_NO_TRADE",
            "EDGE_DESTROYED_BY_COSTS",
            "SIGNAL_DECAY_BEFORE_ENTRY",
        }
        lesson_type = {
            "MISSED_OPPORTUNITY": "entry_timing_bad",
            "ORDER_NOT_FILLED": "entry_timing_bad",
            "SIGNAL_DECAY_BEFORE_ENTRY": "entry_timing_bad",
            "EDGE_DESTROYED_BY_COSTS": "no_trade_filter_confirmed",
            "CORRECT_NO_TRADE": "no_trade_filter_confirmed",
        }.get(outcome, "setup_confirmed" if positive else "setup_failed")
        observation = intraday_lesson(trade)
        evidence_type = trade.evidence_type or PAPER_FORWARD_INTRADAY
        experimental = evidence_type == PAPER_FORWARD_INTRADAY_EXPERIMENTAL
        evidence = TradeLearningEvidence(
            trade_id=trade.ledger_trade_id,
            ticker=trade.ticker,
            setup_type=trade.setup_type,
            regime=(trade.frozen_decision_payload or {}).get("regime") or "unknown",
            lesson_type=lesson_type,
            observation=observation,
            sample_size=1,
            supporting_trades_json={
                "paper_forward_trade_id": trade.id,
                "evidence_type": evidence_type,
                "market": trade.market,
                "desk": trade.desk,
                "timeframe_stack": trade.timeframe_stack,
                "session": trade.session_name,
                "exit_reason": trade.close_reason,
                "costs_paid": trade.costs_paid,
                "r_multiple": trade.r_multiple,
                "benchmark_excess": trade.excess_return_vs_benchmark,
            },
            affected_module="intraday_paper_engine",
            action_taken=identity,
            confidence=max(10.0, min(90.0, 50.0 + abs(float(trade.r_multiple or 0.0)) * 10.0)),
        )
        db.add(evidence)
        memory_namespace = "intraday_experimental" if experimental else "intraday"
        memory_key = f"{memory_namespace}:{trade.setup_type}:{trade.market or 'unknown'}:{(trade.frozen_decision_payload or {}).get('regime') or 'unknown'}"
        memory = db.scalar(select(StrategyMemory).where(StrategyMemory.memory_key == memory_key).limit(1))
        if memory is None:
            memory = StrategyMemory(
                memory_key=memory_key,
                category="intraday_experimental_paper" if experimental else "intraday_paper",
                conditions={"setup": trade.setup_type, "market": trade.market, "regime": (trade.frozen_decision_payload or {}).get("regime"), "evidence_lane": evidence_type},
                evidence={},
            )
            db.add(memory)
        memory.sample_count = int(memory.sample_count or 0) + 1
        memory.positive_count = int(memory.positive_count or 0) + (1 if positive else 0)
        memory.negative_count = int(memory.negative_count or 0) + (0 if positive else 1)
        memory.reliability_score = round(memory.positive_count / max(1, memory.sample_count) * 100, 4)
        memory.lesson = observation
        memory.evidence = {"latest_trade_id": trade.id, "latest_r_multiple": trade.r_multiple, "latest_costs_paid": trade.costs_paid, "evidence_type": evidence_type}
        memory.last_seen_at = trade.closed_at

        signal_name = f"{memory_namespace}:{trade.setup_type}"
        signal = db.scalar(select(SignalPerformance).where(SignalPerformance.signal_name == signal_name, SignalPerformance.timeframe == "1m", SignalPerformance.market_regime == ((trade.frozen_decision_payload or {}).get("regime") or "unknown")).limit(1))
        if signal is None:
            signal = SignalPerformance(signal_name=signal_name, timeframe="1m", market_regime=(trade.frozen_decision_payload or {}).get("regime") or "unknown")
            db.add(signal)
        signal.sample_count = int(signal.sample_count or 0) + 1
        signal.correct_count = int(signal.correct_count or 0) + (1 if positive else 0)
        signal.false_positive_count = int(signal.false_positive_count or 0) + (0 if positive else 1)
        signal.reliability_score = round(signal.correct_count / max(1, signal.sample_count) * 100, 4)
        signal.average_return = running_average(signal.average_return, signal.sample_count, float(trade.pnl_percent or 0.0))
        signal.evidence = {"latest_trade_id": trade.id, "evidence_type": evidence_type, "costs_paid": trade.costs_paid}
        audit = FeedbackLoopAudit(
            ticker=trade.ticker,
            model_version_used=trade.model_version_used or "base-static",
            learned_knowledge_json={"lesson": observation, "strategy_memory_key": memory_key, "signal": signal_name},
            changes_applied_json={"strategy_reliability": memory.reliability_score, "signal_reliability": signal.reliability_score},
            future_decision_json={"source_trade_id": trade.id, "evidence_type": evidence_type, "applies_to_future_only": True},
            outcome_json={"r_multiple": trade.r_multiple, "net_pnl": trade.net_pnl_eur, "benchmark_excess": trade.excess_return_vs_benchmark, "close_reason": trade.close_reason},
            improvement_detected=False,
            evidence_grade=("experimental_forward_sample" if experimental else "insufficient") if signal.sample_count < 30 else ("experimental_forward_evidence" if experimental else "forward_sample"),
            summary=(
                "Closed experimental intraday outcome stored in an isolated future-only learning lane."
                if experimental
                else "Closed intraday paper outcome stored for future-only confidence and reliability calibration."
            ),
        )
        db.add(audit)
        db.add(LearningEvent(event_type="intraday_paper_trade_closed", severity="Info", title=f"{trade.ticker} intraday paper outcome", description=observation, payload={"paper_forward_trade_id": trade.id, "evidence_type": evidence_type, "r_multiple": trade.r_multiple}))
        db.flush()
        strategy_id = strategy_identity(trade.setup_type, trade.promoted_validation_id)[0]
        timeline = EvidenceTimelineService()
        timeline.append_once(
            db,
            event_key=f"intraday-lesson:{trade.id}",
            event_type="lesson_created",
            strategy_id=strategy_id,
            trade_id=trade.id,
            payload={"evidence_id": evidence.id, "lesson_type": lesson_type, "observation": observation},
        )
        timeline.append_once(
            db,
            event_key=f"intraday-memory:{trade.id}",
            event_type="memory_updated",
            strategy_id=strategy_id,
            trade_id=trade.id,
            payload={"strategy_memory_key": memory_key, "signal_name": signal_name, "sample_size": signal.sample_count},
        )
        return {"status": "applied", "trade_id": trade.id, "evidence_id": evidence.id, "memory_key": memory_key}


def intraday_snapshot_summary(db: Session, *, now: datetime | None = None) -> dict:
    """Read-only projection; callers must never trigger the intraday command."""

    now = now or datetime.utcnow()
    day = now.date()
    latest_run = db.scalar(select(IntradayPaperRun).order_by(desc(IntradayPaperRun.started_at)).limit(1))
    rows = db.scalars(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.evidence_type == PAPER_FORWARD_INTRADAY).order_by(desc(LiveForwardPaperTrade.created_at)).limit(500)).all()
    experimental_rows = db.scalars(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.evidence_type == PAPER_FORWARD_INTRADAY_EXPERIMENTAL).order_by(desc(LiveForwardPaperTrade.created_at)).limit(500)).all()
    all_rows = [*rows, *experimental_rows]
    today_rows = [row for row in all_rows if (row.decision_date or row.created_at.date()) == day]
    closed = [row for row in rows if row.status in TERMINAL_STATUSES]
    experimental_closed = [row for row in experimental_rows if row.status in TERMINAL_STATUSES]
    costs = sum(float(row.costs_paid or 0.0) for row in closed)
    open_rows = [row for row in all_rows if row.status == "OPEN"]
    rejection_counts = {
        "rejected_due_to_costs": int(latest_run.rejected_due_to_costs or 0) if latest_run else 0,
        "rejected_due_to_concentration": int(latest_run.rejected_due_to_concentration or 0) if latest_run else 0,
    }
    no_trade_rows = db.execute(
        select(IntradayNoTradeDecision.outcome_label, func.count(IntradayNoTradeDecision.id))
        .where(IntradayNoTradeDecision.status == "EVALUATED")
        .group_by(IntradayNoTradeDecision.outcome_label)
    ).all()
    no_trade_evidence = {str(label): int(count) for label, count in no_trade_rows if label}
    no_trade_pending = int(
        db.scalar(select(func.count(IntradayNoTradeDecision.id)).where(IntradayNoTradeDecision.status == "PENDING")) or 0
    )
    strategy_registry = BlumPromotedStrategyRegistry().status(db)
    if not latest_run:
        inactivity_reason = "No intraday run has completed."
        next_action = "Wait for the bounded backend worker or invoke the explicit manual POST."
    elif not all_rows:
        latest_blockers = latest_run.data_blockers or []
        inactivity_reason = str((latest_blockers[0] if latest_blockers else {}).get("reason") or "No strategy passed all forward gates.")
        next_action = "Resolve the recorded data/promotion blocker; do not force a paper trade."
    else:
        inactivity_reason = None
        next_action = "Manage open positions from later one-minute bars and continue strict scans."
    return {
        "status": latest_run.status if latest_run else "NO_INTRADAY_RUNS",
        "intraday_engine_status": latest_run.status if latest_run else "NO_INTRADAY_RUNS",
        "last_run_at": latest_run.started_at.isoformat() if latest_run else None,
        "last_run_duration_seconds": latest_run.duration_seconds if latest_run else None,
        "intraday_scans_today": int(db.scalar(select(func.count(IntradayPaperRun.id)).where(func.date(IntradayPaperRun.started_at) == day)) or 0),
        "candidates_today": len(today_rows),
        "intraday_candidates_today": len(today_rows),
        "trades_opened_today": sum(1 for row in today_rows if row.opened_at is not None),
        "intraday_opened_today": sum(1 for row in today_rows if row.opened_at is not None),
        "trades_closed_today": sum(1 for row in rows if row.closed_at and row.closed_at.date() == day),
        "intraday_closed_today": sum(1 for row in rows if row.closed_at and row.closed_at.date() == day),
        "open_positions": len(open_rows),
        "open_positions_by_market": dict(Counter(row.market or "UNKNOWN" for row in open_rows)),
        "open_positions_by_desk": dict(Counter(row.desk or "UNKNOWN" for row in open_rows)),
        "open_positions_by_ticker": dict(Counter(row.ticker for row in open_rows)),
        "distinct_markets_traded_today": len({row.market for row in today_rows if row.market}),
        "distinct_tickers_traded_today": len({row.ticker for row in today_rows if row.ticker}),
        "closed_sample_size": len(closed),
        "experimental_closed_sample_size": len(experimental_closed),
        "experimental_candidates_today": sum(1 for row in today_rows if row.evidence_type == PAPER_FORWARD_INTRADAY_EXPERIMENTAL),
        "certified_candidates_today": sum(1 for row in today_rows if row.evidence_type == PAPER_FORWARD_INTRADAY),
        "experimental_realized_pnl": round(sum(float(row.net_pnl_eur or 0.0) for row in experimental_closed), 4) if experimental_closed else None,
        "experimental_average_r": round(sum(float(row.r_multiple or 0.0) for row in experimental_closed) / len(experimental_closed), 4) if experimental_closed else None,
        "realized_pnl": round(sum(float(row.net_pnl_eur or 0.0) for row in closed), 4) if closed else None,
        "average_r": round(sum(float(row.r_multiple or 0.0) for row in closed) / len(closed), 4) if closed else None,
        "benchmark_excess": average_present([row.excess_return_vs_benchmark for row in closed]),
        "average_holding_minutes": average_present([row.holding_minutes for row in closed]),
        "avg_holding_minutes": average_present([row.holding_minutes for row in closed]),
        "avg_net_r": round(sum(float(row.r_multiple or 0.0) for row in closed) / len(closed), 4) if closed else None,
        "realized_intraday_pnl": round(sum(float(row.net_pnl_eur or 0.0) for row in closed), 4) if closed else None,
        "intraday_benchmark_excess": average_present([row.excess_return_vs_benchmark for row in closed]),
        "costs_paid": round(costs, 4) if closed else None,
        "no_trade_evidence": no_trade_evidence,
        "no_trade_pending": no_trade_pending,
        **rejection_counts,
        "reason_if_no_intraday_trades": inactivity_reason,
        "next_intraday_action": next_action,
        "markets": dict(Counter(row.market or "UNKNOWN" for row in all_rows)),
        "desks": dict(Counter(row.desk or "UNKNOWN" for row in all_rows)),
        "setups": dict(Counter(row.setup_type for row in all_rows)),
        "latest_blockers": latest_run.data_blockers if latest_run else ["No intraday run has completed."],
        "strategy_registry": strategy_registry,
        "evidence_type": PAPER_FORWARD_INTRADAY,
        "experimental_evidence_type": PAPER_FORWARD_INTRADAY_EXPERIMENTAL,
        "policy": "Read-only forward paper evidence. No trade or recalculation is triggered by this snapshot.",
    }


def desk_and_benchmark(asset: Asset) -> tuple[str, str]:
    country = normalize_market(asset.country or "")
    exchange = str(asset.exchange or "").upper()
    asset_type = str(asset.asset_type or asset.category or "").upper()
    if country == "FOREX" or "FOREX" in asset_type or "CURRENCY" in asset_type:
        return "ForexDeskAgent", "UUP"
    if country == "USA" and "NASDAQ" in exchange:
        return "NasdaqAgent", "QQQ"
    if country == "USA":
        return "WallStreetAgent", "SPY"
    if country == "ITALY":
        return "FTSEMIBAgent", "FTSEMIB.MI"
    if country == "GERMANY":
        return "DAXAgent", "^GDAXI"
    if country == "FRANCE":
        return "CAC40Agent", "^FCHI"
    return "CrossMarketAgent", "SPY"


def intraday_lesson(trade: LiveForwardPaperTrade) -> str:
    result = "worked" if float(trade.net_pnl_eur or 0.0) > 0 else "failed"
    return f"{trade.setup_type} {result} in {trade.market or 'unknown'} / {(trade.frozen_decision_payload or {}).get('regime') or 'unknown'} after costs; exit={trade.close_reason}, R={float(trade.r_multiple or 0.0):.2f}."


def running_average(previous: float | None, sample_count: int, value: float) -> float:
    previous_count = max(0, int(sample_count) - 1)
    return round(((float(previous or 0.0) * previous_count) + value) / max(1, int(sample_count)), 6)


def minimum_quality_from_trade(trade: LiveForwardPaperTrade) -> float | None:
    evidence = (trade.frozen_decision_payload or {}).get("evidence") or {}
    values = [float(value) for value in (evidence.get("quality_scores") or {}).values() if value is not None]
    return min(values) if values else None


def average_present(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return round(sum(present) / len(present), 4) if present else None


def classify_unfilled_order(*, theoretical_price: float, target_price: float | None, bars: Iterable) -> str:
    rows = list(bars)
    if theoretical_price <= 0 or not rows:
        return "ORDER_NOT_FILLED"
    if target_price is not None and any(float(row.high if row.high is not None else row.close) >= target_price for row in rows):
        return "MISSED_OPPORTUNITY"
    latest = rows[-1]
    if float(latest.close) < theoretical_price:
        return "SIGNAL_DECAY_BEFORE_ENTRY"
    return "ORDER_NOT_FILLED"


def execution_bar_from_replay(row: ReplayMarketBar, *, spread_bps: float, fallback_session: str = "regular") -> ExecutionMarketBar:
    metadata = dict(row.source_metadata or {})
    session = str(metadata.get("market_session") or metadata.get("session") or fallback_session)
    halted = bool(metadata.get("is_halted") or metadata.get("market_halt") or metadata.get("halted"))
    close = float(row.close)
    high = float(row.high if row.high is not None else close)
    low = float(row.low if row.low is not None else close)
    return ExecutionMarketBar(
        timestamp=row.bar_timestamp,
        open=float(row.open if row.open is not None else close),
        high=high,
        low=low,
        close=close,
        volume=float(row.volume or 0.0),
        spread_bps=float(spread_bps),
        volatility_bps=abs(high - low) / max(close, 0.0001) * 10_000,
        session=session,
        is_halted=halted,
        available_at=bar_available_at(row),
    )


def point_in_time_fx_rate(db: Session, *, asset_currency: str, account_currency: str, at: datetime) -> float | None:
    asset_code = str(asset_currency or "").upper()
    account_code = str(account_currency or "").upper()
    if not asset_code or not account_code:
        return None
    if asset_code == account_code:
        return 1.0
    direct_symbols = (f"{account_code}{asset_code}=X", f"{account_code}{asset_code}")
    inverse_symbols = (f"{asset_code}{account_code}=X", f"{asset_code}{account_code}")
    for symbols, invert in ((direct_symbols, False), (inverse_symbols, True)):
        fx_asset = db.scalar(select(Asset).where(func.upper(Asset.ticker).in_(symbols)).limit(1))
        if fx_asset is None:
            continue
        row = db.scalar(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == fx_asset.id, ReplayMarketBar.bar_timestamp <= at)
            .order_by(desc(ReplayMarketBar.bar_timestamp))
            .limit(1)
        )
        if row is None or float(row.close or 0.0) <= 0:
            continue
        rate = float(row.close)
        return round(1.0 / rate if invert else rate, 8)
    return None


def json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    return value
