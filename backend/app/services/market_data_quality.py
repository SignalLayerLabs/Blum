"""Shared acceptance boundary for attributable historical price observations."""
from __future__ import annotations

import math


def valid_ohlcv(opened, high, low, close, volume=None) -> bool:
    try:
        opened, high, low, close = (float(value) for value in (opened, high, low, close))
        if not all(math.isfinite(value) and value > 0 for value in (opened, high, low, close)):
            return False
        if low > min(opened, close) or high < max(opened, close) or low > high:
            return False
        return volume is None or (math.isfinite(float(volume)) and float(volume) >= 0)
    except (TypeError, ValueError, OverflowError):
        return False
