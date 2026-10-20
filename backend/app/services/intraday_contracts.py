from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


PAPER_FORWARD_INTRADAY = "PAPER_FORWARD_INTRADAY"
PAPER_FORWARD_INTRADAY_EXPERIMENTAL = "PAPER_FORWARD_INTRADAY_EXPERIMENTAL"
INTRADAY_TRADE_CANDIDATE = "INTRADAY_TRADE_CANDIDATE"
INTRADAY_WATCHLIST = "INTRADAY_WATCHLIST"
INTRADAY_BLOCKED = "INTRADAY_BLOCKED"
INTRADAY_DATA_BLOCKED = "INTRADAY_DATA_BLOCKED"
REQUIRED_INTRADAY_TIMEFRAMES = ("1d", "15m", "5m", "1m")


@dataclass(frozen=True)
class PromotedIntradayStrategy:
    validation_id: int | None
    strategy_id: str
    setup_type: str
    supported_markets: tuple[str, ...]
    supported_asset_classes: tuple[str, ...]
    timeframe_stack: tuple[str, ...]
    entry_rules: dict[str, Any]
    stop_rules: dict[str, Any]
    target_rules: dict[str, Any]
    minimum_confidence: float
    minimum_edge_score: float
    validated_trade_count: int
    walk_forward_score: float
    expected_costs: dict[str, Any]
    max_allowed_drawdown: float
    promotion_timestamp: datetime
    model_version: str
    evidence_type: str
    executable_strategy: dict[str, Any]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntradayDataBundle:
    status: str
    ticker: str
    market: str
    as_of: datetime
    bars: dict[str, tuple[Any, ...]]
    latest_timestamps: dict[str, datetime | None]
    providers: dict[str, str | None]
    quality_scores: dict[str, float]
    blockers: tuple[str, ...] = ()
    provider_attempts: tuple[dict[str, Any], ...] = ()
    information_context: Any | None = None

    @property
    def ready(self) -> bool:
        return self.status == "READY" and not self.blockers


@dataclass(frozen=True)
class IntradayPositionSize:
    quantity: float
    notional: float
    risk_amount: float
    risk_percent: float
    reason: str


@dataclass(frozen=True)
class IntradayDecision:
    status: str
    reason_code: str
    explanation: str
    ticker: str
    market: str
    desk: str
    benchmark_ticker: str
    strategy_id: str
    validation_id: int | None
    setup_type: str
    decision_timestamp: datetime
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    trailing_stop: float | None = None
    confidence: float = 0.0
    edge_score: float = 0.0
    expected_move_bps: float = 0.0
    net_expectancy_bps: float = 0.0
    liquidity_score: float = 0.0
    volatility_bps: float = 0.0
    regime: str = "unknown"
    session: str = "unknown"
    costs: dict[str, Any] = field(default_factory=dict)
    sizing: IntradayPositionSize | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
