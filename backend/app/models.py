from datetime import UTC, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base


JsonType = JSON().with_variant(JSONB, "postgresql")


class AlphaCallRegistration(Base):
    __tablename__ = "alpha_call_registrations"
    __table_args__ = (
        Index("ix_alpha_calls_market_registered", "market", "registered_at", "id"),
        Index("ix_alpha_calls_source", "source_type", "source_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_uid: Mapped[str] = mapped_column(String(220), unique=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[int] = mapped_column(Integer)
    market: Mapped[str] = mapped_column(String(16), index=True)
    asset: Mapped[str] = mapped_column(String(32))
    decision_at: Mapped[datetime] = mapped_column(DateTime)
    registered_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_revision: Mapped[str] = mapped_column(String(40))
    source_content_hash: Mapped[str] = mapped_column(String(64))
    manifest_json: Mapped[dict] = mapped_column(JsonType)
    manifest_sha256: Mapped[str] = mapped_column(String(64))


class AscentGeneration(Base):
    __tablename__ = "ascent_generations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generation_uid: Mapped[str] = mapped_column(String(80), unique=True)
    parent_uid: Mapped[str | None] = mapped_column(String(80))
    market_family: Mapped[str] = mapped_column(String(24))
    evidence_lane: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), index=True)
    source_revision: Mapped[str] = mapped_column(String(80))
    seed: Mapped[int] = mapped_column(Integer, default=3407)
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    snapshot_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    manifest_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    summary_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    selected_experiment_uid: Mapped[str | None] = mapped_column(String(100))
    holdout_opened: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AscentExperiment(Base):
    __tablename__ = "ascent_experiments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_uid: Mapped[str] = mapped_column(String(100), unique=True)
    generation_uid: Mapped[str] = mapped_column(ForeignKey("ascent_generations.generation_uid", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    source_text: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    development_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    result_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class AscentEvidenceUse(Base):
    __tablename__ = "ascent_evidence_use"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_uid: Mapped[str] = mapped_column(String(200), unique=True)
    decision_identity: Mapped[str] = mapped_column(String(64), unique=True)
    generation_uid: Mapped[str] = mapped_column(ForeignKey("ascent_generations.generation_uid", ondelete="RESTRICT"), index=True)
    partition: Mapped[str] = mapped_column(String(24))


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(220))
    category: Mapped[str] = mapped_column(String(80), index=True)
    sector: Mapped[str] = mapped_column(String(120), index=True)
    industry: Mapped[str] = mapped_column(String(160), default="")
    country: Mapped[str] = mapped_column(String(80), index=True)
    asset_type: Mapped[str] = mapped_column(String(24), index=True)
    currency: Mapped[str] = mapped_column(String(16), default="USD")
    exchange: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    prices = relationship("PriceHistory", back_populates="asset", cascade="all, delete-orphan")
    signals = relationship("SignalSnapshot", back_populates="asset", cascade="all, delete-orphan")


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("asset_id", "date", name="uq_price_asset_date"),
        Index("ix_price_asset_date", "asset_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(40), default="yfinance")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    asset = relationship("Asset", back_populates="prices")


class PriceProviderCheck(Base):
    __tablename__ = "price_provider_checks"
    __table_args__ = (
        UniqueConstraint("asset_id", "date", name="uq_price_provider_check_asset_date"),
        Index("ix_price_provider_checks_ticker_date", "ticker", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    provider_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    reference_close: Mapped[float | None] = mapped_column(Float)
    max_divergence_pct: Mapped[float | None] = mapped_column(Float, index=True)
    status: Mapped[str] = mapped_column(String(80), default="not_checked", index=True)
    observations: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(160), index=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, unique=True)
    canonical_key: Mapped[str] = mapped_column(String(260), unique=True, index=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    theme_tags: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    links = relationship("NewsAssetLink", back_populates="article", cascade="all, delete-orphan")
    sentiments = relationship("SentimentAnalysis", back_populates="article", cascade="all, delete-orphan")


class NewsAssetLink(Base):
    __tablename__ = "news_asset_links"
    __table_args__ = (UniqueConstraint("article_id", "asset_id", name="uq_news_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)

    article = relationship("NewsArticle", back_populates="links")
    asset = relationship("Asset")


class SentimentAnalysis(Base):
    __tablename__ = "sentiment_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    model_name: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(40), index=True)
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_vader: Mapped[float | None] = mapped_column(Float)
    raw_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    article = relationship("NewsArticle", back_populates="sentiments")
    asset = relationship("Asset")


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"
    __table_args__ = (UniqueConstraint("asset_id", "date", name="uq_indicator_asset_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    indicators: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    asset = relationship("Asset")


class SignalSnapshot(Base):
    __tablename__ = "signal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    classification: Mapped[str] = mapped_column(String(80), index=True)
    blum_score: Mapped[float] = mapped_column(Float, index=True)
    risk_level: Mapped[str] = mapped_column(String(40), index=True)
    time_horizon: Mapped[str] = mapped_column(String(80), default="Short/Medium term")
    score_version: Mapped[str] = mapped_column(String(40), default="blum-score-v0.4", index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    lifecycle_state: Mapped[str] = mapped_column(String(40), default="new", index=True)
    score_breakdown: Mapped[dict] = mapped_column(JsonType, default=dict)
    technical_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    narrative_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    watch_points: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset", back_populates="signals")


class ThemeCluster(Base):
    __tablename__ = "theme_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(120), index=True)
    keywords: Mapped[dict] = mapped_column(JsonType, default=dict)
    article_ids: Mapped[dict] = mapped_column(JsonType, default=dict)
    asset_tickers: Mapped[dict] = mapped_column(JsonType, default=dict)
    centroid: Mapped[dict] = mapped_column(JsonType, default=dict)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class EmbeddingVector(Base):
    __tablename__ = "embedding_vectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    model_name: Mapped[str] = mapped_column(String(160), index=True)
    vector: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIInsight(Base):
    __tablename__ = "ai_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    model_name: Mapped[str] = mapped_column(String(160), index=True)
    insight_type: Mapped[str] = mapped_column(String(80), default="asset_explanation")
    structured_output: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ETFTrend(Base):
    __tablename__ = "etf_trends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)
    momentum_score: Mapped[float] = mapped_column(Float, default=0.0)
    thematic_score: Mapped[float] = mapped_column(Float, default=0.0)
    confirmation_score: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_name: Mapped[str] = mapped_column(String(160), index=True)
    benchmark: Mapped[str] = mapped_column(String(32), default="SPY")
    parameters: Mapped[dict] = mapped_column(JsonType, default=dict)
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    results: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("ticker", "watchlist_name", name="uq_watchlist_ticker_name"),
        Index("ix_watchlist_items_name_created", "watchlist_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    watchlist_name: Mapped[str] = mapped_column(String(120), default="Strategic Watchlist", index=True)
    status: Mapped[str] = mapped_column(String(80), default="active", index=True)
    thesis: Mapped[str] = mapped_column(Text, default="")
    alert_rules: Mapped[dict] = mapped_column(JsonType, default=dict)
    last_score: Mapped[float | None] = mapped_column(Float)
    metadata_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    asset = relationship("Asset")


class IntelligenceReport(Base):
    __tablename__ = "intelligence_reports"
    __table_args__ = (Index("ix_intelligence_reports_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    report_type: Mapped[str] = mapped_column(String(80), default="asset_intelligence", index=True)
    title: Mapped[str] = mapped_column(String(260))
    summary: Mapped[str] = mapped_column(Text, default="")
    structured_output: Mapped[dict] = mapped_column(JsonType, default=dict)
    data_mode: Mapped[str] = mapped_column(String(80), default="real_public_data", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class PortfolioScenario(Base):
    __tablename__ = "portfolio_scenarios"
    __table_args__ = (Index("ix_portfolio_scenarios_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_name: Mapped[str] = mapped_column(String(160), index=True)
    risk_profile: Mapped[str] = mapped_column(String(80), default="balanced", index=True)
    allocation: Mapped[dict] = mapped_column(JsonType, default=dict)
    rationale: Mapped[dict] = mapped_column(JsonType, default=dict)
    disclaimer: Mapped[str] = mapped_column(Text, default="")
    data_mode: Mapped[str] = mapped_column(String(80), default="real_public_data", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        UniqueConstraint("session_key", name="uq_chat_session_key"),
        Index("ix_chat_sessions_updated", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_key: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(220), default="Blum Chat Session")
    language: Mapped[str] = mapped_column(String(12), default="en", index=True)
    horizon: Mapped[str] = mapped_column(String(80), default="multi-horizon", index=True)
    risk_profile: Mapped[str] = mapped_column(String(80), default="balanced", index=True)
    metadata_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_created", "session_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(24), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(12), default="en", index=True)
    response_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    session = relationship("ChatSession")


class SignalEvaluation(Base):
    __tablename__ = "signal_evaluations"
    __table_args__ = (
        UniqueConstraint("signal_id", "horizon_days", name="uq_signal_evaluation_signal_horizon"),
        Index("ix_signal_evaluations_ticker_horizon", "ticker", "horizon_days"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal_snapshots.id", ondelete="SET NULL"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="", index=True)
    signal_type: Mapped[str] = mapped_column(String(80), index=True)
    expected_direction: Mapped[str] = mapped_column(String(40), default="up_or_resilient", index=True)
    time_horizon: Mapped[str] = mapped_column(String(80), default="")
    horizon_days: Mapped[int] = mapped_column(Integer, index=True)
    signal_created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    initial_confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    initial_sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    initial_momentum: Mapped[float] = mapped_column(Float, default=0.0)
    news_evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    price_at_signal: Mapped[float | None] = mapped_column(Float)
    price_after_horizon: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    max_upside: Mapped[float | None] = mapped_column(Float)
    realized_return: Mapped[float | None] = mapped_column(Float, index=True)
    volatility_after_signal: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(40), default="inconclusive", index=True)
    explanation_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    evaluation_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    signal = relationship("SignalSnapshot")
    asset = relationship("Asset")


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"
    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_signal_outcome_signal"),
        Index("ix_signal_outcomes_ticker_created", "ticker", "signal_created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal_snapshots.id", ondelete="SET NULL"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="", index=True)
    signal_type: Mapped[str] = mapped_column(String(80), index=True)
    signal_created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    initial_score: Mapped[float] = mapped_column(Float, default=0.0)
    initial_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    final_outcome: Mapped[str] = mapped_column(String(40), default="inconclusive", index=True)
    best_horizon_days: Mapped[int | None] = mapped_column(Integer)
    worst_horizon_days: Mapped[int | None] = mapped_column(Integer)
    average_realized_return: Mapped[float | None] = mapped_column(Float)
    outcome_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    signal = relationship("SignalSnapshot")
    asset = relationship("Asset")


class ModelWeightVersion(Base):
    __tablename__ = "model_weight_versions"
    __table_args__ = (Index("ix_model_weight_versions_active_created", "is_active", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    weights: Mapped[dict] = mapped_column(JsonType, default=dict)
    previous_weights: Mapped[dict] = mapped_column(JsonType, default=dict)
    calibration_metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    change_reason: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LearningEvent(Base):
    __tablename__ = "learning_events"
    __table_args__ = (Index("ix_learning_events_type_created", "event_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="Info", index=True)
    title: Mapped[str] = mapped_column(String(260))
    description: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class HistoricalSimilarityCase(Base):
    __tablename__ = "historical_similarity_cases"
    __table_args__ = (Index("ix_similarity_cases_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    reference_signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal_snapshots.id", ondelete="SET NULL"), index=True)
    case_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    features: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")
    reference_signal = relationship("SignalSnapshot")


class ConfidenceAdjustment(Base):
    __tablename__ = "confidence_adjustments"
    __table_args__ = (Index("ix_confidence_adjustments_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    signal_type: Mapped[str | None] = mapped_column(String(80), index=True)
    base_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    adjusted_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    adjustment: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class SourceReliabilityScore(Base):
    __tablename__ = "source_reliability_scores"
    __table_args__ = (
        UniqueConstraint("source", name="uq_source_reliability_source"),
        Index("ix_source_reliability_score", "reliability_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(160), index=True)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    linked_signal_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_signal_rate: Mapped[float | None] = mapped_column(Float)
    false_positive_rate: Mapped[float | None] = mapped_column(Float)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class TickerAccuracyProfile(Base):
    __tablename__ = "ticker_accuracy_profiles"
    __table_args__ = (
        UniqueConstraint("ticker", name="uq_ticker_accuracy_profile"),
        Index("ix_ticker_accuracy_profiles_score", "accuracy_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    evaluated_signals: Mapped[int] = mapped_column(Integer, default=0)
    correct_rate: Mapped[float | None] = mapped_column(Float)
    neutral_rate: Mapped[float | None] = mapped_column(Float)
    average_return: Mapped[float | None] = mapped_column(Float)
    average_drawdown: Mapped[float | None] = mapped_column(Float)
    accuracy_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    profile_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    asset = relationship("Asset")


class SectorAccuracyProfile(Base):
    __tablename__ = "sector_accuracy_profiles"
    __table_args__ = (
        UniqueConstraint("sector", name="uq_sector_accuracy_profile"),
        Index("ix_sector_accuracy_profiles_score", "accuracy_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector: Mapped[str] = mapped_column(String(120), index=True)
    evaluated_signals: Mapped[int] = mapped_column(Integer, default=0)
    correct_rate: Mapped[float | None] = mapped_column(Float)
    neutral_rate: Mapped[float | None] = mapped_column(Float)
    average_return: Mapped[float | None] = mapped_column(Float)
    average_drawdown: Mapped[float | None] = mapped_column(Float)
    accuracy_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    profile_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ChartAnalysis(Base):
    __tablename__ = "chart_analyses"
    __table_args__ = (
        Index("ix_chart_analyses_ticker_timeframe_created", "ticker", "timeframe", "created_at"),
        Index("ix_chart_analyses_image_hash", "image_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="6M", index=True)
    period: Mapped[str] = mapped_column(String(40), default="1y", index=True)
    image_hash: Mapped[str | None] = mapped_column(String(128))
    model_used: Mapped[str] = mapped_column(String(180), default="deterministic_technical_analysis", index=True)
    visual_analysis_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    deterministic_analysis_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    hybrid_analysis_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    chart_image: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class TechnicalLevel(Base):
    __tablename__ = "technical_levels"
    __table_args__ = (
        UniqueConstraint("ticker", "timeframe", name="uq_technical_levels_ticker_timeframe"),
        Index("ix_technical_levels_ticker_updated", "ticker", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="6M", index=True)
    support_levels_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    resistance_levels_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    breakout_level: Mapped[float | None] = mapped_column(Float)
    breakdown_level: Mapped[float | None] = mapped_column(Float)
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    asset = relationship("Asset")


class TechnicalSignal(Base):
    __tablename__ = "technical_signals"
    __table_args__ = (Index("ix_technical_signals_ticker_timeframe_created", "ticker", "timeframe", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="6M", index=True)
    signal_type: Mapped[str] = mapped_column(String(120), index=True)
    direction: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class ChartPatternMemory(Base):
    __tablename__ = "chart_pattern_memory"
    __table_args__ = (Index("ix_chart_pattern_memory_ticker_pattern_created", "ticker", "pattern_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="6M", index=True)
    pattern_type: Mapped[str] = mapped_column(String(120), index=True)
    setup_embedding: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_1d: Mapped[float | None] = mapped_column(Float)
    outcome_7d: Mapped[float | None] = mapped_column(Float)
    outcome_30d: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    success: Mapped[bool | None] = mapped_column(Boolean, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class AccuracySnapshot(Base):
    __tablename__ = "accuracy_snapshots"
    __table_args__ = (Index("ix_accuracy_snapshots_scope_created", "scope", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    scope: Mapped[str] = mapped_column(String(80), default="asset", index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    confidence_label: Mapped[str] = mapped_column(String(40), default="Low", index=True)
    components: Mapped[dict] = mapped_column(JsonType, default=dict)
    issues: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class CorporateActionEvent(Base):
    __tablename__ = "corporate_action_events"
    __table_args__ = (
        UniqueConstraint("asset_id", "action_type", "effective_date", "source", name="uq_corporate_action_event"),
        Index("ix_corporate_action_events_ticker_date", "ticker", "effective_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    action_type: Mapped[str] = mapped_column(String(80), index=True)
    effective_date: Mapped[datetime] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(120), default="price_anomaly_detector", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class FundamentalSnapshot(Base):
    __tablename__ = "fundamental_snapshots"
    __table_args__ = (
        UniqueConstraint("asset_id", "provider", "period_end", name="uq_fundamental_asset_provider_period"),
        Index("ix_fundamental_snapshots_ticker_created", "ticker", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(120), default="sec_companyfacts", index=True)
    period_end: Mapped[datetime | None] = mapped_column(Date, index=True)
    fiscal_period: Mapped[str] = mapped_column(String(40), default="")
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class MacroSnapshot(Base):
    __tablename__ = "macro_snapshots"
    __table_args__ = (
        UniqueConstraint("indicator", "date", "provider", name="uq_macro_indicator_date_provider"),
        Index("ix_macro_snapshots_indicator_created", "indicator", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indicator: Mapped[str] = mapped_column(String(80), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    value: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(120), default="fred", index=True)
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class IPOCompany(Base):
    __tablename__ = "ipo_companies"
    __table_args__ = (
        UniqueConstraint("cik", "name", name="uq_ipo_company_cik_name"),
        Index("ix_ipo_companies_last_seen", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[str | None] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(260), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    exchange: Mapped[str | None] = mapped_column(String(80), index=True)
    country: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    industry: Mapped[str] = mapped_column(String(160), default="Unknown")
    status: Mapped[str] = mapped_column(String(80), default="filing_observed", index=True)
    company_metadata: Mapped[dict] = mapped_column(JsonType, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    filings = relationship("IPOFiling", back_populates="company", cascade="all, delete-orphan")
    scores = relationship("IPOScore", back_populates="company", cascade="all, delete-orphan")


class IPOFiling(Base):
    __tablename__ = "ipo_filings"
    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_ipo_filing_accession"),
        Index("ix_ipo_filings_company_form_date", "company_id", "form_type", "filing_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ipo_companies.id", ondelete="CASCADE"), index=True)
    cik: Mapped[str | None] = mapped_column(String(20), index=True)
    company_name: Mapped[str] = mapped_column(String(260), index=True)
    form_type: Mapped[str] = mapped_column(String(40), index=True)
    filing_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    accession_number: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str] = mapped_column(String(120), default="SEC EDGAR", index=True)
    raw_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    company = relationship("IPOCompany", back_populates="filings")
    scores = relationship("IPOScore", back_populates="filing")


class IPOScore(Base):
    __tablename__ = "ipo_scores"
    __table_args__ = (Index("ix_ipo_scores_company_created", "company_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ipo_companies.id", ondelete="CASCADE"), index=True)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("ipo_filings.id", ondelete="SET NULL"), index=True)
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    listing_probability_score: Mapped[float] = mapped_column(Float, default=0.0)
    narrative_heat_score: Mapped[float] = mapped_column(Float, default=0.0)
    valuation_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    opportunity_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    classification: Mapped[str] = mapped_column(String(80), index=True)
    time_horizon: Mapped[str] = mapped_column(String(80), default="IPO watch")
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    company = relationship("IPOCompany", back_populates="scores")
    filing = relationship("IPOFiling", back_populates="scores")


class MarketBrainSnapshot(Base):
    __tablename__ = "market_brain_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    brain_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    regime: Mapped[str] = mapped_column(String(120), index=True)
    horizon: Mapped[str] = mapped_column(String(80), default="Multi-horizon")
    summary: Mapped[str] = mapped_column(Text, default="")
    structured_output: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BlumKnowledgeRecord(Base):
    __tablename__ = "blum_knowledge_records"
    __table_args__ = (
        UniqueConstraint("reasoning_hash", name="uq_blum_knowledge_reasoning_hash"),
        Index("ix_blum_knowledge_ticker_created", "ticker", "created_at"),
        Index("ix_blum_knowledge_regime_created", "market_regime", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal_snapshots.id", ondelete="SET NULL"), index=True)
    ai_insight_id: Mapped[int | None] = mapped_column(ForeignKey("ai_insights.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="", index=True)
    industry: Mapped[str] = mapped_column(String(160), default="")
    source_type: Mapped[str] = mapped_column(String(80), default="signal_snapshot", index=True)
    reasoning_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="Sideways", index=True)
    volatility_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    risk_sentiment: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    conviction_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    market_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    asset_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    blum_reasoning: Mapped[dict] = mapped_column(JsonType, default=dict)
    prediction_horizons: Mapped[dict] = mapped_column(JsonType, default=dict)
    quality_scores: Mapped[dict] = mapped_column(JsonType, default=dict)
    self_critique: Mapped[dict] = mapped_column(JsonType, default=dict)
    training_sample: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    asset = relationship("Asset")
    signal = relationship("SignalSnapshot")
    ai_insight = relationship("AIInsight")


class BlumThesisOutcome(Base):
    __tablename__ = "blum_thesis_outcomes"
    __table_args__ = (
        UniqueConstraint("knowledge_record_id", "horizon_days", name="uq_blum_thesis_outcome_record_horizon"),
        Index("ix_blum_thesis_outcomes_ticker_horizon", "ticker", "horizon_days"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, index=True)
    expected_direction: Mapped[str] = mapped_column(String(80), default="up_or_resilient", index=True)
    price_at_thesis: Mapped[float | None] = mapped_column(Float)
    price_after_horizon: Mapped[float | None] = mapped_column(Float)
    realized_return: Mapped[float | None] = mapped_column(Float, index=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    max_upside: Mapped[float | None] = mapped_column(Float)
    realized_volatility: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(40), default="inconclusive", index=True)
    success: Mapped[bool | None] = mapped_column(Boolean, index=True)
    outcome_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")
    asset = relationship("Asset")


class BlumReasoningMemory(Base):
    __tablename__ = "blum_reasoning_memory"
    __table_args__ = (Index("ix_blum_reasoning_memory_ticker_type_created", "ticker", "memory_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int | None] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    memory_type: Mapped[str] = mapped_column(String(80), default="asset_thesis", index=True)
    embedding_model: Mapped[str] = mapped_column(String(160), default="", index=True)
    embedding: Mapped[dict] = mapped_column(JsonType, default=dict)
    memory_text: Mapped[str] = mapped_column(Text, default="")
    metadata_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_label: Mapped[str] = mapped_column(String(80), default="pending", index=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")
    asset = relationship("Asset")


class BlumTrainingExample(Base):
    __tablename__ = "blum_training_examples"
    __table_args__ = (
        UniqueConstraint("knowledge_record_id", "task_type", name="uq_blum_training_record_task"),
        Index("ix_blum_training_examples_ready_created", "export_ready", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int | None] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    task_type: Mapped[str] = mapped_column(String(100), default="financial_thesis_generation", index=True)
    dataset_split: Mapped[str] = mapped_column(String(40), default="train", index=True)
    base_model_family: Mapped[str] = mapped_column(String(80), default="qwen_llama_mistral", index=True)
    input_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    output_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    messages: Mapped[dict] = mapped_column(JsonType, default=dict)
    quality_scores: Mapped[dict] = mapped_column(JsonType, default=dict)
    preference_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    export_ready: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")


class BlumThesisQualityScore(Base):
    __tablename__ = "blum_thesis_quality_scores"
    __table_args__ = (UniqueConstraint("knowledge_record_id", name="uq_blum_quality_record"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    reasoning_depth: Mapped[float] = mapped_column(Float, default=0.0)
    consistency: Mapped[float] = mapped_column(Float, default=0.0)
    contradiction_handling: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_calibration: Mapped[float] = mapped_column(Float, default=0.0)
    historical_alignment: Mapped[float] = mapped_column(Float, default=0.0)
    narrative_quality: Mapped[float] = mapped_column(Float, default=0.0)
    explainability_quality: Mapped[float] = mapped_column(Float, default=0.0)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evaluator_version: Mapped[str] = mapped_column(String(80), default="blum-quality-v0.1", index=True)
    quality_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")


class BlumSelfCritique(Base):
    __tablename__ = "blum_self_critiques"
    __table_args__ = (UniqueConstraint("knowledge_record_id", name="uq_blum_self_critique_record"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    analyst_view: Mapped[dict] = mapped_column(JsonType, default=dict)
    skeptic_view: Mapped[dict] = mapped_column(JsonType, default=dict)
    historical_view: Mapped[dict] = mapped_column(JsonType, default=dict)
    final_view: Mapped[dict] = mapped_column(JsonType, default=dict)
    critique_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")


class BlumNarrativeMemory(Base):
    __tablename__ = "blum_narrative_memory"
    __table_args__ = (Index("ix_blum_narrative_stage_updated", "lifecycle_stage", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    narrative: Mapped[str] = mapped_column(String(160), index=True)
    lifecycle_stage: Mapped[str] = mapped_column(String(80), default="Emerging", index=True)
    intensity: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    velocity: Mapped[float] = mapped_column(Float, default=0.0)
    saturation: Mapped[float] = mapped_column(Float, default=0.0)
    crowding: Mapped[float] = mapped_column(Float, default=0.0)
    linked_assets: Mapped[dict] = mapped_column(JsonType, default=dict)
    sectors: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class BlumRegimeMemory(Base):
    __tablename__ = "blum_regime_memory"
    __table_args__ = (Index("ix_blum_regime_memory_regime_updated", "market_regime", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_regime: Mapped[str] = mapped_column(String(120), index=True)
    volatility_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    liquidity_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    macro_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    reasoning_patterns: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ThesisLifecycleEvent(Base):
    __tablename__ = "thesis_lifecycle_events"
    __table_args__ = (
        Index("ix_thesis_lifecycle_events_ticker_status", "ticker", "new_status"),
        Index("ix_thesis_lifecycle_events_record_created", "knowledge_record_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    previous_status: Mapped[str] = mapped_column(String(40), default="NEW", index=True)
    new_status: Mapped[str] = mapped_column(String(40), default="ACTIVE", index=True)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    conviction_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    outcome_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    evidence_delta: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")


class ModelReliabilityMatrix(Base):
    __tablename__ = "model_reliability_matrix"
    __table_args__ = (
        UniqueConstraint("engine_name", "sector", "market_regime", "timeframe", name="uq_model_reliability_context"),
        Index("ix_model_reliability_matrix_score", "reliability_score"),
        Index("ix_model_reliability_matrix_engine_updated", "engine_name", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engine_name: Mapped[str] = mapped_column(String(100), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="All", index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="All", index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="All", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, default=0)
    inconclusive_count: Mapped[int] = mapped_column(Integer, default=0)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    weight_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    calibration_error: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ConfidenceCalibrationBucket(Base):
    __tablename__ = "confidence_calibration_buckets"
    __table_args__ = (
        UniqueConstraint("bucket_label", name="uq_confidence_calibration_bucket_label"),
        Index("ix_confidence_calibration_buckets_error", "calibration_error"),
        Index("ix_confidence_calibration_buckets_updated", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_label: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    min_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    max_confidence: Mapped[float] = mapped_column(Float, default=100.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    average_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    empirical_success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    calibration_error: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    suggested_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class MetaLearningEvent(Base):
    __tablename__ = "meta_learning_events"
    __table_args__ = (
        Index("ix_meta_learning_events_type_created", "event_type", "created_at"),
        Index("ix_meta_learning_events_engine_status", "engine_name", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    engine_name: Mapped[str | None] = mapped_column(String(100), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="Info", index=True)
    lesson: Mapped[str] = mapped_column(Text, default="")
    root_cause: Mapped[str] = mapped_column(String(160), default="", index=True)
    proposed_change: Mapped[dict] = mapped_column(JsonType, default=dict)
    trigger_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ThesisSurvivalMetric(Base):
    __tablename__ = "thesis_survival_metrics"
    __table_args__ = (
        UniqueConstraint("thesis_id", name="uq_thesis_survival_metric_thesis"),
        Index("ix_thesis_survival_ticker_status", "ticker", "survival_status"),
        Index("ix_thesis_survival_regime_quality", "regime_primary", "survival_quality_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="", index=True)
    thesis_type: Mapped[str] = mapped_column(String(100), default="research_thesis", index=True)
    direction: Mapped[str] = mapped_column(String(40), default="neutral", index=True)
    horizon: Mapped[str] = mapped_column(String(40), default="multi", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    thesis_age_days: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    survival_status: Mapped[str] = mapped_column(String(40), default="ACTIVE", index=True)
    survival_days: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    initial_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    current_confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    confidence_decay: Mapped[float] = mapped_column(Float, default=0.0)
    max_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    min_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    final_return: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    excess_return: Mapped[float | None] = mapped_column(Float, index=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    regime_primary: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    regime_secondary: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    sector_regime: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    failure_reason: Mapped[str] = mapped_column(String(180), default="", index=True)
    survival_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    notes_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    thesis = relationship("BlumKnowledgeRecord")


class ThesisConvictionHistory(Base):
    __tablename__ = "thesis_conviction_history"
    __table_args__ = (
        Index("ix_thesis_conviction_thesis_evaluated", "thesis_id", "evaluated_at"),
        Index("ix_thesis_conviction_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    previous_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    new_confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    confidence_delta: Mapped[float] = mapped_column(Float, default=0.0)
    decay_score: Mapped[float] = mapped_column(Float, default=0.0)
    strengthening_score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    contradiction_pressure: Mapped[float] = mapped_column(Float, default=0.0)
    price_confirmation_score: Mapped[float] = mapped_column(Float, default=0.0)
    volume_confirmation_score: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment_confirmation_score: Mapped[float] = mapped_column(Float, default=0.0)
    narrative_confirmation_score: Mapped[float] = mapped_column(Float, default=0.0)
    regime_confirmation_score: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_confirmation_score: Mapped[float] = mapped_column(Float, default=0.0)
    invalidation_distance: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(40), default="stable", index=True)
    explanation: Mapped[str] = mapped_column(Text, default="")

    thesis = relationship("BlumKnowledgeRecord")


class ModelReliabilityByRegime(Base):
    __tablename__ = "model_reliability_by_regime"
    __table_args__ = (
        UniqueConstraint(
            "engine_name",
            "signal_type",
            "setup_type",
            "thesis_type",
            "sector",
            "industry",
            "asset_class",
            "horizon",
            "market_regime",
            "volatility_regime",
            "breadth_regime",
            name="uq_model_reliability_by_regime_context",
        ),
        Index("ix_reliability_by_regime_engine_score", "engine_name", "reliability_score"),
        Index("ix_reliability_by_regime_context", "market_regime", "sector", "horizon"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engine_name: Mapped[str] = mapped_column(String(100), index=True)
    signal_type: Mapped[str] = mapped_column(String(100), default="unknown", index=True)
    setup_type: Mapped[str] = mapped_column(String(100), default="unknown", index=True)
    thesis_type: Mapped[str] = mapped_column(String(100), default="research_thesis", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    industry: Mapped[str] = mapped_column(String(160), default="", index=True)
    asset_class: Mapped[str] = mapped_column(String(40), default="stock", index=True)
    horizon: Mapped[str] = mapped_column(String(40), default="multi", index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    volatility_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    breadth_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    hit_rate: Mapped[float] = mapped_column(Float, default=0.0)
    average_return: Mapped[float | None] = mapped_column(Float)
    excess_return_vs_benchmark: Mapped[float | None] = mapped_column(Float)
    average_r_multiple: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    false_positive_rate: Mapped[float] = mapped_column(Float, default=0.0)
    false_negative_rate: Mapped[float] = mapped_column(Float, default=0.0)
    calibration_error: Mapped[float | None] = mapped_column(Float)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    confidence_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ThesisCompetition(Base):
    __tablename__ = "thesis_competitions"
    __table_args__ = (
        Index("ix_thesis_competitions_ticker_status", "ticker", "status"),
        Index("ix_thesis_competitions_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    sector_regime: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    winning_thesis_id: Mapped[int | None] = mapped_column(ForeignKey("competing_theses.id", ondelete="SET NULL"), index=True)
    runner_up_thesis_id: Mapped[int | None] = mapped_column(ForeignKey("competing_theses.id", ondelete="SET NULL"), index=True)
    uncertainty_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    judge_summary: Mapped[str] = mapped_column(Text, default="")
    next_evidence_to_watch: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)


class CompetingThesis(Base):
    __tablename__ = "competing_theses"
    __table_args__ = (
        Index("ix_competing_theses_competition_side", "competition_id", "thesis_side"),
        Index("ix_competing_theses_judge_score", "judge_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("thesis_competitions.id", ondelete="CASCADE"), index=True)
    thesis_side: Mapped[str] = mapped_column(String(40), index=True)
    thesis_text: Mapped[str] = mapped_column(Text, default="")
    supporting_evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    contradicting_evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    judge_score: Mapped[float] = mapped_column(Float, default=0.0)
    invalidation_conditions_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    expected_horizon: Mapped[str] = mapped_column(String(80), default="multi", index=True)
    outcome_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    benchmark_relative_outcome: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    competition = relationship("ThesisCompetition", foreign_keys=[competition_id])


class EngineVote(Base):
    __tablename__ = "engine_votes"
    __table_args__ = (
        UniqueConstraint("thesis_id", "engine_name", "horizon", name="uq_engine_vote_thesis_engine_horizon"),
        Index("ix_engine_votes_ticker_engine", "ticker", "engine_name"),
        Index("ix_engine_votes_outcome", "outcome_evaluated", "was_correct"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    engine_name: Mapped[str] = mapped_column(String(100), index=True)
    vote: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evidence_quality: Mapped[float] = mapped_column(Float, default=0.0)
    horizon: Mapped[str] = mapped_column(String(40), default="multi", index=True)
    regime: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    outcome_evaluated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, index=True)
    excess_return_contribution: Mapped[float | None] = mapped_column(Float)
    reliability_weight_at_time: Mapped[float] = mapped_column(Float, default=0.5)

    thesis = relationship("BlumKnowledgeRecord")


class EnsembleWeightVersion(Base):
    __tablename__ = "ensemble_weight_versions"
    __table_args__ = (Index("ix_ensemble_weight_versions_active_created", "is_active", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    version_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    weights_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    validation_score: Mapped[float] = mapped_column(Float, default=0.0)
    calibration_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class TrainingExampleQualityScore(Base):
    __tablename__ = "training_example_quality_scores"
    __table_args__ = (
        UniqueConstraint("training_example_id", name="uq_training_example_quality_example"),
        Index("ix_training_quality_value", "final_training_value_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_example_id: Mapped[int] = mapped_column(ForeignKey("blum_training_examples.id", ondelete="CASCADE"), index=True)
    thesis_id: Mapped[int | None] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="SET NULL"), index=True)
    reasoning_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    outcome_clarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    contradiction_handling_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_calibration_score: Mapped[float] = mapped_column(Float, default=0.0)
    regime_context_score: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    reproducibility_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_training_value_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    include_in_sft: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    include_in_preference_training: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    include_in_dpo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    exclusion_reason: Mapped[str] = mapped_column(Text, default="")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    training_example = relationship("BlumTrainingExample")
    thesis = relationship("BlumKnowledgeRecord")


class BenchmarkRelativeOutcome(Base):
    __tablename__ = "benchmark_relative_outcomes"
    __table_args__ = (
        UniqueConstraint("object_type", "object_id", "benchmark_ticker", name="uq_benchmark_relative_object_benchmark"),
        Index("ix_benchmark_relative_ticker", "ticker"),
        Index("ix_benchmark_relative_hit", "hit_vs_benchmark"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    object_type: Mapped[str] = mapped_column(String(80), index=True)
    object_id: Mapped[int] = mapped_column(Integer, index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    benchmark_ticker: Mapped[str] = mapped_column(String(32), index=True)
    start_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    end_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    asset_return: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    excess_return: Mapped[float | None] = mapped_column(Float, index=True)
    max_drawdown_asset: Mapped[float | None] = mapped_column(Float)
    max_drawdown_benchmark: Mapped[float | None] = mapped_column(Float)
    volatility_asset: Mapped[float | None] = mapped_column(Float)
    volatility_benchmark: Mapped[float | None] = mapped_column(Float)
    hit_vs_benchmark: Mapped[bool | None] = mapped_column(Boolean, index=True)
    information_ratio_proxy: Mapped[float | None] = mapped_column(Float)
    opportunity_cost: Mapped[float | None] = mapped_column(Float)
    evaluation_notes: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class BlumKnowledgeGraphNode(Base):
    __tablename__ = "blum_knowledge_graph_nodes"
    __table_args__ = (UniqueConstraint("canonical_key", name="uq_blum_graph_node_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_type: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(220), index=True)
    canonical_key: Mapped[str] = mapped_column(String(260), unique=True, index=True)
    properties: Mapped[dict] = mapped_column(JsonType, default=dict)
    embedding: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class BlumKnowledgeGraphEdge(Base):
    __tablename__ = "blum_knowledge_graph_edges"
    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "relation_type", name="uq_blum_graph_edge"),
        Index("ix_blum_graph_edges_relation_created", "relation_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_node_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_graph_nodes.id", ondelete="CASCADE"), index=True)
    target_node_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_graph_nodes.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(100), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    source_node = relationship("BlumKnowledgeGraphNode", foreign_keys=[source_node_id])
    target_node = relationship("BlumKnowledgeGraphNode", foreign_keys=[target_node_id])


class BlumDatasetExport(Base):
    __tablename__ = "blum_dataset_exports"
    __table_args__ = (Index("ix_blum_dataset_exports_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    export_name: Mapped[str] = mapped_column(String(180), index=True)
    format: Mapped[str] = mapped_column(String(40), default="jsonl", index=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(Text, default="")
    filters: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(80), default="created", index=True)
    payload_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BlumModelTrainingJob(Base):
    __tablename__ = "blum_model_training_jobs"
    __table_args__ = (Index("ix_blum_training_jobs_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(180), index=True)
    model_family: Mapped[str] = mapped_column(String(80), index=True)
    base_model: Mapped[str] = mapped_column(String(180), index=True)
    method: Mapped[str] = mapped_column(String(80), index=True)
    dataset_export_id: Mapped[int | None] = mapped_column(ForeignKey("blum_dataset_exports.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(80), default="planned", index=True)
    training_config: Mapped[dict] = mapped_column(JsonType, default=dict)
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    dataset_export = relationship("BlumDatasetExport")


class ExternalDatasetSource(Base):
    __tablename__ = "external_dataset_sources"
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_external_dataset_source_dataset_id"),
        Index("ix_external_dataset_sources_status_priority", "status", "priority"),
        Index("ix_external_dataset_sources_domain_updated", "primary_domain", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), default="hugging_face", index=True)
    title: Mapped[str] = mapped_column(String(260), default="")
    primary_domain: Mapped[str] = mapped_column(String(80), default="market_data", index=True)
    data_domains: Mapped[dict] = mapped_column(JsonType, default=dict)
    license: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    ingestion_mode: Mapped[str] = mapped_column(String(80), default="catalog_only", index=True)
    status: Mapped[str] = mapped_column(String(80), default="discovered", index=True)
    dataset_url: Mapped[str] = mapped_column(Text, default="")
    viewer_status: Mapped[dict] = mapped_column(JsonType, default=dict)
    parquet_files: Mapped[dict] = mapped_column(JsonType, default=dict)
    size_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    usage_policy: Mapped[dict] = mapped_column(JsonType, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class AutonomousEngineRun(Base):
    __tablename__ = "autonomous_engine_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_autonomous_engine_run_id"),
        Index("ix_autonomous_engine_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    trigger: Mapped[str] = mapped_column(String(80), default="scheduled", index=True)
    status: Mapped[str] = mapped_column(String(80), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    stage_results: Mapped[dict] = mapped_column(JsonType, default=dict)
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    data_coverage_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    reasoning_memory_created: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    error_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LearningRun(Base):
    __tablename__ = "learning_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_learning_run_id"),
        Index("ix_learning_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    trigger: Mapped[str] = mapped_column(String(80), default="scheduled", index=True)
    status: Mapped[str] = mapped_column(String(80), default="running", index=True)
    evaluation_mode: Mapped[str] = mapped_column(String(80), default="walk_forward", index=True)
    asset_universe: Mapped[str] = mapped_column(String(120), default="stocks,etfs", index=True)
    batch_size: Mapped[int] = mapped_column(Integer, default=0)
    predictions_created: Mapped[int] = mapped_column(Integer, default=0)
    outcomes_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    mistakes_found: Mapped[int] = mapped_column(Integer, default=0)
    memory_updates: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    anti_overfitting_report: Mapped[dict] = mapped_column(JsonType, default=dict)
    error_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BlumLearningExperiment(Base):
    __tablename__ = "blum_learning_experiments"
    __table_args__ = (
        UniqueConstraint("experiment_id", name="uq_blum_learning_experiment_id"),
        Index("ix_blum_learning_experiments_status_created", "status", "created_at"),
        Index("ix_blum_learning_experiments_setup_status", "target_setup", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    target_market: Mapped[str] = mapped_column(String(100), default="", index=True)
    target_asset_class: Mapped[str] = mapped_column(String(80), default="", index=True)
    target_setup: Mapped[str] = mapped_column(String(140), default="", index=True)
    training_window: Mapped[dict] = mapped_column(JsonType, default=dict)
    validation_window: Mapped[dict] = mapped_column(JsonType, default=dict)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    benchmark_asset: Mapped[str] = mapped_column(String(32), default="SPY", index=True)
    status: Mapped[str] = mapped_column(String(40), default="PROPOSED", index=True)
    result_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    conclusion: Mapped[str] = mapped_column(Text, default="")
    next_action: Mapped[str] = mapped_column(Text, default="")
    source_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class HistoricalPrediction(Base):
    __tablename__ = "historical_predictions"
    __table_args__ = (
        Index("ix_historical_predictions_ticker_date", "ticker", "analysis_date"),
        Index("ix_historical_predictions_run_created", "learning_run_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    learning_run_id: Mapped[int | None] = mapped_column(ForeignKey("learning_runs.id", ondelete="SET NULL"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    asset_type: Mapped[str] = mapped_column(String(40), default="", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="", index=True)
    market: Mapped[str] = mapped_column(String(80), default="", index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    volatility_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    analysis_date: Mapped[datetime] = mapped_column(Date, index=True)
    initial_price: Mapped[float | None] = mapped_column(Float)
    prediction_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    point_in_time_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    expected_direction: Mapped[str] = mapped_column(String(40), default="neutral", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    model_version: Mapped[str] = mapped_column(String(80), default="blum-learning-loop-v1", index=True)
    model_version_used: Mapped[str] = mapped_column(String(100), default="base-static", index=True)
    weights_used: Mapped[dict] = mapped_column(JsonType, default=dict)
    learning_memory_used: Mapped[dict] = mapped_column(JsonType, default=dict)
    strategy_memory_used: Mapped[dict] = mapped_column(JsonType, default=dict)
    research_priority_used: Mapped[dict] = mapped_column(JsonType, default=dict)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    learning_run = relationship("LearningRun")
    asset = relationship("Asset")


class PredictionOutcome(Base):
    __tablename__ = "prediction_outcomes"
    __table_args__ = (
        UniqueConstraint("prediction_id", "timeframe", name="uq_prediction_outcome_prediction_timeframe"),
        Index("ix_prediction_outcomes_ticker_timeframe", "ticker", "timeframe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("historical_predictions.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, index=True)
    evaluation_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    price_at_evaluation: Mapped[float | None] = mapped_column(Float)
    realized_return: Mapped[float | None] = mapped_column(Float, index=True)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    drawdown: Mapped[float | None] = mapped_column(Float)
    time_to_target: Mapped[int | None] = mapped_column(Integer)
    time_to_invalidation: Mapped[int | None] = mapped_column(Integer)
    target_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    invalidation_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean, index=True)
    false_positive: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    false_negative: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    missed_opportunity: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    outcome_label: Mapped[str] = mapped_column(String(40), default="inconclusive", index=True)
    confidence_calibration_error: Mapped[float | None] = mapped_column(Float)
    metrics_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    prediction = relationship("HistoricalPrediction")


class FeedbackLoopAudit(Base):
    __tablename__ = "feedback_loop_audits"
    __table_args__ = (
        Index("ix_feedback_loop_audits_prediction_created", "prediction_id", "created_at"),
        Index("ix_feedback_loop_audits_model_created", "model_version_used", "created_at"),
        Index("ix_feedback_loop_audits_improvement", "improvement_detected", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("historical_predictions.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    model_version_used: Mapped[str] = mapped_column(String(100), default="base-static", index=True)
    learned_knowledge_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    changes_applied_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    future_decision_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    improvement_detected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    evidence_grade: Mapped[str] = mapped_column(String(80), default="insufficient", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    prediction = relationship("HistoricalPrediction")


class MistakeAnalysis(Base):
    __tablename__ = "mistake_analysis"
    __table_args__ = (Index("ix_mistake_analysis_error_created", "error_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("historical_predictions.id", ondelete="CASCADE"), index=True)
    outcome_id: Mapped[int | None] = mapped_column(ForeignKey("prediction_outcomes.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), index=True)
    error_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="Info", index=True)
    predicted: Mapped[dict] = mapped_column(JsonType, default=dict)
    actual: Mapped[dict] = mapped_column(JsonType, default=dict)
    misleading_signal: Mapped[str] = mapped_column(Text, default="")
    signal_to_weight_more: Mapped[str] = mapped_column(Text, default="")
    rule_adjustment: Mapped[str] = mapped_column(Text, default="")
    future_impact: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    prediction = relationship("HistoricalPrediction")
    outcome = relationship("PredictionOutcome")


class SignalPerformance(Base):
    __tablename__ = "signal_performance"
    __table_args__ = (
        UniqueConstraint("signal_name", "timeframe", "market_regime", name="uq_signal_performance_signal_timeframe_regime"),
        Index("ix_signal_performance_reliability", "reliability_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_name: Mapped[str] = mapped_column(String(120), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="All", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    false_positive_count: Mapped[int] = mapped_column(Integer, default=0)
    false_negative_count: Mapped[int] = mapped_column(Integer, default=0)
    average_return: Mapped[float | None] = mapped_column(Float)
    average_drawdown: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    weight_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class StrategyMemory(Base):
    __tablename__ = "strategy_memory"
    __table_args__ = (
        UniqueConstraint("memory_key", name="uq_strategy_memory_key"),
        Index("ix_strategy_memory_category_reliability", "category", "reliability_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    memory_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    lesson: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[dict] = mapped_column(JsonType, default=dict)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    positive_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (Index("ix_model_versions_active_created", "is_active", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    model_name: Mapped[str] = mapped_column(String(160), default="BLUM Learning Loop", index=True)
    weights: Mapped[dict] = mapped_column(JsonType, default=dict)
    previous_weights: Mapped[dict] = mapped_column(JsonType, default=dict)
    training_window: Mapped[dict] = mapped_column(JsonType, default=dict)
    validation_metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    anti_overfitting_report: Mapped[dict] = mapped_column(JsonType, default=dict)
    change_log: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LearningMetric(Base):
    __tablename__ = "learning_metrics"
    __table_args__ = (Index("ix_learning_metrics_name_timeframe_created", "metric_name", "timeframe", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(120), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="all", index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="all", index=True)
    metric_value: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class MarketRegimeSnapshot(Base):
    __tablename__ = "market_regime_snapshots"
    __table_args__ = (Index("ix_market_regime_snapshots_date_created", "date", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    regime_primary: Mapped[str] = mapped_column(String(80), default="range_bound", index=True)
    regime_secondary: Mapped[str] = mapped_column(String(80), default="low_volatility", index=True)
    volatility_state: Mapped[str] = mapped_column(String(80), default="normal", index=True)
    breadth_state: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    risk_appetite_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    sector_rotation_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    data_sources: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SetupLibrary(Base):
    __tablename__ = "setup_library"
    __table_args__ = (
        UniqueConstraint("setup_type", name="uq_setup_library_setup_type"),
        Index("ix_setup_library_quality_reliability", "setup_quality_score", "historical_reliability"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup_type: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    setup_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    setup_maturity: Mapped[str] = mapped_column(String(80), default="developing", index=True)
    required_confirmation: Mapped[str] = mapped_column(Text, default="")
    invalidation_logic: Mapped[str] = mapped_column(Text, default="")
    best_timeframe: Mapped[str] = mapped_column(String(80), default="short/medium", index=True)
    historical_reliability: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    regime_sensitivity: Mapped[dict] = mapped_column(JsonType, default=dict)
    common_failure_modes: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SniperScore(Base):
    __tablename__ = "sniper_scores"
    __table_args__ = (Index("ix_sniper_scores_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), default="avoid_no_edge", index=True)
    sniper_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    actionability: Mapped[str] = mapped_column(String(80), default="avoid", index=True)
    components: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class TradePlan(Base):
    __tablename__ = "trade_plans"
    __table_args__ = (Index("ix_trade_plans_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    sniper_score_id: Mapped[int | None] = mapped_column(ForeignKey("sniper_scores.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    actionability: Mapped[str] = mapped_column(String(80), default="watch", index=True)
    timeframe: Mapped[str] = mapped_column(String(80), default="short/medium", index=True)
    entry_zone: Mapped[dict] = mapped_column(JsonType, default=dict)
    entry_trigger: Mapped[str] = mapped_column(Text, default="")
    confirmation_condition: Mapped[str] = mapped_column(Text, default="")
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    stop_logic: Mapped[str] = mapped_column(Text, default="")
    target_1: Mapped[float | None] = mapped_column(Float)
    target_2: Mapped[float | None] = mapped_column(Float)
    trailing_exit_logic: Mapped[str] = mapped_column(Text, default="")
    partial_exit_logic: Mapped[str] = mapped_column(Text, default="")
    no_trade_conditions: Mapped[dict] = mapped_column(JsonType, default=dict)
    expected_holding_period: Mapped[str] = mapped_column(String(80), default="")
    risk_reward_estimate: Mapped[dict] = mapped_column(JsonType, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    historical_setup_reliability: Mapped[float] = mapped_column(Float, default=50.0)
    disclaimer: Mapped[str] = mapped_column(Text, default="Informational trading scenario, not financial advice.")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")
    sniper_score = relationship("SniperScore")


class TradePlanOutcome(Base):
    __tablename__ = "trade_plan_outcomes"
    __table_args__ = (Index("ix_trade_plan_outcomes_ticker_timeframe", "ticker", "timeframe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="short", index=True)
    entry_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    exit_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    entry_price: Mapped[float | None] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float)
    realized_r_multiple: Mapped[float | None] = mapped_column(Float, index=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    outcome_label: Mapped[str] = mapped_column(String(80), default="inconclusive", index=True)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    trade_plan = relationship("TradePlan")


class ExecutionSimulation(Base):
    __tablename__ = "execution_simulations"
    __table_args__ = (Index("ix_execution_simulations_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("historical_predictions.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    simulation_mode: Mapped[str] = mapped_column(String(80), default="historical_trigger", index=True)
    entry_model: Mapped[str] = mapped_column(String(80), default="conditional", index=True)
    exit_model: Mapped[str] = mapped_column(String(80), default="risk_managed", index=True)
    realized_r_multiple: Mapped[float | None] = mapped_column(Float, index=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    time_in_trade: Mapped[int | None] = mapped_column(Integer)
    stop_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    target_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    trailing_exit_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    missed_entry: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    false_breakout: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    failed_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    opportunity_cost: Mapped[float | None] = mapped_column(Float)
    simulation_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    trade_plan = relationship("TradePlan")
    prediction = relationship("HistoricalPrediction")


class RMultipleMetric(Base):
    __tablename__ = "r_multiple_metrics"
    __table_args__ = (
        UniqueConstraint("setup_type", "timeframe", "market_regime", "sector", name="uq_r_metric_setup_timeframe_regime_sector"),
        Index("ix_r_multiple_metrics_expectancy", "expectancy_r"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="all", index=True)
    market_regime: Mapped[str] = mapped_column(String(80), default="all", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="all", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    hit_rate: Mapped[float | None] = mapped_column(Float)
    average_r: Mapped[float | None] = mapped_column(Float)
    median_r: Mapped[float | None] = mapped_column(Float)
    max_drawdown_r: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    payoff_ratio: Mapped[float | None] = mapped_column(Float)
    expectancy_r: Mapped[float | None] = mapped_column(Float, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SignalReliabilityMatrix(Base):
    __tablename__ = "signal_reliability_matrix"
    __table_args__ = (
        UniqueConstraint("signal_name", "setup_type", "timeframe", "sector", "market_regime", "volatility_state", "asset_class", "liquidity_bucket", name="uq_signal_reliability_context"),
        Index("ix_signal_reliability_matrix_score", "reliability_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_name: Mapped[str] = mapped_column(String(120), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="all", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="all", index=True)
    market_regime: Mapped[str] = mapped_column(String(80), default="all", index=True)
    volatility_state: Mapped[str] = mapped_column(String(80), default="all", index=True)
    asset_class: Mapped[str] = mapped_column(String(40), default="all", index=True)
    liquidity_bucket: Mapped[str] = mapped_column(String(80), default="all", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    false_positive_count: Mapped[int] = mapped_column(Integer, default=0)
    average_r: Mapped[float | None] = mapped_column(Float)
    expectancy_r: Mapped[float | None] = mapped_column(Float, index=True)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class NoTradeDecision(Base):
    __tablename__ = "no_trade_decisions"
    __table_args__ = (Index("ix_no_trade_decisions_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    trade_plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    conditions: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")
    trade_plan = relationship("TradePlan")


class ExitSignal(Base):
    __tablename__ = "exit_signals"
    __table_args__ = (Index("ix_exit_signals_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    trade_plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    exit_type: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(80), default="hold_review", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")
    trade_plan = relationship("TradePlan")


class PortfolioRiskContext(Base):
    __tablename__ = "portfolio_risk_context"
    __table_args__ = (Index("ix_portfolio_risk_context_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    context_name: Mapped[str] = mapped_column(String(120), default="default_research_book", index=True)
    sector_concentration: Mapped[dict] = mapped_column(JsonType, default=dict)
    factor_concentration: Mapped[dict] = mapped_column(JsonType, default=dict)
    correlation: Mapped[dict] = mapped_column(JsonType, default=dict)
    beta: Mapped[dict] = mapped_column(JsonType, default=dict)
    volatility_contribution: Mapped[dict] = mapped_column(JsonType, default=dict)
    overlapping_etf_exposure: Mapped[dict] = mapped_column(JsonType, default=dict)
    max_simultaneous_setups: Mapped[int] = mapped_column(Integer, default=8)
    risk_per_theme: Mapped[dict] = mapped_column(JsonType, default=dict)
    risk_per_regime: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class TradingGame(Base):
    __tablename__ = "trading_games"
    __table_args__ = (Index("ix_trading_games_status_started", "status", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    mode: Mapped[str] = mapped_column(String(80), default="paper_pl_learning", index=True)
    starting_capital: Mapped[float] = mapped_column(Float, default=100.0)
    current_capital: Mapped[float] = mapped_column(Float, default=100.0, index=True)
    cash: Mapped[float] = mapped_column(Float, default=100.0)
    exposure: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pl: Mapped[float] = mapped_column(Float, default=0.0)
    peak_capital: Mapped[float] = mapped_column(Float, default=100.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_ticker: Mapped[str] = mapped_column(String(32), default="SPY", index=True)
    benchmark_start_price: Mapped[float | None] = mapped_column(Float)
    benchmark_end_price: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    alpha: Mapped[float | None] = mapped_column(Float)
    beta: Mapped[float | None] = mapped_column(Float)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float | None] = mapped_column(Float)
    expectancy_r: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    average_r: Mapped[float | None] = mapped_column(Float)
    sharpe: Mapped[float | None] = mapped_column(Float)
    sortino: Mapped[float | None] = mapped_column(Float)
    risk_per_trade: Mapped[float] = mapped_column(Float, default=1.0)
    risk_of_ruin: Mapped[float | None] = mapped_column(Float)
    max_consecutive_losses: Mapped[int] = mapped_column(Integer, default=0)
    time_to_double_days: Mapped[int | None] = mapped_column(Integer)
    time_to_ruin_days: Mapped[int | None] = mapped_column(Integer)
    configuration: Mapped[dict] = mapped_column(JsonType, default=dict)
    failure_report: Mapped[dict] = mapped_column(JsonType, default=dict)
    success_report: Mapped[dict] = mapped_column(JsonType, default=dict)
    lessons: Mapped[dict] = mapped_column(JsonType, default=dict)
    ledger_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    reality_check_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    target_capital: Mapped[float | None] = mapped_column(Float)
    active_cycle_id: Mapped[int | None] = mapped_column(Integer, index=True)
    target_cycles_completed: Mapped[int] = mapped_column(Integer, default=0)
    bankrupt_cycles: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    transparency_updated_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class TradingGameTrade(Base):
    __tablename__ = "trading_game_trades"
    __table_args__ = (Index("ix_trading_game_trades_game_created", "game_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    execution_simulation_id: Mapped[int | None] = mapped_column(ForeignKey("execution_simulations.id", ondelete="SET NULL"), index=True)
    mode: Mapped[str] = mapped_column(String(80), default="historical_simulation", index=True)
    capital_cycle_id: Mapped[int | None] = mapped_column(Integer, index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    asset_name: Mapped[str | None] = mapped_column(String(220))
    asset_type: Mapped[str | None] = mapped_column(String(40), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    industry: Mapped[str | None] = mapped_column(String(160))
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    thesis_id: Mapped[int | None] = mapped_column(Integer, index=True)
    sniper_score_at_entry: Mapped[float | None] = mapped_column(Float)
    opportunity_score_at_entry: Mapped[float | None] = mapped_column(Float)
    confidence_at_entry: Mapped[float | None] = mapped_column(Float)
    actionability_state_at_entry: Mapped[str | None] = mapped_column(String(80), index=True)
    market_regime_at_entry: Mapped[str | None] = mapped_column(String(120), index=True)
    sector_regime_at_entry: Mapped[str | None] = mapped_column(String(120))
    benchmark_ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="daily", index=True)
    decision_state: Mapped[str] = mapped_column(String(80), default="wait_for_trigger", index=True)
    entry_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    exit_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    entry_price: Mapped[float | None] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float)
    entry_reason: Mapped[str | None] = mapped_column(Text)
    entry_trigger: Mapped[str | None] = mapped_column(Text)
    confirmation_condition: Mapped[str | None] = mapped_column(Text)
    position_size: Mapped[float] = mapped_column(Float, default=0.0)
    notional_value: Mapped[float | None] = mapped_column(Float)
    risk_amount: Mapped[float] = mapped_column(Float, default=0.0)
    risk_percent: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    initial_target_1: Mapped[float | None] = mapped_column(Float)
    initial_target_2: Mapped[float | None] = mapped_column(Float)
    trailing_stop: Mapped[str | None] = mapped_column(Text)
    max_expected_loss: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    exit_trigger: Mapped[str | None] = mapped_column(Text)
    holding_days: Mapped[int | None] = mapped_column(Integer)
    gross_pnl_eur: Mapped[float | None] = mapped_column(Float)
    net_pnl_eur: Mapped[float | None] = mapped_column(Float)
    pnl_percent: Mapped[float | None] = mapped_column(Float)
    pnl_per_share: Mapped[float | None] = mapped_column(Float)
    realized_r_multiple: Mapped[float | None] = mapped_column(Float, index=True)
    realized_pl: Mapped[float] = mapped_column(Float, default=0.0)
    capital_before: Mapped[float] = mapped_column(Float, default=0.0)
    capital_after: Mapped[float] = mapped_column(Float, default=0.0)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    stop_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    target_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    target_1_hit: Mapped[bool | None] = mapped_column(Boolean, index=True)
    target_2_hit: Mapped[bool | None] = mapped_column(Boolean, index=True)
    invalidation_hit: Mapped[bool | None] = mapped_column(Boolean, index=True)
    missed_entry: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    false_breakout: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    slippage_bps: Mapped[float] = mapped_column(Float, default=8.0)
    spread_bps: Mapped[float] = mapped_column(Float, default=6.0)
    reproducibility_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    benchmark_return_same_period: Mapped[float | None] = mapped_column(Float)
    excess_return_vs_benchmark: Mapped[float | None] = mapped_column(Float)
    trade_quality_score: Mapped[float | None] = mapped_column(Float, index=True)
    data_quality_score: Mapped[float | None] = mapped_column(Float)
    outcome_label: Mapped[str | None] = mapped_column(String(80), index=True)
    lesson_generated: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    game = relationship("TradingGame")
    execution_simulation = relationship("ExecutionSimulation")


class TradingGameEquityCurve(Base):
    __tablename__ = "trading_game_equity_curve"
    __table_args__ = (Index("ix_trading_game_equity_game_date", "game_id", "equity_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    equity_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    equity: Mapped[float] = mapped_column(Float, default=100.0, index=True)
    cash: Mapped[float] = mapped_column(Float, default=100.0)
    exposure: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_equity: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    event_type: Mapped[str | None] = mapped_column(String(100), index=True)
    related_trade_id: Mapped[int | None] = mapped_column(Integer, index=True)
    annotation_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    game = relationship("TradingGame")


class TradingGameFailure(Base):
    __tablename__ = "trading_game_failures"
    __table_args__ = (Index("ix_trading_game_failures_game_created", "game_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="SET NULL"), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    report: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    game = relationship("TradingGame")


class CapitalManagementLesson(Base):
    __tablename__ = "capital_management_lessons"
    __table_args__ = (Index("ix_capital_management_lessons_category_updated", "category", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    lesson: Mapped[str] = mapped_column(Text, default="")
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class TradeEngineAttribution(Base):
    __tablename__ = "trade_engine_attributions"
    __table_args__ = (
        UniqueConstraint("trade_id", "engine_name", name="uq_trade_engine_attribution_trade_engine"),
        Index("ix_trade_engine_attributions_trade_engine", "trade_id", "engine_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trading_game_trades.id", ondelete="CASCADE"), index=True)
    engine_name: Mapped[str] = mapped_column(String(120), index=True)
    vote: Mapped[str] = mapped_column(String(80), default="neutral", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    contribution_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evidence_quality: Mapped[float] = mapped_column(Float, default=0.0)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, index=True)
    reliability_delta: Mapped[float] = mapped_column(Float, default=0.0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    trade = relationship("TradingGameTrade")


class TradeQualityScore(Base):
    __tablename__ = "trade_quality_scores"
    __table_args__ = (
        UniqueConstraint("trade_id", name="uq_trade_quality_scores_trade"),
        Index("ix_trade_quality_scores_final_created", "final_trade_quality_score", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trading_game_trades.id", ondelete="CASCADE"), index=True)
    entry_quality: Mapped[float] = mapped_column(Float, default=0.0)
    exit_quality: Mapped[float] = mapped_column(Float, default=0.0)
    risk_reward_quality: Mapped[float] = mapped_column(Float, default=0.0)
    sizing_quality: Mapped[float] = mapped_column(Float, default=0.0)
    regime_alignment: Mapped[float] = mapped_column(Float, default=0.0)
    reproducibility_quality: Mapped[float] = mapped_column(Float, default=0.0)
    thesis_consistency: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_relative_quality: Mapped[float] = mapped_column(Float, default=0.0)
    rule_compliance: Mapped[float] = mapped_column(Float, default=0.0)
    luck_factor: Mapped[float] = mapped_column(Float, default=0.0)
    final_trade_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    trade = relationship("TradingGameTrade")


class TradeLearningEvidence(Base):
    __tablename__ = "trade_learning_evidence"
    __table_args__ = (Index("ix_trade_learning_evidence_setup_regime", "setup_type", "regime", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trading_game_trades.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    regime: Mapped[str] = mapped_column(String(120), default="unknown", index=True)
    lesson_type: Mapped[str] = mapped_column(String(120), index=True)
    observation: Mapped[str] = mapped_column(Text, default="")
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    supporting_trades_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    contradicted_rules_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    proposed_rule_id: Mapped[int | None] = mapped_column(Integer, index=True)
    affected_module: Mapped[str] = mapped_column(String(120), default="trading_game", index=True)
    action_taken: Mapped[str] = mapped_column(String(160), default="logged_for_learning", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    trade = relationship("TradingGameTrade")
    game = relationship("TradingGame")


class TradingGameRealityCheck(Base):
    __tablename__ = "trading_game_reality_checks"
    __table_args__ = (Index("ix_trading_game_reality_checks_game_eval", "game_id", "evaluated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    trades_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    unique_tickers: Mapped[int] = mapped_column(Integer, default=0)
    unique_sectors: Mapped[int] = mapped_column(Integer, default=0)
    unique_regimes: Mapped[int] = mapped_column(Integer, default=0)
    profit_concentration_top_1: Mapped[float | None] = mapped_column(Float)
    profit_concentration_top_3: Mapped[float | None] = mapped_column(Float)
    sample_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    realism_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    statistical_confidence: Mapped[str] = mapped_column(String(80), default="low", index=True)
    warnings_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")

    game = relationship("TradingGame")


class EquityCurveAnnotation(Base):
    __tablename__ = "equity_curve_annotations"
    __table_args__ = (Index("ix_equity_curve_annotations_game_time", "game_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    equity_curve_id: Mapped[int | None] = mapped_column(ForeignKey("trading_game_equity_curve.id", ondelete="SET NULL"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    label: Mapped[str] = mapped_column(String(180), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    related_trade_id: Mapped[int | None] = mapped_column(ForeignKey("trading_game_trades.id", ondelete="SET NULL"), index=True)
    related_thesis_id: Mapped[int | None] = mapped_column(Integer, index=True)
    pnl_impact: Mapped[float | None] = mapped_column(Float)
    capital_after_event: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    game = relationship("TradingGame")
    equity_curve = relationship("TradingGameEquityCurve")
    trade = relationship("TradingGameTrade")


class TradingCapitalCycle(Base):
    __tablename__ = "trading_capital_cycles"
    __table_args__ = (Index("ix_trading_capital_cycles_game_cycle", "game_id", "cycle_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    cycle_number: Mapped[int] = mapped_column(Integer, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    start_capital: Mapped[float] = mapped_column(Float, default=100.0)
    target_capital: Mapped[float] = mapped_column(Float, default=10000.0, index=True)
    final_capital: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(60), default="active", index=True)
    reached_target: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    went_to_zero: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    return_percent: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    trades_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    missed_entries: Mapped[int] = mapped_column(Integer, default=0)
    target_hits: Mapped[int] = mapped_column(Integer, default=0)
    stop_hits: Mapped[int] = mapped_column(Integer, default=0)
    no_trade_correct: Mapped[int] = mapped_column(Integer, default=0)
    no_trade_missed_opportunity: Mapped[int] = mapped_column(Integer, default=0)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    expectancy_r: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    excess_return_vs_benchmark: Mapped[float | None] = mapped_column(Float)
    best_trade_id: Mapped[int | None] = mapped_column(Integer, index=True)
    worst_trade_id: Mapped[int | None] = mapped_column(Integer, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    success_reason: Mapped[str | None] = mapped_column(Text)
    lessons_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    game = relationship("TradingGame")


class TradingIntelligenceMetric(Base):
    __tablename__ = "trading_intelligence_metrics"
    __table_args__ = (Index("ix_trading_intel_metrics_scope_window", "scope", "scope_id", "window_type", "window_size"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    scope: Mapped[str] = mapped_column(String(80), default="game", index=True)
    scope_id: Mapped[str | None] = mapped_column(String(120), index=True)
    window_type: Mapped[str] = mapped_column(String(80), default="all", index=True)
    window_size: Mapped[int | None] = mapped_column(Integer, index=True)
    trades_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    win_rate: Mapped[float | None] = mapped_column(Float)
    loss_rate: Mapped[float | None] = mapped_column(Float)
    missed_entry_rate: Mapped[float | None] = mapped_column(Float)
    target_hit_rate: Mapped[float | None] = mapped_column(Float)
    stop_hit_rate: Mapped[float | None] = mapped_column(Float)
    no_trade_correct_rate: Mapped[float | None] = mapped_column(Float)
    no_trade_missed_opportunity_rate: Mapped[float | None] = mapped_column(Float)
    expectancy_r: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    average_r: Mapped[float | None] = mapped_column(Float)
    median_r: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    benchmark_excess: Mapped[float | None] = mapped_column(Float)
    entry_timing_score: Mapped[float | None] = mapped_column(Float)
    exit_timing_score: Mapped[float | None] = mapped_column(Float)
    sizing_quality_score: Mapped[float | None] = mapped_column(Float)
    risk_reward_quality_score: Mapped[float | None] = mapped_column(Float)
    reproducibility_score: Mapped[float | None] = mapped_column(Float)
    trade_quality_score: Mapped[float | None] = mapped_column(Float)
    intelligence_growth_score: Mapped[float | None] = mapped_column(Float, index=True)
    notes_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class IntradayPaperRun(Base):
    __tablename__ = "intraday_paper_runs"
    __table_args__ = (
        Index("ix_intraday_paper_runs_status_started", "status", "started_at"),
        Index("ix_intraday_paper_runs_trigger_started", "trigger", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_uid: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    trigger: Mapped[str] = mapped_column(String(40), default="scheduled", index=True)
    status: Mapped[str] = mapped_column(String(40), default="RUNNING", index=True)
    markets_checked: Mapped[int] = mapped_column(Integer, default=0)
    assets_checked: Mapped[int] = mapped_column(Integer, default=0)
    candidates_found: Mapped[int] = mapped_column(Integer, default=0)
    candidates_approved: Mapped[int] = mapped_column(Integer, default=0)
    trades_opened: Mapped[int] = mapped_column(Integer, default=0)
    trades_updated: Mapped[int] = mapped_column(Integer, default=0)
    trades_closed: Mapped[int] = mapped_column(Integer, default=0)
    rejected_due_to_costs: Mapped[int] = mapped_column(Integer, default=0)
    rejected_due_to_risk: Mapped[int] = mapped_column(Integer, default=0)
    rejected_due_to_concentration: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    data_blockers: Mapped[list] = mapped_column(JsonType, default=list)
    summary_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class IntradayNoTradeDecision(Base):
    __tablename__ = "intraday_no_trade_decisions"
    __table_args__ = (
        UniqueConstraint("decision_uid", name="uq_intraday_no_trade_decision_uid"),
        Index("ix_intraday_no_trade_status_due", "status", "evaluation_due_at"),
        Index("ix_intraday_no_trade_ticker_time", "ticker", "decision_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_uid: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("intraday_paper_runs.id", ondelete="SET NULL"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(48), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    market: Mapped[str] = mapped_column(String(60), index=True)
    desk: Mapped[str | None] = mapped_column(String(100), index=True)
    benchmark_ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    reason_code: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    evaluation_due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    theoretical_price: Mapped[float] = mapped_column(Float)
    expected_move_bps: Mapped[float] = mapped_column(Float, default=0.0)
    expected_cost_bps: Mapped[float] = mapped_column(Float, default=0.0)
    future_return: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    capital_preserved: Mapped[float] = mapped_column(Float, default=0.0)
    opportunity_cost: Mapped[float] = mapped_column(Float, default=0.0)
    outcome_label: Mapped[str | None] = mapped_column(String(100), index=True)
    decision_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    evaluation_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LiveForwardPaperGame(Base):
    __tablename__ = "live_forward_paper_games"
    __table_args__ = (Index("ix_live_forward_paper_games_status_started", "status", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(60), default="active", index=True)
    starting_capital: Mapped[float] = mapped_column(Float, default=100.0)
    current_capital: Mapped[float] = mapped_column(Float, default=100.0, index=True)
    target_capital: Mapped[float] = mapped_column(Float, default=10000.0)
    cash: Mapped[float] = mapped_column(Float, default=100.0)
    exposure: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pl: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_ticker: Mapped[str] = mapped_column(String(32), default="SPY", index=True)
    open_positions: Mapped[int] = mapped_column(Integer, default=0, index=True)
    cycle_number: Mapped[int] = mapped_column(Integer, default=1, index=True)
    configuration: Mapped[dict] = mapped_column(JsonType, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class LiveForwardPaperPosition(Base):
    __tablename__ = "live_forward_paper_positions"
    __table_args__ = (Index("ix_live_forward_positions_game_status", "game_id", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("live_forward_paper_games.id", ondelete="CASCADE"), index=True)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trading_game_trades.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(60), default="open", index=True)
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    entry_price: Mapped[float | None] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float)
    position_size: Mapped[float] = mapped_column(Float, default=0.0)
    risk_amount: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    target_1: Mapped[float | None] = mapped_column(Float)
    target_2: Mapped[float | None] = mapped_column(Float)
    thesis_snapshot: Mapped[dict] = mapped_column(JsonType, default=dict)
    data_snapshot: Mapped[dict] = mapped_column(JsonType, default=dict)
    no_future_data_policy: Mapped[str] = mapped_column(Text, default="Decision timestamp is frozen; outcomes are evaluated only on later refreshes.")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    game = relationship("LiveForwardPaperGame")
    trade = relationship("TradingGameTrade")


class LiveForwardPaperTrade(Base):
    __tablename__ = "live_forward_paper_trades"
    __table_args__ = (
        UniqueConstraint("duplicate_key", name="uq_live_forward_paper_trade_duplicate_key"),
        Index("ix_live_forward_trades_status_created", "status", "created_at"),
        Index("ix_live_forward_trades_ticker_decision", "ticker", "decision_date"),
        Index("ix_live_forward_trades_game_status", "game_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_uid: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("live_forward_paper_games.id", ondelete="CASCADE"), index=True)
    ledger_trade_id: Mapped[int | None] = mapped_column(ForeignKey("trading_game_trades.id", ondelete="SET NULL"), index=True)
    feedback_loop_audit_id: Mapped[int | None] = mapped_column(ForeignKey("feedback_loop_audits.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    asset_name: Mapped[str | None] = mapped_column(String(220))
    asset_type: Mapped[str | None] = mapped_column(String(40), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    industry: Mapped[str | None] = mapped_column(String(160))
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    side: Mapped[str | None] = mapped_column(String(8), index=True)
    accounting_status: Mapped[str] = mapped_column(
        String(64),
        default="VALID",
        server_default="PENDING_SIDE_VERIFICATION",
        index=True,
    )
    accounting_version: Mapped[str | None] = mapped_column(String(64), index=True)
    accounting_recomputed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(60), default="CANDIDATE", index=True)
    close_reason: Mapped[str | None] = mapped_column(String(80), index=True)
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    decision_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    model_version_used: Mapped[str] = mapped_column(String(100), default="base-static", index=True)
    weights_used: Mapped[dict] = mapped_column(JsonType, default=dict)
    confidence_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    learning_memory_used: Mapped[dict] = mapped_column(JsonType, default=dict)
    strategy_memory_used: Mapped[dict] = mapped_column(JsonType, default=dict)
    research_priority_used: Mapped[dict] = mapped_column(JsonType, default=dict)
    frozen_decision_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    trading_mode: Mapped[str | None] = mapped_column(String(60), index=True)
    evidence_type: Mapped[str | None] = mapped_column(String(60), index=True)
    promoted_validation_id: Mapped[int | None] = mapped_column(ForeignKey("replay_strategy_validations.id", ondelete="SET NULL"), index=True)
    intraday_run_id: Mapped[int | None] = mapped_column(ForeignKey("intraday_paper_runs.id", ondelete="SET NULL"), index=True)
    market: Mapped[str | None] = mapped_column(String(60), index=True)
    desk: Mapped[str | None] = mapped_column(String(100), index=True)
    session_name: Mapped[str | None] = mapped_column(String(60), index=True)
    timeframe_stack: Mapped[list] = mapped_column(JsonType, default=list)
    data_timestamps: Mapped[dict] = mapped_column(JsonType, default=dict)
    execution_costs: Mapped[dict] = mapped_column(JsonType, default=dict)
    spread_cost: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    commission_cost: Mapped[float] = mapped_column(Float, default=0.0)
    costs_paid: Mapped[float] = mapped_column(Float, default=0.0)
    net_expectancy_bps: Mapped[float | None] = mapped_column(Float)
    sizing_reason: Mapped[str | None] = mapped_column(Text)
    trailing_stop: Mapped[float | None] = mapped_column(Float)
    last_managed_bar_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    holding_minutes: Mapped[float | None] = mapped_column(Float)
    intraday_metadata: Mapped[dict] = mapped_column(JsonType, default=dict)
    actionability_state: Mapped[str | None] = mapped_column(String(80), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    sniper_score: Mapped[float | None] = mapped_column(Float, index=True)
    benchmark_ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    entry_trigger: Mapped[str | None] = mapped_column(Text)
    confirmation_condition: Mapped[str | None] = mapped_column(Text)
    entry_price: Mapped[float | None] = mapped_column(Float)
    entry_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    target_1: Mapped[float | None] = mapped_column(Float)
    target_2: Mapped[float | None] = mapped_column(Float)
    position_size: Mapped[float] = mapped_column(Float, default=0.0)
    notional_value: Mapped[float | None] = mapped_column(Float)
    risk_amount: Mapped[float] = mapped_column(Float, default=0.0)
    risk_percent: Mapped[float] = mapped_column(Float, default=0.0)
    expected_risk: Mapped[float | None] = mapped_column(Float)
    expected_reward: Mapped[float | None] = mapped_column(Float)
    expected_r_multiple: Mapped[float | None] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    exit_price: Mapped[float | None] = mapped_column(Float)
    exit_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    gross_pnl_eur: Mapped[float | None] = mapped_column(Float)
    net_pnl_eur: Mapped[float | None] = mapped_column(Float)
    pnl_percent: Mapped[float | None] = mapped_column(Float)
    pnl_per_share: Mapped[float | None] = mapped_column(Float)
    r_multiple: Mapped[float | None] = mapped_column(Float, index=True)
    max_favorable_excursion: Mapped[float] = mapped_column(Float, default=0.0)
    max_adverse_excursion: Mapped[float] = mapped_column(Float, default=0.0)
    target_1_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    target_2_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    stop_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    invalidation_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    benchmark_return_same_period: Mapped[float | None] = mapped_column(Float)
    excess_return_vs_benchmark: Mapped[float | None] = mapped_column(Float)
    outcome_label: Mapped[str | None] = mapped_column(String(80), index=True)
    lesson_learned: Mapped[str | None] = mapped_column(Text)
    duplicate_key: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    game = relationship("LiveForwardPaperGame")
    ledger_trade = relationship("TradingGameTrade")
    feedback_loop_audit = relationship("FeedbackLoopAudit")
    promoted_validation = relationship("ReplayStrategyValidation")
    intraday_run = relationship("IntradayPaperRun")

    @property
    def decision_payload_frozen(self) -> dict:
        return self.frozen_decision_payload

    @decision_payload_frozen.setter
    def decision_payload_frozen(self, value: dict) -> None:
        self.frozen_decision_payload = value

    @property
    def open_price(self) -> float | None:
        return self.entry_price

    @open_price.setter
    def open_price(self, value: float | None) -> None:
        self.entry_price = value

    @property
    def open_timestamp(self) -> datetime | None:
        return self.opened_at

    @open_timestamp.setter
    def open_timestamp(self, value: datetime | None) -> None:
        self.opened_at = value

    @property
    def close_price(self) -> float | None:
        return self.exit_price

    @close_price.setter
    def close_price(self, value: float | None) -> None:
        self.exit_price = value

    @property
    def close_timestamp(self) -> datetime | None:
        return self.closed_at

    @close_timestamp.setter
    def close_timestamp(self, value: datetime | None) -> None:
        self.closed_at = value

    @property
    def pnl(self) -> float | None:
        return self.net_pnl_eur

    @pnl.setter
    def pnl(self, value: float | None) -> None:
        self.net_pnl_eur = value

    @property
    def benchmark_return(self) -> float | None:
        return self.benchmark_return_same_period

    @benchmark_return.setter
    def benchmark_return(self, value: float | None) -> None:
        self.benchmark_return_same_period = value

    @property
    def benchmark_excess(self) -> float | None:
        return self.excess_return_vs_benchmark

    @benchmark_excess.setter
    def benchmark_excess(self, value: float | None) -> None:
        self.excess_return_vs_benchmark = value

    @property
    def outcome(self) -> str | None:
        return self.outcome_label

    @outcome.setter
    def outcome(self, value: str | None) -> None:
        self.outcome_label = value

    @property
    def entry_type(self) -> str | None:
        payload = self.frozen_decision_payload or {}
        plan = payload.get("trade_plan") or {}
        return plan.get("entry_type") or self.actionability_state or "conditional"

    @property
    def reward_amount(self) -> float | None:
        return self.expected_reward

    @reward_amount.setter
    def reward_amount(self, value: float | None) -> None:
        self.expected_reward = value

    @property
    def risk_reward_ratio(self) -> float | None:
        return self.expected_r_multiple

    @risk_reward_ratio.setter
    def risk_reward_ratio(self, value: float | None) -> None:
        self.expected_r_multiple = value


class LiveForwardPaperTradeEvent(Base):
    __tablename__ = "live_forward_paper_trade_events"
    __table_args__ = (
        Index("ix_live_forward_events_trade_time", "paper_trade_id", "event_timestamp"),
        Index("ix_live_forward_events_type_time", "event_type", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_trade_id: Mapped[int] = mapped_column(ForeignKey("live_forward_paper_trades.id", ondelete="CASCADE"), index=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    price_used: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    paper_trade = relationship("LiveForwardPaperTrade")

    @property
    def trade_id(self) -> int:
        return self.paper_trade_id

    @trade_id.setter
    def trade_id(self, value: int) -> None:
        self.paper_trade_id = value


PaperForwardTrade = LiveForwardPaperTrade
PaperForwardTradeEvent = LiveForwardPaperTradeEvent


class HistoricalLiveComparison(Base):
    __tablename__ = "historical_live_comparisons"
    __table_args__ = (Index("ix_historical_live_comparisons_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    historical_sample_size: Mapped[int] = mapped_column(Integer, default=0)
    live_sample_size: Mapped[int] = mapped_column(Integer, default=0)
    historical_win_rate: Mapped[float | None] = mapped_column(Float)
    live_win_rate: Mapped[float | None] = mapped_column(Float)
    historical_expectancy: Mapped[float | None] = mapped_column(Float)
    live_expectancy: Mapped[float | None] = mapped_column(Float)
    historical_target_hit_rate: Mapped[float | None] = mapped_column(Float)
    live_target_hit_rate: Mapped[float | None] = mapped_column(Float)
    historical_missed_entry_rate: Mapped[float | None] = mapped_column(Float)
    live_missed_entry_rate: Mapped[float | None] = mapped_column(Float)
    historical_max_drawdown: Mapped[float | None] = mapped_column(Float)
    live_max_drawdown: Mapped[float | None] = mapped_column(Float)
    historical_benchmark_excess: Mapped[float | None] = mapped_column(Float)
    live_benchmark_excess: Mapped[float | None] = mapped_column(Float)
    historical_profit_factor: Mapped[float | None] = mapped_column(Float)
    live_profit_factor: Mapped[float | None] = mapped_column(Float)
    sample_warning: Mapped[str | None] = mapped_column(Text)
    comparison_payload: Mapped[dict] = mapped_column(JsonType, default=dict)


class BlumTradingPowerScore(Base):
    __tablename__ = "blum_trading_power_scores"
    __table_args__ = (
        Index("ix_blum_trading_power_scores_mode_created", "mode", "calculated_at"),
        Index("ix_blum_trading_power_scores_scope_score", "scope", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    mode: Mapped[str] = mapped_column(String(80), default="historical_plus_live", index=True)
    scope: Mapped[str] = mapped_column(String(120), default="global", index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    classification: Mapped[str] = mapped_column(String(120), default="Not usable", index=True)
    benchmark_relative_score: Mapped[float] = mapped_column(Float, default=0.0)
    expectancy_score: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown_control_score: Mapped[float] = mapped_column(Float, default=0.0)
    win_loss_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    missed_entry_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    risk_management_score: Mapped[float] = mapped_column(Float, default=0.0)
    capital_cycle_score: Mapped[float] = mapped_column(Float, default=0.0)
    live_forward_validation_score: Mapped[float] = mapped_column(Float, default=0.0)
    regime_robustness_score: Mapped[float] = mapped_column(Float, default=0.0)
    setup_diversity_score: Mapped[float] = mapped_column(Float, default=0.0)
    statistical_confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    reproducibility_score: Mapped[float] = mapped_column(Float, default=0.0)
    decision_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    learning_velocity_score: Mapped[float] = mapped_column(Float, default=0.0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class LearningBenchmarkComparison(Base):
    __tablename__ = "learning_benchmark_comparisons"
    __table_args__ = (
        Index("ix_learning_benchmark_mode_name_created", "mode", "benchmark_name", "calculated_at"),
        Index("ix_learning_benchmark_result", "result_label", "statistical_confidence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    mode: Mapped[str] = mapped_column(String(80), default="historical_simulation", index=True)
    benchmark_name: Mapped[str] = mapped_column(String(120), index=True)
    benchmark_type: Mapped[str] = mapped_column(String(80), default="market", index=True)
    period_start: Mapped[datetime | None] = mapped_column(Date, index=True)
    period_end: Mapped[datetime | None] = mapped_column(Date, index=True)
    blum_return: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    excess_return: Mapped[float | None] = mapped_column(Float, index=True)
    blum_max_drawdown: Mapped[float | None] = mapped_column(Float)
    benchmark_max_drawdown: Mapped[float | None] = mapped_column(Float)
    blum_volatility: Mapped[float | None] = mapped_column(Float)
    benchmark_volatility: Mapped[float | None] = mapped_column(Float)
    sharpe_proxy: Mapped[float | None] = mapped_column(Float)
    sortino_proxy: Mapped[float | None] = mapped_column(Float)
    calmar_proxy: Mapped[float | None] = mapped_column(Float)
    information_ratio_proxy: Mapped[float | None] = mapped_column(Float)
    hit_rate_vs_benchmark: Mapped[float | None] = mapped_column(Float)
    risk_adjusted_advantage: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    statistical_confidence: Mapped[str] = mapped_column(String(80), default="very low evidence", index=True)
    result_label: Mapped[str] = mapped_column(String(80), default="insufficient_sample", index=True)
    explanation: Mapped[str] = mapped_column(Text, default="")


class LearningProgressSnapshot(Base):
    __tablename__ = "learning_progress_snapshots"
    __table_args__ = (
        Index("ix_learning_progress_window_created", "window_type", "window_size", "calculated_at"),
        Index("ix_learning_progress_trend", "trend_label", "intelligence_growth_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    window_type: Mapped[str] = mapped_column(String(80), default="rolling", index=True)
    window_size: Mapped[int | None] = mapped_column(Integer, index=True)
    trades_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    win_rate: Mapped[float | None] = mapped_column(Float)
    missed_entry_rate: Mapped[float | None] = mapped_column(Float)
    loss_rate: Mapped[float | None] = mapped_column(Float)
    target_hit_rate: Mapped[float | None] = mapped_column(Float)
    stop_hit_rate: Mapped[float | None] = mapped_column(Float)
    expectancy_r: Mapped[float | None] = mapped_column(Float)
    benchmark_excess: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    trade_quality_avg: Mapped[float | None] = mapped_column(Float)
    confidence_calibration_error: Mapped[float | None] = mapped_column(Float)
    repeated_mistake_rate: Mapped[float | None] = mapped_column(Float)
    intelligence_growth_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    trend_label: Mapped[str] = mapped_column(String(80), default="inconclusive", index=True)
    explanation: Mapped[str] = mapped_column(Text, default="")


class LearningStrengthWeaknessMap(Base):
    __tablename__ = "learning_strength_weakness_map"
    __table_args__ = (
        Index("ix_learning_strength_dimension_entity", "dimension", "entity"),
        Index("ix_learning_strength_priority", "priority", "weakness_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    dimension: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(180), index=True)
    strength_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    weakness_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    main_problem: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(80), default="open", index=True)


class SelfImprovementAction(Base):
    __tablename__ = "self_improvement_actions"
    __table_args__ = (
        Index("ix_self_improvement_status_priority", "status", "priority"),
        Index("ix_self_improvement_source", "source_dimension", "affected_module"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    source_metric: Mapped[str] = mapped_column(String(120), index=True)
    source_dimension: Mapped[str] = mapped_column(String(120), index=True)
    detected_problem: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    affected_module: Mapped[str] = mapped_column(String(120), index=True)
    priority: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    expected_impact: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(80), default="proposed", index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    before_metric: Mapped[float | None] = mapped_column(Float)
    after_metric: Mapped[float | None] = mapped_column(Float)
    improvement_observed: Mapped[bool | None] = mapped_column(Boolean, index=True)
    notes_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class DecisionUniverseSnapshot(Base):
    __tablename__ = "decision_universe_snapshots"
    __table_args__ = (
        Index("ix_decision_universe_selected_created", "selected_asset", "timestamp"),
        Index("ix_decision_universe_regime_created", "market_regime", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    market_regime: Mapped[str | None] = mapped_column(String(120), index=True)
    volatility_regime: Mapped[str | None] = mapped_column(String(120), index=True)
    selected_asset: Mapped[str] = mapped_column(String(32), index=True)
    selected_rank: Mapped[int | None] = mapped_column(Integer)
    selected_score: Mapped[float | None] = mapped_column(Float)
    total_candidates: Mapped[int] = mapped_column(Integer, default=0)
    candidates_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    benchmark_snapshot: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class OpportunityRecallMetric(Base):
    __tablename__ = "opportunity_recall_metrics"
    __table_args__ = (Index("ix_opportunity_recall_scope", "sector", "setup", "regime", "timeframe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    setup: Mapped[str | None] = mapped_column(String(120), index=True)
    regime: Mapped[str | None] = mapped_column(String(120), index=True)
    timeframe: Mapped[str | None] = mapped_column(String(80), index=True)
    captured_outperformers: Mapped[int] = mapped_column(Integer, default=0)
    total_outperformers: Mapped[int] = mapped_column(Integer, default=0)
    opportunity_recall: Mapped[float | None] = mapped_column(Float, index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class OpportunityPrecisionMetric(Base):
    __tablename__ = "opportunity_precision_metrics"
    __table_args__ = (Index("ix_opportunity_precision_scope", "sector", "setup", "regime", "timeframe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    setup: Mapped[str | None] = mapped_column(String(120), index=True)
    regime: Mapped[str | None] = mapped_column(String(120), index=True)
    timeframe: Mapped[str | None] = mapped_column(String(80), index=True)
    successful_opportunities: Mapped[int] = mapped_column(Integer, default=0)
    selected_opportunities: Mapped[int] = mapped_column(Integer, default=0)
    opportunity_precision: Mapped[float | None] = mapped_column(Float, index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class AlphaCaptureMetric(Base):
    __tablename__ = "alpha_capture_metrics"
    __table_args__ = (Index("ix_alpha_capture_scope", "ticker", "sector", "regime", "timeframe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    regime: Mapped[str | None] = mapped_column(String(120), index=True)
    timeframe: Mapped[str | None] = mapped_column(String(80), index=True)
    available_alpha: Mapped[float | None] = mapped_column(Float)
    captured_alpha: Mapped[float | None] = mapped_column(Float)
    alpha_capture_rate: Mapped[float | None] = mapped_column(Float, index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class RankingAccuracyMetric(Base):
    __tablename__ = "ranking_accuracy_metrics"
    __table_args__ = (Index("ix_ranking_accuracy_scope", "sector", "setup", "regime", "timeframe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    setup: Mapped[str | None] = mapped_column(String(120), index=True)
    regime: Mapped[str | None] = mapped_column(String(120), index=True)
    timeframe: Mapped[str | None] = mapped_column(String(80), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    top1_accuracy: Mapped[float | None] = mapped_column(Float)
    top3_accuracy: Mapped[float | None] = mapped_column(Float)
    top5_accuracy: Mapped[float | None] = mapped_column(Float)
    ranking_correlation: Mapped[float | None] = mapped_column(Float)
    ranking_decay: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class DecisionSuperiorityScore(Base):
    __tablename__ = "decision_superiority_scores"
    __table_args__ = (
        Index("ix_decision_superiority_mode_created", "mode", "calculated_at"),
        Index("ix_decision_superiority_score", "score", "classification"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    mode: Mapped[str] = mapped_column(String(80), default="historical_plus_live", index=True)
    scope: Mapped[str] = mapped_column(String(120), default="global", index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    classification: Mapped[str] = mapped_column(String(120), default="Weak", index=True)
    opportunity_recall: Mapped[float | None] = mapped_column(Float)
    opportunity_precision: Mapped[float | None] = mapped_column(Float)
    alpha_capture: Mapped[float | None] = mapped_column(Float)
    ranking_accuracy: Mapped[float | None] = mapped_column(Float)
    benchmark_excess: Mapped[float | None] = mapped_column(Float)
    live_validation: Mapped[float | None] = mapped_column(Float)
    regime_consistency: Mapped[float | None] = mapped_column(Float)
    reproducibility: Mapped[float | None] = mapped_column(Float)
    drawdown_control: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class BusinessQualityProfile(Base):
    __tablename__ = "business_quality_profiles"
    __table_args__ = (Index("ix_business_quality_profiles_ticker_created", "ticker", "calculated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    growth_quality: Mapped[float | None] = mapped_column(Float)
    profitability_quality: Mapped[float | None] = mapped_column(Float)
    cash_flow_quality: Mapped[float | None] = mapped_column(Float)
    balance_sheet_quality: Mapped[float | None] = mapped_column(Float)
    capital_allocation_quality: Mapped[float | None] = mapped_column(Float)
    moat_quality: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    asset = relationship("Asset")


class ManagementQualityProfile(Base):
    __tablename__ = "management_quality_profiles"
    __table_args__ = (Index("ix_management_quality_profiles_ticker_created", "ticker", "calculated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    insider_alignment: Mapped[float | None] = mapped_column(Float)
    execution_consistency: Mapped[float | None] = mapped_column(Float)
    earnings_delivery: Mapped[float | None] = mapped_column(Float)
    management_quality: Mapped[float | None] = mapped_column(Float, index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    asset = relationship("Asset")


class FundamentalAlphaPattern(Base):
    __tablename__ = "fundamental_alpha_patterns"
    __table_args__ = (Index("ix_fundamental_alpha_pattern_scope", "pattern_name", "sector", "timeframe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    pattern_name: Mapped[str] = mapped_column(String(160), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    timeframe: Mapped[str | None] = mapped_column(String(80), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    average_forward_return: Mapped[float | None] = mapped_column(Float)
    hit_rate: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class BusinessQualityScore(Base):
    __tablename__ = "business_quality_scores"
    __table_args__ = (
        Index("ix_business_quality_scores_ticker_created", "ticker", "calculated_at"),
        Index("ix_business_quality_scores_score", "business_quality_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    business_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    growth_quality: Mapped[float | None] = mapped_column(Float)
    profitability_quality: Mapped[float | None] = mapped_column(Float)
    cash_flow_quality: Mapped[float | None] = mapped_column(Float)
    balance_sheet_quality: Mapped[float | None] = mapped_column(Float)
    capital_allocation_quality: Mapped[float | None] = mapped_column(Float)
    moat_quality: Mapped[float | None] = mapped_column(Float)
    management_quality: Mapped[float | None] = mapped_column(Float)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    asset = relationship("Asset")


class PortfolioContribution(Base):
    __tablename__ = "portfolio_contributions"
    __table_args__ = (Index("ix_portfolio_contributions_scope", "game_id", "ticker", "calculated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    return_contribution: Mapped[float | None] = mapped_column(Float)
    risk_contribution: Mapped[float | None] = mapped_column(Float)
    drawdown_contribution: Mapped[float | None] = mapped_column(Float)
    alpha_contribution: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    game = relationship("TradingGame")


class PortfolioCorrelation(Base):
    __tablename__ = "portfolio_correlations"
    __table_args__ = (
        UniqueConstraint("scope", "asset_a", "asset_b", name="uq_portfolio_correlation_pair"),
        Index("ix_portfolio_correlations_scope", "scope", "correlation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    scope: Mapped[str] = mapped_column(String(120), default="active_game")
    asset_a: Mapped[str] = mapped_column(String(32), index=True)
    asset_b: Mapped[str] = mapped_column(String(32), index=True)
    correlation: Mapped[float | None] = mapped_column(Float, index=True)
    correlation_type: Mapped[str] = mapped_column(String(80), default="price_return", index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class PortfolioAlphaScore(Base):
    __tablename__ = "portfolio_alpha_scores"
    __table_args__ = (Index("ix_portfolio_alpha_scores_ticker_created", "ticker", "calculated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    portfolio_alpha_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    marginal_return_score: Mapped[float | None] = mapped_column(Float)
    marginal_risk_score: Mapped[float | None] = mapped_column(Float)
    diversification_score: Mapped[float | None] = mapped_column(Float)
    benchmark_excess_score: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    game = relationship("TradingGame")


class PositionSizingOutcome(Base):
    __tablename__ = "position_sizing_outcomes"
    __table_args__ = (Index("ix_position_sizing_outcomes_logic", "sizing_logic", "timeframe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    sizing_logic: Mapped[str] = mapped_column(String(120), index=True)
    timeframe: Mapped[str | None] = mapped_column(String(80), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    average_r: Mapped[float | None] = mapped_column(Float)
    drawdown_impact: Mapped[float | None] = mapped_column(Float)
    capital_efficiency: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class DashboardSnapshot(Base):
    __tablename__ = "dashboard_snapshots"
    __table_args__ = (
        Index("ix_dashboard_snapshots_type_created", "snapshot_type", "created_at"),
        Index("ix_dashboard_snapshots_type_expires", "snapshot_type", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_type: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    source_modules_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    missing_sections_json: Mapped[list] = mapped_column(JsonType, default=list)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    computation_duration_ms: Mapped[float | None] = mapped_column(Float)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)


class TradingGameLedgerSnapshot(Base):
    __tablename__ = "trading_game_ledger_snapshots"
    __table_args__ = (
        Index("ix_trading_game_ledger_snapshots_game_created", "game_id", "created_at"),
        Index("ix_trading_game_ledger_snapshots_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    limit: Mapped[int] = mapped_column(Integer, default=50)
    total_trades: Mapped[int] = mapped_column(Integer, default=0, index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    summary_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    trace_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    payload_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    game = relationship("TradingGame")


class EquityCurveSnapshot(Base):
    __tablename__ = "equity_curve_snapshots"
    __table_args__ = (
        Index("ix_equity_curve_snapshots_game_created", "game_id", "created_at"),
        Index("ix_equity_curve_snapshots_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    limit: Mapped[int] = mapped_column(Integer, default=500)
    point_count: Mapped[int] = mapped_column(Integer, default=0)
    annotation_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    summary_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    trace_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    payload_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    game = relationship("TradingGame")


class BrainRuntimeEvent(Base):
    __tablename__ = "brain_runtime_events"
    __table_args__ = (
        Index("ix_brain_runtime_events_module_created", "source_module", "created_at"),
        Index("ix_brain_runtime_events_type_created", "event_type", "created_at"),
        Index("ix_brain_runtime_events_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    source_module: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(80), default="ok", index=True)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    error_message: Mapped[str] = mapped_column(Text, default="")


class BackgroundJobState(Base):
    __tablename__ = "background_job_state"
    __table_args__ = (
        Index("ix_background_job_state_job_stage", "job_name", "stage_name"),
        Index("ix_background_job_state_status_next", "status", "next_run_after"),
        Index("ix_background_job_state_enabled", "enabled", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(160), index=True)
    stage_name: Mapped[str] = mapped_column(String(160), default="default", index=True)
    status: Mapped[str] = mapped_column(String(80), default="idle", index=True)
    cursor_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    max_items: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    next_run_after: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PortfolioQualityScore(Base):
    __tablename__ = "portfolio_quality_scores"
    __table_args__ = (
        Index("ix_portfolio_quality_game_created", "game_id", "calculated_at"),
        Index("ix_portfolio_quality_score", "portfolio_quality_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    portfolio_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    diversification: Mapped[float | None] = mapped_column(Float)
    concentration_risk: Mapped[float | None] = mapped_column(Float)
    drawdown_control: Mapped[float | None] = mapped_column(Float)
    alpha_generation: Mapped[float | None] = mapped_column(Float)
    benchmark_excess: Mapped[float | None] = mapped_column(Float)
    capital_efficiency: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    game = relationship("TradingGame")


class CapitalAllocationSnapshot(Base):
    __tablename__ = "capital_allocation_snapshots"
    __table_args__ = (
        Index("ix_capital_allocation_snapshots_game_created", "game_id", "calculated_at"),
        Index("ix_capital_allocation_snapshots_quality", "allocation_quality_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(80), default="historical_plus_live", index=True)
    total_capital: Mapped[float | None] = mapped_column(Float)
    cash_reserve_percent: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    deployable_percent: Mapped[float] = mapped_column(Float, default=0.0)
    allocation_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    expected_risk_adjusted_alpha: Mapped[float | None] = mapped_column(Float)
    benchmark_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    allocation_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")

    game = relationship("TradingGame")


class BenchmarkMethodologyValidation(Base):
    __tablename__ = "benchmark_methodology_validations"
    __table_args__ = (
        Index("ix_benchmark_methodology_benchmark_created", "benchmark_name", "created_at"),
        Index("ix_benchmark_methodology_valid_conf", "methodology_valid", "confidence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benchmark_comparison_id: Mapped[int | None] = mapped_column(ForeignKey("learning_benchmark_comparisons.id", ondelete="SET NULL"), index=True)
    benchmark_name: Mapped[str] = mapped_column(String(120), index=True)
    mode: Mapped[str] = mapped_column(String(80), default="historical_simulation", index=True)
    period_start: Mapped[datetime | None] = mapped_column(Date, index=True)
    period_end: Mapped[datetime | None] = mapped_column(Date, index=True)
    methodology_valid: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    corrected_excess_return: Mapped[float | None] = mapped_column(Float)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    validation_checks_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    benchmark_comparison = relationship("LearningBenchmarkComparison")


class AlphaLossAttribution(Base):
    __tablename__ = "alpha_loss_attributions"
    __table_args__ = (
        Index("ix_alpha_loss_attr_benchmark_category", "benchmark_name", "category", "created_at"),
        Index("ix_alpha_loss_attr_contribution", "contribution_value", "confidence"),
        Index("ix_alpha_loss_attr_scope", "ticker", "setup_type", "sector"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    methodology_validation_id: Mapped[int | None] = mapped_column(ForeignKey("benchmark_methodology_validations.id", ondelete="SET NULL"), index=True)
    benchmark_name: Mapped[str] = mapped_column(String(120), index=True)
    mode: Mapped[str] = mapped_column(String(80), default="historical_simulation", index=True)
    period_start: Mapped[datetime | None] = mapped_column(Date, index=True)
    period_end: Mapped[datetime | None] = mapped_column(Date, index=True)
    total_alpha_loss: Mapped[float] = mapped_column(Float, default=0.0)
    category: Mapped[str] = mapped_column(String(120), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    setup_type: Mapped[str | None] = mapped_column(String(120), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    engine_name: Mapped[str | None] = mapped_column(String(120), index=True)
    capital_allocation_bucket: Mapped[str | None] = mapped_column(String(120), index=True)
    contribution_value: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    contribution_percent: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    methodology_validation = relationship("BenchmarkMethodologyValidation")


class MissedWinner(Base):
    __tablename__ = "missed_winners"
    __table_args__ = (
        Index("ix_missed_winners_ticker_date", "ticker", "decision_date"),
        Index("ix_missed_winners_benchmark_created", "benchmark_name", "created_at"),
        Index("ix_missed_winners_return", "benchmark_relative_return", "future_return"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    decision_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    benchmark_name: Mapped[str] = mapped_column(String(120), default="SPY", index=True)
    future_return: Mapped[float | None] = mapped_column(Float, index=True)
    benchmark_relative_return: Mapped[float | None] = mapped_column(Float, index=True)
    blum_rank_at_decision: Mapped[int | None] = mapped_column(Integer, index=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    confidence_at_decision: Mapped[float | None] = mapped_column(Float)
    blocked_rule: Mapped[str | None] = mapped_column(String(180), index=True)
    missed_signals_json: Mapped[list] = mapped_column(JsonType, default=list)
    suggested_learning_action: Mapped[str] = mapped_column(Text, default="")
    source_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("decision_universe_snapshots.id", ondelete="SET NULL"), index=True)
    source_trade_id: Mapped[int | None] = mapped_column(ForeignKey("trading_game_trades.id", ondelete="SET NULL"), index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    source_snapshot = relationship("DecisionUniverseSnapshot")
    source_trade = relationship("TradingGameTrade")


class AlphaRecoveryAction(Base):
    __tablename__ = "alpha_recovery_actions"
    __table_args__ = (
        Index("ix_alpha_recovery_status_priority", "status", "priority"),
        Index("ix_alpha_recovery_benchmark_module", "benchmark_name", "affected_module"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    action_type: Mapped[str] = mapped_column(String(120), index=True)
    detected_problem: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    affected_module: Mapped[str] = mapped_column(String(120), index=True)
    benchmark_name: Mapped[str | None] = mapped_column(String(120), index=True)
    expected_impact: Mapped[str] = mapped_column(Text, default="")
    before_metric: Mapped[float | None] = mapped_column(Float)
    after_metric: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(80), default="proposed", index=True)
    rollback_available: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    priority: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    validation_status: Mapped[str] = mapped_column(String(80), default="untested", index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class LearningFactorImportance(Base):
    __tablename__ = "learning_factor_importance"
    __table_args__ = (
        Index("ix_learning_factor_importance_factor_created", "factor_name", "calculated_at"),
        Index("ix_learning_factor_importance_scope", "factor_family", "horizon", "regime", "sector"),
        Index("ix_learning_factor_importance_reliability", "reliability_score", "confidence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    factor_name: Mapped[str] = mapped_column(String(120), index=True)
    factor_family: Mapped[str] = mapped_column(String(120), index=True)
    horizon: Mapped[str | None] = mapped_column(String(80), index=True)
    regime: Mapped[str | None] = mapped_column(String(120), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    alpha_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    alpha_loss_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    missed_winner_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    capital_preservation_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    noise_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    overvaluation_score: Mapped[float] = mapped_column(Float, default=0.0)
    undervaluation_score: Mapped[float] = mapped_column(Float, default=0.0)
    reliability_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evidence_quality: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    recommended_weight_action: Mapped[str] = mapped_column(String(80), default="freeze_until_more_samples", index=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)


class MetaCognitionEvent(Base):
    __tablename__ = "meta_cognition_events"
    __table_args__ = (
        Index("ix_meta_cognition_events_module_created", "evaluated_module", "created_at"),
        Index("ix_meta_cognition_events_outcome", "improvement_observed", "degradation_observed", "confidence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    source_event_type: Mapped[str] = mapped_column(String(120), index=True)
    source_event_id: Mapped[int | None] = mapped_column(Integer, index=True)
    evaluated_module: Mapped[str] = mapped_column(String(120), index=True)
    evaluated_action: Mapped[str] = mapped_column(Text, default="")
    before_metric: Mapped[float | None] = mapped_column(Float)
    after_metric: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    benchmark_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    live_or_historical: Mapped[str] = mapped_column(String(80), default="historical", index=True)
    improvement_observed: Mapped[bool | None] = mapped_column(Boolean, index=True)
    degradation_observed: Mapped[bool | None] = mapped_column(Boolean, index=True)
    overfitting_risk: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    conclusion: Mapped[str] = mapped_column(Text, default="")
    recommended_next_step: Mapped[str] = mapped_column(Text, default="")
    notes_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class CapitalPreservationAlpha(Base):
    __tablename__ = "capital_preservation_alpha"
    __table_args__ = (
        Index("ix_capital_preservation_ticker_date", "ticker", "decision_date"),
        Index("ix_capital_preservation_quality", "was_correct", "quality_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    no_trade_decision_id: Mapped[int | None] = mapped_column(ForeignKey("trading_game_trades.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    decision_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    setup_type: Mapped[str | None] = mapped_column(String(120), index=True)
    no_trade_reason: Mapped[str] = mapped_column(Text, default="")
    horizon: Mapped[str | None] = mapped_column(String(80), index=True)
    future_return: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    avoided_loss: Mapped[float] = mapped_column(Float, default=0.0)
    missed_gain: Mapped[float] = mapped_column(Float, default=0.0)
    capital_preserved: Mapped[float] = mapped_column(Float, default=0.0)
    opportunity_cost: Mapped[float] = mapped_column(Float, default=0.0)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, index=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    no_trade_decision = relationship("TradingGameTrade")


class LearningFocusPriority(Base):
    __tablename__ = "learning_focus_priorities"
    __table_args__ = (
        Index("ix_learning_focus_status_urgency", "status", "urgency"),
        Index("ix_learning_focus_type_target", "priority_type", "target"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    priority_type: Mapped[str] = mapped_column(String(120), index=True)
    target: Mapped[str] = mapped_column(String(180), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    expected_learning_value: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    urgency: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    sample_gap: Mapped[int] = mapped_column(Integer, default=0, index=True)
    linked_alpha_loss_id: Mapped[int | None] = mapped_column(ForeignKey("alpha_loss_attributions.id", ondelete="SET NULL"), index=True)
    linked_factor_importance_id: Mapped[int | None] = mapped_column(ForeignKey("learning_factor_importance.id", ondelete="SET NULL"), index=True)
    linked_recovery_action_id: Mapped[int | None] = mapped_column(ForeignKey("alpha_recovery_actions.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(80), default="proposed", index=True)
    notes_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    linked_alpha_loss = relationship("AlphaLossAttribution")
    linked_factor_importance = relationship("LearningFactorImportance")
    linked_recovery_action = relationship("AlphaRecoveryAction")


class ReasoningNoiseFlag(Base):
    __tablename__ = "reasoning_noise_flags"
    __table_args__ = (
        Index("ix_reasoning_noise_factor_created", "factor_name", "created_at"),
        Index("ix_reasoning_noise_status_severity", "status", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    factor_name: Mapped[str] = mapped_column(String(120), index=True)
    module_name: Mapped[str] = mapped_column(String(120), index=True)
    noise_type: Mapped[str] = mapped_column(String(120), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    severity: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(80), default="open", index=True)
    explanation: Mapped[str] = mapped_column(Text, default="")


class OpportunityCapitalScore(Base):
    __tablename__ = "opportunity_capital_scores"
    __table_args__ = (
        Index("ix_opportunity_capital_scores_ticker_created", "ticker", "calculated_at"),
        Index("ix_opportunity_capital_scores_score", "capital_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    setup_type: Mapped[str | None] = mapped_column(String(120), index=True)
    capital_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    recommended_weight: Mapped[float] = mapped_column(Float, default=0.0)
    max_weight: Mapped[float] = mapped_column(Float, default=0.0)
    cash_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    risk_adjusted_alpha: Mapped[float | None] = mapped_column(Float)
    portfolio_fit: Mapped[float | None] = mapped_column(Float)
    sizing_confidence: Mapped[float | None] = mapped_column(Float)
    decision_state: Mapped[str] = mapped_column(String(80), default="monitor", index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    game = relationship("TradingGame")


class CashAllocationDecision(Base):
    __tablename__ = "cash_allocation_decisions"
    __table_args__ = (Index("ix_cash_allocation_decisions_game_created", "game_id", "calculated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    cash_reserve_percent: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    deployable_percent: Mapped[float] = mapped_column(Float, default=0.0)
    decision_state: Mapped[str] = mapped_column(String(80), default="partial_cash", index=True)
    market_regime: Mapped[str | None] = mapped_column(String(120), index=True)
    drawdown_state: Mapped[str | None] = mapped_column(String(120), index=True)
    reasons_json: Mapped[list] = mapped_column(JsonType, default=list)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    game = relationship("TradingGame")


class AllocationEfficiencyAudit(Base):
    __tablename__ = "allocation_efficiency_audits"
    __table_args__ = (
        Index("ix_allocation_efficiency_game_created", "game_id", "calculated_at"),
        Index("ix_allocation_efficiency_score", "allocation_efficiency_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    allocation_efficiency_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    allocation_regret_eur: Mapped[float | None] = mapped_column(Float)
    cash_drag_estimate: Mapped[float | None] = mapped_column(Float)
    benchmark_opportunity_cost: Mapped[float | None] = mapped_column(Float)
    overallocated_losers_json: Mapped[list] = mapped_column(JsonType, default=list)
    underallocated_winners_json: Mapped[list] = mapped_column(JsonType, default=list)
    recommendations_json: Mapped[list] = mapped_column(JsonType, default=list)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    game = relationship("TradingGame")


class SizingLogicAllocation(Base):
    __tablename__ = "sizing_logic_allocations"
    __table_args__ = (
        Index("ix_sizing_logic_allocations_logic_created", "sizing_logic", "calculated_at"),
        Index("ix_sizing_logic_allocations_score", "risk_adjusted_alpha"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    sizing_logic: Mapped[str] = mapped_column(String(120), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    average_r: Mapped[float | None] = mapped_column(Float)
    benchmark_excess: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    hit_rate: Mapped[float | None] = mapped_column(Float)
    risk_adjusted_alpha: Mapped[float | None] = mapped_column(Float, index=True)
    recommended_risk_percent: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str] = mapped_column(String(120), default="hold", index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    game = relationship("TradingGame")


class CapitalInteractionRisk(Base):
    __tablename__ = "capital_interaction_risks"
    __table_args__ = (
        Index("ix_capital_interaction_risks_game_created", "game_id", "calculated_at"),
        Index("ix_capital_interaction_risks_entities", "entity_a", "entity_b"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    interaction_type: Mapped[str] = mapped_column(String(120), index=True)
    entity_a: Mapped[str] = mapped_column(String(120), index=True)
    entity_b: Mapped[str | None] = mapped_column(String(120), index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    correlation: Mapped[float | None] = mapped_column(Float)
    combined_weight: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    game = relationship("TradingGame")


class TradingGameReadinessSnapshot(Base):
    __tablename__ = "trading_game_readiness_snapshots"
    __table_args__ = (
        Index("ix_tg_readiness_generated", "generated_at"),
        Index("ix_tg_readiness_status_grade", "status", "evidence_grade"),
        Index("ix_tg_readiness_game_generated", "game_id", "generated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(80), default="WAITING_FOR_SOURCE_DATA", index=True)
    evidence_grade: Mapped[str] = mapped_column(String(80), default="insufficient", index=True)
    blocker: Mapped[str] = mapped_column(Text, default="")
    next_required_action: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    methodology_version: Mapped[str] = mapped_column(String(80), default="trading-game-readiness-v1", index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    game = relationship("TradingGame")


class AlphaReadinessSnapshot(Base):
    __tablename__ = "alpha_readiness_snapshots"
    __table_args__ = (
        Index("ix_alpha_readiness_generated", "generated_at"),
        Index("ix_alpha_readiness_score", "alpha_readiness_score", "evidence_grade"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(80), default="INSUFFICIENT_EVIDENCE", index=True)
    alpha_readiness_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evidence_grade: Mapped[str] = mapped_column(String(80), default="insufficient", index=True)
    classification: Mapped[str] = mapped_column(String(120), default="not_ready", index=True)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    methodology_version: Mapped[str] = mapped_column(String(80), default="alpha-readiness-v1", index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class AlphaGateSnapshot(Base):
    __tablename__ = "alpha_gate_snapshots"
    __table_args__ = (
        Index("ix_alpha_gate_generated", "generated_at"),
        Index("ix_alpha_gate_status", "gate_name", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gate_name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(80), default="blocked", index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class EdgeMapSnapshot(Base):
    __tablename__ = "edge_map_snapshots"
    __table_args__ = (
        Index("ix_edge_map_generated", "generated_at"),
        Index("ix_edge_map_scope", "scope", "evidence_grade"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(120), default="global", index=True)
    evidence_grade: Mapped[str] = mapped_column(String(80), default="insufficient", index=True)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PaperCopyStrategy(Base):
    __tablename__ = "paper_copy_strategies"
    __table_args__ = (
        Index("ix_paper_copy_strategy_status_created", "status", "created_at"),
        Index("ix_paper_copy_strategy_score", "copyability_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180), default="BLUM Paper Copy Strategy")
    status: Mapped[str] = mapped_column(String(80), default="paper_only", index=True)
    strategy_type: Mapped[str] = mapped_column(String(120), default="conditional_copy_watchlist", index=True)
    copyability_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    risk_budget_percent: Mapped[float] = mapped_column(Float, default=1.0)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=5)
    rules_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    paper_only: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    no_broker_execution: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class PaperCopyPortfolio(Base):
    __tablename__ = "paper_copy_portfolios"
    __table_args__ = (
        Index("ix_paper_copy_portfolio_status_updated", "status", "updated_at"),
        Index("ix_paper_copy_portfolio_strategy", "strategy_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("paper_copy_strategies.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(80), default="paper_active", index=True)
    starting_capital: Mapped[float] = mapped_column(Float, default=100.0)
    current_capital: Mapped[float] = mapped_column(Float, default=100.0, index=True)
    cash: Mapped[float] = mapped_column(Float, default=100.0)
    exposure: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_ticker: Mapped[str] = mapped_column(String(32), default="SPY", index=True)
    risk_state: Mapped[str] = mapped_column(String(80), default="conservative", index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    strategy = relationship("PaperCopyStrategy")


class PaperCopyOrder(Base):
    __tablename__ = "paper_copy_orders"
    __table_args__ = (
        Index("ix_paper_copy_orders_portfolio_created", "portfolio_id", "created_at"),
        Index("ix_paper_copy_orders_ticker_status", "ticker", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("paper_copy_portfolios.id", ondelete="CASCADE"), index=True)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("paper_copy_strategies.id", ondelete="SET NULL"), index=True)
    source_trade_plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(40), default="paper_buy", index=True)
    status: Mapped[str] = mapped_column(String(80), default="planned", index=True)
    order_type: Mapped[str] = mapped_column(String(80), default="conditional_paper", index=True)
    trigger_condition: Mapped[str] = mapped_column(Text, default="")
    paper_price: Mapped[float | None] = mapped_column(Float)
    paper_quantity: Mapped[float | None] = mapped_column(Float)
    risk_amount: Mapped[float | None] = mapped_column(Float)
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    target_1: Mapped[float | None] = mapped_column(Float)
    target_2: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    portfolio = relationship("PaperCopyPortfolio")
    strategy = relationship("PaperCopyStrategy")
    source_trade_plan = relationship("TradePlan")


class PaperCopyPosition(Base):
    __tablename__ = "paper_copy_positions"
    __table_args__ = (
        Index("ix_paper_copy_positions_portfolio_status", "portfolio_id", "status"),
        Index("ix_paper_copy_positions_ticker_opened", "ticker", "opened_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("paper_copy_portfolios.id", ondelete="CASCADE"), index=True)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("paper_copy_strategies.id", ondelete="SET NULL"), index=True)
    source_order_id: Mapped[int | None] = mapped_column(ForeignKey("paper_copy_orders.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(80), default="open", index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price: Mapped[float | None] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float)
    market_value: Mapped[float | None] = mapped_column(Float)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float)
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    target_1: Mapped[float | None] = mapped_column(Float)
    target_2: Mapped[float | None] = mapped_column(Float)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    portfolio = relationship("PaperCopyPortfolio")
    strategy = relationship("PaperCopyStrategy")
    source_order = relationship("PaperCopyOrder")


class PaperCopyPortfolioSnapshot(Base):
    __tablename__ = "paper_copy_portfolio_snapshots"
    __table_args__ = (
        Index("ix_paper_copy_portfolio_snapshots_portfolio_created", "portfolio_id", "created_at"),
        Index("ix_paper_copy_portfolio_snapshots_score", "copyability_score", "evidence_grade"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("paper_copy_portfolios.id", ondelete="CASCADE"), index=True)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("paper_copy_strategies.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    capital: Mapped[float | None] = mapped_column(Float)
    exposure: Mapped[float | None] = mapped_column(Float)
    open_positions: Mapped[int] = mapped_column(Integer, default=0)
    pending_orders: Mapped[int] = mapped_column(Integer, default=0)
    copyability_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evidence_grade: Mapped[str] = mapped_column(String(80), default="insufficient", index=True)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)

    portfolio = relationship("PaperCopyPortfolio")
    strategy = relationship("PaperCopyStrategy")


class ReplayMarketBar(Base):
    __tablename__ = "replay_market_bars"
    __table_args__ = (
        UniqueConstraint("asset_id", "timeframe", "bar_timestamp", name="uq_replay_bar_timestamp"),
        Index("ix_replay_bars_asset_timeframe_timestamp", "asset_id", "timeframe", "bar_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    source_symbol: Mapped[str] = mapped_column(String(48), index=True)
    normalized_symbol: Mapped[str] = mapped_column(String(48), index=True)
    market: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    bar_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(48), index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    source_metadata: Mapped[dict] = mapped_column(JsonType, default=dict)

    asset = relationship("Asset")


class ReplayDataCoverage(Base):
    __tablename__ = "replay_data_coverages"
    __table_args__ = (
        UniqueConstraint("asset_id", "timeframe", "provider", name="uq_replay_coverage_asset_timeframe_provider"),
        Index("ix_replay_coverage_status_updated", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    source_symbol: Mapped[str] = mapped_column(String(48), index=True)
    normalized_symbol: Mapped[str] = mapped_column(String(48), index=True)
    market: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    provider: Mapped[str] = mapped_column(String(48), index=True)
    requested_start: Mapped[datetime | None] = mapped_column(DateTime)
    requested_end: Mapped[datetime | None] = mapped_column(DateTime)
    available_start: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    available_end: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    rows_available: Mapped[int] = mapped_column(Integer, default=0)
    coverage_percent: Mapped[float] = mapped_column(Float, default=0.0)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    status: Mapped[str] = mapped_column(String(40), default="INITIALIZING", index=True)
    missing_intervals: Mapped[list] = mapped_column(JsonType, default=list)
    blockers: Mapped[list] = mapped_column(JsonType, default=list)
    source_metadata: Mapped[dict] = mapped_column(JsonType, default=dict)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    asset = relationship("Asset")


class DeterministicExecutionRun(Base):
    __tablename__ = "deterministic_execution_runs"
    __table_args__ = (
        UniqueConstraint("reproducibility_fingerprint", name="uq_deterministic_execution_fingerprint"),
        Index("ix_deterministic_execution_runs_status_created", "status", "created_at"),
        Index("ix_deterministic_execution_runs_source", "source_object_type", "source_object_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_uid: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(40), index=True)
    kernel_name: Mapped[str] = mapped_column(String(80), default="nautilus_trader", index=True)
    kernel_version: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), index=True)
    source_object_type: Mapped[str | None] = mapped_column(String(80), index=True)
    source_object_id: Mapped[str | None] = mapped_column(String(120), index=True)
    reproducibility_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    order_event_count: Mapped[int] = mapped_column(Integer, default=0)
    position_event_count: Mapped[int] = mapped_column(Integer, default=0)
    costs_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    diagnostics_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class DeterministicExecutionEvent(Base):
    __tablename__ = "deterministic_execution_events"
    __table_args__ = (
        UniqueConstraint("event_uid", name="uq_deterministic_execution_event_uid"),
        Index("ix_deterministic_execution_events_run_timestamp", "run_id", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("deterministic_execution_runs.id", ondelete="CASCADE"), index=True)
    event_uid: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    decision_id: Mapped[str | None] = mapped_column(String(160), index=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ExecutionParityComparison(Base):
    __tablename__ = "execution_parity_comparisons"
    __table_args__ = (
        Index("ix_execution_parity_status_created", "status", "created_at"),
        Index("ix_execution_parity_source", "source_object_type", "source_object_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("deterministic_execution_runs.id", ondelete="CASCADE"), index=True)
    source_object_type: Mapped[str | None] = mapped_column(String(80), index=True)
    source_object_id: Mapped[str | None] = mapped_column(String(120), index=True)
    asset_class: Mapped[str | None] = mapped_column(String(40), index=True)
    regime: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    state_agreement: Mapped[bool | None] = mapped_column(Boolean, index=True)
    quantity_difference: Mapped[float | None] = mapped_column(Float)
    fill_price_difference: Mapped[float | None] = mapped_column(Float)
    cost_difference: Mapped[float | None] = mapped_column(Float)
    pnl_difference: Mapped[float | None] = mapped_column(Float)
    reasons_json: Mapped[list] = mapped_column(JsonType, default=list)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ExecutionKernelState(Base):
    __tablename__ = "execution_kernel_state"
    __table_args__ = (Index("ix_execution_kernel_state_mode_updated", "mode", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state_key: Mapped[str] = mapped_column(String(80), unique=True, default="primary", index=True)
    mode: Mapped[str] = mapped_column(String(40), default="SHADOW", index=True)
    previous_mode: Mapped[str | None] = mapped_column(String(40))
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    matched_samples: Mapped[int] = mapped_column(Integer, default=0)
    state_agreement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    asset_classes_json: Mapped[list] = mapped_column(JsonType, default=list)
    regimes_json: Mapped[list] = mapped_column(JsonType, default=list)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime)
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime)
    rollback_reason: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class HyperbolicReplayRun(Base):
    __tablename__ = "hyperbolic_replay_runs"
    __table_args__ = (Index("ix_hyperbolic_replay_runs_status_started", "status", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    trigger: Mapped[str] = mapped_column(String(40), default="scheduled", index=True)
    status: Mapped[str] = mapped_column(String(40), default="RUNNING", index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), default="REPLAY_EVIDENCE", index=True)
    adaptive_state: Mapped[str] = mapped_column(String(40), default="RUNNING", index=True)
    assets_selected: Mapped[int] = mapped_column(Integer, default=0)
    trades_generated: Mapped[int] = mapped_column(Integer, default=0)
    trades_validated: Mapped[int] = mapped_column(Integer, default=0)
    experiments_run: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    markets_json: Mapped[list] = mapped_column(JsonType, default=list)
    timeframes_json: Mapped[list] = mapped_column(JsonType, default=list)
    cursor_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    resource_limits_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    blockers_json: Mapped[list] = mapped_column(JsonType, default=list)
    summary_json: Mapped[dict] = mapped_column(JsonType, default=dict)


class HyperbolicReplayTrade(Base):
    __tablename__ = "hyperbolic_replay_trades"
    __table_args__ = (
        UniqueConstraint("asset_id", "strategy_fingerprint", "timeframe", "decision_timestamp", name="uq_replay_trade_strategy_decision"),
        Index("ix_hyperbolic_replay_trades_run_state", "run_id", "state"),
        Index("ix_hyperbolic_replay_trades_ticker_decision", "ticker", "decision_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("hyperbolic_replay_runs.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(48), index=True)
    market: Mapped[str] = mapped_column(String(40), index=True)
    setup_type: Mapped[str] = mapped_column(String(80), index=True)
    strategy_fingerprint: Mapped[str] = mapped_column(String(96), default="legacy", index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), default="REPLAY_EVIDENCE", index=True)
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    entry_timestamp: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    exit_timestamp: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    entry_price: Mapped[float | None] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float)
    stop_price: Mapped[float | None] = mapped_column(Float)
    target_price: Mapped[float | None] = mapped_column(Float)
    position_size: Mapped[float] = mapped_column(Float, default=0.0)
    gross_pnl: Mapped[float | None] = mapped_column(Float)
    net_pnl: Mapped[float | None] = mapped_column(Float)
    r_multiple: Mapped[float | None] = mapped_column(Float, index=True)
    benchmark_excess: Mapped[float | None] = mapped_column(Float, index=True)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    decision_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    execution_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    run = relationship("HyperbolicReplayRun")
    asset = relationship("Asset")


class ReplayStrategyValidation(Base):
    __tablename__ = "replay_strategy_validations"
    __table_args__ = (
        Index("ix_replay_strategy_validations_setup_verdict", "setup_type", "verdict"),
        Index("ix_replay_strategy_validations_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("blum_learning_experiments.id", ondelete="SET NULL"), index=True)
    setup_type: Mapped[str] = mapped_column(String(80), index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), default="WALK_FORWARD_EVIDENCE", index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, index=True)
    markets_json: Mapped[list] = mapped_column(JsonType, default=list)
    windows_json: Mapped[list] = mapped_column(JsonType, default=list)
    metrics_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    overfitting_score: Mapped[float] = mapped_column(Float, default=100.0)
    verdict: Mapped[str] = mapped_column(String(60), default="NEEDS_MORE_EVIDENCE", index=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    experiment = relationship("BlumLearningExperiment")


class StrategyEvidenceSnapshot(Base):
    __tablename__ = "strategy_evidence_snapshots"
    __table_args__ = (
        Index("ix_strategy_evidence_snapshots_latest", "strategy_id", "evidence_class", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(160), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    evidence_class: Mapped[str] = mapped_column(String(60), index=True)
    total_trades: Mapped[int | None] = mapped_column(Integer)
    closed_trades: Mapped[int | None] = mapped_column(Integer)
    forward_trades: Mapped[int | None] = mapped_column(Integer)
    win_rate: Mapped[float | None] = mapped_column(Float)
    gross_expectancy: Mapped[float | None] = mapped_column(Float)
    net_expectancy: Mapped[float | None] = mapped_column(Float)
    average_r: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    sharpe_proxy: Mapped[float | None] = mapped_column(Float)
    sortino_proxy: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    benchmark_excess: Mapped[float | None] = mapped_column(Float)
    total_costs: Mapped[float | None] = mapped_column(Float)
    average_slippage: Mapped[float | None] = mapped_column(Float)
    metrics_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    markets_json: Mapped[list] = mapped_column(JsonType, default=list)
    timeframes_json: Mapped[list] = mapped_column(JsonType, default=list)
    source_rows_json: Mapped[list] = mapped_column(JsonType, default=list)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    concentration_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    regimes_json: Mapped[list] = mapped_column(JsonType, default=list)
    confidence_interval_json: Mapped[dict | None] = mapped_column(JsonType)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class StrategyReadinessHistory(Base):
    __tablename__ = "strategy_readiness_history"
    __table_args__ = (
        Index("ix_strategy_readiness_history_latest", "strategy_id", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(160), index=True)
    previous_copy_readiness_status: Mapped[str | None] = mapped_column(String(80))
    copy_readiness_status: Mapped[str] = mapped_column(String(80), index=True)
    maturity_score: Mapped[float | None] = mapped_column(Float)
    global_forward_trades: Mapped[int | None] = mapped_column(Integer)
    strategy_forward_trades: Mapped[int | None] = mapped_column(Integer)
    observation_days: Mapped[int | None] = mapped_column(Integer)
    passed_gates_json: Mapped[list] = mapped_column(JsonType, default=list)
    failed_gates_json: Mapped[list] = mapped_column(JsonType, default=list)
    blockers_json: Mapped[list] = mapped_column(JsonType, default=list)
    reasons_json: Mapped[list] = mapped_column(JsonType, default=list)
    decay_status: Mapped[str | None] = mapped_column(String(80), index=True)
    real_capital_eligibility: Mapped[str | None] = mapped_column(String(100), index=True)
    threshold_version: Mapped[str] = mapped_column(String(80), default="copy-readiness-v1", index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class EvidenceTimelineEvent(Base):
    __tablename__ = "evidence_timeline_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_evidence_timeline_events_event_key"),
        Index("ix_evidence_timeline_events_strategy_time", "strategy_id", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(220), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    strategy_id: Mapped[str | None] = mapped_column(String(160), index=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, index=True)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class StrategyFactoryRun(Base):
    __tablename__ = "strategy_factory_runs"
    __table_args__ = (
        Index("ix_strategy_factory_runs_family_started", "hypothesis_family", "started_at"),
        Index("ix_strategy_factory_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_uid: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    hypothesis_family: Mapped[str] = mapped_column(String(80), index=True)
    generation_seed: Mapped[int] = mapped_column(Integer, default=7)
    status: Mapped[str] = mapped_column(String(60), default="RUNNING", index=True)
    variants_examined: Mapped[int] = mapped_column(Integer, default=0)
    promoted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejection_counts_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    budgets_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    summary_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class StrategyCandidateVariant(Base):
    __tablename__ = "strategy_candidate_variants"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_strategy_candidate_variants_fingerprint"),
        Index("ix_strategy_candidate_variants_family_verdict", "family", "final_verdict"),
        Index("ix_strategy_candidate_variants_state_created", "lifecycle_state", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    factory_run_id: Mapped[int] = mapped_column(ForeignKey("strategy_factory_runs.id", ondelete="CASCADE"), index=True)
    validation_id: Mapped[int | None] = mapped_column(ForeignKey("replay_strategy_validations.id", ondelete="SET NULL"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(96), index=True)
    family: Mapped[str] = mapped_column(String(80), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    market: Mapped[str] = mapped_column(String(80), default="global", index=True)
    asset_class: Mapped[str] = mapped_column(String(60), default="stocks,etfs", index=True)
    timeframe_stack: Mapped[list] = mapped_column(JsonType, default=list)
    specification_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    complexity: Mapped[int] = mapped_column(Integer, default=1)
    benchmark_ticker: Mapped[str] = mapped_column(String(32), default="SPY", index=True)
    lifecycle_state: Mapped[str] = mapped_column(String(60), default="GENERATED", index=True)
    final_verdict: Mapped[str | None] = mapped_column(String(80), index=True)
    is_champion: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class StrategyValidationFold(Base):
    __tablename__ = "strategy_validation_folds"
    __table_args__ = (
        UniqueConstraint("candidate_id", "fold_number", name="uq_strategy_validation_folds_candidate_fold"),
        Index("ix_strategy_validation_folds_candidate_validation", "candidate_id", "validation_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("strategy_candidate_variants.id", ondelete="CASCADE"), index=True)
    fold_number: Mapped[int] = mapped_column(Integer)
    train_start: Mapped[datetime] = mapped_column(DateTime)
    train_end: Mapped[datetime] = mapped_column(DateTime)
    validation_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    validation_end: Mapped[datetime] = mapped_column(DateTime)
    purge_bars: Mapped[int] = mapped_column(Integer, default=0)
    embargo_bars: Mapped[int] = mapped_column(Integer, default=0)
    train_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    coverage_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class StrategyPromotionEvent(Base):
    __tablename__ = "strategy_promotion_events"
    __table_args__ = (
        Index("ix_strategy_promotion_events_registry_time", "registry_key", "created_at"),
        Index("ix_strategy_promotion_events_candidate_type", "candidate_id", "event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("strategy_candidate_variants.id", ondelete="CASCADE"), index=True)
    validation_id: Mapped[int | None] = mapped_column(ForeignKey("replay_strategy_validations.id", ondelete="SET NULL"), index=True)
    previous_candidate_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_candidate_variants.id", ondelete="SET NULL"), index=True)
    registry_key: Mapped[str] = mapped_column(String(240), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    reversible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PaperExecutionOrder(Base):
    __tablename__ = "paper_execution_orders"
    __table_args__ = (
        UniqueConstraint("order_uid", name="uq_paper_execution_orders_uid"),
        UniqueConstraint("duplicate_key", name="uq_paper_execution_orders_duplicate_key"),
        Index("ix_paper_execution_orders_status_submitted", "status", "submitted_at"),
        Index("ix_paper_execution_orders_ticker_decision", "ticker", "decision_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_uid: Mapped[str] = mapped_column(String(140), index=True)
    duplicate_key: Mapped[str] = mapped_column(String(220), index=True)
    paper_trade_id: Mapped[int | None] = mapped_column(ForeignKey("live_forward_paper_trades.id", ondelete="SET NULL"), index=True)
    replay_trade_id: Mapped[int | None] = mapped_column(ForeignKey("hyperbolic_replay_trades.id", ondelete="SET NULL"), index=True)
    validation_id: Mapped[int | None] = mapped_column(ForeignKey("replay_strategy_validations.id", ondelete="SET NULL"), index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_candidate_variants.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(48), index=True)
    side: Mapped[str] = mapped_column(String(12), index=True)
    order_type: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(40), default="SUBMITTED", index=True)
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    theoretical_price: Mapped[float] = mapped_column(Float)
    requested_quantity: Mapped[float] = mapped_column(Float)
    filled_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    remaining_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    average_fill_price: Mapped[float | None] = mapped_column(Float)
    limit_price: Mapped[float | None] = mapped_column(Float)
    stop_price: Mapped[float | None] = mapped_column(Float)
    target_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(16), default="USD")
    account_currency: Mapped[str] = mapped_column(String(16), default="USD")
    fx_rate: Mapped[float | None] = mapped_column(Float)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    order_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class PaperExecutionFill(Base):
    __tablename__ = "paper_execution_fills"
    __table_args__ = (
        UniqueConstraint("fill_uid", name="uq_paper_execution_fills_uid"),
        Index("ix_paper_execution_fills_order_market_time", "order_id", "market_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_execution_orders.id", ondelete="CASCADE"), index=True)
    fill_uid: Mapped[str] = mapped_column(String(180), index=True)
    market_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    quantity: Mapped[float] = mapped_column(Float)
    reference_price: Mapped[float] = mapped_column(Float)
    executed_price: Mapped[float] = mapped_column(Float)
    spread_bps: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_bps: Mapped[float] = mapped_column(Float, default=0.0)
    commission_bps: Mapped[float] = mapped_column(Float, default=0.0)
    spread_cost: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    commission_cost: Mapped[float] = mapped_column(Float, default=0.0)
    fx_cost: Mapped[float] = mapped_column(Float, default=0.0)
    borrow_cost: Mapped[float] = mapped_column(Float, default=0.0)
    gap_cost: Mapped[float] = mapped_column(Float, default=0.0)
    participation_rate: Mapped[float] = mapped_column(Float, default=0.0)
    fill_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ForexTraderCycle(Base):
    __tablename__ = "forex_trader_cycles"
    __table_args__ = (
        UniqueConstraint("cycle_key", name="uq_forex_trader_cycles_key"),
        Index("ix_forex_cycles_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_uid: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    cycle_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="RUNNING", index=True)
    session: Mapped[str | None] = mapped_column(String(60), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    pairs_scanned: Mapped[list] = mapped_column(JsonType, default=list)
    agent_outputs: Mapped[dict] = mapped_column(JsonType, default=dict)
    candidates_json: Mapped[list] = mapped_column(JsonType, default=list)
    approved_candidates: Mapped[list] = mapped_column(JsonType, default=list)
    rejected_candidates: Mapped[list] = mapped_column(JsonType, default=list)
    orders_json: Mapped[list] = mapped_column(JsonType, default=list)
    fills_json: Mapped[list] = mapped_column(JsonType, default=list)
    position_updates: Mapped[list] = mapped_column(JsonType, default=list)
    closed_trades: Mapped[list] = mapped_column(JsonType, default=list)
    blockers: Mapped[list] = mapped_column(JsonType, default=list)
    learning_events: Mapped[list] = mapped_column(JsonType, default=list)
    next_action: Mapped[str | None] = mapped_column(Text)
    code_commit: Mapped[str | None] = mapped_column(String(80))
    strategy_version: Mapped[str] = mapped_column(String(80), default="1")
    cost_model_version: Mapped[str] = mapped_column(String(80), default="forex-paper-execution-v1")
    configuration_hash: Mapped[str] = mapped_column(String(64), index=True)
    data_coverage_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ForexDecision(Base):
    __tablename__ = "forex_decisions"
    __table_args__ = (
        UniqueConstraint("decision_uid", name="uq_forex_decisions_uid"),
        Index("ix_forex_decisions_pair_time", "pair", "decision_timestamp"),
        Index("ix_forex_decisions_status_time", "status", "decision_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_uid: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("forex_trader_cycles.id", ondelete="CASCADE"), index=True)
    pair: Mapped[str] = mapped_column(String(32), index=True)
    strategy_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    blockers: Mapped[list] = mapped_column(JsonType, default=list)
    proposal_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    risk_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    execution_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    input_snapshot: Mapped[dict] = mapped_column(JsonType, default=dict)
    evidence_type: Mapped[str] = mapped_column(String(60), default="PAPER_FORWARD_FOREX", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ForexPosition(Base):
    __tablename__ = "forex_positions"
    __table_args__ = (
        UniqueConstraint("position_uid", name="uq_forex_positions_uid"),
        Index("ix_forex_positions_status_pair", "status", "pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_uid: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("forex_decisions.id", ondelete="RESTRICT"), index=True)
    pair: Mapped[str] = mapped_column(String(32), index=True)
    strategy_id: Mapped[str] = mapped_column(String(120), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    quantity_lots: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    target_price: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    exit_price: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(String(80), index=True)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    realized_r: Mapped[float | None] = mapped_column(Float)
    spread_cost: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    swap_accrued: Mapped[float] = mapped_column(Float, default=0.0)
    margin_used: Mapped[float] = mapped_column(Float, default=0.0)
    mfe: Mapped[float] = mapped_column(Float, default=0.0)
    mae: Mapped[float] = mapped_column(Float, default=0.0)
    last_managed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    contract_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ForexLearningEvidence(Base):
    __tablename__ = "forex_learning_evidence"
    __table_args__ = (Index("ix_forex_learning_strategy_time", "strategy_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("forex_decisions.id", ondelete="SET NULL"), index=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("forex_positions.id", ondelete="SET NULL"), index=True)
    strategy_id: Mapped[str] = mapped_column(String(120), index=True)
    pair: Mapped[str] = mapped_column(String(32), index=True)
    session: Mapped[str | None] = mapped_column(String(60), index=True)
    regime: Mapped[str | None] = mapped_column(String(60), index=True)
    setup_family: Mapped[str | None] = mapped_column(String(80), index=True)
    direction: Mapped[str | None] = mapped_column(String(16), index=True)
    outcome: Mapped[str] = mapped_column(String(80), index=True)
    expected_result: Mapped[float | None] = mapped_column(Float)
    realized_result: Mapped[float | None] = mapped_column(Float)
    difference: Mapped[float | None] = mapped_column(Float)
    likely_cause: Mapped[str | None] = mapped_column(Text)
    lesson: Mapped[str] = mapped_column(Text)
    evidence_strength: Mapped[float] = mapped_column(Float, default=0.0)
    model_update_justified: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_type: Mapped[str] = mapped_column(String(60), default="PAPER_FORWARD_FOREX", index=True)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ForexStrategyReadiness(Base):
    __tablename__ = "forex_strategy_readiness"
    __table_args__ = (Index("ix_forex_readiness_level_updated", "readiness_level", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    readiness_level: Mapped[str] = mapped_column(String(60), default="TRAINING_SIGNAL", index=True)
    closed_forward_trades: Mapped[int] = mapped_column(Integer, default=0)
    net_expectancy_r: Mapped[float | None] = mapped_column(Float)
    risk_adjusted_alpha: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    pair_count: Mapped[int] = mapped_column(Integer, default=0)
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    regime_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence_interval_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    replay_forward_decay: Mapped[float | None] = mapped_column(Float)
    blockers: Mapped[list] = mapped_column(JsonType, default=list)
    threshold_version: Mapped[str] = mapped_column(String(80), default="forex-alpha-readiness-v1")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ForexPolicyState(Base):
    __tablename__ = "forex_policy_states"
    __table_args__ = (
        UniqueConstraint("policy_key", name="uq_forex_policy_state_key"),
        Index("ix_forex_policy_context", "strategy_id", "session", "regime", "setup_family", "direction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(120), index=True)
    session: Mapped[str] = mapped_column(String(60), index=True)
    regime: Mapped[str] = mapped_column(String(60), index=True)
    setup_family: Mapped[str] = mapped_column(String(80), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    q_value: Mapped[float] = mapped_column(Float, default=0.0)
    reward_sum: Mapped[float] = mapped_column(Float, default=0.0)
    reward_sq_sum: Mapped[float] = mapped_column(Float, default=0.0)
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, default=0)
    cause_counts_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    evidence_grade: Mapped[str] = mapped_column(String(40), default="LEARNING_ONLY", index=True)
    confidence_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    last_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("forex_learning_evidence.id", ondelete="SET NULL"), index=True)
    policy_version: Mapped[str] = mapped_column(String(80), default="forex-hierarchical-contextual-bandit-v2")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ForexPolicyUpdate(Base):
    __tablename__ = "forex_policy_updates"
    __table_args__ = (
        UniqueConstraint(
            "evidence_id",
            "policy_scope",
            name="uq_forex_policy_update_evidence_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_state_id: Mapped[int] = mapped_column(ForeignKey("forex_policy_states.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("forex_learning_evidence.id", ondelete="CASCADE"), index=True)
    policy_scope: Mapped[str] = mapped_column(String(32), default="FULL_CONTEXT", index=True)
    previous_q: Mapped[float] = mapped_column(Float)
    reward: Mapped[float] = mapped_column(Float)
    new_q: Mapped[float] = mapped_column(Float)
    learning_rate: Mapped[float] = mapped_column(Float)
    sample_size_after: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[str] = mapped_column(String(80), default="forex-hierarchical-contextual-bandit-v2")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class FinancialModelAdvisor(Base):
    __tablename__ = "financial_model_advisors"
    __table_args__ = (UniqueConstraint("advisor_key", name="uq_financial_model_advisor_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    advisor_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    provider_type: Mapped[str] = mapped_column(String(60), index=True)
    model_id: Mapped[str | None] = mapped_column(String(240))
    source_url: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(120), index=True)
    execution_mode: Mapped[str] = mapped_column(String(60), index=True)
    runtime_status: Mapped[str] = mapped_column(String(60), index=True)
    license: Mapped[str] = mapped_column(String(80), default="review_required")
    resource_profile: Mapped[dict] = mapped_column(JsonType, default=dict)
    capabilities: Mapped[list] = mapped_column(JsonType, default=list)
    direct_trading_authority: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class FinancialModelVote(Base):
    __tablename__ = "financial_model_votes"
    __table_args__ = (
        UniqueConstraint("advisor_key", "object_type", "object_id", "task", "evidence_hash", name="uq_financial_model_vote_evidence"),
        Index("ix_financial_model_vote_object", "object_type", "object_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    advisor_key: Mapped[str] = mapped_column(String(80), index=True)
    object_type: Mapped[str] = mapped_column(String(80), index=True)
    object_id: Mapped[str] = mapped_column(String(120), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    task: Mapped[str] = mapped_column(String(80), index=True)
    vote: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_quality: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    output_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    runtime_status: Mapped[str] = mapped_column(String(60), index=True)
    direct_action_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome_evaluated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reward_contribution: Mapped[float | None] = mapped_column(Float)
    was_helpful: Mapped[bool | None] = mapped_column(Boolean, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime)


class ForexTraderRuntimeState(Base):
    __tablename__ = "forex_trader_runtime_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    runtime_key: Mapped[str] = mapped_column(String(80), unique=True, default="default")
    desired_state: Mapped[str] = mapped_column(String(40), default="RUNNING", index=True)
    scheduler_status: Mapped[str] = mapped_column(String(40), default="STARTING", index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    current_cycle_key: Mapped[str | None] = mapped_column(String(180), index=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_run_after: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ForexKnowledgeSource(Base):
    __tablename__ = "forex_knowledge_sources"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_forex_knowledge_sources_key"),
        Index("ix_forex_knowledge_source_status", "validation_status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    provider: Mapped[str] = mapped_column(String(80), index=True)
    source_type: Mapped[str] = mapped_column(String(80), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(String(120))
    usage_policy: Mapped[dict] = mapped_column(JsonType, default=dict)
    schema_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    validation_status: Mapped[str] = mapped_column(String(40), default="CATALOGED", index=True)
    validation_notes: Mapped[list] = mapped_column(JsonType, default=list)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ForexCurriculumAssignment(Base):
    __tablename__ = "forex_curriculum_assignments"
    __table_args__ = (
        UniqueConstraint("assignment_key", name="uq_forex_curriculum_assignment_key"),
        Index("ix_forex_curriculum_status_priority", "status", "priority_score"),
        Index("ix_forex_curriculum_context", "pair", "session", "regime", "setup_family"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    priority_type: Mapped[str] = mapped_column(String(60), index=True)
    pair: Mapped[str] = mapped_column(String(32), index=True)
    session: Mapped[str] = mapped_column(String(60), index=True)
    regime: Mapped[str] = mapped_column(String(60), index=True)
    setup_family: Mapped[str] = mapped_column(String(80), index=True)
    hypothesis: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    expected_information_gain: Mapped[float] = mapped_column(Float)
    priority_score: Mapped[float] = mapped_column(Float, index=True)
    sample_gap: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE", index=True)
    replay_spec_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    samples_generated: Mapped[int] = mapped_column(Integer, default=0)
    last_sampled_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ForexContextualMemory(Base):
    __tablename__ = "forex_contextual_memory"
    __table_args__ = (
        UniqueConstraint("memory_key", name="uq_forex_contextual_memory_key"),
        Index("ix_forex_memory_context", "strategy_id", "session", "regime", "setup_family"),
        Index("ix_forex_memory_grade_updated", "evidence_grade", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    memory_key: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(120), index=True)
    pair_family: Mapped[str] = mapped_column(String(40), index=True)
    session: Mapped[str] = mapped_column(String(60), index=True)
    regime: Mapped[str] = mapped_column(String(60), index=True)
    setup_family: Mapped[str] = mapped_column(String(80), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float | None] = mapped_column(Float)
    net_expectancy_r: Mapped[float | None] = mapped_column(Float)
    benchmark_excess: Mapped[float | None] = mapped_column(Float)
    cost_failure_rate: Mapped[float | None] = mapped_column(Float)
    confidence_interval_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    evidence_grade: Mapped[str] = mapped_column(String(40), default="LEARNING_ONLY", index=True)
    confidence_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    source_evidence_ids: Mapped[list] = mapped_column(JsonType, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    compiled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ForexKnowledgeIngestionRun(Base):
    __tablename__ = "forex_knowledge_ingestion_runs"
    __table_args__ = (Index("ix_forex_ingestion_source_status", "source_key", "status", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    cursor_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    rows_seen: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    validation_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class TradingMLModelVersion(Base):
    __tablename__ = "trading_ml_model_versions"
    __table_args__ = (
        UniqueConstraint("model_uid", name="uq_trading_ml_model_uid"),
        Index("ix_trading_ml_models_market_status", "market_family", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_uid: Mapped[str] = mapped_column(String(160))
    market_family: Mapped[str] = mapped_column(String(32))
    algorithm: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="SHADOW")
    feature_schema_version: Mapped[str] = mapped_column(String(80))
    feature_schema_hash: Mapped[str] = mapped_column(String(64))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    evidence_lane_counts_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    training_window_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    validation_window_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    asset_count: Mapped[int] = mapped_column(Integer, default=0)
    regime_count: Mapped[int] = mapped_column(Integer, default=0)
    setup_count: Mapped[int] = mapped_column(Integer, default=0)
    training_metrics_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    validation_metrics_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    baseline_metrics_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    promotion_gates_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    promotion_decision: Mapped[str | None] = mapped_column(String(80))
    artifact_path: Mapped[str] = mapped_column(Text)
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    artifact_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    parent_model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("trading_ml_model_versions.id", ondelete="SET NULL")
    )
    champion_model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("trading_ml_model_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    degraded_at: Mapped[datetime | None] = mapped_column(DateTime)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")


class TradingMLTrainingRun(Base):
    __tablename__ = "trading_ml_training_runs"
    __table_args__ = (
        Index("ix_trading_ml_runs_market_started", "market_family", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_uid: Mapped[str] = mapped_column(String(160), unique=True)
    market_family: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(80))
    cursor_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    resource_limits_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    rows_considered: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rejection_reasons_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    split_metadata_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="RUNNING")
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    candidate_model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("trading_ml_model_versions.id", ondelete="SET NULL")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class TradingMLPrediction(Base):
    __tablename__ = "trading_ml_predictions"
    __table_args__ = (
        UniqueConstraint(
            "source_object_type",
            "source_object_id",
            "model_version_id",
            name="uq_trading_ml_prediction_source_model",
        ),
        Index("ix_trading_ml_predictions_market_created", "market_family", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_object_type: Mapped[str] = mapped_column(String(80))
    source_object_id: Mapped[str] = mapped_column(String(160))
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("trading_ml_model_versions.id", ondelete="CASCADE")
    )
    market_family: Mapped[str] = mapped_column(String(32))
    feature_hash: Mapped[str] = mapped_column(String(64))
    probability_positive_r: Mapped[float | None] = mapped_column(Float)
    predicted_net_r: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    baseline_output_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    proposed_confidence_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    applied_confidence_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    guardrails_json: Mapped[list] = mapped_column(JsonType, default=list)
    explanation_json: Mapped[list] = mapped_column(JsonType, default=list)
    realized_outcome_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentCouncilRun(Base):
    __tablename__ = "agent_council_runs"
    __table_args__ = (
        UniqueConstraint("run_uid", name="uq_agent_council_run_uid"),
        Index("ix_agent_council_runs_status_created", "status", "created_at"),
        Index("ix_agent_council_runs_ticker_asof", "ticker", "as_of"),
        Index("ix_agent_council_runs_record_status", "knowledge_record_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    knowledge_record_id: Mapped[int] = mapped_column(
        ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(40), default="RUNNING", index=True)
    current_stage: Mapped[str] = mapped_column(String(60), default="analyst", index=True)
    stage_cursor: Mapped[int] = mapped_column(Integer, default=0)
    base_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    final_confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    final_action: Mapped[str] = mapped_column(String(32), default="WAIT", index=True)
    disagreement_score: Mapped[float] = mapped_column(Float, default=100.0)
    evidence_quality: Mapped[float] = mapped_column(Float, default=0.0)
    memory_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    source_snapshot_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    checkpoint_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    final_decision_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    warnings_json: Mapped[list] = mapped_column(JsonType, default=list)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")


class AgentCouncilTurn(Base):
    __tablename__ = "agent_council_turns"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "stage", "agent_name", "round_number", name="uq_agent_council_turn"
        ),
        Index("ix_agent_council_turns_run_sequence", "run_id", "turn_sequence"),
        Index("ix_agent_council_turns_agent_created", "agent_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_council_runs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(60), index=True)
    agent_name: Mapped[str] = mapped_column(String(100), index=True)
    round_number: Mapped[int] = mapped_column(Integer, default=1)
    turn_sequence: Mapped[int] = mapped_column(Integer)
    stance: Mapped[str] = mapped_column(String(32), default="neutral", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reliability_weight: Mapped[float] = mapped_column(Float, default=0.5)
    argument: Mapped[str] = mapped_column(Text, default="")
    supporting_evidence_json: Mapped[list] = mapped_column(JsonType, default=list)
    contradicting_evidence_json: Mapped[list] = mapped_column(JsonType, default=list)
    evidence_refs_json: Mapped[list] = mapped_column(JsonType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    run = relationship("AgentCouncilRun")


class AgentCouncilReflection(Base):
    __tablename__ = "agent_council_reflections"
    __table_args__ = (
        UniqueConstraint("run_id", "outcome_id", name="uq_agent_council_reflection_outcome"),
        Index("ix_agent_council_reflections_ticker_created", "ticker", "created_at"),
        Index("ix_agent_council_reflections_result", "direction_correct", "excess_return"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_council_runs.id", ondelete="CASCADE"), index=True
    )
    outcome_id: Mapped[int] = mapped_column(
        ForeignKey("blum_thesis_outcomes.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, index=True)
    expected_action: Mapped[str] = mapped_column(String(32), index=True)
    realized_return: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    excess_return: Mapped[float | None] = mapped_column(Float, index=True)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean, index=True)
    actionability_was_helpful: Mapped[bool | None] = mapped_column(Boolean, index=True)
    lesson: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    run = relationship("AgentCouncilRun")
    outcome = relationship("BlumThesisOutcome")
