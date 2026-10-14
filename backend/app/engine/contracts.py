from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ENGINE_VERSION = "2.3.0"
PROJECT_FEATURE_SET = "clean-core"
BLUM_ANALYST_REPOSITORY = "Italianhype/Blum-Analyst"


EngineEventType = Literal[
    "market_updated",
    "news_processed",
    "decision_created",
    "trade_opened",
    "trade_closed",
    "paper_trade_completed",
    "benchmark_updated",
    "learning_cycle_completed",
    "knowledge_updated",
    "brain_score_updated",
    "dataset_exported",
    "alpha_improved",
    "confidence_changed",
    "portfolio_updated",
]


@dataclass(frozen=True)
class EngineModuleContract:
    name: str
    responsibility: str
    owns_truth: bool
    produces: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    event_outputs: list[EngineEventType] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EngineDecisionContract:
    """Stable decision object emitted by the Engine.

    This is a contract definition, not an execution instruction. It exists so
    Runtime, exports and future assistants all speak the same decision language.
    """

    ticker: str
    decision_type: str
    actionability: str
    thesis_id: str | None = None
    confidence: float | None = None
    decision_quality: float | None = None
    expected_alpha: float | None = None
    entry_zone: dict[str, Any] | None = None
    invalidation: dict[str, Any] | None = None
    targets: list[dict[str, Any]] = field(default_factory=list)
    bull_thesis: str | None = None
    bear_thesis: str | None = None
    risks: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EngineStatusContract:
    version: str
    feature_set: str
    source_of_truth: bool
    headless_capable: bool
    intelligence_modules: list[EngineModuleContract]
    event_contract: list[EngineEventType]
    current_brain_status: dict[str, Any]
    current_learning_status: dict[str, Any]
    current_alpha_status: dict[str, Any]
    current_paper_trading_status: dict[str, Any]
    policy: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["intelligence_modules"] = [module.to_dict() for module in self.intelligence_modules]
        return payload


def engine_module_catalog() -> list[EngineModuleContract]:
    return [
        EngineModuleContract(
            name="market_listener",
            responsibility="Normalize market, news, price, fundamental and macro evidence for downstream research.",
            owns_truth=True,
            produces=["market_evidence", "news_evidence", "fundamental_evidence"],
            consumes=[],
            event_outputs=["market_updated", "news_processed"],
        ),
        EngineModuleContract(
            name="signal_generator",
            responsibility="Convert point-in-time evidence into technical, sentiment, narrative and fundamental signal candidates.",
            owns_truth=True,
            produces=["signal_candidates", "factor_scores"],
            consumes=["market_evidence", "news_evidence", "fundamental_evidence"],
            event_outputs=["confidence_changed"],
        ),
        EngineModuleContract(
            name="decision_engine",
            responsibility="Create benchmark-aware, risk-defined decision objects from competing evidence.",
            owns_truth=True,
            produces=["decision_objects", "decision_quality"],
            consumes=["signal_candidates", "factor_scores", "portfolio_context"],
            event_outputs=["decision_created"],
        ),
        EngineModuleContract(
            name="paper_trading",
            responsibility="Freeze paper decisions, track outcomes and preserve auditable trade evidence.",
            owns_truth=True,
            produces=["paper_trades", "trade_outcomes"],
            consumes=["decision_objects"],
            event_outputs=["trade_opened", "trade_closed", "paper_trade_completed"],
        ),
        EngineModuleContract(
            name="learning_loop",
            responsibility="Evaluate outcomes, classify mistakes and update confidence, weights and knowledge as data.",
            owns_truth=True,
            produces=["learning_events", "strategy_memory", "confidence_updates"],
            consumes=["trade_outcomes", "benchmark_outcomes"],
            event_outputs=["learning_cycle_completed", "knowledge_updated", "confidence_changed"],
        ),
        EngineModuleContract(
            name="portfolio_intelligence",
            responsibility="Evaluate position interaction, concentration, capital allocation and portfolio-level risk.",
            owns_truth=True,
            produces=["portfolio_status", "capital_allocation_rules"],
            consumes=["decision_objects", "trade_outcomes"],
            event_outputs=["portfolio_updated"],
        ),
        EngineModuleContract(
            name="alpha_validation",
            responsibility="Compare BLUM decisions against benchmarks, baselines and available opportunity sets.",
            owns_truth=True,
            produces=["alpha_status", "benchmark_evidence", "alpha_loss_attribution"],
            consumes=["trade_outcomes", "decision_objects", "benchmark_outcomes"],
            event_outputs=["benchmark_updated", "alpha_improved"],
        ),
        EngineModuleContract(
            name="brain_score",
            responsibility="Measure whether decision quality, learning velocity, evidence quality and alpha readiness are improving.",
            owns_truth=True,
            produces=["brain_status", "brain_score"],
            consumes=["learning_events", "alpha_status", "portfolio_status"],
            event_outputs=["brain_score_updated"],
        ),
        EngineModuleContract(
            name="dataset_export",
            responsibility="Export curated reasoning examples for BLUM Analyst without making the model a source of truth.",
            owns_truth=True,
            produces=["reasoning_dataset", "training_manifest"],
            consumes=["decision_objects", "learning_events", "self_critique"],
            event_outputs=["dataset_exported"],
        ),
    ]


def event_contract() -> list[EngineEventType]:
    return [
        "market_updated",
        "news_processed",
        "decision_created",
        "trade_opened",
        "trade_closed",
        "paper_trade_completed",
        "benchmark_updated",
        "learning_cycle_completed",
        "knowledge_updated",
        "brain_score_updated",
        "dataset_exported",
        "alpha_improved",
        "confidence_changed",
        "portfolio_updated",
    ]
