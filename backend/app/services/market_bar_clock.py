"""Conservative UTC-naive bar clocks shared by paper execution and research."""

from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

from app.services.executable_strategy import normalize_market


def session_start(start: datetime, timeframe: str, market: str) -> datetime:
    if timeframe == "1d" and normalize_market(market) == "USA":
        opening = datetime.combine(
            start.date(), time(9, 30), ZoneInfo("America/New_York")
        )
        return opening.astimezone(timezone.utc).replace(tzinfo=None)
    return start


def available_at(start: datetime, timeframe: str, market: str) -> datetime:
    if timeframe == "1d":
        if normalize_market(market) == "USA":
            close = datetime.combine(
                start.date(), time(16), ZoneInfo("America/New_York")
            )
            return close.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(
                minutes=1
            )
        # Non-US daily provider clocks are not certified. Never treat a23:00
        # opening label as a candle that closes at the next midnight.
        return start + timedelta(hours=26, minutes=1)
    return start + timedelta(
        minutes={"1m": 1, "5m": 5, "15m": 15, "1h": 60}[timeframe] + 1
    )
