"""Paper order validation and explicit execution profile contracts."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import field_validator, model_validator

from .domain import Contract, Instrument, decimal, utc


class Conversion(Contract):
    rate: Decimal
    at: datetime
    source_ref: str

    @field_validator('at', mode='before')
    @classmethod
    def clock(cls, value): return utc(value)

    @model_validator(mode='after')
    def validate_rate(self):
        if self.rate <= 0 or not self.rate.is_finite() or not self.source_ref:
            raise ValueError('invalid_conversion')
        return self


def conversion_rate(instrument: Instrument, currency: str, fx: dict | None, as_of: datetime) -> Decimal:
    if instrument.quote_currency == currency:
        return Decimal(1)
    if fx is None:
        raise ValueError('missing_conversion')
    quote = Conversion.model_validate(fx)
    age = (as_of - quote.at).total_seconds()
    if age < 0 or age > 86400:
        raise ValueError('stale_or_future_conversion')
    return quote.rate


def aligned(value: Decimal, increment: Decimal) -> bool:
    return value % increment == 0


class ExecutionProfile(Contract):
    spread_bps: Decimal = Decimal('5')
    slippage_bps: Decimal = Decimal('2')
    commission_bps: Decimal = Decimal('1')
    minimum_commission: Decimal = Decimal('0')
    participation: Decimal = Decimal('0.01')
    fx_capacity: Decimal = Decimal('100000')
    latency_bars: int = 0
    max_holding_bars: int = 20
    financing_bps_per_day: Decimal | None = None
    source: str = 'declared-paper-scenario-v1'

    @model_validator(mode='after')
    def valid(self):
        if any(not value.is_finite() or value < 0 for value in (self.spread_bps,self.slippage_bps,self.commission_bps,self.minimum_commission,self.participation,self.fx_capacity)):
            raise ValueError('invalid_execution_profile')
        if self.participation > 1 or self.latency_bars < 0 or self.latency_bars > 20 or self.max_holding_bars < 1:
            raise ValueError('invalid_execution_profile')
        if self.financing_bps_per_day is not None and not self.financing_bps_per_day.is_finite():
            raise ValueError('invalid_financing')
        return self
