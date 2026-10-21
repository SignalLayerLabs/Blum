from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from typing import ClassVar
from app.services.information.contracts import OpportunityContext


class ForexDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    WATCH = "WATCH"
    ABSTAIN = "ABSTAIN"


class ForexReadiness(str, Enum):
    TRAINING_SIGNAL = "TRAINING_SIGNAL"
    PAPER_TRADE_ELIGIBLE = "PAPER_TRADE_ELIGIBLE"
    ALPHA_SIGNAL_ELIGIBLE = "ALPHA_SIGNAL_ELIGIBLE"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"


@dataclass(frozen=True)
class ForexPairConfig:
    ticker: str
    display: str
    base_currency: str
    quote_currency: str
    pip_size: float
    pip_value_per_standard_lot: float
    minimum_lot: float = 0.01
    lot_step: float = 0.01
    price_precision: int = 5
    trading_hours: str = "24x5"
    benchmark: str = "UUP"
    supported_brokers: tuple[str, ...] = ("paper_eu_30x",)
    supported_timeframes: tuple[str, ...] = ("1h", "15m", "5m", "1m")


_PAIR_ROWS = (
    ("EURUSD=X", "EUR/USD", "EUR", "USD", 0.0001, 10.0, 5),
    ("GBPUSD=X", "GBP/USD", "GBP", "USD", 0.0001, 10.0, 5),
    ("USDJPY=X", "USD/JPY", "USD", "JPY", 0.01, 9.0, 3),
    ("USDCHF=X", "USD/CHF", "USD", "CHF", 0.0001, 11.0, 5),
    ("AUDUSD=X", "AUD/USD", "AUD", "USD", 0.0001, 10.0, 5),
    ("USDCAD=X", "USD/CAD", "USD", "CAD", 0.0001, 7.4, 5),
    ("NZDUSD=X", "NZD/USD", "NZD", "USD", 0.0001, 10.0, 5),
    ("EURGBP=X", "EUR/GBP", "EUR", "GBP", 0.0001, 12.8, 5),
    ("EURJPY=X", "EUR/JPY", "EUR", "JPY", 0.01, 9.0, 3),
    ("GBPJPY=X", "GBP/JPY", "GBP", "JPY", 0.01, 9.0, 3),
    ("AUDJPY=X", "AUD/JPY", "AUD", "JPY", 0.01, 9.0, 3),
    ("EURCHF=X", "EUR/CHF", "EUR", "CHF", 0.0001, 11.0, 5),
)
PAIR_CONFIGS = {
    row[0]: ForexPairConfig(
        ticker=row[0],
        display=row[1],
        base_currency=row[2],
        quote_currency=row[3],
        pip_size=row[4],
        pip_value_per_standard_lot=row[5],
        price_precision=row[6],
    )
    for row in _PAIR_ROWS
}


class _PairLookup:
    def __call__(self, ticker: str) -> ForexPairConfig:
        canonical = ticker.upper().replace("/", "")
        if not canonical.endswith("=X"):
            canonical += "=X"
        if canonical not in PAIR_CONFIGS:
            raise KeyError(f"Unsupported Forex pair: {ticker}")
        return PAIR_CONFIGS[canonical]

    def all(self) -> tuple[ForexPairConfig, ...]:
        return tuple(PAIR_CONFIGS.values())


pair_config = _PairLookup()


@dataclass(frozen=True)
class MarketFrame:
    timeframe: str
    market_timestamp: datetime
    acquired_at: datetime
    provider: str
    opens: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    closes: tuple[float, ...]
    quality_score: float
    missing_intervals: tuple[str, ...] = ()
    adjustment_status: str = "RAW"
    bar_timestamps: tuple[datetime, ...] = ()
    volumes: tuple[float | None, ...] = ()

    def validate(self) -> None:
        if self.timeframe not in {"1h", "15m", "5m", "1m"}:
            raise ValueError(f"Unsupported Forex timeframe: {self.timeframe}")
        lengths = {len(self.opens), len(self.highs), len(self.lows), len(self.closes)}
        if len(lengths) != 1 or not self.closes:
            raise ValueError("OHLC arrays must be non-empty and aligned")


@dataclass(frozen=True)
class ForexQuote:
    bid: float
    ask: float
    timestamp: datetime
    source: str

    def __post_init__(self) -> None:
        if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value) for value in (self.bid,self.ask)) or self.bid <= 0 or self.ask <= self.bid:
            raise ValueError("Forex quote requires positive bid and ask > bid")


