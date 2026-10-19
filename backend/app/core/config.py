from functools import lru_cache
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Blum AI Financial Intelligence"
    app_version: str = "2.3.0"
    public_observatory_enabled: bool = Field(default=False, alias="BLUM_PUBLIC_OBSERVATORY_ENABLED")
    environment: str = Field(default="demo", alias="ENVIRONMENT")
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/blum",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    enable_model_loading: bool = Field(default=True, alias="BLUM_ENABLE_MODEL_LOADING")
    finbert_model: str = Field(default="ProsusAI/finbert", alias="BLUM_FINBERT_MODEL")
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", alias="BLUM_EMBEDDING_MODEL")
    llm_model: str = Field(default="Qwen/Qwen2.5-0.5B-Instruct", alias="BLUM_LLM_MODEL")
    enable_financial_brain_model: bool = Field(default=False, alias="BLUM_ENABLE_FINANCIAL_BRAIN_MODEL")
    financial_brain_model: str = Field(default="AdaptLLM/finance-chat", alias="BLUM_FINANCIAL_BRAIN_MODEL")
    financial_brain_max_new_tokens: int = Field(default=420, alias="BLUM_FINANCIAL_BRAIN_MAX_NEW_TOKENS")
    chart_vision_model: str = Field(default="Qwen/Qwen3-VL", alias="CHART_VISION_MODEL")
    chart_vision_fallback_model: str = Field(default="OpenGVLab/InternVL3", alias="CHART_VISION_FALLBACK_MODEL")
    chart_vision_mode: str = Field(default="disabled", alias="CHART_VISION_MODE")
    chart_vision_remote_url: str = Field(default="", alias="CHART_VISION_REMOTE_URL")
    chart_vision_remote_token: str = Field(default="", alias="CHART_VISION_REMOTE_TOKEN")
    chart_vision_min_confidence: float = Field(default=0.70, alias="CHART_VISION_MIN_CONFIDENCE")
    default_benchmark: str = Field(default="SPY", alias="BLUM_DEFAULT_BENCHMARK")
    enable_yfinance_fallback: bool = Field(default=False, alias="BLUM_ENABLE_YFINANCE_FALLBACK")
    max_update_assets: int = Field(default=160, alias="BLUM_MAX_UPDATE_ASSETS")
    enable_live_startup: bool = Field(default=True, alias="BLUM_ENABLE_LIVE_STARTUP")
    enable_autonomous_engine: bool = Field(default=True, alias="BLUM_ENABLE_AUTONOMOUS_ENGINE")
    startup_run_full_autonomous: bool = Field(default=False, alias="BLUM_STARTUP_RUN_FULL_AUTONOMOUS")
    blum_autonomous_max_seconds_per_job: int = Field(default=120, alias="BLUM_AUTONOMOUS_MAX_SECONDS_PER_JOB")
    blum_autonomous_max_items_per_job: int = Field(default=50, alias="BLUM_AUTONOMOUS_MAX_ITEMS_PER_JOB")
    market_refresh_max_items_per_job: int = Field(default=10, alias="BLUM_MARKET_REFRESH_MAX_ITEMS_PER_JOB")
    market_provider_validation_max_items: int = Field(default=2, alias="BLUM_MARKET_PROVIDER_VALIDATION_MAX_ITEMS")
    autonomous_cycle_minutes: int = Field(default=20, alias="BLUM_AUTONOMOUS_CYCLE_MINUTES")
    autonomous_repair_limit: int = Field(default=80, alias="BLUM_AUTONOMOUS_REPAIR_LIMIT")
    seed_historical_prices_on_startup: bool = Field(default=True, alias="BLUM_SEED_HISTORICAL_PRICES_ON_STARTUP")
    seed_signals_on_startup: bool = Field(default=True, alias="BLUM_SEED_SIGNALS_ON_STARTUP")
    seed_accuracy_on_startup: bool = Field(default=True, alias="BLUM_SEED_ACCURACY_ON_STARTUP")
    startup_pipeline_limit: int = Field(default=160, alias="BLUM_STARTUP_PIPELINE_LIMIT")
    news_refresh_minutes: int = Field(default=10, alias="BLUM_NEWS_REFRESH_MINUTES")
    market_refresh_minutes: int = Field(default=45, alias="BLUM_MARKET_REFRESH_MINUTES")
    data_gap_repair_minutes: int = Field(default=180, alias="BLUM_DATA_GAP_REPAIR_MINUTES")
    accuracy_audit_minutes: int = Field(default=240, alias="BLUM_ACCURACY_AUDIT_MINUTES")
    enable_learning_loop: bool = Field(default=True, validation_alias=AliasChoices("LEARNING_LOOP_ENABLED", "BLUM_ENABLE_LEARNING_LOOP"))
    learning_loop_minutes: int = Field(default=360, validation_alias=AliasChoices("LEARNING_LOOP_MINUTES", "BLUM_LEARNING_LOOP_MINUTES"))
    learning_batch_size: int = Field(default=100, alias="LEARNING_BATCH_SIZE")
    learning_max_daily_runs: int = Field(default=5000, alias="LEARNING_MAX_DAILY_RUNS")
    learning_random_seed: str = Field(default="", alias="LEARNING_RANDOM_SEED")
    learning_min_history_years: int = Field(default=3, alias="LEARNING_MIN_HISTORY_YEARS")
    learning_asset_universe: str = Field(default="stocks,etfs", alias="LEARNING_ASSET_UNIVERSE")
    learning_evaluation_mode: str = Field(default="walk_forward", alias="LEARNING_EVALUATION_MODE")
    learning_random_sample_ratio: float = Field(default=0.40, alias="LEARNING_RANDOM_SAMPLE_RATIO")
    learning_alpha_loss_sample_ratio: float = Field(default=0.30, alias="LEARNING_ALPHA_LOSS_SAMPLE_RATIO")
    learning_factor_focus_sample_ratio: float = Field(default=0.20, alias="LEARNING_FACTOR_FOCUS_SAMPLE_RATIO")
    learning_capital_preservation_sample_ratio: float = Field(default=0.10, alias="LEARNING_CAPITAL_PRESERVATION_SAMPLE_RATIO")
    professional_learning_enabled: bool = Field(default=True, alias="BLUM_PROFESSIONAL_LEARNING_ENABLED")
    professional_learning_minutes: int = Field(default=30, alias="BLUM_PROFESSIONAL_LEARNING_MINUTES")
    professional_learning_batch_size: int = Field(default=20, alias="BLUM_PROFESSIONAL_LEARNING_BATCH_SIZE")
    blum_model_cycle_minutes: int = Field(default=5, alias="BLUM_MODEL_CYCLE_MINUTES")
    blum_model_cycle_limit: int = Field(default=160, alias="BLUM_MODEL_CYCLE_LIMIT")
    fundamentals_refresh_minutes: int = Field(default=720, alias="BLUM_FUNDAMENTALS_REFRESH_MINUTES")
    macro_refresh_minutes: int = Field(default=240, alias="BLUM_MACRO_REFRESH_MINUTES")
    stale_price_max_age_days: int = Field(default=7, alias="BLUM_STALE_PRICE_MAX_AGE_DAYS")
    minimum_history_rows: int = Field(default=220, alias="BLUM_MINIMUM_HISTORY_ROWS")
    ipo_refresh_minutes: int = Field(default=120, alias="BLUM_IPO_REFRESH_MINUTES")
    news_fetch_workers: int = Field(default=10, alias="BLUM_NEWS_FETCH_WORKERS")
    max_dynamic_asset_news_feeds: int = Field(default=60, alias="BLUM_MAX_DYNAMIC_ASSET_NEWS_FEEDS")
    historical_price_period: str = Field(default="max", alias="BLUM_HISTORICAL_PRICE_PERIOD")
    refresh_price_period: str = Field(default="6mo", alias="BLUM_REFRESH_PRICE_PERIOD")
    sec_user_agent: str = Field(default="Blum-AI-Financial-Intelligence research demo", alias="BLUM_SEC_USER_AGENT")
    blum_model_repository: str = Field(default="Italianhype/Blum", alias="BLUM_MODEL_REPOSITORY")
    blum_analyst_repository: str = Field(default="Italianhype/Blum-Analyst", alias="BLUM_ANALYST_REPOSITORY")
    training_export_dir: str = Field(default="/tmp/blum_training_exports", alias="BLUM_TRAINING_EXPORT_DIR")
    ascent_enabled: bool = Field(default=False, alias="BLUM_ASCENT_ENABLED")
    ascent_scheduler_enabled: bool = Field(default=False, alias="BLUM_ASCENT_SCHEDULER_ENABLED")
    ascent_interval_minutes: int = Field(default=360, ge=60, alias="BLUM_ASCENT_INTERVAL_MINUTES")
    ascent_max_rows: int = Field(default=2000, ge=400, le=2000, alias="BLUM_ASCENT_MAX_ROWS")
    ascent_max_seconds: int = Field(default=90, ge=1, le=90, alias="BLUM_ASCENT_MAX_SECONDS")
    ascent_artifact_root: str = Field(default="/data/ascent", alias="BLUM_ASCENT_ARTIFACT_ROOT")
    ascent_admin_key: str = Field(default="", alias="BLUM_ASCENT_ADMIN_KEY")

    hf_training_enabled: bool = Field(default=False, alias="BLUM_HF_TRAINING_ENABLED")
    hf_training_auto_launch: bool = Field(default=False, alias="BLUM_HF_TRAINING_AUTO_LAUNCH")
    hf_training_scheduler_enabled: bool = Field(default=False, alias="BLUM_HF_TRAINING_SCHEDULER_ENABLED")
    hf_training_supervisor_minutes: int = Field(default=60, alias="BLUM_HF_TRAINING_SUPERVISOR_MINUTES")
    hf_dataset_snapshot_enabled: bool = Field(default=True, alias="BLUM_HF_DATASET_SNAPSHOT_ENABLED")
    hf_dataset_snapshot_dir: str = Field(default="/data/blum_model_snapshots", alias="BLUM_HF_DATASET_SNAPSHOT_DIR")
    hf_training_dataset_repository: str = Field(default="Italianhype/Blum-Finance-Reasoning", alias="BLUM_HF_DATASET_REPOSITORY")
    hf_training_champion_repository: str = Field(default="Italianhype/Blum-Finance-4B", alias="BLUM_HF_CHAMPION_REPOSITORY")
    hf_training_challenger_repository: str = Field(default="Italianhype/Blum-Finance-4B-Challenger", alias="BLUM_HF_CHALLENGER_REPOSITORY")
    hf_training_mlx_repository: str = Field(default="Italianhype/Blum", alias="BLUM_HF_MLX_REPOSITORY")
    hf_training_base_model: str = Field(default="Qwen/Qwen3-4B", alias="BLUM_HF_BASE_MODEL")
    hf_training_hardware: str = Field(default="a10g-large", alias="BLUM_HF_TRAINING_HARDWARE")
    hf_training_job_image: str = Field(default="", alias="BLUM_HF_TRAINING_IMAGE")
    hf_training_timeout: str = Field(default="8h", alias="BLUM_HF_TRAINING_TIMEOUT")
    hf_training_max_examples: int = Field(default=5000, alias="BLUM_HF_TRAINING_MAX_EXAMPLES")
    hf_training_minimum_examples: int = Field(default=250, alias="BLUM_HF_TRAINING_MINIMUM_EXAMPLES")
    hf_training_minimum_matured_ratio: float = Field(default=0.80, alias="BLUM_HF_TRAINING_MINIMUM_MATURED_RATIO")
    hf_training_minimum_days_between_runs: int = Field(default=30, alias="BLUM_HF_TRAINING_MINIMUM_DAYS_BETWEEN_RUNS")
    hf_training_minimum_quality: float = Field(default=70.0, alias="BLUM_HF_TRAINING_MINIMUM_QUALITY")
    hf_training_admin_key: str = Field(default="", alias="BLUM_HF_TRAINING_ADMIN_KEY")
    hf_training_eval_max_examples: int = Field(default=53, alias="BLUM_HF_EVAL_MAX_EXAMPLES")
    enable_hf_dataset_catalog: bool = Field(default=True, alias="BLUM_ENABLE_HF_DATASET_CATALOG")
    hf_dataset_refresh_hours: int = Field(default=24, alias="BLUM_HF_DATASET_REFRESH_HOURS")
    hf_dataset_max_sources: int = Field(default=40, alias="BLUM_HF_DATASET_MAX_SOURCES")
    trading_min_timeframe: str = Field(default="4h", alias="TRADING_MIN_TIMEFRAME")
    trading_default_timeframe: str = Field(default="daily", alias="TRADING_DEFAULT_TIMEFRAME")
    trading_allow_microscalping: bool = Field(default=False, alias="TRADING_ALLOW_MICROSCALPING")
    trading_require_reproducible_setup: bool = Field(default=True, alias="TRADING_REQUIRE_REPRODUCIBLE_SETUP")
    trading_curriculum_enabled: bool = True
    trading_curriculum_minutes: int = Field(default=1, ge=1, le=60)
    trading_ml_enabled: bool = True
    trading_ml_worker_minutes: int = 15
    trading_ml_new_label_threshold: int = 25
    trading_ml_max_runtime_seconds: int = 120
    trading_ml_max_rows_per_slice: int = 500
    trading_ml_online_max_rows_per_slice: int = Field(default=10_000, ge=1, le=100_000)
    trading_ml_min_replay_samples: int = 300
    trading_ml_min_folds: int = 3
    trading_ml_min_assets: int = 6
    trading_ml_brier_improvement: float = 0.05
    trading_ml_max_confidence_adjustment: float = 5.0
    trading_ml_max_combined_adjustment: float = 10.0
    trading_ml_optuna_trials: int = 12
    trading_ml_optuna_timeout_seconds: int = 90
    trading_ml_artifact_root: str = "/data/trading_ml"
    forex_history_enabled: bool = Field(
        default=False,
        alias="BLUM_FOREX_HISTORY_ENABLED",
    )
    forex_history_source_path: str = Field(
        default="",
        alias="BLUM_FOREX_HISTORY_SOURCE_PATH",
    )
    forex_history_sample_weight: float = Field(
        default=0.25,
        alias="BLUM_FOREX_HISTORY_SAMPLE_WEIGHT",
    )
    finrlx_enabled: bool = Field(default=False, alias="BLUM_FINRLX_ENABLED")
    finrlx_runner_command: str = Field(default="", alias="BLUM_FINRLX_RUNNER_COMMAND")
    finrlx_artifact_root: str = Field(default="/data/trading_ml/finrlx", alias="BLUM_FINRLX_ARTIFACT_ROOT")
    finrlx_manifest_path: str = Field(default="", alias="BLUM_FINRLX_MANIFEST_PATH")
    finrlx_feature_schema_hash: str = Field(default="", alias="BLUM_FINRLX_FEATURE_SCHEMA_HASH")
    finrlx_timeout_seconds: int = Field(default=90, alias="BLUM_FINRLX_TIMEOUT_SECONDS")
    trading_game_enabled: bool = Field(default=True, alias="TRADING_GAME_ENABLED")
    trading_game_initial_capital: float = Field(default=100.0, alias="TRADING_GAME_INITIAL_CAPITAL")
    trading_game_target_capital: float = Field(default=10000.0, alias="TRADING_GAME_TARGET_CAPITAL")
    trading_game_reset_on_target: bool = Field(default=True, alias="TRADING_GAME_RESET_ON_TARGET")
    trading_game_reset_on_bankruptcy: bool = Field(default=True, alias="TRADING_GAME_RESET_ON_BANKRUPTCY")
    trading_game_max_cycle_days: int = Field(default=365, alias="TRADING_GAME_MAX_CYCLE_DAYS")
    trading_game_batch_size: int = Field(default=60, alias="TRADING_GAME_BATCH_SIZE")
    trading_game_max_risk_percent: float = Field(default=2.0, alias="TRADING_GAME_MAX_RISK_PERCENT")
    trading_game_default_risk_percent: float = Field(default=1.0, alias="TRADING_GAME_DEFAULT_RISK_PERCENT")
    trading_game_benchmark: str = Field(default="SPY", alias="TRADING_GAME_BENCHMARK")
    live_trading_game_enabled: bool = Field(default=True, alias="LIVE_TRADING_GAME_ENABLED")
    live_trading_game_initial_capital: float = Field(default=100.0, alias="LIVE_TRADING_GAME_INITIAL_CAPITAL")
    live_trading_game_target_capital: float = Field(default=10000.0, alias="LIVE_TRADING_GAME_TARGET_CAPITAL")
    live_trading_game_max_open_positions: int = Field(default=5, alias="LIVE_TRADING_GAME_MAX_OPEN_POSITIONS")
    live_trading_game_max_risk_per_trade: float = Field(default=1.0, alias="LIVE_TRADING_GAME_MAX_RISK_PER_TRADE")
    live_trading_game_require_actionable_setup: bool = Field(default=True, alias="LIVE_TRADING_GAME_REQUIRE_ACTIONABLE_SETUP")
    live_trading_game_allow_fractional_shares: bool = Field(default=True, alias="LIVE_TRADING_GAME_ALLOW_FRACTIONAL_SHARES")
    live_trading_game_benchmark: str = Field(default="SPY", alias="LIVE_TRADING_GAME_BENCHMARK")
    intraday_paper_enabled: bool = Field(default=True, alias="BLUM_INTRADAY_PAPER_ENABLED")
    intraday_paper_minutes: int = Field(default=2, alias="BLUM_INTRADAY_PAPER_MINUTES")
    intraday_max_assets_per_run: int = Field(default=20, alias="BLUM_INTRADAY_MAX_ASSETS_PER_RUN")
    intraday_max_runtime_seconds: int = Field(default=45, alias="BLUM_INTRADAY_MAX_RUNTIME_SECONDS")
    intraday_max_open_positions: int = Field(default=5, alias="BLUM_INTRADAY_MAX_OPEN_POSITIONS")
    intraday_max_positions_per_market: int = Field(default=3, alias="BLUM_INTRADAY_MAX_POSITIONS_PER_MARKET")
    intraday_max_positions_per_desk: int = Field(default=2, alias="BLUM_INTRADAY_MAX_POSITIONS_PER_DESK")
    intraday_max_positions_per_asset_class: int = Field(default=3, alias="BLUM_INTRADAY_MAX_POSITIONS_PER_ASSET_CLASS")
    intraday_max_total_risk_percent: float = Field(default=5.0, alias="BLUM_INTRADAY_MAX_TOTAL_RISK_PERCENT")
    intraday_max_holding_minutes: int = Field(default=90, alias="BLUM_INTRADAY_MAX_HOLDING_MINUTES")
    intraday_min_expected_move_bps: float = Field(default=12.0, alias="BLUM_INTRADAY_MIN_EXPECTED_MOVE_BPS")
    intraday_max_spread_to_target_ratio: float = Field(default=0.25, alias="BLUM_INTRADAY_MAX_SPREAD_TO_TARGET_RATIO")
    intraday_min_liquidity_score: float = Field(default=35.0, alias="BLUM_INTRADAY_MIN_LIQUIDITY_SCORE")
    intraday_min_volatility_bps: float = Field(default=1.0, alias="BLUM_INTRADAY_MIN_VOLATILITY_BPS")
    intraday_max_one_minute_age_minutes: int = Field(default=3, alias="BLUM_INTRADAY_MAX_ONE_MINUTE_AGE_MINUTES")
    intraday_experimental_paper_enabled: bool = Field(default=True, alias="BLUM_INTRADAY_EXPERIMENTAL_PAPER_ENABLED")
    intraday_experimental_min_samples: int = Field(default=50, alias="BLUM_INTRADAY_EXPERIMENTAL_MIN_SAMPLES")
    intraday_experimental_risk_multiplier: float = Field(default=0.25, alias="BLUM_INTRADAY_EXPERIMENTAL_RISK_MULTIPLIER")
    strategy_factory_enabled: bool = Field(default=True, alias="BLUM_STRATEGY_FACTORY_ENABLED")
    strategy_factory_minutes: int = Field(default=15, alias="BLUM_STRATEGY_FACTORY_MINUTES")
    strategy_factory_max_variants_per_family: int = Field(default=24, alias="BLUM_STRATEGY_FACTORY_MAX_VARIANTS_PER_FAMILY")
    strategy_factory_seed: int = Field(default=7, alias="BLUM_STRATEGY_FACTORY_SEED")
    paper_execution_lifecycle_minutes: int = Field(default=1, alias="BLUM_PAPER_EXECUTION_LIFECYCLE_MINUTES")
    paper_execution_account_currency: str = Field(default="EUR", alias="BLUM_PAPER_EXECUTION_ACCOUNT_CURRENCY")
    paper_execution_fx_spread_bps: float = Field(default=2.0, alias="BLUM_PAPER_EXECUTION_FX_SPREAD_BPS")
    intraday_allow_overnight: bool = Field(default=False, alias="BLUM_INTRADAY_ALLOW_OVERNIGHT")
    intraday_no_trade_evaluation_minutes: int = Field(default=30, alias="BLUM_INTRADAY_NO_TRADE_EVALUATION_MINUTES")
    forex_trader_enabled: bool = Field(default=True, alias="BLUM_FOREX_TRADER_ENABLED")
    forex_trader_minutes: int = Field(default=1, alias="BLUM_FOREX_TRADER_MINUTES")
    forex_trader_max_pairs_per_cycle: int = Field(default=12, alias="BLUM_FOREX_TRADER_MAX_PAIRS_PER_CYCLE")
    forex_trader_refresh_pairs_per_cycle: int = Field(default=1, alias="BLUM_FOREX_TRADER_REFRESH_PAIRS_PER_CYCLE")
    forex_trader_freshness_budget_minutes: int = Field(default=3, alias="BLUM_FOREX_TRADER_FRESHNESS_BUDGET_MINUTES")
    forex_risk_per_trade_percent: float = Field(default=0.5, alias="BLUM_FOREX_RISK_PER_TRADE_PERCENT")
    forex_daily_loss_limit_percent: float = Field(default=2.0, alias="BLUM_FOREX_DAILY_LOSS_LIMIT_PERCENT")
    forex_max_open_positions: int = Field(default=4, alias="BLUM_FOREX_MAX_OPEN_POSITIONS")
    forex_alpha_min_forward_trades: int = Field(default=100, alias="BLUM_FOREX_ALPHA_MIN_FORWARD_TRADES")
    forex_alpha_min_expectancy_r: float = Field(default=0.0, alias="BLUM_FOREX_ALPHA_MIN_EXPECTANCY_R")
    forex_alpha_min_benchmark_excess: float = Field(default=0.0, alias="BLUM_FOREX_ALPHA_MIN_BENCHMARK_EXCESS")
    forex_alpha_max_drawdown_r: float = Field(default=15.0, alias="BLUM_FOREX_ALPHA_MAX_DRAWDOWN_R")
    forex_alpha_min_pairs: int = Field(default=2, alias="BLUM_FOREX_ALPHA_MIN_PAIRS")
    forex_alpha_min_sessions: int = Field(default=2, alias="BLUM_FOREX_ALPHA_MIN_SESSIONS")
    forex_alpha_min_regimes: int = Field(default=2, alias="BLUM_FOREX_ALPHA_MIN_REGIMES")
    forex_alpha_max_replay_forward_decay: float = Field(default=0.5, alias="BLUM_FOREX_ALPHA_MAX_REPLAY_FORWARD_DECAY")
    forex_alpha_max_currency_concentration: float = Field(default=0.7, alias="BLUM_FOREX_ALPHA_MAX_CURRENCY_CONCENTRATION")
    forex_alpha_threshold_version: str = Field(default="forex-alpha-readiness-v1", alias="BLUM_FOREX_ALPHA_THRESHOLD_VERSION")
    forex_news_block_before_minutes: int = Field(default=30, alias="BLUM_FOREX_NEWS_BLOCK_BEFORE_MINUTES")
    forex_news_block_after_minutes: int = Field(default=30, alias="BLUM_FOREX_NEWS_BLOCK_AFTER_MINUTES")
    paper_forward_lifecycle_enabled: bool = Field(default=False, alias="PAPER_FORWARD_LIFECYCLE_ENABLED")
    paper_forward_max_holding_days: int = Field(default=10, alias="PAPER_FORWARD_MAX_HOLDING_DAYS")
    paper_forward_min_confidence: float = Field(default=50.0, alias="PAPER_FORWARD_MIN_CONFIDENCE")
    paper_forward_min_risk_reward: float = Field(default=1.0, alias="PAPER_FORWARD_MIN_RISK_REWARD")
    paper_forward_min_data_quality: float = Field(default=50.0, alias="PAPER_FORWARD_MIN_DATA_QUALITY")
    paper_forward_max_candidates_per_run: int = Field(default=30, alias="PAPER_FORWARD_MAX_CANDIDATES_PER_RUN")
    paper_forward_allow_watchlist_candidates: bool = Field(default=True, alias="PAPER_FORWARD_ALLOW_WATCHLIST_CANDIDATES")
    paper_forward_allow_trade_candidates: bool = Field(default=True, alias="PAPER_FORWARD_ALLOW_TRADE_CANDIDATES")
    paper_forward_enabled_markets: str = Field(
        default="us_equities,european_equities,global_equities,etfs,indexes,commodities,forex,crypto,bonds,volatility",
        alias="PAPER_FORWARD_ENABLED_MARKETS",
    )
    paper_forward_enabled_asset_classes: str = Field(
        default="equities,etfs,indexes,commodities,forex,crypto,bonds,volatility",
        alias="PAPER_FORWARD_ENABLED_ASSET_CLASSES",
    )
    paper_forward_require_benchmark: bool = Field(default=False, alias="PAPER_FORWARD_REQUIRE_BENCHMARK")
    paper_forward_min_liquidity_score: float = Field(default=0.0, alias="PAPER_FORWARD_MIN_LIQUIDITY_SCORE")
    paper_forward_max_assets_per_market: int = Field(default=25, alias="PAPER_FORWARD_MAX_ASSETS_PER_MARKET")
    paper_forward_scan_stale_data_max_age_hours: float = Field(default=72.0, alias="PAPER_FORWARD_SCAN_STALE_DATA_MAX_AGE_HOURS")
    paper_forward_cross_market_ranking_enabled: bool = Field(default=True, alias="PAPER_FORWARD_CROSS_MARKET_RANKING_ENABLED")
    copy_readiness_threshold_version: str = Field(
        default="copy-readiness-v1",
        validation_alias=AliasChoices("COPY_READINESS_THRESHOLD_VERSION", "BLUM_COPY_READINESS_THRESHOLD_VERSION"),
    )
    copy_readiness_global_forward_trades: int = Field(
        default=100,
        validation_alias=AliasChoices("COPY_READINESS_GLOBAL_FORWARD_TRADES", "BLUM_COPY_READINESS_GLOBAL_FORWARD_TRADES"),
    )
    copy_readiness_strategy_forward_trades: int = Field(
        default=30,
        validation_alias=AliasChoices("COPY_READINESS_STRATEGY_FORWARD_TRADES", "BLUM_COPY_READINESS_STRATEGY_FORWARD_TRADES"),
    )
    copy_readiness_observation_days: int = Field(
        default=90,
        validation_alias=AliasChoices("COPY_READINESS_OBSERVATION_DAYS", "BLUM_COPY_READINESS_OBSERVATION_DAYS"),
    )
    copy_readiness_max_drawdown: float = Field(
        default=15.0,
        validation_alias=AliasChoices("COPY_READINESS_MAX_DRAWDOWN", "BLUM_COPY_READINESS_MAX_DRAWDOWN"),
    )
    copy_readiness_max_decay_pct: float = Field(
        default=35.0,
        validation_alias=AliasChoices("COPY_READINESS_MAX_DECAY_PCT", "BLUM_COPY_READINESS_MAX_DECAY_PCT"),
    )
    copy_readiness_min_tickers: int = Field(
        default=5,
        validation_alias=AliasChoices("COPY_READINESS_MIN_TICKERS", "BLUM_COPY_READINESS_MIN_TICKERS"),
    )
    copy_readiness_min_regimes: int = Field(
        default=2,
        validation_alias=AliasChoices("COPY_READINESS_MIN_REGIMES", "BLUM_COPY_READINESS_MIN_REGIMES"),
    )
    copy_readiness_max_ticker_concentration: float = Field(
        default=0.35,
        validation_alias=AliasChoices(
            "COPY_READINESS_MAX_TICKER_CONCENTRATION",
            "BLUM_COPY_READINESS_MAX_TICKER_CONCENTRATION",
        ),
    )
    copy_readiness_max_market_concentration: float = Field(
        default=0.70,
        validation_alias=AliasChoices(
            "COPY_READINESS_MAX_MARKET_CONCENTRATION",
            "BLUM_COPY_READINESS_MAX_MARKET_CONCENTRATION",
        ),
    )
    copy_readiness_high_confidence_global_forward_trades: int = Field(
        default=300,
        validation_alias=AliasChoices(
            "COPY_READINESS_HIGH_CONFIDENCE_GLOBAL_FORWARD_TRADES",
            "BLUM_COPY_READINESS_HIGH_CONFIDENCE_GLOBAL_FORWARD_TRADES",
        ),
    )
    copy_readiness_high_confidence_strategy_forward_trades: int = Field(
        default=100,
        validation_alias=AliasChoices(
            "COPY_READINESS_HIGH_CONFIDENCE_STRATEGY_FORWARD_TRADES",
            "BLUM_COPY_READINESS_HIGH_CONFIDENCE_STRATEGY_FORWARD_TRADES",
        ),
    )
    copy_readiness_high_confidence_observation_days: int = Field(
        default=180,
        validation_alias=AliasChoices(
            "COPY_READINESS_HIGH_CONFIDENCE_OBSERVATION_DAYS",
            "BLUM_COPY_READINESS_HIGH_CONFIDENCE_OBSERVATION_DAYS",
        ),
    )
    copy_readiness_high_confidence_max_drawdown: float = Field(
        default=12.0,
        validation_alias=AliasChoices(
            "COPY_READINESS_HIGH_CONFIDENCE_MAX_DRAWDOWN",
            "BLUM_COPY_READINESS_HIGH_CONFIDENCE_MAX_DRAWDOWN",
        ),
    )
    copy_readiness_high_confidence_max_decay_pct: float = Field(
        default=25.0,
        validation_alias=AliasChoices(
            "COPY_READINESS_HIGH_CONFIDENCE_MAX_DECAY_PCT",
            "BLUM_COPY_READINESS_HIGH_CONFIDENCE_MAX_DECAY_PCT",
        ),
    )
    copy_readiness_high_confidence_min_tickers: int = Field(
        default=8,
        validation_alias=AliasChoices(
            "COPY_READINESS_HIGH_CONFIDENCE_MIN_TICKERS",
            "BLUM_COPY_READINESS_HIGH_CONFIDENCE_MIN_TICKERS",
        ),
    )
    copy_readiness_high_confidence_min_regimes: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "COPY_READINESS_HIGH_CONFIDENCE_MIN_REGIMES",
            "BLUM_COPY_READINESS_HIGH_CONFIDENCE_MIN_REGIMES",
        ),
    )
    copy_readiness_high_confidence_max_ticker_concentration: float = Field(
        default=0.30,
        validation_alias=AliasChoices(
            "COPY_READINESS_HIGH_CONFIDENCE_MAX_TICKER_CONCENTRATION",
            "BLUM_COPY_READINESS_HIGH_CONFIDENCE_MAX_TICKER_CONCENTRATION",
        ),
    )
    copy_readiness_high_confidence_max_market_concentration: float = Field(
        default=0.60,
        validation_alias=AliasChoices(
            "COPY_READINESS_HIGH_CONFIDENCE_MAX_MARKET_CONCENTRATION",
            "BLUM_COPY_READINESS_HIGH_CONFIDENCE_MAX_MARKET_CONCENTRATION",
        ),
    )
    limited_external_validation_global_forward_trades: int = Field(
        default=500,
        validation_alias=AliasChoices(
            "LIMITED_EXTERNAL_VALIDATION_GLOBAL_FORWARD_TRADES",
            "BLUM_LIMITED_EXTERNAL_VALIDATION_GLOBAL_FORWARD_TRADES",
        ),
    )
    limited_external_validation_strategy_forward_trades: int = Field(
        default=150,
        validation_alias=AliasChoices(
            "LIMITED_EXTERNAL_VALIDATION_STRATEGY_FORWARD_TRADES",
            "BLUM_LIMITED_EXTERNAL_VALIDATION_STRATEGY_FORWARD_TRADES",
        ),
    )
    limited_external_validation_observation_days: int = Field(
        default=270,
        validation_alias=AliasChoices(
            "LIMITED_EXTERNAL_VALIDATION_OBSERVATION_DAYS",
            "BLUM_LIMITED_EXTERNAL_VALIDATION_OBSERVATION_DAYS",
        ),
    )
    limited_external_validation_max_drawdown: float = Field(
        default=10.0,
        validation_alias=AliasChoices(
            "LIMITED_EXTERNAL_VALIDATION_MAX_DRAWDOWN",
            "BLUM_LIMITED_EXTERNAL_VALIDATION_MAX_DRAWDOWN",
        ),
    )
    limited_external_validation_max_decay_pct: float = Field(
        default=20.0,
        validation_alias=AliasChoices(
            "LIMITED_EXTERNAL_VALIDATION_MAX_DECAY_PCT",
            "BLUM_LIMITED_EXTERNAL_VALIDATION_MAX_DECAY_PCT",
        ),
    )
    limited_external_validation_min_tickers: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "LIMITED_EXTERNAL_VALIDATION_MIN_TICKERS",
            "BLUM_LIMITED_EXTERNAL_VALIDATION_MIN_TICKERS",
        ),
    )
    limited_external_validation_min_regimes: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "LIMITED_EXTERNAL_VALIDATION_MIN_REGIMES",
            "BLUM_LIMITED_EXTERNAL_VALIDATION_MIN_REGIMES",
        ),
    )
    limited_external_validation_max_ticker_concentration: float = Field(
        default=0.30,
        validation_alias=AliasChoices(
            "LIMITED_EXTERNAL_VALIDATION_MAX_TICKER_CONCENTRATION",
            "BLUM_LIMITED_EXTERNAL_VALIDATION_MAX_TICKER_CONCENTRATION",
        ),
    )
    limited_external_validation_max_market_concentration: float = Field(
        default=0.60,
        validation_alias=AliasChoices(
            "LIMITED_EXTERNAL_VALIDATION_MAX_MARKET_CONCENTRATION",
            "BLUM_LIMITED_EXTERNAL_VALIDATION_MAX_MARKET_CONCENTRATION",
        ),
    )
    blum_enabled_market_desk_agents: str = Field(
        default=(
            "FTSEMIBAgent,DAXAgent,CAC40Agent,IBEX35Agent,SMIAgent,EuroStoxx50Agent,"
            "WallStreetAgent,SP500Agent,NasdaqAgent,DowJonesAgent,Russell2000Agent,"
            "NikkeiAgent,HangSengAgent,IndiaNiftyAgent,ChinaAAgent,EmergingMarketsAgent,"
            "ETFDeskAgent,CryptoDeskAgent,ForexDeskAgent,CommodityDeskAgent,"
            "RatesBondProxyAgent,VolatilityDeskAgent"
        ),
        alias="BLUM_ENABLED_MARKET_DESK_AGENTS",
    )
    blum_max_candidates_per_agent: int = Field(default=5, alias="BLUM_MAX_CANDIDATES_PER_AGENT")
    blum_max_candidates_per_market: int = Field(default=8, alias="BLUM_MAX_CANDIDATES_PER_MARKET")
    blum_max_candidates_per_asset_class: int = Field(default=12, alias="BLUM_MAX_CANDIDATES_PER_ASSET_CLASS")
    blum_max_candidates_per_ticker: int = Field(default=1, alias="BLUM_MAX_CANDIDATES_PER_TICKER")
    blum_cross_market_orchestrator_enabled: bool = Field(default=True, alias="BLUM_CROSS_MARKET_ORCHESTRATOR_ENABLED")
    blum_quant_edge_min_score: float = Field(default=60.0, alias="BLUM_QUANT_EDGE_MIN_SCORE")
    blum_quant_edge_min_sample_size: int = Field(default=20, alias="BLUM_QUANT_EDGE_MIN_SAMPLE_SIZE")
    blum_reject_high_overfitting_risk: bool = Field(default=True, alias="BLUM_REJECT_HIGH_OVERFITTING_RISK")
    blum_learning_acceleration_enabled: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_ENABLED")
    blum_learning_acceleration_max_batches_per_run: int = Field(default=3, alias="BLUM_LEARNING_ACCELERATION_MAX_BATCHES_PER_RUN")
    blum_learning_acceleration_max_assets_per_run: int = Field(default=30, alias="BLUM_LEARNING_ACCELERATION_MAX_ASSETS_PER_RUN")
    blum_learning_acceleration_min_samples: int = Field(default=20, alias="BLUM_LEARNING_ACCELERATION_MIN_SAMPLES")
    blum_learning_acceleration_max_runtime_seconds: int = Field(default=20, alias="BLUM_LEARNING_ACCELERATION_MAX_RUNTIME_SECONDS")
    blum_learning_acceleration_budget_guard_enabled: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_BUDGET_GUARD_ENABLED")
    blum_learning_acceleration_prioritize_uncertainty: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_PRIORITIZE_UNCERTAINTY")
    blum_learning_acceleration_prioritize_missed_winners: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_PRIORITIZE_MISSED_WINNERS")
    blum_learning_acceleration_prioritize_repeated_blockers: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_PRIORITIZE_REPEATED_BLOCKERS")
    blum_experiment_manager_enabled: bool = Field(default=True, alias="BLUM_EXPERIMENT_MANAGER_ENABLED")
    blum_experiment_max_active_experiments: int = Field(default=5, alias="BLUM_EXPERIMENT_MAX_ACTIVE_EXPERIMENTS")
    replay_training_enabled: bool = Field(default=True, alias="BLUM_REPLAY_TRAINING_ENABLED")
    replay_training_minutes: int = Field(default=15, alias="BLUM_REPLAY_TRAINING_MINUTES")
    replay_target_validated_trades_per_day: int = Field(default=5000, alias="BLUM_REPLAY_TARGET_VALIDATED_TRADES_PER_DAY")
    replay_max_seconds_per_cycle: int = Field(default=120, alias="BLUM_REPLAY_MAX_SECONDS_PER_CYCLE")
    replay_max_assets_per_cycle: int = Field(default=20, alias="BLUM_REPLAY_MAX_ASSETS_PER_CYCLE")
    replay_max_trades_per_cycle: int = Field(default=500, alias="BLUM_REPLAY_MAX_TRADES_PER_CYCLE")
    replay_max_experiments_per_cycle: int = Field(default=5, alias="BLUM_REPLAY_MAX_EXPERIMENTS_PER_CYCLE")
    replay_min_promotion_samples: int = Field(default=300, alias="BLUM_REPLAY_MIN_PROMOTION_SAMPLES")
    replay_cpu_throttle_percent: float = Field(default=80.0, alias="BLUM_REPLAY_CPU_THROTTLE_PERCENT")
    replay_cpu_pause_percent: float = Field(default=95.0, alias="BLUM_REPLAY_CPU_PAUSE_PERCENT")
    replay_memory_throttle_percent: float = Field(default=80.0, alias="BLUM_REPLAY_MEMORY_THROTTLE_PERCENT")
    replay_memory_pause_percent: float = Field(default=92.0, alias="BLUM_REPLAY_MEMORY_PAUSE_PERCENT")
    replay_api_throttle_p95_ms: float = Field(default=2000.0, alias="BLUM_REPLAY_API_THROTTLE_P95_MS")
    replay_api_pause_p95_ms: float = Field(default=5000.0, alias="BLUM_REPLAY_API_PAUSE_P95_MS")
    replay_markets: str = Field(default="UNITED STATES,USA,ITALY,GERMANY,FRANCE,EUROPE,FOREX", alias="BLUM_REPLAY_MARKETS")
    replay_timeframes: str = Field(default="1d,1h,15m,5m,1m", alias="BLUM_REPLAY_TIMEFRAMES")
    replay_provider_priority: str = Field(default="yahoo_chart,yfinance,stooq,nasdaq", alias="BLUM_REPLAY_PROVIDER_PRIORITY")
    replay_min_data_quality: float = Field(default=35.0, alias="BLUM_REPLAY_MIN_DATA_QUALITY")
    self_improvement_enabled: bool = Field(default=True, alias="SELF_IMPROVEMENT_ENABLED")
    self_improvement_auto_apply: bool = Field(default=False, alias="SELF_IMPROVEMENT_AUTO_APPLY")
    self_improvement_auto_apply_low_risk: bool = Field(default=True, alias="SELF_IMPROVEMENT_AUTO_APPLY_LOW_RISK")
    self_improvement_min_sample_size: int = Field(default=50, alias="SELF_IMPROVEMENT_MIN_SAMPLE_SIZE")
    self_improvement_require_benchmark_check: bool = Field(default=True, alias="SELF_IMPROVEMENT_REQUIRE_BENCHMARK_CHECK")
    self_improvement_require_live_confirmation: bool = Field(default=False, alias="SELF_IMPROVEMENT_REQUIRE_LIVE_CONFIRMATION")
    self_improvement_rollback_enabled: bool = Field(default=True, alias="SELF_IMPROVEMENT_ROLLBACK_ENABLED")
    blum_nautilus_enabled: bool = Field(default=True, alias="BLUM_NAUTILUS_ENABLED")
    blum_nautilus_mode: str = Field(default="shadow", alias="BLUM_NAUTILUS_MODE")
    blum_nautilus_asset_classes: str = Field(default="equity,etf,forex", alias="BLUM_NAUTILUS_ASSET_CLASSES")
    blum_nautilus_crypto_enabled: bool = Field(default=False, alias="BLUM_NAUTILUS_CRYPTO_ENABLED")
    blum_nautilus_authoritative_auto_promote: bool = Field(default=True, alias="BLUM_NAUTILUS_AUTHORITATIVE_AUTO_PROMOTE")
    blum_nautilus_min_parity_samples: int = Field(default=100, alias="BLUM_NAUTILUS_MIN_PARITY_SAMPLES")
    blum_nautilus_max_job_seconds: int = Field(default=120, alias="BLUM_NAUTILUS_MAX_JOB_SECONDS")
    blum_nautilus_max_items_per_job: int = Field(default=5000, alias="BLUM_NAUTILUS_MAX_ITEMS_PER_JOB")
    blum_nautilus_catalog_path: str = Field(default="/data/blum/nautilus/catalog", alias="BLUM_NAUTILUS_CATALOG_PATH")
    blum_nautilus_fallback_enabled: bool = Field(default=True, alias="BLUM_NAUTILUS_FALLBACK_ENABLED")
    decision_council_enabled: bool = Field(default=True, alias="BLUM_DECISION_COUNCIL_ENABLED")
    decision_council_minutes: int = Field(default=10, alias="BLUM_DECISION_COUNCIL_MINUTES")
    decision_council_max_items: int = Field(default=25, alias="BLUM_DECISION_COUNCIL_MAX_ITEMS")
    decision_council_min_evidence_sources: int = Field(default=2, alias="BLUM_DECISION_COUNCIL_MIN_EVIDENCE_SOURCES")
    decision_council_min_memory_samples: int = Field(default=5, alias="BLUM_DECISION_COUNCIL_MIN_MEMORY_SAMPLES")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
