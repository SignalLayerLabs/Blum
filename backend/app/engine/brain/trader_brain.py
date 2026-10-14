from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.engine.contracts import ENGINE_VERSION, PROJECT_FEATURE_SET
from app.models import (
    AlphaRecoveryAction,
    BlumLearningExperiment,
    BlumTradingPowerScore,
    DashboardSnapshot,
    DecisionSuperiorityScore,
    ExecutionSimulation,
    FeedbackLoopAudit,
    HistoricalPrediction,
    LearningBenchmarkComparison,
    LearningEvent,
    LearningFocusPriority,
    LearningRun,
    LearningStrengthWeaknessMap,
    MetaCognitionEvent,
    ReasoningNoiseFlag,
    SelfImprovementAction,
    TradeLearningEvidence,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    PredictionOutcome,
    TradingCapitalCycle,
    TradingGame,
    TradingGameTrade,
    TradingIntelligenceMetric,
)
from app.services.alpha_operating_system import (
    AlphaGateService,
    AlphaReadinessEngine,
    EdgeMapService,
    PaperCopyTradingService,
    TradingGameReadinessService,
)
from app.services.learning_summary import LearningSummaryService
from app.services.copy_readiness_evidence import CopyReadinessSummaryService
from app.services.brain_learning_proof import BrainLearningProofService
from app.services.research_planner import AutonomousResearchPlanner
from app.services.trading_intelligence_lab import paper_forward_actionability_summary
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.paper_forward_direction import (
    INVALID_PENDING_RECOMPUTATION,
    paper_trade_evidence_is_eligible,
)


TRADER_BRAIN_VERSION = ENGINE_VERSION
TRADER_BRAIN_FEATURE_SET = PROJECT_FEATURE_SET
settings = get_settings()


class TraderBrainService:
    """Trader-focused read model built from stored evidence only.

    This service is intentionally thin: it does not run the Learning Loop,
    recalculate benchmarks, create trades, or modify weights. It turns the
    existing BLUM subsystems into four product-grade read surfaces.
    """

    def brain(self, db: Session) -> dict:
        proof = BrainLearningProofService().snapshot(db)
        latest_power = latest_row(db, BlumTradingPowerScore)
        latest_decision = latest_row(db, DecisionSuperiorityScore)
        latest_metric = latest_row(db, TradingIntelligenceMetric)
        latest_run = latest_row(db, LearningRun)
        latest_lesson = latest_row(db, TradeLearningEvidence)
        latest_regression = latest_row(db, ReasoningNoiseFlag)
        latest_improvement = latest_row(db, SelfImprovementAction)
        weakness = db.scalar(
            select(LearningStrengthWeaknessMap)
            .order_by(desc(LearningStrengthWeaknessMap.weakness_score), desc(LearningStrengthWeaknessMap.calculated_at))
            .limit(1)
        )
        strength = db.scalar(
            select(LearningStrengthWeaknessMap)
            .order_by(desc(LearningStrengthWeaknessMap.strength_score), desc(LearningStrengthWeaknessMap.calculated_at))
            .limit(1)
        )
        focus = db.scalar(
            select(LearningFocusPriority)
            .where(LearningFocusPriority.status.in_(["active", "proposed"]))
            .order_by(desc(LearningFocusPriority.expected_learning_value), desc(LearningFocusPriority.created_at))
            .limit(1)
        )
        benchmarks = latest_benchmarks(db)
        learning = lightweight_learning_status(latest_run)
        readiness = lightweight_trading_readiness(latest_metric, latest_power, latest_lesson)
        alpha = lightweight_alpha_status(benchmarks, latest_power, latest_metric)
        decision_quality = decision_quality_score(latest_decision, latest_metric)
        unified_paper = DashboardSnapshotService().latest(db, "unified_paper_trading_summary")
        unified_payload = unified_paper.get("payload") or {}
        unified_counts = (unified_payload.get("counts") or {}).get("aggregate") or {}
        unified_metrics = (unified_payload.get("metrics") or {}).get("aggregate") or {}
        forward_closed_trades = int(safe_float(unified_counts.get("closed"), 0.0) or 0)
        forward_expectancy = safe_float(
            unified_metrics.get("expectancy_r", unified_metrics.get("average_r")),
            None,
        )
        evidence_quality = evidence_quality_score(
            readiness,
            alpha,
            benchmarks,
            forward_closed_trades=forward_closed_trades,
            forward_expectancy=forward_expectancy,
        )
        calibration = safe_float(getattr(latest_power, "statistical_confidence_score", None), None)
        learning_velocity = safe_float(getattr(latest_power, "learning_velocity_score", None), None)
        knowledge_quality = knowledge_quality_score(db)
        risk_management = safe_float(getattr(latest_power, "risk_management_score", None), None)
        alpha_readiness = safe_float(alpha.get("alpha_readiness_score"), None)
        reproducibility = safe_float(getattr(latest_power, "reproducibility_score", None), None)
        explainability = explainability_score(db)
        market_coverage = market_coverage_score(db)
        portfolio_intelligence = safe_float(getattr(latest_power, "regime_robustness_score", None), None)
        components = {
            "decision_quality": decision_quality,
            "evidence_quality": evidence_quality,
            "calibration": calibration,
            "learning_stability": stability_score(latest_metric),
            "risk_management": risk_management,
            "alpha_readiness": alpha_readiness,
            "reproducibility": reproducibility,
            "explainability": explainability,
            "market_coverage": market_coverage,
            "portfolio_intelligence": portfolio_intelligence,
            "knowledge_quality": knowledge_quality,
        }
        brain_score = safe_float(getattr(latest_power, "score", None), None)
        if brain_score is None:
            brain_score = weighted_average(components)
        truth = truth_lines(brain_score, learning, alpha, benchmarks)
        if forward_closed_trades == 0:
            truth.insert(1, "No closed forward trades are available; activity is not evidence of trading skill.")
        elif forward_expectancy is not None and forward_expectancy <= 0:
            truth.insert(
                1,
                f"Forward expectancy is {forward_expectancy:.3f}R; negative-edge strategies must remain quarantined.",
            )
        return {
            "status": "ready" if brain_score is not None else "insufficient_evidence",
            "version": TRADER_BRAIN_VERSION,
            "feature_set": TRADER_BRAIN_FEATURE_SET,
            "generated_at": datetime.utcnow().isoformat(),
            "brain_score": brain_score,
            "brain_classification": classify_brain_score(brain_score),
            "decision_quality": decision_quality,
            "alpha_readiness": alpha_readiness,
            "learning_progress": {
                "latest_run_status": learning.get("latest_learning_run_status"),
                "latest_run_at": learning.get("latest_learning_run_at"),
                "last_cycle_status": getattr(latest_run, "status", None) if latest_run else None,
                "learning_velocity": learning_velocity,
                "target_progress": learning.get("target_progress"),
            },
            "current_learning_objective": focus_payload(focus),
            "current_learning_phase": phase_from_run(latest_run, readiness),
            "last_validated_improvement": improvement_payload(latest_improvement),
            "latest_regression": noise_payload(latest_regression),
            "current_weakness": weakness_payload(weakness),
            "current_strength": weakness_payload(strength),
            "evidence_quality": evidence_quality,
            "learning_velocity": learning_velocity,
            "knowledge_quality": knowledge_quality,
            "brain_status": status_line(brain_score, alpha, readiness),
            "last_learning_cycle": run_payload(latest_run),
            "next_planned_experiment": focus_payload(focus),
            "learning_chart": learning_chart(db),
            **proof,
            "truth": truth[:6],
            "component_scores": components,
            "readiness": {
                "trading_game": readiness.get("status"),
                "alpha": alpha.get("status"),
                "evidence_grade": alpha.get("evidence_grade") or readiness.get("evidence_grade"),
            },
            "latest_lesson": lesson_payload(latest_lesson),
            "paper_trading_performance": {
                "snapshot_status": unified_paper.get("status"),
                "snapshot_created_at": unified_paper.get("created_at"),
                "counts": (unified_payload.get("counts") or {}).get("aggregate") or {},
                "metrics": (unified_payload.get("metrics") or {}).get("aggregate") or {},
                "by_market": (unified_payload.get("metrics") or {}).get("by_market") or {},
            },
            "policy": "Trader Brain is read-only. It observes stored evidence and never triggers training, trading or recalculation during page render.",
        }

    def training_ground(self, db: Session) -> dict:
        from app.services.adaptive_replay_training import ReplayTrainingSnapshotService

        latest_run = latest_row(db, LearningRun)
        replay = ReplayTrainingSnapshotService().snapshot(db)
        research_planner = AutonomousResearchPlanner().summary(db)
        lessons = dedupe_lessons(
            db.scalars(select(TradeLearningEvidence).order_by(desc(TradeLearningEvidence.created_at)).limit(80)).all()
        )
        focus = db.scalars(
            select(LearningFocusPriority)
            .where(LearningFocusPriority.status.in_(["active", "proposed"]))
            .order_by(desc(LearningFocusPriority.expected_learning_value), desc(LearningFocusPriority.created_at))
            .limit(8)
        ).all()
        improvements = db.scalars(select(SelfImprovementAction).order_by(desc(SelfImprovementAction.created_at)).limit(8)).all()
        noise = db.scalars(select(ReasoningNoiseFlag).order_by(desc(ReasoningNoiseFlag.created_at)).limit(8)).all()
        latest_trade = latest_row(db, TradingGameTrade)
        paper_rows = db.scalars(select(LiveForwardPaperTrade).order_by(desc(LiveForwardPaperTrade.created_at)).limit(250)).all()
        paper_actionability = paper_forward_actionability_summary(paper_rows)
        validation = validation_summary(db, latest_run)
        training_continuity = training_continuity_payload(db, latest_run)
        return {
            "status": "ready",
            "version": TRADER_BRAIN_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "current_experiment": experiment_from_focus(focus[0] if focus else None, latest_run),
            "current_hypothesis": hypothesis_from_focus(focus[0] if focus else None),
            "research_planner": research_planner,
            "current_validation": validation,
            "budget_guard": validation.get("budget_guard"),
            "training_continuity": training_continuity,
            "learning_acceleration": latest_learning_acceleration_payload(db),
            "learning_experiments": latest_learning_experiments_payload(db),
            "trades_being_analyzed": trade_analysis_payload(db),
            "patterns_discovered": [lesson_payload(row) for row in lessons if row.lesson_type not in ["setup_failed", "entry_timing_bad"]][:8],
            "patterns_rejected": [lesson_payload(row) for row in lessons if row.lesson_type in ["setup_failed", "entry_timing_bad"]][:8],
            "knowledge_gained": [lesson_payload(row) for row in lessons[:10]],
            "confidence_updated": latest_confidence_update(db),
            "why_model_changed": [improvement_payload(row) for row in improvements],
            "learning_timeline": learning_timeline(db),
            "active_focus": [focus_payload(row) for row in focus],
            "noise_flags": [noise_payload(row) for row in noise],
            "latest_trade": trade_payload(latest_trade),
            "paper_forward_learning_blocker": paper_forward_learning_blocker(paper_actionability),
            "paper_forward_actionability_summary": paper_actionability,
            **replay,
            "hyperbolic_replay": replay,
            "policy": "Training Ground observes the autonomous Learning Loop. It does not start experiments from the frontend.",
        }

    def paper_trading(self, db: Session, limit: int = 20) -> dict:
        copy = PaperCopyTradingService().summary(db, limit=limit)
        ledger = db.scalars(select(TradingGameTrade).order_by(desc(TradingGameTrade.created_at)).limit(limit)).all()
        paper_decisions = [paper_decision(row) for row in copy.get("rows", [])]
        closed_decisions = [completed_trade_decision(row) for row in ledger if row.exit_date is not None][:limit]
        open_trade_decisions = [completed_trade_decision(row) for row in ledger if row.exit_date is None][:limit]
        open_decisions = open_trade_decisions + [pending_paper_decision(row) for row in paper_decisions]
        readiness_state = paper_trading_readiness_state(copy, paper_decisions, open_trade_decisions, closed_decisions)
        return {
            "status": copy.get("status", "ok"),
            "version": TRADER_BRAIN_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "snapshot_type": "PaperTradingSnapshot",
            "mode": "paper_only",
            "no_broker_execution": True,
            "copy_readiness": copy.get("readiness"),
            "readiness_state": readiness_state,
            "readiness_explanation": paper_trading_readiness_explanation(readiness_state, copy),
            "readiness_states_supported": [
                "READY",
                "NO_DECISIONS",
                "NO_ELIGIBLE_SETUPS",
                "NO_SNAPSHOTS",
                "WORKER_FAILED",
                "DATA_BLOCKED",
                "INSUFFICIENT_EVIDENCE",
            ],
            "decisions": paper_decisions,
            "pending_decisions": [pending_paper_decision(row) for row in paper_decisions],
            "completed_decisions": closed_decisions,
            "closed_decisions": closed_decisions,
            "open_decisions": open_decisions[:limit],
            "journal_summary": paper_journal_summary(open_decisions, closed_decisions, paper_decisions),
            "truth_layer": copy.get("truth_layer") or ["Paper trading evidence is informational only."],
            "warnings": copy.get("warnings", []),
            "policy": "No brokers, no live execution, no financial advice. Copyability increases only with stored paper evidence.",
        }

    def alpha(self, db: Session) -> dict:
        alpha_readiness = AlphaReadinessEngine().readiness(db)
        copy_readiness = CopyReadinessSummaryService().summary(db)
        gates = AlphaGateService().gates(db)
        live_game = latest_row(db, LiveForwardPaperGame)
        benchmarks = latest_benchmarks(db)
        paper_rows = db.scalars(select(LiveForwardPaperTrade).order_by(desc(LiveForwardPaperTrade.created_at)).limit(500)).all()
        closed_history = db.scalars(select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.status.in_(["CLOSED", "EXPIRED", "INVALIDATED"]),
                LiveForwardPaperTrade.closed_at.is_not(None), LiveForwardPaperTrade.exit_price.is_not(None),
                LiveForwardPaperTrade.position_size > 0)
            .order_by(desc(LiveForwardPaperTrade.closed_at), desc(LiveForwardPaperTrade.id)).limit(500)).all()
        paper_rows = list({row.id: row for row in [*paper_rows, *closed_history]}.values())
        excluded_evidence_types = {
            "PAPER_FORWARD_INTRADAY_EXPERIMENTAL",
            "PAPER_FORWARD_INVALID_ENTRY_GEOMETRY",
            INVALID_PENDING_RECOMPUTATION,
        }
        eligible_paper_rows = [
            row
            for row in paper_rows
            if row.evidence_type not in excluded_evidence_types
            and paper_trade_evidence_is_eligible(row)
        ]
        intraday_rows = [row for row in eligible_paper_rows if row.evidence_type == "PAPER_FORWARD_INTRADAY"]
        standard_paper_rows = [row for row in eligible_paper_rows if row.evidence_type != "PAPER_FORWARD_INTRADAY"]
        lesson_rows = dedupe_lessons(
            db.scalars(select(TradeLearningEvidence).order_by(desc(TradeLearningEvidence.created_at)).limit(60)).all()
        )
        closed_rows = [row for row in eligible_paper_rows if paper_forward_trade_is_closed(row)]
        open_rows = [row for row in eligible_paper_rows if paper_forward_trade_is_open(row)]
        all_benchmark_rows = [row for row in closed_rows if row.benchmark_return_same_period is not None or row.excess_return_vs_benchmark is not None]
        paper_summary = paper_forward_alpha_summary(eligible_paper_rows, live_game)
        actionability_summary = paper_forward_actionability_summary(eligible_paper_rows)
        lifecycle_mode = paper_forward_lifecycle_mode(actionability_summary)
        blocker_rows = alpha_blockers(eligible_paper_rows, closed_rows, benchmarks, paper_summary, actionability_summary=actionability_summary, lifecycle_mode=lifecycle_mode)
        historical_split = historical_replay_evidence_split(db, benchmarks)
        walk_forward_split = walk_forward_evidence_split(db, benchmarks)
        standard_actionability = paper_forward_actionability_summary(standard_paper_rows)
        paper_split = paper_forward_evidence_split(standard_paper_rows, live_game, label="Paper-Forward Evidence", actionability_summary=standard_actionability, lifecycle_mode=lifecycle_mode)
        live_split = live_forward_evidence_split(standard_paper_rows, live_game, actionability_summary=standard_actionability, lifecycle_mode=lifecycle_mode)
        intraday_split = intraday_paper_evidence_split(intraday_rows, live_game)
        unified_paper = DashboardSnapshotService().latest(db, "unified_paper_trading_summary")
        forex_split = forex_paper_evidence_split(unified_paper)
        evidence_split = {
            "historical_replay": historical_split,
            "walk_forward_validation": walk_forward_split,
            "paper_forward": paper_split,
            "intraday_paper_forward": intraday_split,
            "forex_paper_forward": forex_split,
            "live_forward": live_split,
        }
        evidence_grade, evidence_reason = alpha_grade_from_splits(evidence_split)
        verdict = alpha_verdict_from_splits(evidence_split, evidence_grade)
        latest_update = latest_alpha_update_from_splits(evidence_split) or latest_paper_forward_update(eligible_paper_rows, benchmarks)
        primary_evidence = primary_alpha_evidence(evidence_split)
        # live_forward is a second view of paper_forward, not independent observations.
        total_evidence_sample = sum(int(split.get("sample_size") or 0) for key, split in evidence_split.items() if isinstance(split, dict) and key != "live_forward")
        unified_payload = unified_paper.get("payload") or {}
        unified_counts = (unified_payload.get("counts") or {}).get("aggregate") or {}
        unified_metrics = (unified_payload.get("metrics") or {}).get("aggregate") or {}
        return {
            "status": evidence_grade,
            "version": TRADER_BRAIN_VERSION,
            "snapshot_type": "AlphaSnapshot",
            "generated_at": datetime.utcnow().isoformat(),
            "readiness_status": evidence_grade,
            "evidence_grade": evidence_grade,
            "evidence_reason": evidence_reason,
            "verdict": verdict,
            "last_updated_at": latest_update,
            "sample_size": len(closed_rows),
            "forward_sample_size": len(closed_rows),
            "total_evidence_sample_size": total_evidence_sample,
            "primary_evidence": primary_evidence,
            "closed_trade_count": len(closed_rows),
            "combined_closed_trade_count": int(unified_counts.get("closed") or len(closed_rows)),
            "open_trade_count": len(open_rows),
            "paper_forward_lifecycle_mode": lifecycle_mode,
            "paper_forward_actionability_summary": actionability_summary,
            "min_required_sample_size": 30,
            "blum_return": paper_summary["blum_return"],
            "benchmark_return": paper_summary["benchmark_return"],
            "alpha": paper_summary["alpha"],
            "sharpe": paper_summary["sharpe"],
            "sortino": paper_summary["sortino"],
            "max_drawdown": paper_summary["max_drawdown"],
            "drawdown": paper_summary["max_drawdown"],
            "expectancy": paper_summary["expectancy"],
            "profit_factor": paper_summary["profit_factor"],
            "win_rate": paper_summary["win_rate"],
            "average_r": paper_summary["average_r"],
            "median_r": paper_summary["median_r"],
            "best_trade": alpha_trade_summary(paper_summary["best_trade"]),
            "worst_trade": alpha_trade_summary(paper_summary["worst_trade"]),
            "benchmark_excess": paper_summary["benchmark_excess"],
            "realized_pnl": paper_summary["realized_pnl"],
            "unrealized_pnl": paper_summary["unrealized_pnl"],
            "combined_paper_forward_performance": {
                "snapshot_status": unified_paper.get("status"),
                "snapshot_created_at": unified_paper.get("created_at"),
                "counts": unified_counts,
                "metrics": unified_metrics,
                "by_market": (unified_payload.get("metrics") or {}).get("by_market") or {},
            },
            "paper_forward_alpha": paper_summary["alpha"],
            "historical_alpha": historical_split.get("benchmark_excess"),
            "walk_forward_alpha": walk_forward_split.get("benchmark_excess"),
            "walk_forward_benchmark_status": alpha_benchmark_gap_payload(
                int(walk_forward_split.get("sample_size") or 0),
                walk_forward_split.get("blum_return"),
                walk_forward_split.get("benchmark_return"),
                walk_forward_split.get("benchmark_excess"),
            ),
            "live_forward_alpha": live_split.get("benchmark_excess"),
            "best_edge": edge_summary(eligible_paper_rows, "best"),
            "worst_edge": edge_summary(eligible_paper_rows, "worst"),
            "biggest_weakness": blocker_rows[0] if blocker_rows else None,
            "current_blocker": blocker_rows[0]["title"] if blocker_rows else None,
            "current_risk_warning": alpha_risk_warning(paper_summary, blocker_rows),
            "latest_lesson_affecting_alpha": latest_alpha_lesson(closed_rows, lesson_rows),
            "confidence_in_evidence": confidence_in_alpha_evidence(evidence_grade, len(closed_rows), bool(all_benchmark_rows or benchmarks)),
            "evidence_split": evidence_split,
            "historical": historical_split,
            "walk_forward": walk_forward_split,
            "paper_forward": paper_split,
            "intraday_paper_forward": intraday_split,
            "forex_paper_forward": forex_split,
            "live_forward": live_split,
            "current_alpha_readiness": alpha_readiness,
            "copy_readiness": copy_readiness,
            "edge_map": alpha_edge_map(eligible_paper_rows),
            "weakness_map": alpha_weakness_map(eligible_paper_rows, closed_rows, benchmarks, paper_summary),
            "current_blockers": blocker_rows,
            "latest_alpha_lessons": alpha_lessons(closed_rows, lesson_rows),
            "gates": gates,
            "truth": alpha_truth_lines(verdict, blocker_rows, paper_summary, evidence_split),
            "policy": "Alpha page reports benchmark-relative paper-forward evidence. It never hides underperformance and never claims market beating without sufficient samples.",
        }


