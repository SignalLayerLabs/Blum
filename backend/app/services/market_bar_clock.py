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


from functools import lru_cache
import exchange_calendars as xcals
import pandas as pd


@lru_cache(maxsize=1)
def nyse_calendar():
    return xcals.get_calendar("XNYS", start="1990-01-01", end="2035-12-31")


@lru_cache(maxsize=20000)
def consecutive(
    previous: datetime, current: datetime, timeframe: str, market: str
) -> bool:
    """Reject missing trading intervals; exchange closures are not missing bars."""
    if current <= previous:
        return False
    if normalize_market(market) == "USA":
        calendar = nyse_calendar()
        session = pd.Timestamp(previous.date())
        try:
            if not calendar.is_session(session):
                return False
            if timeframe == "1d":
                return current.date() == calendar.next_session(session).date()
            opened = calendar.session_open(session).to_pydatetime().replace(tzinfo=None)
            closed = (
                calendar.session_close(session).to_pydatetime().replace(tzinfo=None)
            )
            if not opened <= previous < closed:
                return False
            expected = previous + timedelta(
                minutes={"1m": 1, "5m": 5, "15m": 15, "1h": 60}[timeframe]
            )
            if expected >= closed:
                expected = (
                    calendar.session_open(calendar.next_session(session))
                    .to_pydatetime()
                    .replace(tzinfo=None)
                )
            return current == expected
        except (ValueError, KeyError):
            return False
    if timeframe == "1d":
        zone = ZoneInfo("Europe/London")
        prev_date = previous.replace(tzinfo=timezone.utc).astimezone(zone).date()
        next_date = current.replace(tzinfo=timezone.utc).astimezone(zone).date()
        expected = prev_date + timedelta(days=1)
        while expected.weekday() > 4:
            expected += timedelta(days=1)
        return (
            prev_date.weekday() < 5
            and next_date == expected
            and timedelta(hours=20) <= current - previous <= timedelta(hours=98)
        )
    zone = ZoneInfo("America/New_York")
    local = previous.replace(tzinfo=timezone.utc).astimezone(zone)
    if (
        local.weekday() == 5
        or (local.weekday() == 6 and local.hour < 17)
        or (local.weekday() == 4 and local.hour >= 17)
    ):
        return False
    expected = previous + timedelta(
        minutes={"1m": 1, "5m": 5, "15m": 15, "1h": 60}[timeframe]
    )
    next_local = expected.replace(tzinfo=timezone.utc).astimezone(zone)
    if next_local.weekday() == 4 and next_local.hour >= 17:
        sunday = local.date() + timedelta(days=2)
        expected = (
            datetime.combine(sunday, time(17), zone)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
    return current == expected


@lru_cache(maxsize=20000)
def first_execution_start(decision: datetime, timeframe: str, market: str) -> datetime:
    """First modeled opening strictly after a decision, using declared sessions."""
    if normalize_market(market) == "USA":
        calendar = nyse_calendar()
        session = calendar.date_to_session(
            pd.Timestamp(decision.date()), direction="next"
        )
        opening = calendar.session_open(session).to_pydatetime().replace(tzinfo=None)
        closing = calendar.session_close(session).to_pydatetime().replace(tzinfo=None)
        if decision < opening:
            return opening
        if timeframe == "1d" or decision >= closing:
            return (
                calendar.session_open(calendar.next_session(session))
                .to_pydatetime()
                .replace(tzinfo=None)
            )
        seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}[timeframe]
        candidate = opening + timedelta(
            seconds=(int((decision - opening).total_seconds()) // seconds + 1) * seconds
        )
        return (
            candidate
            if candidate < closing
            else calendar.session_open(calendar.next_session(session))
            .to_pydatetime()
            .replace(tzinfo=None)
        )
    if timeframe == "1d":
        # Explicit Yahoo-style London provider-day convention. Other daily
        # opening labels fail the exact-first-bar check, rather than guessing.
        zone = ZoneInfo("Europe/London")
        local = decision.replace(tzinfo=timezone.utc).astimezone(zone)
        day = local.date() + timedelta(days=1)
        while day.weekday() > 4:
            day += timedelta(days=1)
        return (
            datetime.combine(day, time(), zone)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
    seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}[timeframe]
    midnight = datetime.combine(decision.date(), time())
    candidate = midnight + timedelta(
        seconds=(int((decision - midnight).total_seconds()) // seconds + 1) * seconds
    )
    zone = ZoneInfo("America/New_York")
    local = candidate.replace(tzinfo=timezone.utc).astimezone(zone)
    if local.weekday() == 4 and local.hour >= 17:
        day = local.date() + timedelta(days=2)
    elif local.weekday() == 5:
        day = local.date() + timedelta(days=1)
    elif local.weekday() == 6 and local.hour < 17:
        day = local.date()
    else:
        return candidate
    return (
        datetime.combine(day, time(17), zone)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
