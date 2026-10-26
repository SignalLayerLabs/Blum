"""Strategies observe a closed prefix only and express target sleeve exposure."""
from decimal import Decimal as D

from .domain import Bar


def target_weight(closed: tuple[Bar,...], *, market: str, strategy: str, lookback: int, weight: D) -> D:
    if strategy=='cash': return D(0)
    if strategy=='hold': return weight
    if len(closed)<=lookback: return D(0)
    # Missing paths do not become warmup data across arbitrary outages.
    if any((right.timestamp-left.available_at).total_seconds()>4*86400 for left,right in zip(closed[-lookback-1:],closed[-lookback:])):
        return D(0)
    trend=closed[-1].close/closed[-lookback-1].close-1
    if trend>0: return weight
    return -weight if market=='forex' and trend<0 else D(0)