def latest_row(db: Session, model):
    order_attr = None
    for name in ("calculated_at", "created_at", "updated_at", "started_at", "generated_at"):
        if hasattr(model, name):
            order_attr = getattr(model, name)
            break
    if order_attr is None:
        order_attr = getattr(model, "id")
    return db.scalar(select(model).order_by(desc(order_attr)).limit(1))


def latest_benchmarks(db: Session) -> list[LearningBenchmarkComparison]:
    rows = db.scalars(select(LearningBenchmarkComparison).order_by(desc(LearningBenchmarkComparison.calculated_at)).limit(60)).all()
    latest: dict[str, LearningBenchmarkComparison] = {}
    for row in rows:
        latest.setdefault(f"{row.mode}:{row.benchmark_name}", row)
    return list(latest.values())


def lightweight_learning_status(row: LearningRun | None) -> dict:
    return {
        "latest_learning_run_status": getattr(row, "status", None),
        "latest_learning_run_at": row.started_at.isoformat() if row and row.started_at else None,
        "target_progress": None,
        "warnings": [],
    }


def lightweight_trading_readiness(
    metric: TradingIntelligenceMetric | None,
    power: BlumTradingPowerScore | None,
    latest_lesson: TradeLearningEvidence | None,
) -> dict:
    has_evidence = any([metric, power, latest_lesson])
    return {
        "status": "READY" if has_evidence else "INSUFFICIENT_EVIDENCE",
        "evidence_grade": lightweight_evidence_grade(
            getattr(metric, "trades_count", None),
            getattr(power, "statistical_confidence_score", None),
        ),
    }


def lightweight_alpha_status(
    benchmarks: list[LearningBenchmarkComparison],
    power: BlumTradingPowerScore | None,
    metric: TradingIntelligenceMetric | None,
) -> dict:
    benchmark_samples = sum(int(getattr(row, "sample_size", 0) or 0) for row in benchmarks)
    return {
        "status": "READY" if benchmark_samples >= 30 else "INSUFFICIENT_EVIDENCE",
        "evidence_grade": lightweight_evidence_grade(
            benchmark_samples or getattr(metric, "trades_count", None),
            getattr(power, "statistical_confidence_score", None),
        ),
        "alpha_readiness_score": safe_float(getattr(power, "benchmark_relative_score", None), None),
        "trade_count": safe_float(getattr(metric, "trades_count", None), 0.0),
    }


def lightweight_evidence_grade(sample_size: Any, confidence_score: Any = None) -> str:
    confidence = safe_float(confidence_score, None)
    samples = int(safe_float(sample_size, 0.0) or 0)
    if samples >= 100 and (confidence is None or confidence >= 70):
        return "strong"
    if samples >= 50:
        return "medium"
    if samples >= 10:
        return "low"
    return "insufficient"


def decision_quality_score(decision: DecisionSuperiorityScore | None, metric: TradingIntelligenceMetric | None) -> float | None:
    values = [
        safe_float(getattr(decision, "score", None), None),
        safe_float(getattr(metric, "trade_quality_score", None), None),
        safe_float(getattr(metric, "risk_reward_quality_score", None), None),
        safe_float(getattr(metric, "entry_timing_score", None), None),
        safe_float(getattr(metric, "exit_timing_score", None), None),
    ]
    return average_present(values)


def evidence_quality_score(
    readiness: dict,
    alpha: dict,
    benchmarks: list[LearningBenchmarkComparison],
    *,
    forward_closed_trades: int = 0,
    forward_expectancy: float | None = None,
) -> float | None:
    grade = str(alpha.get("evidence_grade") or readiness.get("evidence_grade") or "insufficient").lower()
    grade_score = {"strong": 82.0, "medium": 62.0, "low": 42.0, "weak": 34.0, "insufficient": 20.0}.get(grade, 35.0)
    benchmark_score = min(100.0, len(benchmarks) * 18.0)
    forward_trade_score = min(100.0, max(0, int(forward_closed_trades)) / 30.0 * 100.0)
    score = (grade_score * 0.35) + (benchmark_score * 0.25) + (forward_trade_score * 0.40)
    if forward_closed_trades <= 0:
        score = min(score, 25.0)
    if not benchmarks:
        score = min(score, 45.0)
    if forward_expectancy is None:
        score = min(score, 50.0)
    elif forward_expectancy <= 0:
        score -= 30.0
    return round(max(0.0, min(100.0, score)), 2)


def knowledge_quality_score(db: Session) -> float | None:
    lessons = int(db.scalar(select(func.count(TradeLearningEvidence.id))) or 0)
    meta = int(db.scalar(select(func.count(MetaCognitionEvent.id))) or 0)
    focus = int(db.scalar(select(func.count(LearningFocusPriority.id))) or 0)
    total = lessons + meta + focus
    if total == 0:
        return None
    return round(min(100.0, 20.0 + lessons * 0.4 + meta * 1.2 + focus * 1.5), 2)


def explainability_score(db: Session) -> float | None:
    with_lessons = int(db.scalar(select(func.count(TradeLearningEvidence.id))) or 0)
    trades = int(db.scalar(select(func.count(TradingGameTrade.id))) or 0)
    if trades == 0:
        return None
    return round(min(100.0, 35.0 + (with_lessons / max(1, min(trades, 500))) * 100.0), 2)


def market_coverage_score(db: Session) -> float | None:
    tickers = int(db.scalar(select(func.count(func.distinct(TradingGameTrade.ticker)))) or 0)
    sectors = int(db.scalar(select(func.count(func.distinct(TradingGameTrade.sector)))) or 0)
    if tickers == 0:
        return None
    return round(min(100.0, tickers * 1.5 + sectors * 5.0), 2)


def stability_score(metric: TradingIntelligenceMetric | None) -> float | None:
    if metric is None:
        return None
    drawdown = abs(safe_float(getattr(metric, "max_drawdown", None), 0.0))
    profit_factor = safe_float(getattr(metric, "profit_factor", None), 0.0)
    score = 55.0 + min(25.0, profit_factor * 5.0) - min(35.0, drawdown)
    return round(max(0.0, min(100.0, score)), 2)


def weighted_average(values: dict[str, float | None]) -> float | None:
    present = [value for value in values.values() if value is not None]
    if not present:
        return None
    return round(mean(present), 2)


def learning_chart(db: Session) -> list[dict]:
    rows = db.scalars(select(BlumTradingPowerScore).order_by(desc(BlumTradingPowerScore.calculated_at)).limit(30)).all()
    return [
        {
            "timestamp": row.calculated_at.isoformat() if row.calculated_at else None,
            "brain_score": row.score,
            "decision_quality": row.decision_quality_score,
            "learning_velocity": row.learning_velocity_score,
            "classification": row.classification,
        }
        for row in reversed(rows)
    ]


def truth_lines(brain_score: float | None, learning: dict, alpha: dict, benchmarks: list[LearningBenchmarkComparison]) -> list[str]:
    lines: list[str] = []
    if brain_score is None:
        lines.append("Not enough stored evidence to score the Trader Brain yet.")
    else:
        lines.append(f"Trader Brain Score is {brain_score:.1f}/100: {classify_brain_score(brain_score)}.")
    if alpha.get("status") in {"INSUFFICIENT_EVIDENCE", "DATA_QUALITY_BLOCKED"}:
        lines.append("Alpha evidence is not mature enough for trust.")
    for row in benchmarks[:3]:
        label = row.result_label or "inconclusive"
        lines.append(f"BLUM vs {row.benchmark_name}: {label}, excess {format_pct(row.excess_return)}; sample {row.sample_size or 0}.")
    for warning in (learning.get("warnings") or [])[:2]:
        lines.append(str(warning))
    return lines[:6]


