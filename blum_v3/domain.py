"""Closed, immutable financial contracts. Monetary values serialize as decimals."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Literal, Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


def utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timezone_required')
    return parsed.astimezone(timezone.utc)


def now() -> datetime:
    return datetime.now(timezone.utc)


def decimal(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('finite_number_required')
    return result


def encode(value: Any) -> str:
    def fallback(item):
        if isinstance(item, BaseModel):
            return item.model_dump(mode='json')
        if isinstance(item, (Decimal, datetime)):
            return str(item) if isinstance(item, Decimal) else utc(item).isoformat()
        raise TypeError(type(item).__name__)
    return json.dumps(value, default=fallback, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', allow_inf_nan=False)


class Instrument(Contract):
    symbol: str
    market: Literal['equity', 'forex']
    quote_currency: str
    base_currency: str | None = None
    tick_size: Decimal = Decimal('0.01')
    lot_size: Decimal = Decimal('1')
    calendar: str = 'WEEKDAY'

    @field_validator('symbol', 'quote_currency', 'base_currency')
    @classmethod
    def identifiers(cls, value):
        if value is None:
            return value
        value = value.strip().upper()
        if not value or len(value) > 40 or not all(c.isalnum() or c in '.=_-' for c in value):
            raise ValueError('invalid_instrument_identifier')
        return value

    @field_validator('tick_size', 'lot_size')
    @classmethod
    def positive(cls, value):
        if not value.is_finite() or value <= 0:
            raise ValueError('positive_increment_required')
        return value


class Provenance(Contract):
    provider: str
    rights: str
    first_seen_at: datetime
    availability_policy: Literal['historical_bar_close', 'observed_prospectively']
    source_revision: str = ''
    source_url: str = ''
    adjustment_policy: str = 'price_only_no_dividends'

    @field_validator('first_seen_at', mode='before')
    @classmethod
    def time(cls, value):
        return utc(value)

    @field_validator('provider', 'rights')
    @classmethod
    def required(cls, value):
        if not value.strip() or len(value) > 1000:
            raise ValueError('source_attribution_required')
        return value.strip()


class Bar(Contract):
    timestamp: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None

    @field_validator('timestamp', 'available_at', mode='before')
    @classmethod
    def time(cls, value):
        return utc(value)

    @model_validator(mode='after')
    def coherent(self):
        prices = (self.open, self.high, self.low, self.close)
        if any(not v.is_finite() or v <= 0 for v in prices):
            raise ValueError('positive_finite_prices_required')
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError('incoherent_ohlc')
        if self.available_at <= self.timestamp:
            raise ValueError('bar_not_yet_closed')
        if self.volume is not None and (not self.volume.is_finite() or self.volume < 0):
            raise ValueError('invalid_volume')
        if (self.bid is None) != (self.ask is None):
            raise ValueError('joint_bid_ask_required')
        if self.bid is not None and (not self.bid.is_finite() or not self.ask.is_finite() or self.bid <= 0 or self.ask < self.bid):
            raise ValueError('invalid_quote')
        return self


class Rejection(Contract):
    row: int
    reason: str


class AcceptedDataset(Contract):
    schema_version: int = 1
    dataset_id: str
    instrument: Instrument
    provenance: Provenance
    bars: tuple[Bar, ...]
    rejected: tuple[Rejection, ...]
    duplicate_count: int
    evidence_tier: Literal['BAR_RESEARCH'] = 'BAR_RESEARCH'
    warnings: tuple[str, ...] = ()


class RiskProfile(Contract):
    gross_limit: Decimal = Decimal('1')
    instrument_limit: Decimal = Decimal('0.20')
    daily_loss_limit: Decimal = Decimal('0.02')
    drawdown_limit: Decimal = Decimal('0.10')

    @model_validator(mode='after')
    def valid(self):
        if any(v <= 0 or v > 1 or not v.is_finite() for v in (self.gross_limit, self.instrument_limit, self.daily_loss_limit, self.drawdown_limit)):
            raise ValueError('risk_fraction_must_be_between_zero_and_one')
        return self
