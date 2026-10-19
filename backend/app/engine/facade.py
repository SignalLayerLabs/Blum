from __future__ import annotations

from sqlalchemy.orm import Session

from app.engine.contracts import (
    ENGINE_VERSION,
    PROJECT_FEATURE_SET,
    EngineStatusContract,
    engine_module_catalog,
    event_contract,
)
from app.engine.agents.registry import agent_boundaries, collect_agent_evidence
from app.engine.brain.trader_brain import TraderBrainService
from app.services.paper_forward_opportunity_scanner import PaperForwardOpportunityScanner
from app.services.adaptive_replay_training import BlumAdaptiveTrainingController
from app.services.unified_paper_trading import UnifiedPaperTradingProjectionService


class BlumEngineFacade:
    """Headless intelligence boundary for BLUM.

    This facade is the first stable seam between the financial operating system
    and the application runtime. It delegates to legacy services while enforcing
    a contract that has no presentation responsibility.
    """

    def status(self, db: Session) -> dict:
        trader = TraderBrainService()
        brain = trader.brain(db)
        training = trader.training_ground(db)
        paper = trader.paper_trading(db, limit=12)
        alpha = trader.alpha(db)
        contract = EngineStatusContract(
            version=ENGINE_VERSION,
            feature_set=PROJECT_FEATURE_SET,
            source_of_truth=True,
            headless_capable=True,
            intelligence_modules=engine_module_catalog(),
            event_contract=event_contract(),
            current_brain_status=self._brain_status(brain),
            current_learning_status=self._learning_status(training),
            current_alpha_status=self._alpha_status(alpha),
            current_paper_trading_status=self._paper_status(paper),
            policy=(
                "BLUM Engine owns intelligence, decisions, learning, evidence and knowledge. "
                "It can run without any product surface and never depends on presentation code."
            ),
        )
        return contract.to_dict()

    def contract(self) -> dict:
        return {
            "version": ENGINE_VERSION,
            "feature_set": PROJECT_FEATURE_SET,
            "source_of_truth": True,
            "headless_capable": True,
            "modules": [module.to_dict() for module in engine_module_catalog()],
            "agents": agent_boundaries(),
            "events": event_contract(),
            "decision_object": {
                "ticker": "string",
                "decision_type": "paper_trade | thesis | no_trade | portfolio_action",
                "actionability": "avoid | watch | wait_for_trigger | active_setup | manage | reduce | exit",
                "thesis_id": "optional string",
                "confidence": "optional 0-100",
                "decision_quality": "optional 0-100",
                "expected_alpha": "optional benchmark-relative estimate",
                "entry_zone": "optional structured zone",
                "invalidation": "required for trade-like decisions",
                "targets": "optional structured target zones",
                "bull_thesis": "evidence-backed bull case",
                "bear_thesis": "evidence-backed contradiction case",
                "risks": "list of explicit risks",
                "evidence_refs": "stable references to stored Engine evidence",
            },
            "policy": "The Engine emits evidence-bound objects only; it does not execute real trades and does not own product delivery.",
        }

    def curriculum_snapshot(self, db: Session) -> dict:
        from app.services.curriculum_worker import TradingCurriculumWorker
        return TradingCurriculumWorker().snapshot(db)

    def run_curriculum(self, db: Session) -> dict:
        from app.services.curriculum_worker import TradingCurriculumWorker
        return TradingCurriculumWorker().run_once(db)

    def brain_snapshot(self, db: Session) -> dict:
        return TraderBrainService().brain(db)

    def training_snapshot(self, db: Session) -> dict:
        return TraderBrainService().training_ground(db)

    def training_acceleration(self, db: Session) -> dict:
        scanner = PaperForwardOpportunityScanner()
        scanner_summary = {"top_blockers": [], "markets_scanned": [], "asset_classes_scanned": []}
        acceleration = scanner.learning_acceleration_agent.accelerate(db, scanner_summary=scanner_summary, execute=True)
        experiments = scanner.experiment_manager_agent.propose(db, acceleration_report=acceleration)
        acceleration["experiments_created"] = experiments.get("experiments_created", 0)
        acceleration["experiments_completed"] = experiments.get("experiments_completed", 0)
        db.commit()
        return {
            "status": acceleration.get("status"),
            "targets_selected": {
                "priority_markets": acceleration.get("priority_markets", []),
                "priority_asset_classes": acceleration.get("priority_asset_classes", []),
                "priority_tickers": acceleration.get("priority_tickers", []),
                "priority_setups": acceleration.get("priority_setups", []),
                "uncertainty_targets": acceleration.get("uncertainty_targets", []),
                "missed_opportunity_targets": acceleration.get("missed_opportunity_targets", []),
                "repeated_blockers": acceleration.get("repeated_blockers", []),
            },
            "batches_requested": acceleration.get("batches_requested", 0),
            "batches_completed": acceleration.get("batches_completed", 0),
            "experiments_created": experiments.get("experiments_created", 0),
            "experiments_completed": experiments.get("experiments_completed", 0),
            "memory_updates": acceleration.get("memory_updates", 0),
            "model_version_changes": acceleration.get("model_version_changes", []),
            "benchmark_blockers": acceleration.get("benchmark_blockers", []),
            "safety_limits_applied": acceleration.get("safety_limits_applied", {}),
            "next_action": acceleration.get("next_acceleration_action"),
            "learning_acceleration": acceleration,
            "experiment_manager": experiments,
        }

    def run_training_replay(self, db: Session) -> dict:
        return BlumAdaptiveTrainingController().run_once(db, trigger="manual")

    def paper_trading_snapshot(self, db: Session, *, limit: int = 20) -> dict:
        return TraderBrainService().paper_trading(db, limit=limit)

    def unified_paper_trading_snapshot(self, db: Session) -> dict:
        return UnifiedPaperTradingProjectionService().latest(db)

    def unified_paper_trading_detail(self, db: Session, source_engine: str, source_trade_id: int) -> dict:
        return UnifiedPaperTradingProjectionService().detail(db, source_engine, source_trade_id)

    def alpha_snapshot(self, db: Session) -> dict:
        from app.services.alpha_desk_projection import AlphaDeskProjectionService
        return {**TraderBrainService().alpha(db), "registered_alpha_desk": AlphaDeskProjectionService().latest(db)}

    def alpha_desk_snapshot(self, db: Session) -> dict:
        from app.services.alpha_desk_projection import AlphaDeskProjectionService
        return AlphaDeskProjectionService().latest(db)

    def agent_evidence(self, db: Session, *, agents: list[str] | None = None, limit: int = 8) -> dict:
        return collect_agent_evidence(db, names=agents, limit=limit)

    @staticmethod
    def _brain_status(payload: dict) -> dict:
        return {
            "status": payload.get("status"),
            "brain_score": payload.get("brain_score"),
            "decision_quality": payload.get("decision_quality"),
            "alpha_readiness": payload.get("alpha_readiness"),
            "evidence_quality": payload.get("evidence_quality"),
            "latest_lesson": payload.get("latest_lesson"),
            "current_weakness": payload.get("current_weakness"),
            "current_strength": payload.get("current_strength"),
        }

    @staticmethod
    def _learning_status(payload: dict) -> dict:
        validation = payload.get("current_validation") or {}
        return {
            "status": payload.get("status"),
            "current_experiment": payload.get("current_experiment"),
            "current_hypothesis": payload.get("current_hypothesis"),
            "outcomes_evaluated": validation.get("outcomes_evaluated"),
            "mistakes_analyzed": validation.get("mistakes_analyzed"),
            "memory_updates": validation.get("memory_updates"),
        }

    @staticmethod
    def _paper_status(payload: dict) -> dict:
        return {
            "status": payload.get("status"),
            "mode": payload.get("mode"),
            "no_broker_execution": payload.get("no_broker_execution"),
            "decision_count": len(payload.get("decisions") or []),
            "completed_decision_count": len(payload.get("completed_decisions") or []),
        }

    @staticmethod
    def _alpha_status(payload: dict) -> dict:
        return {
            "status": payload.get("status"),
            "alpha": payload.get("alpha"),
            "sample_size": payload.get("sample_size"),
            "evidence_grade": payload.get("evidence_grade"),
            "truth": payload.get("truth"),
        }