@dataclass(frozen=True)
class AgentMarketInput:
    pair: str
    as_of: datetime
    frames: dict[str, MarketFrame]
    quote: ForexQuote
    session: str
    macro_event_impact: str = "LOW_IMPACT"
    macro_event_timestamp: datetime | None = None
    liquidity_score: float = 0.0
    volatility_score: float = 0.0
    macro_payload: dict = field(default_factory=dict)
    information_context: OpportunityContext | None = None

    REQUIRED: ClassVar[tuple[str, ...]] = ("1h", "15m", "5m", "1m")

    def blockers(self, *, max_one_minute_age_seconds: int = 180) -> list[str]:
        missing = [item for item in self.REQUIRED if item not in self.frames]
        if missing:
            return ["TIMEFRAME_UNAVAILABLE"]
        for frame in self.frames.values():
            frame.validate()
            if frame.market_timestamp > self.as_of:
                return ["FUTURE_DATA_DETECTED"]
            max_age = {"1h": 7200, "15m": 2700, "5m": 900, "1m": max_one_minute_age_seconds}[frame.timeframe]
            if (self.as_of - frame.market_timestamp).total_seconds() > max_age:
                return ["STALE_DATA"]
            if frame.missing_intervals or frame.quality_score < 0.35:
                return ["TIMEFRAME_UNAVAILABLE"]
        if self.as_of.weekday() >= 5:
            return ["MARKET_CLOSED"]
        age = (self.as_of - self.frames["1m"].market_timestamp).total_seconds()
        if age < 0 or age > max_one_minute_age_seconds:
            return ["STALE_DATA"]
        if self.quote.timestamp > self.as_of or (self.as_of - self.quote.timestamp).total_seconds() > max_one_minute_age_seconds:
            return ["STALE_DATA"]
        return []

    def data_hash(self) -> str:
        payload = {
            "pair": self.pair,
            "as_of": self.as_of.isoformat(),
            "quote": asdict(self.quote),
            "session": self.session,
            "macro_event_impact": self.macro_event_impact,
            "macro_event_timestamp": self.macro_event_timestamp.isoformat() if self.macro_event_timestamp else None,
            "liquidity_score": self.liquidity_score,
            "volatility_score": self.volatility_score,
            "macro_payload": self.macro_payload,
            "information_context_hash": self.information_context.hash if self.information_context else None,
            "frames": {key: asdict(value) for key, value in self.frames.items()},
        }
        return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class ForexStrategyEvidence:
    strategy_id: str
    readiness: ForexReadiness
    sample_size: int
    net_expectancy_r: float
    replay_forward_decay: float | None = None
    currency_concentration: float | None = None
    active_blockers: tuple[str, ...] = ()
    is_news_strategy: bool = False
    strategy_version: str = "1"
    contextual_memory: dict = field(default_factory=dict)
    evidence_lane: str = "certified_paper"
    certified_for_copy_readiness: bool = True
    executable_strategy: dict = field(default_factory=dict)
    strategy_fingerprint: str = ""
    required_feature_schema_hash: str = ""
    holding_horizon_bars: int | None = None


@dataclass(frozen=True)
class MarketContextOutput:
    regime: str
    directional_bias: ForexDirection
    volatility_state: str
    session_state: str
    liquidity_state: str
    data_quality: float
    active_macro_risks: tuple[str, ...]
    confidence: float
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class PriceActionOutput:
    setup_family: str
    direction: ForexDirection
    setup_quality: float
    trigger: str
    entry_zone: tuple[float, float]
    stop_level: float
    target_levels: tuple[float, ...]
    invalidation: str
    expected_holding_minutes: int
    expected_gross_pips: float
    technical_evidence: tuple[str, ...]
    confidence: float
    blockers: tuple[str, ...] = ()
    strategy_fingerprint: str = ""
    executable_strategy: dict = field(default_factory=dict)
    execution_timeframe: str = ""
    maximum_holding_bars: int | None = None
    trailing_stop: float | None = None
    feature_schema_hash: str = ""


@dataclass(frozen=True)
class MacroOutput:
    macro_bias: ForexDirection
    event_risk: str
    news_window_status: str
    cross_asset_confirmation: str
    cross_asset_divergence: str | None
    confidence: float
    veto_reason: str | None


@dataclass(frozen=True)
class ForexTradeProposal:
    pair: str
    direction: ForexDirection
    strategy_id: str
    setup_family: str
    entry: float
    stop: float
    target: float
    secondary_target: float | None
    invalidation: str
    expected_holding_minutes: int
    expected_gross_pips: float
    expected_cost_pips: float
    expected_net_pips: float
    expected_r: float
    confidence: float
    supporting_evidence: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    reason_to_trade: str | None
    reason_to_abstain: str | None
    confidence_components: dict[str, float] = field(default_factory=dict)
    actionability_status: str = "UNASSESSED"
    knowledge_context: dict = field(default_factory=dict)
    evidence_lane: str = "certified_paper"
    certified_for_copy_readiness: bool = True
    strategy_fingerprint: str = ""
    executable_strategy: dict = field(default_factory=dict)
    execution_timeframe: str = ""
    maximum_holding_bars: int | None = None
    trailing_stop: float | None = None
    feature_schema_hash: str = ""
    information_advice: dict = field(default_factory=dict)
    information_policy: dict = field(default_factory=dict)
    regime: str = "unknown"


@dataclass(frozen=True)
class RiskObjectionOutput:
    objections: tuple[str, ...]
    severity: str
    risk_reduction: float
    veto: bool
    veto_reason: str | None


@dataclass(frozen=True)
class ForexOrderRequest:
    pair: str
    side: ForexDirection
    order_type: str
    quantity_lots: float
    theoretical_price: float
    stop_price: float | None = None
    target_price: float | None = None
    limit_price: float | None = None
    session: str = "UNKNOWN"
    liquidity_score: float = 0.5
    volatility_score: float = 0.5
    event_impact: str = "LOW_IMPACT"
    account_conversion: dict = field(default_factory=dict)

    @classmethod
    def from_proposal(
        cls,
        proposal: ForexTradeProposal,
        *,
        quantity_lots: float,
        market: AgentMarketInput | None = None,
    ) -> "ForexOrderRequest":
        return cls(
            proposal.pair,
            proposal.direction,
            "MARKET",
            quantity_lots,
            proposal.entry,
            proposal.stop,
            proposal.target,
            session=market.session if market else "UNKNOWN",
            liquidity_score=market.liquidity_score if market else 0.5,
            volatility_score=market.volatility_score if market else 0.5,
            event_impact=market.macro_event_impact if market else "LOW_IMPACT",
        )


@dataclass(frozen=True)
class EvaluationOutcome:
    approved: bool
    proposal: ForexTradeProposal
    blockers: tuple[str, ...]
    agent_outputs: dict