def classify_brain_score(score: float | None) -> str:
    if score is None:
        return "insufficient evidence"
    if score < 25:
        return "not trader-ready"
    if score < 45:
        return "amateur learning"
    if score < 60:
        return "research grade"
    if score < 75:
        return "promising trader brain"
    if score < 88:
        return "strong paper-trading brain"
    return "external validation required"


def status_line(score: float | None, alpha: dict, readiness: dict) -> str:
    if readiness.get("status") not in {"READY", "STALE_BUT_USABLE"}:
        return f"training evidence not renderable: {readiness.get('status')}"
    if alpha.get("status") == "INSUFFICIENT_EVIDENCE":
        return "learning, but alpha evidence remains insufficient"
    return classify_brain_score(score)


def phase_from_run(row: LearningRun | None, readiness: dict) -> str:
    if readiness.get("status") not in {"READY", "STALE_BUT_USABLE"}:
        return "evidence construction"
    if row is None:
        return "waiting for first learning cycle"
    if row.status in {"running", "started"}:
        return "experiment running"
    if row.status in {"completed", "ok"}:
        return "post-experiment evaluation"
    return row.status or "unknown"


def focus_payload(row: LearningFocusPriority | None) -> dict | None:
    if row is None:
        return None
    return {
        "priority_type": row.priority_type,
        "target": row.target,
        "reason": row.reason,
        "expected_learning_value": row.expected_learning_value,
        "urgency": row.urgency,
        "sample_gap": row.sample_gap,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def improvement_payload(row: SelfImprovementAction | None) -> dict | None:
    if row is None:
        return None
    return {
        "detected_problem": row.detected_problem,
        "recommended_action": row.recommended_action,
        "affected_module": row.affected_module,
        "priority": row.priority,
        "status": row.status,
        "improvement_observed": row.improvement_observed,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def noise_payload(row: ReasoningNoiseFlag | None) -> dict | None:
    if row is None:
        return None
    return {
        "factor_name": row.factor_name,
        "module_name": row.module_name,
        "noise_type": row.noise_type,
        "severity": row.severity,
        "recommended_action": row.recommended_action,
        "status": row.status,
        "explanation": row.explanation,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def weakness_payload(row: LearningStrengthWeaknessMap | None) -> dict | None:
    if row is None:
        return None
    return {
        "dimension": row.dimension,
        "entity": row.entity,
        "strength_score": row.strength_score,
        "weakness_score": row.weakness_score,
        "sample_size": row.sample_size,
        "main_problem": row.main_problem,
        "recommended_action": row.recommended_action,
        "priority": row.priority,
    }


def run_payload(row: LearningRun | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "trigger": row.trigger,
        "batch_size": row.batch_size,
        "predictions_generated": row.predictions_created,
        "outcomes_evaluated": row.outcomes_evaluated,
        "mistakes_analyzed": row.mistakes_found,
        "memory_updates": row.memory_updates,
    }


def lesson_payload(row: TradeLearningEvidence | None) -> dict | None:
    if row is None:
        return None
    return {
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "regime": row.regime,
        "lesson_type": row.lesson_type,
        "observation": row.observation,
        "sample_size": row.sample_size,
        "affected_module": row.affected_module,
        "action_taken": row.action_taken,
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def trade_payload(row: TradingGameTrade | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "entry_date": row.entry_date.isoformat() if row.entry_date else None,
        "exit_date": row.exit_date.isoformat() if row.exit_date else None,
        "outcome_label": row.outcome_label,
        "net_pnl_eur": row.net_pnl_eur,
        "r_multiple": row.realized_r_multiple,
        "lesson_generated": row.lesson_generated,
    }


def paper_decision(row: dict) -> dict:
    ticker = row.get("ticker")
    payload = row if isinstance(row, dict) else {}
    return {
        "decision_id": f"candidate-{ticker or 'unknown'}-{str(payload.get('setup_type') or payload.get('actionability') or 'paper').lower()}",
        "source_type": "paper_candidate",
        "status": "pending_trigger",
        "ticker": ticker,
        "side": infer_side(payload),
        "entry": payload.get("entry_zone") or payload.get("entry_trigger"),
        "exit": None,
        "stop": payload.get("invalidation_level"),
        "targets": [item for item in [payload.get("target_1"), payload.get("target_2")] if item is not None],
        "holding_period": payload.get("expected_holding_period") or payload.get("timeframe"),
        "holding_estimate": payload.get("expected_holding_period") or payload.get("timeframe"),
        "position_size": payload.get("position_size"),
        "risk": payload.get("risk_amount_eur") or payload.get("risk_reward_estimate"),
        "expected_risk": payload.get("risk_amount_eur") or payload.get("risk_reward_estimate"),
        "reward": payload.get("risk_reward_estimate"),
        "expected_reward": payload.get("risk_reward_estimate"),
        "expected_alpha": payload.get("historical_reliability"),
        "pnl": None,
        "pnl_percent": None,
        "pnl_per_share": None,
        "r_multiple": None,
        "benchmark_excess": None,
        "outcome": "waiting_for_trigger",
        "lesson_learned": "No outcome yet. This candidate can only teach BLUM after trigger, paper execution and evaluation.",
        "decision_quality": payload.get("copy_readiness_score"),
        "confidence": payload.get("confidence"),
        "copyability": payload.get("copy_readiness"),
        "why": payload.get("paper_instruction"),
        "bull_thesis": payload.get("bull_thesis") or payload.get("why_now"),
        "bear_thesis": payload.get("bear_thesis") or payload.get("what_could_go_wrong"),
        "risk_notes": payload.get("risk") or payload.get("missing_data"),
        "missing_data": payload.get("missing_data") or [],
        "trade_replay": {
            "state": "pending_trigger",
            "entry_decision": payload.get("paper_instruction") or payload.get("entry_trigger"),
            "exit_decision": "No exit exists because this is not a completed paper trade.",
            "risk_plan": {
                "stop": payload.get("invalidation_level"),
                "targets": [item for item in [payload.get("target_1"), payload.get("target_2")] if item is not None],
                "risk": payload.get("risk_amount_eur") or payload.get("risk_reward_estimate"),
                "reward": payload.get("risk_reward_estimate"),
            },
            "lesson": "Pending trigger; no learning outcome stored yet.",
        },
    }


def pending_paper_decision(row: dict) -> dict:
    payload = dict(row)
    payload["decision_id"] = payload.get("decision_id") or f"pending-{payload.get('ticker', 'unknown')}"
    payload["source_type"] = "paper_candidate"
    payload["status"] = payload.get("status") or "pending_trigger"
    return payload


def completed_trade_decision(row: TradingGameTrade) -> dict:
    payload = row.payload if isinstance(row.payload, dict) else {}
    targets = [item for item in [row.initial_target_1, row.initial_target_2] if item is not None]
    decision_quality = first_not_none(
        safe_float(row.trade_quality_score, None),
        average_present([safe_float(row.reproducibility_score, None), safe_float(row.confidence_at_entry, None)]),
    )
    r_multiple = safe_float(row.realized_r_multiple, None)
    status = "closed" if row.exit_date is not None else "open"
    outcome = row.outcome_label or ("open" if row.exit_date is None else "closed")
    return {
        "decision_id": f"trade-{row.id}",
        "trade_id": row.id,
        "source_type": "trading_game_trade",
        "status": status,
        "mode": row.mode,
        "ticker": row.ticker,
        "asset_name": row.asset_name,
        "asset_type": row.asset_type,
        "sector": row.sector,
        "setup_type": row.setup_type,
        "thesis_id": row.thesis_id,
        "side": payload.get("side") or infer_side({"actionability": row.actionability_state_at_entry or row.decision_state}),
        "entry_date": row.entry_date.isoformat() if row.entry_date else None,
        "exit_date": row.exit_date.isoformat() if row.exit_date else None,
        "entry": row.entry_price,
        "stop": row.stop_loss or row.invalidation_level,
        "targets": targets,
        "exit": row.exit_price,
        "holding_period": holding_period(row),
        "holding_days": row.holding_days,
        "position_size": row.position_size,
        "notional_value": row.notional_value,
        "risk": {
            "risk_amount": row.risk_amount,
            "risk_percent": row.risk_percent,
            "max_expected_loss": row.max_expected_loss,
        },
        "reward": {
            "target_1": row.initial_target_1,
            "target_2": row.initial_target_2,
            "max_favorable_excursion": row.max_favorable_excursion,
        },
        "outcome": outcome,
        "pnl": row.net_pnl_eur,
        "gross_pnl": row.gross_pnl_eur,
        "pnl_percent": row.pnl_percent,
        "pnl_per_share": row.pnl_per_share,
        "r_multiple": r_multiple,
        "benchmark_ticker": row.benchmark_ticker,
        "benchmark_return": first_not_none(row.benchmark_return_same_period, row.benchmark_return),
        "benchmark_excess": row.excess_return_vs_benchmark,
        "target_1_hit": row.target_1_hit,
        "target_2_hit": row.target_2_hit,
        "target_hit": row.target_hit,
        "stop_hit": row.stop_hit,
        "invalidation_hit": row.invalidation_hit,
        "missed_entry": row.missed_entry,
        "decision_quality": decision_quality,
        "copyability": copyability_from_trade(row, decision_quality),
        "confidence": row.confidence_at_entry,
        "reproducibility_score": row.reproducibility_score,
        "trade_quality_score": row.trade_quality_score,
        "data_quality_score": row.data_quality_score,
        "lesson_learned": row.lesson_generated,
        "confidence_recalibration": row.payload.get("confidence_recalibration") if isinstance(row.payload, dict) else None,
        "why": row.entry_reason or row.entry_trigger or payload.get("why"),
        "bull_thesis": payload.get("bull_thesis") or row.entry_reason,
        "bear_thesis": payload.get("bear_thesis") or row.exit_reason or payload.get("risk"),
        "risk_notes": payload.get("risk") or row.confirmation_condition,
        "trade_replay": {
            "state": status,
            "entry_decision": row.entry_reason or row.entry_trigger or "Entry reason not stored.",
            "entry_trigger": row.entry_trigger,
            "confirmation_condition": row.confirmation_condition,
            "exit_decision": row.exit_reason or ("Open paper trade; no exit stored yet." if row.exit_date is None else "Exit reason not stored."),
            "exit_trigger": row.exit_trigger,
            "risk_plan": {
                "entry": row.entry_price,
                "stop": row.stop_loss or row.invalidation_level,
                "targets": targets,
                "position_size": row.position_size,
                "risk_amount": row.risk_amount,
                "risk_percent": row.risk_percent,
                "trailing_stop": row.trailing_stop,
            },
            "outcome": {
                "label": outcome,
                "pnl": row.net_pnl_eur,
                "pnl_percent": row.pnl_percent,
                "r_multiple": r_multiple,
                "benchmark_excess": row.excess_return_vs_benchmark,
            },
            "lesson": row.lesson_generated or "No lesson has been generated for this paper trade yet.",
        },
    }


def paper_trading_readiness_state(copy: dict, decisions: list[dict], open_trades: list[dict], closed_decisions: list[dict]) -> str:
    readiness = copy.get("readiness") or {}
    status_text = " ".join(
        str(value)
        for value in [
            copy.get("status"),
            readiness.get("status"),
            *(copy.get("warnings") or []),
            *(readiness.get("warnings") or []),
        ]
        if value
    ).lower()
    if "failed" in status_text or "error" in status_text:
        return "WORKER_FAILED"
    if "blocked" in status_text or "data_blocked" in status_text:
        return "DATA_BLOCKED"
    if decisions or open_trades or closed_decisions:
        return "READY"
    if copy.get("portfolio_snapshot") is None and readiness.get("strategy_count", 0) == 0 and readiness.get("portfolio_count", 0) == 0:
        return "NO_SNAPSHOTS"
    candidate_count = int(readiness.get("candidate_count") or 0)
    copyable_count = int(readiness.get("copyable_candidate_count") or 0)
    if candidate_count > 0 and copyable_count == 0:
        return "NO_ELIGIBLE_SETUPS"
    if candidate_count == 0:
        return "INSUFFICIENT_EVIDENCE"
    return "NO_DECISIONS"


def paper_trading_readiness_explanation(state: str, copy: dict) -> str:
    explanations = {
        "READY": "Paper trading snapshot contains open candidates or completed paper trade evidence.",
        "NO_DECISIONS": "The paper trading worker has state, but no open or closed paper decisions are stored yet.",
        "NO_ELIGIBLE_SETUPS": "BLUM scanned candidates, but no setup currently satisfies copyability, trigger and risk requirements.",
        "NO_SNAPSHOTS": "No durable paper trading snapshot exists yet. The backend worker must create a snapshot before the journal can show trades.",
        "WORKER_FAILED": "The paper trading worker or upstream evidence service reported a failure. The journal is intentionally not fabricating trades.",
        "DATA_BLOCKED": "Required market or paper trading data is blocked or unavailable. BLUM cannot build a reliable paper decision journal.",
        "INSUFFICIENT_EVIDENCE": "There is not enough stored evidence to create a paper decision without inventing data.",
    }
    warnings = copy.get("warnings") or []
    suffix = f" Warnings: {', '.join(map(str, warnings[:3]))}." if warnings else ""
    return f"{explanations.get(state, explanations['NO_DECISIONS'])}{suffix}"


def paper_journal_summary(open_decisions: list[dict], closed_decisions: list[dict], pending_decisions: list[dict]) -> dict:
    closed_r = [safe_float(row.get("r_multiple"), None) for row in closed_decisions]
    closed_pnl = [safe_float(row.get("pnl"), None) for row in closed_decisions]
    wins = len([row for row in closed_decisions if str(row.get("outcome") or "").lower() in {"win", "target_hit", "partial_profit"} or safe_float(row.get("pnl"), 0.0) > 0])
    losses = len([row for row in closed_decisions if str(row.get("outcome") or "").lower() in {"loss", "stopped_out", "stop_hit"} or safe_float(row.get("pnl"), 0.0) < 0])
    return {
        "open_count": len(open_decisions),
        "closed_count": len(closed_decisions),
        "pending_candidate_count": len(pending_decisions),
        "wins": wins,
        "losses": losses,
        "average_r": average_present(closed_r),
        "total_pnl": round(sum(value for value in closed_pnl if value is not None), 4) if closed_pnl else None,
    }


def holding_period(row: TradingGameTrade) -> str | None:
    if row.holding_days is not None:
        return f"{row.holding_days} days"
    if row.entry_date and row.exit_date:
        return f"{(row.exit_date - row.entry_date).days} days"
    if row.entry_date and row.exit_date is None:
        return "open"
    return None


def copyability_from_trade(row: TradingGameTrade, decision_quality: float | None) -> str:
    if row.exit_date is None:
        return "manage_open_position"
    if row.missed_entry:
        return "missed_entry_review"
    if decision_quality is None:
        return "evidence_incomplete"
    if decision_quality >= 75 and (row.realized_r_multiple or 0) > 0:
        return "copyability_improved_by_evidence"
    if decision_quality >= 55:
        return "process_validated_needs_more_samples"
    return "do_not_copy_without_more_evidence"


def infer_side(row: dict) -> str:
    action = str(row.get("actionability") or "").lower()
    if "exit" in action or "reduce" in action:
        return "SELL"
    return "BUY"


def experiment_from_focus(row: LearningFocusPriority | None, latest_run: LearningRun | None) -> dict:
    if row:
        return {
            "name": row.priority_type,
            "target": row.target,
            "reason": row.reason,
            "status": row.status,
            "expected_learning_value": row.expected_learning_value,
        }
    return {
        "name": "background_learning_cycle",
        "target": getattr(latest_run, "trigger", None) or "stored market evidence",
        "reason": "No active focus priority is stored; scheduler continues broad coverage.",
        "status": getattr(latest_run, "status", None) or "waiting",
        "expected_learning_value": None,
    }


def hypothesis_from_focus(row: LearningFocusPriority | None) -> str:
    if row is None:
        return "BLUM is still collecting enough evidence to choose the next focused hypothesis."
    return f"If BLUM studies {row.target}, it may reduce {row.reason or 'a current decision weakness'}."


def validation_from_run(row: LearningRun | None) -> dict:
    if row is None:
        return {"status": "not_started", "summary": "No LearningRun is stored yet."}
    return {
        "status": row.status,
        "predictions_generated": row.predictions_created,
        "outcomes_evaluated": row.outcomes_evaluated,
        "mistakes_analyzed": row.mistakes_found,
        "memory_updates": row.memory_updates,
    }


def validation_summary(db: Session, latest_run: LearningRun | None) -> dict:
    latest_productive = db.scalar(
        select(LearningRun)
        .where(
            (LearningRun.predictions_created > 0)
            | (LearningRun.outcomes_evaluated > 0)
            | (LearningRun.mistakes_found > 0)
            | (LearningRun.memory_updates > 0)
        )
        .order_by(desc(LearningRun.started_at))
        .limit(1)
    )
    since = datetime.utcnow() - timedelta(hours=24)
    totals = learning_run_totals(db)
    totals_24h = learning_run_totals(db, since=since)
    latest_payload = validation_from_run(latest_run)
    productive_payload = validation_from_run(latest_productive)
    visible_payload = (
        productive_payload
        if latest_run
        and latest_run.status in {"budget_wait", "skipped"}
        and latest_productive is not None
        else latest_payload
    )
    return {
        **visible_payload,
        "latest_scheduler_status": latest_payload.get("status"),
        "latest_run": run_payload(latest_run),
        "latest_productive_run": run_payload(latest_productive),
        "budget_guard": budget_guard_payload(latest_run),
        "display_status": display_training_status(latest_run, latest_productive),
        "evidence_total": totals,
        "evidence_24h": totals_24h,
        "summary": training_validation_summary(latest_payload, productive_payload, totals, totals_24h),
    }


def learning_run_totals(db: Session, since: datetime | None = None) -> dict:
    query = select(
        func.count(LearningRun.id),
        func.coalesce(func.sum(LearningRun.predictions_created), 0),
        func.coalesce(func.sum(LearningRun.outcomes_evaluated), 0),
        func.coalesce(func.sum(LearningRun.mistakes_found), 0),
        func.coalesce(func.sum(LearningRun.memory_updates), 0),
    )
    if since is not None:
        query = query.where(LearningRun.started_at >= since)
    runs, predictions, outcomes, mistakes, memory = db.execute(query).one()
    return {
        "runs": int(runs or 0),
        "predictions_generated": int(predictions or 0),
        "outcomes_evaluated": int(outcomes or 0),
        "mistakes_analyzed": int(mistakes or 0),
        "memory_updates": int(memory or 0),
    }


def training_continuity_payload(db: Session, latest_run: LearningRun | None) -> dict:
    productive = db.scalar(
        select(LearningRun)
        .where(
            (LearningRun.predictions_created > 0)
            | (LearningRun.outcomes_evaluated > 0)
            | (LearningRun.memory_updates > 0)
        )
        .order_by(desc(LearningRun.completed_at), desc(LearningRun.started_at))
        .limit(1)
    )
    latest_status = getattr(latest_run, "status", None)
    is_budget_wait = latest_status in {"budget_wait", "skipped"}
    if latest_run is None:
        status = "UNKNOWN"
    elif is_budget_wait and productive is not None:
        status = "THROTTLED"
    elif latest_status in {"failed", "error"}:
        status = "BROKEN"
    elif productive is None:
        status = "STALLED"
    else:
        status = "ACTIVE"
    summary = latest_run.summary if latest_run and isinstance(latest_run.summary, dict) else {}
    guard = summary.get("daily_guard") if isinstance(summary.get("daily_guard"), dict) else {}
    return {
        "status": status,
        "latest_run_status": latest_status,
        "latest_run_at": latest_run.started_at.isoformat() if latest_run and latest_run.started_at else None,
        "last_productive_learning_run_at": (
            productive.completed_at.isoformat()
            if productive and productive.completed_at
            else productive.started_at.isoformat()
            if productive and productive.started_at
            else None
        ),
        "last_productive_predictions": int(productive.predictions_created or 0) if productive else 0,
        "last_productive_outcomes": int(productive.outcomes_evaluated or 0) if productive else 0,
        "last_productive_memory_updates": int(productive.memory_updates or 0) if productive else 0,
        "latest_budget_wait_reason": summary.get("budget_wait_reason") or summary.get("reason") or guard.get("reason") if is_budget_wait else None,
        "learning_throttle_active": status == "THROTTLED",
        "is_learning_stalled": status == "STALLED",
        "next_learning_allowed_at": summary.get("next_allowed_at") or guard.get("next_allowed_at"),
        "policy": "Budget-wait and skipped scheduler rows do not erase the last productive learning evidence.",
    }


def latest_learning_acceleration_payload(db: Session) -> dict:
    event = db.scalar(
        select(LearningEvent)
        .where(LearningEvent.event_type.in_(["blum_learning_acceleration_completed", "OPPORTUNITY_SCANNED", "paper_forward_opportunity_scan_completed"]))
        .order_by(desc(LearningEvent.created_at))
        .limit(1)
    )
    payload = event.payload if event and isinstance(event.payload, dict) else {}
    if event and event.event_type == "blum_learning_acceleration_completed":
        return payload
    acceleration = payload.get("learning_acceleration") if isinstance(payload.get("learning_acceleration"), dict) else None
    if acceleration:
        return acceleration
    return {
        "enabled": settings.blum_learning_acceleration_enabled,
        "status": "no_recent_acceleration",
        "batches_scheduled": 0,
        "batches_completed": 0,
        "priority_markets": [],
        "priority_asset_classes": [],
        "priority_setups": [],
        "uncertainty_targets": [],
        "missed_opportunity_targets": [],
        "repeated_blockers": [],
        "estimated_learning_gain": 0,
        "safety_limits_applied": {
            "max_batches_per_run": settings.blum_learning_acceleration_max_batches_per_run,
            "max_runtime_seconds": settings.blum_learning_acceleration_max_runtime_seconds,
        },
        "next_acceleration_action": "Run backend scanner or manual training acceleration.",
    }


def latest_learning_experiments_payload(db: Session) -> dict:
    rows = db.scalars(
        select(BlumLearningExperiment)
        .order_by(desc(BlumLearningExperiment.updated_at), desc(BlumLearningExperiment.created_at))
        .limit(8)
    ).all()
    active = [learning_experiment_payload(row) for row in rows if row.status not in {"COMPLETED", "REJECTED", "RETIRED"}]
    completed = [learning_experiment_payload(row) for row in rows if row.status == "COMPLETED"]
    return {
        "count": len(rows),
        "active_count": len(active),
        "completed_count": len(completed),
        "active": active,
        "completed": completed,
        "status": "NO_EXPERIMENTS" if not rows else "READY",
    }


def learning_experiment_payload(row: BlumLearningExperiment) -> dict:
    return {
        "experiment_id": row.experiment_id,
        "hypothesis": row.hypothesis,
        "target_market": row.target_market,
        "target_asset_class": row.target_asset_class,
        "target_setup": row.target_setup,
        "sample_size": row.sample_size,
        "benchmark_asset": row.benchmark_asset,
        "status": row.status,
        "result_summary": row.result_summary if isinstance(row.result_summary, dict) else {},
        "conclusion": row.conclusion,
        "next_action": row.next_action,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def alpha_benchmark_gap_payload(
    sample_size: int,
    blum_return: float | None,
    benchmark_return: float | None,
    benchmark_excess: float | None,
) -> dict:
    available = benchmark_return is not None or benchmark_excess is not None
    return {
        "walk_forward_sample_size": sample_size,
        "walk_forward_blum_return": blum_return,
        "walk_forward_benchmark_return": benchmark_return,
        "walk_forward_benchmark_excess": benchmark_excess,
        "benchmark_available": available,
        "benchmark_blocker": None if available else "WALK_FORWARD_BENCHMARK_MISSING",
        "why_benchmark_return_is_unavailable": None
        if available
        else "No stored same-period benchmark comparison is available for walk-forward outcomes.",
        "benchmark_comparison_real": available,
    }


def display_training_status(latest_run: LearningRun | None, latest_productive: LearningRun | None) -> str:
    if latest_run is None and latest_productive is None:
        return "no_training_data"
    if latest_run and latest_run.status in {"running", "started"}:
        return "training_running"
    if latest_run and latest_run.status in {"budget_wait", "skipped"} and latest_productive is not None:
        return "waiting_budget_using_latest_evidence"
    if latest_productive is not None:
        return "evidence_available"
    return getattr(latest_run, "status", None) or "unknown"


def training_validation_summary(latest: dict, productive: dict, totals: dict, totals_24h: dict) -> str:
    if totals["runs"] == 0:
        return "No LearningRun evidence is stored yet."
    if latest.get("status") in {"budget_wait", "skipped"} and productive.get("status") != "not_started":
        return (
            f"Latest run is {latest.get('status')}, but stored evidence exists: "
            f"{totals['predictions_generated']} predictions, {totals['outcomes_evaluated']} outcomes, "
            f"{totals['mistakes_analyzed']} mistakes and {totals['memory_updates']} memory updates."
        )
    if totals_24h["runs"] > 0:
        return (
            f"Last 24h: {totals_24h['runs']} runs, {totals_24h['predictions_generated']} predictions, "
            f"{totals_24h['outcomes_evaluated']} outcomes and {totals_24h['memory_updates']} memory updates."
        )
    return (
        f"Stored evidence: {totals['runs']} runs, {totals['predictions_generated']} predictions, "
        f"{totals['outcomes_evaluated']} outcomes and {totals['memory_updates']} memory updates."
    )


def budget_guard_payload(latest_run: LearningRun | None) -> dict | None:
    if latest_run is None or latest_run.status not in {"budget_wait", "skipped"}:
        return None
    summary = latest_run.summary if isinstance(latest_run.summary, dict) else {}
    guard = summary.get("daily_guard") if isinstance(summary.get("daily_guard"), dict) else {}
    return {
        "status": latest_run.status,
        "started_at": latest_run.started_at.isoformat() if latest_run.started_at else None,
        "reason": summary.get("reason") or guard.get("reason") or "Learning guard paused this scheduler tick.",
        "today_predictions": guard.get("today_predictions"),
        "max_daily_runs": guard.get("max_daily_runs"),
        "policy": "Budget guard rows are not treated as completed training experiments.",
    }


def paper_forward_learning_blocker(summary: dict) -> dict:
    total = int(summary.get("total_candidates") or 0)
    actionable = int(summary.get("actionable_count") or 0)
    waiting = int(summary.get("waiting_for_trigger_count") or 0)
    skipped = int(summary.get("skipped_count") or 0)
    blocked = int(summary.get("data_blocked_count") or 0)
    if total <= 0:
        return {
            "status": "NO_CANDIDATES",
            "summary": "Paper-forward has not produced candidate decisions yet.",
            "learning_impact": "No forward outcomes can be learned until candidates exist.",
        }
    if not settings.paper_forward_lifecycle_enabled:
        return {
            "status": "LIFECYCLE_DISABLED",
            "summary": "Paper-forward lifecycle is disabled; BLUM is freezing decisions but not opening or closing trades.",
            "learning_impact": "Forward learning is limited to candidate/actionability diagnostics until lifecycle is enabled.",
            "top_rejection_reasons": summary.get("top_rejection_reasons") or [],
        }
    if actionable <= 0 and waiting <= 0 and skipped > 0:
        return {
            "status": "NO_ACTIONABLE_CANDIDATES",
            "summary": "Paper-forward is not producing outcomes because candidates are rejected by actionability policy.",
            "learning_impact": "Learning should focus on rejection reasons before changing thresholds.",
            "top_rejection_reasons": summary.get("top_rejection_reasons") or [],
        }
    if waiting > 0 and actionable <= 0:
        return {
            "status": "WAITING_FOR_TRIGGER",
            "summary": "Paper-forward candidates are waiting for entry triggers.",
            "learning_impact": "No forward outcome exists until price confirms an entry condition.",
            "top_rejection_reasons": summary.get("top_rejection_reasons") or [],
        }
    if blocked > 0:
        return {
            "status": "DATA_BLOCKED",
            "summary": "Some paper-forward candidates are blocked by data quality or missing prices.",
            "learning_impact": "Forward evidence is not reliable until data blockers are resolved.",
            "top_rejection_reasons": summary.get("top_rejection_reasons") or [],
        }
    return {
        "status": "READY_FOR_OUTCOMES",
        "summary": "Paper-forward has candidates that can produce forward outcomes once lifecycle and triggers permit it.",
        "learning_impact": "Closed paper-forward trades will feed future learning evidence.",
        "top_rejection_reasons": summary.get("top_rejection_reasons") or [],
    }


def dedupe_lessons(rows: list[TradeLearningEvidence]) -> list[TradeLearningEvidence]:
    seen: set[tuple[str, str, str, str, str]] = set()
    unique: list[TradeLearningEvidence] = []
    for row in rows:
        key = (
            row.ticker or "",
            row.setup_type or "",
            row.regime or "",
            row.lesson_type or "",
            row.observation or "",
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def trade_analysis_payload(db: Session) -> dict:
    total = int(db.scalar(select(func.count(TradingGameTrade.id))) or 0)
    latest = db.scalar(select(func.max(TradingGameTrade.created_at)))
    open_count = int(db.scalar(select(func.count(TradingGameTrade.id)).where(TradingGameTrade.exit_date.is_(None))) or 0)
    return {"total_trades": total, "open_trades": open_count, "latest_trade_at": latest.isoformat() if latest else None}


def latest_confidence_update(db: Session) -> dict | None:
    row = latest_row(db, BlumTradingPowerScore)
    if row is None:
        return None
    return {
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
        "confidence_calibration_score": row.statistical_confidence_score,
        "decision_quality_score": row.decision_quality_score,
        "learning_velocity_score": row.learning_velocity_score,
    }


def learning_timeline(db: Session) -> list[dict]:
    runs = db.scalars(
        select(LearningRun)
        .where(
            (LearningRun.predictions_created > 0)
            | (LearningRun.outcomes_evaluated > 0)
            | (LearningRun.mistakes_found > 0)
            | (LearningRun.memory_updates > 0)
        )
        .order_by(desc(LearningRun.started_at))
        .limit(12)
    ).all()
    output = []
    for row in runs:
        payload = run_payload(row)
        if payload:
            payload["productive"] = True
            payload["display_detail"] = (
                f"predictions {payload['predictions_generated']} | "
                f"outcomes {payload['outcomes_evaluated']} | memory {payload['memory_updates']}"
            )
            output.append(payload)
    return output


def return_percent(game: TradingGame | None, cycle: TradingCapitalCycle | None) -> float | None:
    if cycle and cycle.return_percent is not None:
        return cycle.return_percent
    if game is None or game.starting_capital in (None, 0) or game.current_capital is None:
        return None
    return round(((game.current_capital - game.starting_capital) / game.starting_capital) * 100, 4)


def best_benchmark_return(rows: list[LearningBenchmarkComparison]) -> float | None:
    values = [safe_float(row.benchmark_return, None) for row in rows if row.benchmark_return is not None]
    return average_present(values)


def best_benchmark_excess(rows: list[LearningBenchmarkComparison]) -> float | None:
    values = [safe_float(row.excess_return, None) for row in rows if row.excess_return is not None]
    return average_present(values)


def empty_alpha_evidence_split(label: str, data_source: str, reason: str) -> dict:
    return {
        "label": label,
        "status": "NO_DATA",
        "sample_size": 0,
        "closed_trade_count": 0,
        "blum_return": None,
        "return": None,
        "benchmark_return": None,
        "alpha": None,
        "benchmark_excess": None,
        "average_excess_return": None,
        "expectancy": None,
        "average_r": None,
        "win_rate": None,
        "profit_factor": None,
        "max_drawdown": None,
        "evidence_grade": "NO_DATA",
        "evidence_reason": reason,
        "data_source": data_source,
        "last_updated_at": None,
        "results": [],
    }


def benchmark_evidence_split(
    rows: list[LearningBenchmarkComparison],
    *,
    modes: set[str],
    label: str,
    data_source: str,
    no_data_reason: str,
) -> dict:
    selected = [row for row in rows if str(row.mode or "") in modes]
    if not selected:
        return empty_alpha_evidence_split(label, data_source, no_data_reason)
    sample_size = sum(row.sample_size or 0 for row in selected)
    average_excess = average_present([row.excess_return for row in selected])
    blum_return = average_present([row.blum_return for row in selected])
    benchmark_return = average_present([row.benchmark_return for row in selected])
    grade = evidence_grade_from_benchmark_rows(selected)
    reason = benchmark_evidence_reason(selected, grade, label)
    return {
        "label": label,
        "status": "ready" if sample_size > 0 else "NO_DATA",
        "sample_size": sample_size,
        "closed_trade_count": sample_size,
        "blum_return": blum_return,
        "return": blum_return,
        "benchmark_return": benchmark_return,
        "alpha": average_excess,
        "benchmark_excess": average_excess,
        "average_excess_return": average_excess,
        "expectancy": None,
        "average_r": None,
        "win_rate": average_present([row.hit_rate_vs_benchmark for row in selected if row.hit_rate_vs_benchmark is not None]),
        "profit_factor": None,
        "max_drawdown": average_present([row.blum_max_drawdown for row in selected if row.blum_max_drawdown is not None]),
        "evidence_grade": grade,
        "evidence_reason": reason,
        "data_source": data_source,
        "last_updated_at": latest_iso([row.calculated_at for row in selected if row.calculated_at]),
        "results": [
            {
                "benchmark": row.benchmark_name,
                "result_label": row.result_label,
                "blum_return": row.blum_return,
                "benchmark_return": row.benchmark_return,
                "excess_return": row.excess_return,
                "sample_size": row.sample_size,
                "statistical_confidence": row.statistical_confidence,
            }
            for row in selected[:6]
        ],
    }


def benchmark_evidence_reason(rows: list[LearningBenchmarkComparison], grade: str, label: str) -> str:
    sample_size = sum(row.sample_size or 0 for row in rows)
    if sample_size <= 0:
        return f"{label} benchmark rows exist but contain no sample size."
    labels = {str(row.result_label or "").lower() for row in rows}
    if grade == "INSUFFICIENT_EVIDENCE":
        return f"{label} has stored benchmark evidence, but only {sample_size} samples."
    if "underperforming" in labels:
        return f"{label} includes benchmark underperformance evidence."
    if "outperforming" in labels:
        return f"{label} includes stored benchmark-relative outperformance evidence."
    return f"{label} benchmark evidence is stored, but the result is inconclusive."


def evidence_slice(rows: list[LearningBenchmarkComparison], mode: str) -> dict:
    return benchmark_evidence_split(
        rows,
        modes={mode},
        label=mode.replace("_", " ").title(),
        data_source="learning_benchmark_comparisons",
        no_data_reason=f"No stored {mode.replace('_', ' ')} benchmark rows found.",
    )


def historical_replay_evidence_split(db: Session, benchmarks: list[LearningBenchmarkComparison]) -> dict:
    rows = db.scalars(
        select(TradingGameTrade)
        .where(TradingGameTrade.mode.in_(["historical_simulation", "historical_replay"]))
        .order_by(desc(TradingGameTrade.created_at))
        .limit(500)
    ).all()
    evaluated = [row for row in rows if trading_game_trade_is_evaluated(row)]
    if evaluated:
        return trading_game_evidence_split(evaluated, label="Historical Replay", data_source="trading_game_trades")

    simulations = db.scalars(
        select(ExecutionSimulation)
        .where(ExecutionSimulation.simulation_mode.in_(["historical_trigger", "historical_simulation"]))
        .order_by(desc(ExecutionSimulation.created_at))
        .limit(500)
    ).all()
    if simulations:
        return execution_simulation_evidence_split(simulations)

    return benchmark_evidence_split(
        benchmarks,
        modes={"historical_simulation", "historical_replay"},
        label="Historical Replay",
        data_source="learning_benchmark_comparisons",
        no_data_reason="No stored historical replay trades found.",
    )


def trading_game_trade_is_evaluated(row: TradingGameTrade) -> bool:
    return bool(
        row.exit_date
        or row.net_pnl_eur is not None
        or row.realized_r_multiple is not None
        or str(row.outcome_label or "").lower() not in {"", "inconclusive", "open"}
    )


def trading_game_evidence_split(rows: list[TradingGameTrade], *, label: str, data_source: str) -> dict:
    pnl_values = [safe_float(row.net_pnl_eur, None) for row in rows if row.net_pnl_eur is not None]
    r_values = [safe_float(row.realized_r_multiple, None) for row in rows if row.realized_r_multiple is not None]
    return_values = [historical_trade_return(row) for row in rows]
    benchmark_returns = [first_not_none(row.benchmark_return_same_period, row.benchmark_return) for row in rows]
    excess_values = [value for row in rows if (value := historical_trade_excess(row)) is not None]
    drawdown_values = [safe_float(row.max_adverse_excursion, None) for row in rows if row.max_adverse_excursion is not None]
    wins = sum(1 for row in rows if trading_game_trade_won(row))
    profit_factor = profit_factor_from_values(pnl_values if pnl_values else r_values)
    alpha = average_present(excess_values)
    grade, reason = split_evidence_grade(
        label=label,
        sample_size=len(rows),
        has_benchmark=alpha is not None or average_present(benchmark_returns) is not None,
        alpha=alpha,
        expectancy=average_present(r_values),
        max_drawdown=average_present(drawdown_values),
        profit_factor=profit_factor,
    )
    return {
        "label": label,
        "status": "ready",
        "sample_size": len(rows),
        "closed_trade_count": len(rows),
        "blum_return": average_present(return_values),
        "return": average_present(return_values),
        "benchmark_return": average_present(benchmark_returns),
        "alpha": alpha,
        "benchmark_excess": alpha,
        "average_excess_return": alpha,
        "expectancy": average_present(r_values),
        "average_r": average_present(r_values),
        "win_rate": round(wins / len(rows), 4) if rows else None,
        "profit_factor": profit_factor,
        "max_drawdown": average_present(drawdown_values),
        "evidence_grade": grade if grade in {"NO_DATA", "WEAK"} else "INSUFFICIENT_EVIDENCE",
        "evidence_reason": "Legacy historical results lack independently verified input and evaluation provenance; descriptive returns are not a validated alpha claim.",
        "provenance_status": "UNVERIFIED_LEGACY",
        "data_source": data_source,
        "last_updated_at": latest_iso([row.created_at for row in rows if row.created_at]),
        "results": [historical_trade_result(row) for row in rows[:6]],
    }


def historical_trade_return(row: TradingGameTrade) -> float | None:
    payload = row.payload if isinstance(row.payload, dict) else {}
    stored_asset_return = safe_float(payload.get("asset_return_percent"), None)
    if stored_asset_return is not None:
        return stored_asset_return
    outcome = str(row.outcome_label or "").lower()
    if row.missed_entry or outcome in {"missed_entry", "no_trade_correct", "no_trade_missed_opportunity"}:
        return 0.0
    if row.entry_price not in (None, 0) and row.exit_price is not None:
        side = str(payload.get("side") or "").lower()
        direction = -1.0 if side in {"sell", "short", "paper_sell"} else 1.0
        return round(((float(row.exit_price) / float(row.entry_price)) - 1.0) * 100.0 * direction, 4)
    if row.pnl_percent is not None:
        return safe_float(row.pnl_percent, None)
    if row.capital_before not in (None, 0) and row.net_pnl_eur is not None:
        return round((float(row.net_pnl_eur) / float(row.capital_before)) * 100.0, 4)
    return None


def historical_trade_excess(row: TradingGameTrade) -> float | None:
    strategy_return = historical_trade_return(row)
    benchmark_return = safe_float(first_not_none(row.benchmark_return_same_period, row.benchmark_return), None)
    if strategy_return is not None and benchmark_return is not None:
        return round(strategy_return - benchmark_return, 4)
    return safe_float(row.excess_return_vs_benchmark, None)


def trading_game_trade_won(row: TradingGameTrade) -> bool:
    outcome = str(row.outcome_label or "").lower()
    if outcome in {"win", "target_hit", "partial_profit", "trailing_exit"}:
        return True
    return (safe_float(row.realized_r_multiple, 0.0) or 0.0) > 0 or (safe_float(row.net_pnl_eur, 0.0) or 0.0) > 0


def historical_trade_result(row: TradingGameTrade) -> dict:
    return {
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "outcome": row.outcome_label,
        "return": historical_trade_return(row),
        "capital_return": row.pnl_percent,
        "benchmark_return": first_not_none(row.benchmark_return_same_period, row.benchmark_return),
        "excess_return": historical_trade_excess(row),
        "r_multiple": row.realized_r_multiple,
    }


def execution_simulation_evidence_split(rows: list[ExecutionSimulation]) -> dict:
    r_values = [safe_float(row.realized_r_multiple, None) for row in rows if row.realized_r_multiple is not None]
    drawdown_values = [safe_float(row.max_adverse_excursion, None) for row in rows if row.max_adverse_excursion is not None]
    wins = sum(1 for row in rows if row.target_hit or (safe_float(row.realized_r_multiple, 0.0) or 0.0) > 0)
    profit_factor = profit_factor_from_values(r_values)
    grade, reason = split_evidence_grade(
        label="Historical Replay",
        sample_size=len(rows),
        has_benchmark=False,
        alpha=None,
        expectancy=average_present(r_values),
        max_drawdown=average_present(drawdown_values),
        profit_factor=profit_factor,
    )
    return {
        "label": "Historical Replay",
        "status": "ready",
        "sample_size": len(rows),
        "closed_trade_count": len(rows),
        "blum_return": None,
        "return": None,
        "benchmark_return": None,
        "alpha": None,
        "benchmark_excess": None,
        "average_excess_return": None,
        "expectancy": average_present(r_values),
        "average_r": average_present(r_values),
        "win_rate": round(wins / len(rows), 4) if rows else None,
        "profit_factor": profit_factor,
        "max_drawdown": average_present(drawdown_values),
        "evidence_grade": grade,
        "evidence_reason": reason,
        "data_source": "execution_simulations",
        "last_updated_at": latest_iso([row.created_at for row in rows if row.created_at]),
        "results": [
            {
                "ticker": row.ticker,
                "setup_type": row.setup_type,
                "r_multiple": row.realized_r_multiple,
                "target_hit": row.target_hit,
                "stop_hit": row.stop_hit,
            }
            for row in rows[:6]
        ],
    }


def walk_forward_evidence_split(db: Session, benchmarks: list[LearningBenchmarkComparison]) -> dict:
    benchmark_split = benchmark_evidence_split(
        benchmarks,
        modes={"walk_forward_validation", "walk_forward"},
        label="Walk-Forward Validation",
        data_source="learning_benchmark_comparisons",
        no_data_reason="No walk-forward validation outcomes found.",
    )
    records = db.execute(
        select(PredictionOutcome, HistoricalPrediction, LearningRun)
        .join(HistoricalPrediction, PredictionOutcome.prediction_id == HistoricalPrediction.id)
        .outerjoin(LearningRun, HistoricalPrediction.learning_run_id == LearningRun.id)
        .order_by(desc(PredictionOutcome.created_at))
        .limit(500)
    ).all()
    outcomes = [(outcome, prediction, run) for outcome, prediction, run in records if prediction_is_walk_forward(prediction, run)]
    if not outcomes:
        audits = walk_forward_audit_rows(db)
        if audits:
            return audit_evidence_split(audits, benchmark_split)
        return benchmark_split

    realized_returns = [safe_float(outcome.realized_return, None) for outcome, _, _ in outcomes if outcome.realized_return is not None]
    drawdown_values = [safe_float(first_not_none(outcome.drawdown, outcome.max_adverse_excursion), None) for outcome, _, _ in outcomes]
    direction_values = [outcome.direction_correct for outcome, _, _ in outcomes if outcome.direction_correct is not None]
    benchmark_excess = benchmark_split.get("benchmark_excess")
    benchmark_return = benchmark_split.get("benchmark_return")
    blum_return = benchmark_split.get("blum_return") if benchmark_split.get("blum_return") is not None else average_present(realized_returns)
    profit_factor = profit_factor_from_values(realized_returns)
    grade, reason = split_evidence_grade(
        label="Walk-Forward Validation",
        sample_size=len(outcomes),
        has_benchmark=benchmark_excess is not None or benchmark_return is not None,
        alpha=benchmark_excess,
        expectancy=average_present(realized_returns),
        max_drawdown=average_present(drawdown_values),
        profit_factor=profit_factor,
    )
    if benchmark_split.get("status") != "NO_DATA" and benchmark_split.get("evidence_grade") not in {"NO_DATA", None}:
        grade = stronger_evidence_grade(grade, benchmark_split["evidence_grade"], sample_size=len(outcomes))
        reason = f"{reason} Benchmark rows are also available."
    return {
        "label": "Walk-Forward Validation",
        "status": "ready",
        "sample_size": len(outcomes),
        "closed_trade_count": len(outcomes),
        "blum_return": blum_return,
        "return": blum_return,
        "benchmark_return": benchmark_return,
        "alpha": benchmark_excess,
        "benchmark_excess": benchmark_excess,
        "average_excess_return": benchmark_excess,
        "expectancy": average_present(realized_returns),
        "average_r": None,
        "win_rate": round(sum(1 for value in direction_values if value) / len(direction_values), 4) if direction_values else benchmark_split.get("win_rate"),
        "profit_factor": profit_factor,
        "max_drawdown": average_present(drawdown_values),
        "evidence_grade": grade,
        "evidence_reason": reason,
        "data_source": "prediction_outcomes+learning_benchmark_comparisons",
        "last_updated_at": latest_iso([outcome.created_at for outcome, _, _ in outcomes if outcome.created_at]),
        "results": [
            {
                "ticker": prediction.ticker,
                "timeframe": outcome.timeframe,
                "realized_return": outcome.realized_return,
                "direction_correct": outcome.direction_correct,
                "outcome_label": outcome.outcome_label,
            }
            for outcome, prediction, _ in outcomes[:6]
        ],
    }


def prediction_is_walk_forward(prediction: HistoricalPrediction, run: LearningRun | None) -> bool:
    mode_payloads = [
        prediction.prediction_payload or {},
        prediction.point_in_time_context or {},
        prediction.learning_memory_used or {},
        prediction.strategy_memory_used or {},
        prediction.research_priority_used or {},
    ]
    for payload in mode_payloads:
        if metadata_mode_flag(payload, "training_replay"):
            return False
        if metadata_mode_flag(payload, "walk_forward_validation") or string_mode(payload) in {"walk_forward", "walk_forward_validation"}:
            return True
    if run and str(run.evaluation_mode or "") in {"walk_forward", "walk_forward_validation"}:
        return True
    return False


def metadata_mode_flag(payload: dict, key: str) -> bool:
    metadata = payload.get("learning_mode_metadata") if isinstance(payload, dict) else None
    if isinstance(metadata, dict) and metadata.get(key) is True:
        return True
    return payload.get(key) is True if isinstance(payload, dict) else False


def string_mode(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    metadata = payload.get("learning_mode_metadata")
    if isinstance(metadata, dict):
        return str(metadata.get("mode") or "")
    return str(payload.get("mode") or "")


def walk_forward_audit_rows(db: Session) -> list[FeedbackLoopAudit]:
    rows = db.scalars(select(FeedbackLoopAudit).order_by(desc(FeedbackLoopAudit.created_at)).limit(200)).all()
    return [row for row in rows if audit_is_walk_forward(row)]


def audit_is_walk_forward(row: FeedbackLoopAudit) -> bool:
    payloads = [row.learned_knowledge_json or {}, row.changes_applied_json or {}, row.future_decision_json or {}, row.outcome_json or {}]
    return any(metadata_mode_flag(payload, "walk_forward_validation") or string_mode(payload) in {"walk_forward", "walk_forward_validation"} for payload in payloads)


def audit_evidence_split(rows: list[FeedbackLoopAudit], benchmark_split: dict) -> dict:
    improvements = [row.improvement_detected for row in rows]
    grade, reason = split_evidence_grade(
        label="Walk-Forward Validation",
        sample_size=len(rows),
        has_benchmark=benchmark_split.get("benchmark_excess") is not None,
        alpha=benchmark_split.get("benchmark_excess"),
        expectancy=None,
        max_drawdown=None,
        profit_factor=None,
    )
    return {
        "label": "Walk-Forward Validation",
        "status": "ready",
        "sample_size": len(rows),
        "closed_trade_count": len(rows),
        "blum_return": benchmark_split.get("blum_return"),
        "return": benchmark_split.get("blum_return"),
        "benchmark_return": benchmark_split.get("benchmark_return"),
        "alpha": benchmark_split.get("benchmark_excess"),
        "benchmark_excess": benchmark_split.get("benchmark_excess"),
        "average_excess_return": benchmark_split.get("benchmark_excess"),
        "expectancy": None,
        "average_r": None,
        "win_rate": round(sum(1 for value in improvements if value) / len(improvements), 4) if improvements else None,
        "profit_factor": None,
        "max_drawdown": benchmark_split.get("max_drawdown"),
        "evidence_grade": grade,
        "evidence_reason": reason,
        "data_source": "feedback_loop_audits+learning_benchmark_comparisons",
        "last_updated_at": latest_iso([row.created_at for row in rows if row.created_at]),
        "results": [
            {
                "ticker": row.ticker,
                "improvement_detected": row.improvement_detected,
                "evidence_grade": row.evidence_grade,
                "summary": row.summary,
            }
            for row in rows[:6]
        ],
    }


def profit_factor_from_values(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    gains = [value for value in present if value > 0]
    losses = [abs(value) for value in present if value < 0]
    if not losses:
        return 999.0 if gains else None
    return round(sum(gains) / sum(losses), 4)


def split_evidence_grade(
    *,
    label: str,
    sample_size: int,
    has_benchmark: bool,
    alpha: float | None,
    expectancy: float | None,
    max_drawdown: float | None,
    profit_factor: float | None,
) -> tuple[str, str]:
    if sample_size <= 0:
        return "NO_DATA", f"No stored {label.lower()} outcomes found."
    if not has_benchmark:
        return "INSUFFICIENT_EVIDENCE", f"{label} outcomes exist, but benchmark comparison is unavailable."
    if sample_size < 30:
        return "INSUFFICIENT_EVIDENCE", f"{label} has only {sample_size} evaluated samples; minimum required sample is 30."
    if (alpha is not None and alpha < 0) or (expectancy is not None and expectancy < 0) or (profit_factor is not None and profit_factor < 1):
        return "WEAK", f"{label} is weak versus stored benchmark or expectancy evidence."
    if max_drawdown is not None and abs(max_drawdown) > 20:
        return "WEAK", f"{label} drawdown is too high for the current evidence level."
    if sample_size < 100:
        return "PROMISING" if positive_alpha_expectancy(alpha, expectancy) else "MIXED", f"{label} evidence exists but is not yet large enough for a strong claim."
    if positive_alpha_expectancy(alpha, expectancy):
        return "STRONG", f"{label} has positive benchmark-relative and expectancy evidence with sufficient sample size."
    return "MIXED", f"{label} has stored evidence, but alpha and expectancy are not both clearly positive."


def stronger_evidence_grade(current: str, benchmark: str, *, sample_size: int) -> str:
    if sample_size < 30:
        return "INSUFFICIENT_EVIDENCE"
    order = {"NO_DATA": 0, "INSUFFICIENT_EVIDENCE": 1, "WEAK": 2, "MIXED": 3, "PROMISING": 4, "STRONG": 5}
    if order.get(benchmark, 0) > order.get(current, 0):
        return benchmark
    return current


def latest_iso(values: list[Any]) -> str | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    latest = max(present)
    return latest.isoformat() if hasattr(latest, "isoformat") else str(latest)


def paper_forward_trade_is_closed(row: LiveForwardPaperTrade) -> bool:
    if str(row.status or "").upper() in {"SKIPPED", "REJECTED", "DATA_BLOCKED"}:
        return False
    if str(row.outcome_label or row.close_reason or "").upper() in {"ORDER_NOT_FILLED", "SIGNAL_DECAY_BEFORE_ENTRY"}:
        return False
    if str(row.status or "").upper() in {"EXPIRED", "INVALIDATED"}:
        return bool(row.opened_at and row.closed_at and row.exit_price is not None and (row.position_size or 0) > 0)
    return bool(
        row.closed_at
        or row.exit_price is not None
        or row.close_reason
        or str(row.status or "").upper() in {"CLOSED", "EXITED"}
    )


def paper_forward_trade_is_open(row: LiveForwardPaperTrade) -> bool:
    status = str(row.status or "").upper()
    return bool(status == "OPEN" or (row.opened_at and not paper_forward_trade_is_closed(row)))


def paper_forward_alpha_summary(rows: list[LiveForwardPaperTrade], game: LiveForwardPaperGame | None) -> dict:
    rows = [row for row in rows if paper_trade_evidence_is_eligible(row)]
    closed = [row for row in rows if paper_forward_trade_is_closed(row)]
    open_rows = [row for row in rows if paper_forward_trade_is_open(row)]
    pnl_values = [safe_float(row.net_pnl_eur, None) for row in closed if row.net_pnl_eur is not None]
    r_values = [safe_float(row.r_multiple, None) for row in closed if row.r_multiple is not None]
    positive_pnl = [value for value in pnl_values if value is not None and value > 0]
    negative_pnl = [abs(value) for value in pnl_values if value is not None and value < 0]
    benchmark_returns = [safe_float(row.benchmark_return_same_period, None) for row in closed if row.benchmark_return_same_period is not None]
    excess_values = [safe_float(row.excess_return_vs_benchmark, None) for row in closed if row.excess_return_vs_benchmark is not None]
    drawdown_candidates = [safe_float(row.max_adverse_excursion, None) for row in closed if row.max_adverse_excursion is not None]
    realized_pnl = round(sum(value for value in pnl_values if value is not None), 4)
    unrealized_pnl = round(sum(safe_float(row.unrealized_pnl, 0.0) or 0.0 for row in open_rows), 4)
    start_capital = safe_float(getattr(game, "starting_capital", None), None)
    if start_capital:
        blum_return = round(((realized_pnl + unrealized_pnl) / start_capital) * 100.0, 4)
    else:
        blum_return = average_present([row.pnl_percent for row in closed if row.pnl_percent is not None])
    wins = sum(1 for row in closed if paper_forward_trade_won(row))
    best_trade = max(closed, key=lambda row: safe_float(row.r_multiple, safe_float(row.net_pnl_eur, 0.0)) or 0.0, default=None)
    worst_trade = min(closed, key=lambda row: safe_float(row.r_multiple, safe_float(row.net_pnl_eur, 0.0)) or 0.0, default=None)
    return {
        "closed_count": len(closed),
        "open_count": len(open_rows),
        "blum_return": blum_return,
        "benchmark_return": average_present(benchmark_returns),
        "alpha": average_present(excess_values),
        "benchmark_excess": average_present(excess_values),
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "expectancy": average_present(r_values),
        "average_r": average_present(r_values),
        "median_r": round(median(r_values), 4) if r_values else None,
        "win_rate": round(wins / len(closed), 4) if closed else None,
        "profit_factor": round(sum(positive_pnl) / sum(negative_pnl), 4) if negative_pnl else (None if not positive_pnl else 999.0),
        "max_drawdown": average_present(drawdown_candidates),
        "average_loss": round(-mean(negative_pnl), 4) if negative_pnl else None,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "sharpe": None,
        "sortino": None,
        "dominant_trade_share": dominant_trade_share(pnl_values),
    }


def paper_forward_trade_won(row: LiveForwardPaperTrade) -> bool:
    outcome = str(row.outcome_label or row.close_reason or "").lower()
    if outcome in {"win", "target_hit", "target_1_hit", "target_2_hit"}:
        return True
    return (safe_float(row.r_multiple, 0.0) or 0.0) > 0 or (safe_float(row.net_pnl_eur, 0.0) or 0.0) > 0


def dominant_trade_share(values: list[float | None]) -> float | None:
    positives = [abs(value) for value in values if value is not None and value > 0]
    total = sum(positives)
    if total <= 0:
        return None
    return round(max(positives) / total, 4)


def alpha_evidence_grade(
    *,
    closed_count: int,
    has_benchmark: bool,
    alpha: float | None,
    expectancy: float | None,
    max_drawdown: float | None,
    profit_factor: float | None,
    setup_count: int,
    regime_count: int,
) -> tuple[str, str]:
    if closed_count == 0:
        return "NO_DATA", "No closed paper-forward trades exist yet."
    if not has_benchmark:
        return "NO_DATA", "Benchmark comparison is unavailable for closed paper-forward trades."
    if closed_count < 30:
        return "INSUFFICIENT_EVIDENCE", f"Only {closed_count} closed paper-forward trades exist; minimum required sample is 30."
    if (alpha is not None and alpha < 0) or (expectancy is not None and expectancy < 0) or (profit_factor is not None and profit_factor < 1):
        return "WEAK", "Alpha, expectancy or profit factor is negative/weak versus the benchmark evidence."
    if max_drawdown is not None and abs(max_drawdown) > 20:
        return "WEAK", "Drawdown is too high for the current evidence level."
    if closed_count < 100:
        return "PROMISING" if positive_alpha_expectancy(alpha, expectancy) else "MIXED", "Paper-forward evidence is directionally useful but not yet large enough for a strong claim."
    if positive_alpha_expectancy(alpha, expectancy) and setup_count > 1 and regime_count > 1:
        return "STRONG", "Positive alpha and expectancy are present with sufficient sample depth and more than one setup/regime."
    return "MIXED", "Some metrics are positive, but evidence is not robust across enough setups or regimes."


def positive_alpha_expectancy(alpha: float | None, expectancy: float | None) -> bool:
    return (alpha is not None and alpha > 0) and (expectancy is not None and expectancy > 0)


def alpha_verdict(grade: str, summary: dict, blockers: list[dict]) -> str:
    if grade == "NO_DATA":
        return "No alpha evidence yet."
    if grade == "INSUFFICIENT_EVIDENCE":
        return f"Evidence insufficient: only {summary.get('closed_count', 0)} closed paper-forward trades."
    if grade == "WEAK":
        return "BLUM is not showing reliable alpha evidence versus benchmark."
    if grade == "MIXED":
        return "BLUM shows mixed alpha evidence; do not trust it yet."
    if grade == "PROMISING":
        return "BLUM shows promising alpha, but evidence is not strong enough yet."
    if grade == "STRONG":
        return "BLUM shows strong paper-forward alpha evidence."
    return blockers[0]["title"] if blockers else "Alpha evidence is inconclusive."


def alpha_grade_from_splits(evidence_split: dict) -> tuple[str, str]:
    paper = evidence_split.get("paper_forward") or {}
    intraday = evidence_split.get("intraday_paper_forward") or {}
    forex = evidence_split.get("forex_paper_forward") or {}
    live = evidence_split.get("live_forward") or {}
    walk = evidence_split.get("walk_forward_validation") or {}
    historical = evidence_split.get("historical_replay") or {}
    paper_grade = str(paper.get("evidence_grade") or "NO_DATA")
    if paper_grade != "NO_DATA":
        return paper_grade, str(paper.get("evidence_reason") or "Paper-forward evidence is available.")
    if split_has_data(intraday):
        return str(intraday.get("evidence_grade") or "INSUFFICIENT_EVIDENCE"), str(intraday.get("evidence_reason") or "Intraday paper-forward evidence is available separately.")
    if split_has_data(forex):
        return str(forex.get("evidence_grade") or "INSUFFICIENT_EVIDENCE"), str(forex.get("evidence_reason") or "Forex paper-forward evidence is available separately.")
    if split_has_data(live):
        live_grade = cap_non_forward_grade(str(live.get("evidence_grade") or "INSUFFICIENT_EVIDENCE"))
        return live_grade, str(live.get("evidence_reason") or "Live-forward evidence exists, but paper-forward evidence remains limited.")
    if split_has_data(walk):
        return "INSUFFICIENT_EVIDENCE", "Walk-forward evidence exists, paper-forward still insufficient."
    if split_has_data(historical):
        return "INSUFFICIENT_EVIDENCE", "No paper-forward evidence yet. Historical evidence is available separately."
    return "NO_DATA", "No stored alpha evidence found across historical replay, walk-forward, paper-forward or live-forward sources."


def alpha_verdict_from_splits(evidence_split: dict, grade: str) -> str:
    paper = evidence_split.get("paper_forward") or {}
    intraday = evidence_split.get("intraday_paper_forward") or {}
    forex = evidence_split.get("forex_paper_forward") or {}
    walk = evidence_split.get("walk_forward_validation") or {}
    historical = evidence_split.get("historical_replay") or {}
    if not split_has_data(paper):
        if split_has_data(intraday):
            return "Intraday paper-forward evidence exists; sample strength is reported separately."
        if split_has_data(forex):
            return "Forex paper-forward evidence exists; sample strength is reported separately."
        if split_has_data(walk):
            return "Walk-forward evidence exists, paper-forward still insufficient."
        if split_has_data(historical):
            return "No paper-forward evidence yet. Historical evidence is available separately."
        return "No paper-forward evidence yet."
    if grade == "INSUFFICIENT_EVIDENCE":
        return "Paper-forward evidence insufficient."
    if grade == "WEAK":
        return "Paper-forward alpha weak."
    if grade in {"PROMISING", "STRONG"}:
        return "Paper-forward alpha promising."
    if grade == "MIXED":
        return "Paper-forward evidence is mixed."
    return "Paper-forward evidence is inconclusive."


def primary_alpha_evidence(evidence_split: dict) -> dict:
    for key in ("paper_forward", "intraday_paper_forward", "forex_paper_forward", "live_forward", "walk_forward_validation", "historical_replay"):
        split = evidence_split.get(key) or {}
        if split_has_data(split):
            return {
                "source": key,
                "label": split.get("label"),
                "sample_size": split.get("sample_size"),
                "evidence_grade": split.get("evidence_grade"),
                "blum_return": split.get("blum_return"),
                "benchmark_return": split.get("benchmark_return"),
                "alpha": split.get("alpha") if split.get("alpha") is not None else split.get("benchmark_excess"),
                "benchmark_excess": split.get("benchmark_excess"),
                "evidence_reason": split.get("evidence_reason"),
                "data_source": split.get("data_source"),
                "last_updated_at": split.get("last_updated_at"),
            }
    return {
        "source": "none",
        "label": "No stored evidence",
        "sample_size": 0,
        "evidence_grade": "NO_DATA",
        "evidence_reason": "No stored alpha evidence found across evidence streams.",
    }


def paper_forward_lifecycle_mode(actionability_summary: dict | None = None) -> str:
    if not settings.paper_forward_lifecycle_enabled:
        return "CANDIDATE_FREEZE_ONLY"
    summary = actionability_summary or {}
    if int(summary.get("actionable_count") or 0) <= 0 and int(summary.get("waiting_for_trigger_count") or 0) <= 0:
        return "LIFECYCLE_BLOCKED_BY_NO_ACTIONABLE_CANDIDATES"
    return "LIFECYCLE_ENABLED"


def paper_forward_no_closed_reason(rows: list[LiveForwardPaperTrade], actionability_summary: dict | None, lifecycle_mode: str | None) -> str:
    summary = actionability_summary or {}
    total = int(summary.get("total_candidates") or len(rows))
    actionable = int(summary.get("actionable_count") or 0)
    waiting = int(summary.get("waiting_for_trigger_count") or 0)
    skipped = int(summary.get("skipped_count") or 0)
    blocked = int(summary.get("data_blocked_count") or 0)
    if lifecycle_mode == "CANDIDATE_FREEZE_ONLY":
        return "Paper-forward lifecycle is currently disabled. BLUM is freezing decisions but not opening or closing trades."
    if total <= 0:
        return "No paper-forward candidates have been stored yet."
    if actionable <= 0 and waiting <= 0 and skipped > 0:
        top = summary.get("top_rejection_reasons") or []
        reason = top[0].get("reason") if top and isinstance(top[0], dict) else "actionability policy"
        return f"Paper-forward candidates exist, but none are actionable. Main rejection reason: {reason}."
    if waiting > 0 and actionable <= 0:
        return "Paper-forward has candidates waiting for entry trigger; no trigger has fired yet."
    if actionable > 0:
        return "Actionable paper-forward candidates exist, but no trade has closed yet."
    if blocked > 0:
        return "Paper-forward candidates are blocked by missing or weak data."
    return "No closed paper-forward trades exist yet."


def split_has_data(split: dict) -> bool:
    return str(split.get("status") or "") != "NO_DATA" and (safe_float(split.get("sample_size"), 0.0) or 0.0) > 0


def cap_non_forward_grade(grade: str) -> str:
    if grade == "STRONG":
        return "PROMISING"
    if grade == "NO_DATA":
        return "INSUFFICIENT_EVIDENCE"
    return grade


def latest_alpha_update_from_splits(evidence_split: dict) -> str | None:
    dates = [split.get("last_updated_at") for split in evidence_split.values() if isinstance(split, dict) and split.get("last_updated_at")]
    return max(dates) if dates else None


def alpha_blockers(
    rows: list[LiveForwardPaperTrade],
    closed_rows: list[LiveForwardPaperTrade],
    benchmarks: list[LearningBenchmarkComparison],
    summary: dict,
    actionability_summary: dict | None = None,
    lifecycle_mode: str | None = None,
) -> list[dict]:
    blockers: list[dict] = []
    actionability_summary = actionability_summary or paper_forward_actionability_summary(rows)
    lifecycle_mode = lifecycle_mode or paper_forward_lifecycle_mode(actionability_summary)
    if not rows:
        blockers.append(blocker("no_paper_forward_candidates", "No paper-forward candidates have been stored yet.", "Let the backend paper-forward worker collect candidate evidence."))
    if not closed_rows:
        blockers.append(blocker("no_closed_paper_forward_trades", paper_forward_no_closed_reason(rows, actionability_summary, lifecycle_mode), "Alpha cannot be evaluated until paper-forward trades complete."))
    if lifecycle_mode == "CANDIDATE_FREEZE_ONLY":
        blockers.append(blocker("paper_forward_lifecycle_disabled", "Paper-forward lifecycle is currently disabled. BLUM is freezing decisions but not opening or closing trades.", "Enable lifecycle explicitly only after actionability gates are certified."))
    if int(actionability_summary.get("total_candidates") or 0) > 0:
        actionable = int(actionability_summary.get("actionable_count") or 0)
        waiting = int(actionability_summary.get("waiting_for_trigger_count") or 0)
        skipped = int(actionability_summary.get("skipped_count") or 0)
        blocked = int(actionability_summary.get("data_blocked_count") or 0)
        if actionable == 0 and waiting == 0 and skipped > 0:
            blockers.append(blocker("no_actionable_paper_forward_candidates", "Paper-forward candidates exist, but all recent candidates were rejected by actionability policy.", "Review top rejection reasons before changing thresholds."))
        if waiting > 0 and actionable == 0:
            blockers.append(blocker("entry_trigger_not_reached", "Paper-forward has candidates waiting for trigger; no entry condition has fired yet.", "Keep observing without forcing trades."))
        if blocked > 0:
            blockers.append(blocker("paper_forward_data_blocked", f"{blocked} paper-forward candidates are blocked by missing or weak data.", "Repair data before evaluating alpha."))
    if len(closed_rows) < 30:
        blockers.append(blocker("insufficient_sample_size", f"Closed sample is {len(closed_rows)}; minimum is 30.", "Keep collecting closed paper-forward outcomes."))
    if not any(row.excess_return_vs_benchmark is not None for row in closed_rows) and not benchmarks:
        blockers.append(blocker("missing_benchmark_data", "Benchmark comparison unavailable.", "Compare closed paper-forward trades against SPY/QQQ or stored benchmark rows."))
    if summary.get("alpha") is not None and summary["alpha"] < 0:
        blockers.append(blocker("alpha_negative", "Paper-forward alpha is negative.", "Diagnose missed entries, exits, sizing and benchmark underperformance before trusting signals."))
    if summary.get("expectancy") is not None and summary["expectancy"] < 0:
        blockers.append(blocker("expectancy_negative", "Expectancy is negative.", "Prioritize setups with positive R-multiple evidence."))
    if summary.get("profit_factor") is not None and summary["profit_factor"] < 1:
        blockers.append(blocker("profit_factor_weak", "Profit factor is below 1.", "Losses are larger than winners in current evidence."))
    if summary.get("dominant_trade_share") is not None and summary["dominant_trade_share"] > 0.55:
        blockers.append(blocker("one_trade_concentration", "Alpha is concentrated in one trade.", "Require broader repeatability before increasing confidence."))
    if summary.get("max_drawdown") is not None and abs(summary["max_drawdown"]) > 20:
        blockers.append(blocker("drawdown_too_high", "Drawdown is too high for the current evidence level.", "Reduce confidence until risk control improves."))
    data_invalid = sum(1 for row in rows if str(row.status or "").upper() in {"ERROR", "DATA_BLOCKED", "SKIPPED"})
    if data_invalid:
        blockers.append(blocker("data_invalid_cases", f"{data_invalid} paper-forward rows are skipped, blocked or errored.", "Inspect blockers before treating candidate quality as alpha evidence."))
    return blockers[:8]


def blocker(code: str, title: str, remedy: str) -> dict:
    return {"code": code, "title": title, "remedy": remedy}


def confidence_in_alpha_evidence(grade: str, sample_size: int, has_benchmark: bool) -> float:
    base = {
        "NO_DATA": 0.0,
        "INSUFFICIENT_EVIDENCE": 18.0,
        "WEAK": 35.0,
        "MIXED": 48.0,
        "PROMISING": 62.0,
        "STRONG": 82.0,
    }.get(grade, 20.0)
    sample_boost = min(12.0, sample_size / 10.0)
    benchmark_boost = 6.0 if has_benchmark else -10.0
    return round(max(0.0, min(100.0, base + sample_boost + benchmark_boost)), 2)


def latest_paper_forward_update(rows: list[LiveForwardPaperTrade], benchmarks: list[LearningBenchmarkComparison]) -> str | None:
    dates = [row.updated_at or row.created_at for row in rows if row.updated_at or row.created_at]
    dates += [row.calculated_at for row in benchmarks if row.calculated_at]
    latest = max(dates, default=None)
    return latest.isoformat() if latest else None


def alpha_trade_summary(row: LiveForwardPaperTrade | None) -> dict | None:
    if row is None:
        return None
    return {
        "trade_id": row.id,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "status": row.status,
        "outcome": row.outcome_label or row.close_reason,
        "pnl": row.net_pnl_eur,
        "pnl_percent": row.pnl_percent,
        "r_multiple": row.r_multiple,
        "benchmark_excess": row.excess_return_vs_benchmark,
        "lesson": row.lesson_learned,
        "model_version_used": row.model_version_used,
    }


def paper_forward_evidence_split(
    rows: list[LiveForwardPaperTrade],
    game: LiveForwardPaperGame | None,
    *,
    label: str,
    actionability_summary: dict | None = None,
    lifecycle_mode: str | None = None,
) -> dict:
    closed = [row for row in rows if paper_forward_trade_is_closed(row)]
    if not closed:
        split = empty_alpha_evidence_split(label, "live_forward_paper_trades", paper_forward_no_closed_reason(rows, actionability_summary, lifecycle_mode))
        split["actionability_summary"] = actionability_summary or paper_forward_actionability_summary(rows)
        split["paper_forward_lifecycle_mode"] = lifecycle_mode or paper_forward_lifecycle_mode(split["actionability_summary"])
        return split
    summary = paper_forward_alpha_summary(rows, game)
    has_benchmark = any(row.excess_return_vs_benchmark is not None or row.benchmark_return_same_period is not None for row in closed)
    grade, reason = alpha_evidence_grade(
        closed_count=len(closed),
        has_benchmark=has_benchmark,
        alpha=summary["alpha"],
        expectancy=summary["expectancy"],
        max_drawdown=summary["max_drawdown"],
        profit_factor=summary["profit_factor"],
        setup_count=len({row.setup_type for row in closed if row.setup_type}),
        regime_count=len({(row.frozen_decision_payload or {}).get("market_regime") or "unknown" for row in closed}),
    )
    return {
        "label": label,
        "status": "ready",
        "sample_size": len(closed),
        "closed_trade_count": len(closed),
        "total_decisions": len(rows),
        "blum_return": summary["blum_return"],
        "return": summary["blum_return"],
        "benchmark_return": summary["benchmark_return"],
        "alpha": summary["benchmark_excess"],
        "benchmark_excess": summary["benchmark_excess"],
        "average_excess_return": summary["benchmark_excess"],
        "expectancy": summary["expectancy"],
        "average_r": summary["average_r"],
        "win_rate": summary["win_rate"],
        "profit_factor": summary["profit_factor"],
        "max_drawdown": summary["max_drawdown"],
        "evidence_grade": grade,
        "evidence_reason": reason,
        "data_source": "live_forward_paper_trades",
        "last_updated_at": latest_iso([row.updated_at or row.created_at for row in rows if row.updated_at or row.created_at]),
        "actionability_summary": actionability_summary or paper_forward_actionability_summary(rows),
        "paper_forward_lifecycle_mode": lifecycle_mode or paper_forward_lifecycle_mode(actionability_summary),
    }


def live_forward_evidence_split(rows: list[LiveForwardPaperTrade], game: LiveForwardPaperGame | None, actionability_summary: dict | None = None, lifecycle_mode: str | None = None) -> dict:
    closed = [row for row in rows if paper_forward_trade_is_closed(row)]
    if not closed:
        split = empty_alpha_evidence_split("Live-Forward Evidence", "live_forward_paper_trades", paper_forward_no_closed_reason(rows, actionability_summary, lifecycle_mode))
        split["actionability_summary"] = actionability_summary or paper_forward_actionability_summary(rows)
        split["paper_forward_lifecycle_mode"] = lifecycle_mode or paper_forward_lifecycle_mode(split["actionability_summary"])
        return split
    split = paper_forward_evidence_split(rows, game, label="Live-Forward Evidence", actionability_summary=actionability_summary, lifecycle_mode=lifecycle_mode)
    split["data_source"] = "live_forward_paper_trades"
    return split


def intraday_paper_evidence_split(rows: list[LiveForwardPaperTrade], game: LiveForwardPaperGame | None) -> dict:
    closed = [row for row in rows if paper_forward_trade_is_closed(row)]
    if not closed:
        split = empty_alpha_evidence_split(
            "Intraday Paper-Forward Evidence",
            "live_forward_paper_trades:PAPER_FORWARD_INTRADAY",
            "No closed intraday paper-forward trades exist yet.",
        )
        split.update({"evidence_type": "PAPER_FORWARD_INTRADAY", "average_holding_minutes": None, "costs_paid": None})
        return split
    split = paper_forward_evidence_split(
        rows,
        game,
        label="Intraday Paper-Forward Evidence",
        actionability_summary=paper_forward_actionability_summary(rows),
        lifecycle_mode="INTRADAY_LIFECYCLE_ENABLED",
    )
    split.update(
        {
            "data_source": "live_forward_paper_trades:PAPER_FORWARD_INTRADAY",
            "evidence_type": "PAPER_FORWARD_INTRADAY",
            "average_holding_minutes": average_present([row.holding_minutes for row in closed]),
            "costs_paid": round(sum(float(row.costs_paid or 0.0) for row in closed), 4),
        }
    )
    return split


def forex_paper_evidence_split(snapshot: dict) -> dict:
    payload = snapshot.get("payload") or {}
    counts = ((payload.get("counts") or {}).get("by_market") or {}).get("forex") or {}
    metrics = ((payload.get("metrics") or {}).get("by_market") or {}).get("forex") or {}
    closed = int(counts.get("closed") or 0)
    if snapshot.get("status") == "missing" or closed <= 0:
        reason = (
            "No unified paper-trading snapshot exists yet."
            if snapshot.get("status") == "missing"
            else "No closed Forex paper-forward trades exist yet."
        )
        return empty_alpha_evidence_split(
            "Forex Paper-Forward Evidence",
            "dashboard_snapshots:unified_paper_trading_summary:forex",
            reason,
        )
    benchmark_excess_raw = safe_float(metrics.get("benchmark_excess"), None)
    benchmark_excess = benchmark_excess_raw * 100.0 if benchmark_excess_raw is not None else None
    expectancy = safe_float(metrics.get("expectancy_r"), None)
    grade, reason = split_evidence_grade(
        label="Forex Paper-Forward Evidence",
        sample_size=closed,
        has_benchmark=benchmark_excess is not None,
        alpha=benchmark_excess,
        expectancy=expectancy,
        max_drawdown=safe_float(metrics.get("max_drawdown"), None),
        profit_factor=safe_float(metrics.get("profit_factor"), None),
    )
    game = payload.get("game") or {}
    starting_capital = safe_float(game.get("starting_capital"), None)
    realized_pnl = safe_float(metrics.get("realized_pnl"), None)
    blum_return = (
        round((realized_pnl / starting_capital) * 100.0, 4)
        if realized_pnl is not None and starting_capital
        else None
    )
    benchmark_return = (
        round(blum_return - benchmark_excess, 4)
        if blum_return is not None and benchmark_excess is not None
        else None
    )
    return {
        "label": "Forex Paper-Forward Evidence",
        "status": "ready",
        "sample_size": closed,
        "closed_trade_count": closed,
        "blum_return": blum_return,
        "return": blum_return,
        "benchmark_return": benchmark_return,
        "alpha": benchmark_excess,
        "benchmark_excess": benchmark_excess,
        "average_excess_return": benchmark_excess,
        "expectancy": expectancy,
        "average_r": safe_float(metrics.get("average_r"), None),
        "win_rate": safe_float(metrics.get("win_rate"), None),
        "profit_factor": safe_float(metrics.get("profit_factor"), None),
        "max_drawdown": safe_float(metrics.get("max_drawdown"), None),
        "realized_pnl": realized_pnl,
        "evidence_grade": grade,
        "evidence_reason": reason,
        "data_source": "dashboard_snapshots:unified_paper_trading_summary:forex",
        "last_updated_at": snapshot.get("created_at"),
    }


def alpha_edge_map(rows: list[LiveForwardPaperTrade]) -> dict:
    closed = [row for row in rows if paper_forward_trade_is_closed(row)]
    return {
        "status": "ready" if closed else "NO_DATA",
        "sample_size": len(closed),
        "by_setup": alpha_edge_groups(closed, lambda row: row.setup_type or "unknown"),
        "by_ticker": alpha_edge_groups(closed, lambda row: row.ticker or "unknown"),
        "by_sector": alpha_edge_groups(closed, lambda row: row.sector or "unknown"),
        "by_regime": alpha_edge_groups(closed, lambda row: str((row.frozen_decision_payload or {}).get("market_regime") or "unknown")),
        "by_model_version": alpha_edge_groups(closed, lambda row: row.model_version_used or "unknown"),
        "warnings": ["low_sample_edges"] if len(closed) < 30 else [],
    }


def alpha_edge_groups(rows: list[LiveForwardPaperTrade], key_fn) -> list[dict]:
    groups: dict[str, list[LiveForwardPaperTrade]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row) or "unknown")].append(row)
    output = []
    for entity, group in groups.items():
        r_values = [safe_float(row.r_multiple, None) for row in group if row.r_multiple is not None]
        excess_values = [safe_float(row.excess_return_vs_benchmark, None) for row in group if row.excess_return_vs_benchmark is not None]
        wins = sum(1 for row in group if paper_forward_trade_won(row))
        output.append(
            {
                "entity": entity,
                "sample_size": len(group),
                "alpha": average_present(excess_values),
                "average_r": average_present(r_values),
                "win_rate": round(wins / len(group), 4) if group else None,
                "evidence_grade": "LOW_SAMPLE" if len(group) < 10 else "MEDIUM" if len(group) < 30 else "STRONG_SAMPLE",
                "warning": "Treat as weak evidence." if len(group) < 10 else "",
            }
        )
    return sorted(output, key=lambda item: safe_float(item.get("alpha"), safe_float(item.get("average_r"), -999.0)) or -999.0, reverse=True)


def edge_summary(rows: list[LiveForwardPaperTrade], direction: str) -> dict | None:
    groups = alpha_edge_groups([row for row in rows if paper_forward_trade_is_closed(row)], lambda row: row.setup_type or row.ticker or "unknown")
    if not groups:
        return None
    return groups[0] if direction == "best" else groups[-1]


def alpha_weakness_map(
    rows: list[LiveForwardPaperTrade],
    closed_rows: list[LiveForwardPaperTrade],
    benchmarks: list[LearningBenchmarkComparison],
    summary: dict,
) -> list[dict]:
    weaknesses = alpha_blockers(rows, closed_rows, benchmarks, summary)
    stop_hits = sum(1 for row in closed_rows if row.stop_hit or str(row.close_reason or "").upper() == "STOP_HIT")
    poor_exits = sum(1 for row in closed_rows if str(row.close_reason or "").upper() in {"TIME_EXIT", "INVALIDATION_HIT"})
    negative_excess = sum(1 for row in closed_rows if (safe_float(row.excess_return_vs_benchmark, 0.0) or 0.0) < 0)
    missed_gains = sum(1 for row in rows if str(row.status or "").upper() == "SKIPPED" and (safe_float(row.expected_r_multiple, 0.0) or 0.0) > 1)
    if stop_hits:
        weaknesses.append(blocker("repeated_stop_hits", f"{stop_hits} closed trades hit stops.", "Review entry quality and volatility assumptions."))
    if poor_exits:
        weaknesses.append(blocker("poor_exit_quality", f"{poor_exits} trades exited by time/invalidation.", "Test exit timing and thesis decay rules."))
    if negative_excess:
        weaknesses.append(blocker("benchmark_underperformance", f"{negative_excess} closed trades underperformed benchmark.", "Reduce confidence in setups that do not beat passive alternatives."))
    if missed_gains:
        weaknesses.append(blocker("missed_gains", f"{missed_gains} skipped candidates had meaningful expected R.", "Review no-trade filters against later outcomes before penalizing or relaxing rules."))
    return weaknesses[:10]


def alpha_risk_warning(summary: dict, blockers: list[dict]) -> str | None:
    if any(item["code"] == "drawdown_too_high" for item in blockers):
        return "Drawdown is too high for the current evidence level."
    if any(item["code"] == "one_trade_concentration" for item in blockers):
        return "Alpha is concentrated in one trade."
    if summary.get("open_count"):
        return "Open paper-forward exposure exists; unrealized P/L can change."
    return blockers[0]["title"] if blockers else None


def latest_alpha_lesson(closed_rows: list[LiveForwardPaperTrade], lesson_rows: list[TradeLearningEvidence]) -> dict | None:
    for row in closed_rows:
        if row.lesson_learned:
            return {
                "ticker": row.ticker,
                "setup_type": row.setup_type,
                "outcome": row.outcome_label or row.close_reason,
                "alpha_impact": row.excess_return_vs_benchmark,
                "benchmark_impact": row.benchmark_return_same_period,
                "what_was_correct": "Trade followed stored paper-forward plan." if (safe_float(row.r_multiple, 0.0) or 0.0) >= 0 else "",
                "what_was_wrong": "" if (safe_float(row.r_multiple, 0.0) or 0.0) >= 0 else "Outcome was negative or benchmark-relative evidence weakened.",
                "what_should_change_next": row.lesson_learned,
                "linked_trade_id": row.id,
            }
    if lesson_rows:
        row = lesson_rows[0]
        return {
            "ticker": row.ticker,
            "setup_type": row.setup_type,
            "outcome": row.lesson_type,
            "alpha_impact": None,
            "benchmark_impact": None,
            "what_was_correct": row.observation,
            "what_was_wrong": "",
            "what_should_change_next": row.action_taken,
            "linked_trade_id": row.trade_id,
        }
    return None


def alpha_lessons(closed_rows: list[LiveForwardPaperTrade], lesson_rows: list[TradeLearningEvidence]) -> list[dict]:
    lessons = []
    for row in closed_rows:
        if not row.lesson_learned:
            continue
        lessons.append(
            {
                "ticker": row.ticker,
                "setup_type": row.setup_type,
                "outcome": row.outcome_label or row.close_reason,
                "alpha_impact": row.excess_return_vs_benchmark,
                "benchmark_impact": row.benchmark_return_same_period,
                "what_was_correct": "Target/risk plan resolved positively." if paper_forward_trade_won(row) else "",
                "what_was_wrong": "" if paper_forward_trade_won(row) else "Trade did not produce positive paper-forward evidence.",
                "what_should_change_next": row.lesson_learned,
                "linked_trade_id": row.id,
            }
        )
    for row in lesson_rows[: max(0, 6 - len(lessons))]:
        lessons.append(
            {
                "ticker": row.ticker,
                "setup_type": row.setup_type,
                "outcome": row.lesson_type,
                "alpha_impact": None,
                "benchmark_impact": None,
                "what_was_correct": row.observation,
                "what_was_wrong": "",
                "what_should_change_next": row.action_taken,
                "linked_trade_id": row.trade_id,
            }
        )
    return lessons[:6]


def alpha_truth_lines(verdict: str, blockers: list[dict], summary: dict, evidence_split: dict | None = None) -> list[str]:
    lines = [verdict]
    if summary.get("alpha") is None:
        lines.append("Benchmark-relative paper-forward alpha is not available yet.")
    elif summary["alpha"] < 0:
        lines.append(f"Paper-forward alpha is negative ({summary['alpha']:.2f}%).")
    else:
        lines.append(f"Paper-forward alpha is {summary['alpha']:.2f}%, but sample quality still matters.")
    split = evidence_split or {}
    historical = split.get("historical_replay") or {}
    walk_forward = split.get("walk_forward_validation") or {}
    if split_has_data(historical) and summary.get("alpha") is None:
        lines.append("Historical replay evidence exists and is shown separately from forward evidence.")
    if split_has_data(walk_forward) and summary.get("alpha") is None:
        lines.append("Walk-forward evidence exists and is shown separately from paper-forward evidence.")
    for item in blockers[:3]:
        lines.append(item["title"])
    return lines[:5]


def evidence_grade_from_benchmark_rows(rows: list[LearningBenchmarkComparison]) -> str:
    sample = sum(row.sample_size or 0 for row in rows)
    if sample <= 0:
        return "NO_DATA"
    if sample < 30:
        return "INSUFFICIENT_EVIDENCE"
    labels = {str(row.result_label or "").lower() for row in rows}
    if "underperforming" in labels:
        return "WEAK"
    if "outperforming" in labels and sample >= 100:
        return "STRONG"
    if "outperforming" in labels:
        return "PROMISING"
    return "MIXED"


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def average_present(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return round(mean(present), 4)


def format_pct(value: Any) -> str:
    number = safe_float(value, None)
    return "n/a" if number is None else f"{number:.2f}%"
