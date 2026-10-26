"""Confirmation consumption follows economic observations, independent of import labels."""
import json
from sqlalchemy import select

from .domain import identity,utc
from .storage import consumed_holdouts


def economic_identity(instrument):
    return identity(dict(market=instrument.market,symbol=instrument.symbol,base_currency=instrument.base_currency,quote_currency=instrument.quote_currency))


def confirmation_window(source,split):
    return dict(instrument_id=economic_identity(source.instrument),start=source.bars[split].timestamp.isoformat(),end=source.bars[-1].available_at.isoformat())


def overlaps(left,right):
    return left['instrument_id']==right['instrument_id'] and max(utc(left['start']),utc(right['start']))<min(utc(left['end']),utc(right['end']))


def claims(conn):
    return [json.loads(raw) for raw in conn.scalars(select(consumed_holdouts.c.payload))]
