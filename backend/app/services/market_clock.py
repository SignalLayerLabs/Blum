"""Session and observation clocks for live decision and execution boundaries."""

from datetime import datetime, time, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from app.services.market_bar_clock import available_at, nyse_calendar


def utc_naive(value: datetime) -> datetime:
    return (
        value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    )


@lru_cache(maxsize=4)
def _calendar(name: str):
    return (
        nyse_calendar()
        if name == "XNYS"
        else xcals.get_calendar(name, start="1990-01-01", end="2035-12-31")
    )


class MarketClock:
    def session(self, market: str, at: datetime) -> str:
        stamp = utc_naive(at)
        key = str(market or "").upper()
        if key in {"FOREX", "FX", "CURRENCY"}:
            local = stamp.replace(tzinfo=timezone.utc).astimezone(
                ZoneInfo("America/New_York")
            )
            closed = (
                local.weekday() == 5
                or (local.weekday() == 6 and local.hour < 17)
                or (local.weekday() == 4 and local.hour >= 17)
            )
            return "closed" if closed else "regular"
        names = {
            "USA": "XNYS",
            "US": "XNYS",
            "UNITED STATES": "XNYS",
            "NASDAQ": "XNYS",
            "NYSE": "XNYS",
            "ITALY": "XMIL",
            "GERMANY": "XETR",
            "FRANCE": "XPAR",
            "EUROPE": "XPAR",
        }
        name = names.get(key)
        if name is None:
            return "closed"
        calendar = _calendar(name)
        day = pd.Timestamp(stamp.date())
        try:
            if not calendar.is_session(day):
                return "closed"
            opened = utc_naive(calendar.session_open(day).to_pydatetime())
            closed = utc_naive(calendar.session_close(day).to_pydatetime())
            return "regular" if opened <= stamp < closed else "closed"
        except (KeyError, ValueError):
            return "closed"

    def forex_session(self, at: datetime) -> str:
        if self.session("FOREX", at) == "closed":
            return "CLOSED"
        stamp = utc_naive(at).replace(tzinfo=timezone.utc)
        london = stamp.astimezone(ZoneInfo("Europe/London")).time().replace(tzinfo=None)
        new_york = (
            stamp.astimezone(ZoneInfo("America/New_York")).time().replace(tzinfo=None)
        )
        if time(17) <= new_york < time(18):
            return "ROLLOVER"
        ldn = time(8) <= london < time(17)
        ny = time(8) <= new_york < time(17)
        if ldn and ny:
            return "LONDON_NEW_YORK_OVERLAP"
        return "LONDON" if ldn else "NEW_YORK" if ny else "ASIA"


def bar_available_at(row) -> datetime:
    stamp = utc_naive(getattr(row, "bar_timestamp", None) or row.timestamp)
    declared = getattr(row, "available_at", None)
    acquired = getattr(row, "acquired_at", None)
    timeframe = getattr(row, "timeframe", None)
    clocks = [stamp]
    if timeframe:
        clocks.append(available_at(stamp, timeframe, getattr(row, "market", "UNKNOWN")))
    for value in (declared, acquired):
        if value is not None:
            clocks.append(utc_naive(value))
    return max(clocks)


def eligible_bar(
    row, *, decision_at: datetime | None, as_of: datetime, mode: str
) -> bool:
    if mode not in {"context", "execution"}:
        raise ValueError("unknown bar eligibility mode")
    stamp = utc_naive(getattr(row, "bar_timestamp", None) or row.timestamp)
    if stamp > utc_naive(as_of) or bar_available_at(row) > utc_naive(as_of):
        return False
    if mode == "execution" and (decision_at is None or stamp <= utc_naive(decision_at)):
        return False
    return True
