from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as clock_time, timedelta, timezone
from typing import Protocol
from urllib.parse import quote

import pandas as pd
import requests
import yfinance as yf

from app.providers.yfinance_provider import NasdaqHistoricalProvider, StooqProvider, provider_headers


REPLAY_TIMEFRAMES = frozenset({"1d", "1h", "15m", "5m", "1m"})
INTRADAY_RETENTION_DAYS = {
    "1h": 729,
    "1m": 7,
    "5m": 59,
    "15m": 59,
}


@dataclass(frozen=True)
class ReplayDataRequest:
    source_symbol: str
    normalized_symbol: str
    market: str
    timeframe: str
    start: datetime
    end: datetime


@dataclass
class ProviderBars:
    provider: str
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_metadata: dict = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)


class ReplayDataProvider(Protocol):
    name: str
    supported_timeframes: frozenset[str]
    source_metadata: dict

    def fetch(self, request: ReplayDataRequest) -> ProviderBars: ...


class NasdaqChartReplayDataProvider:
    """Public US intraday fallback using Nasdaq's observed last-sale chart path."""

    name = "nasdaq_chart"
    supported_timeframes = frozenset({"1m", "5m", "15m"})
    source_metadata = {
        "source": "Nasdaq public quote chart API",
        "license": "Public endpoint; downstream use remains subject to provider terms.",
        "bar_construction": "observed_last_sale_path",
        "ohlcv_completeness": "Price path only; volume unavailable and OHLC is aggregated from observed minute values.",
        "data_quality_score": 55.0,
    }

    def __init__(self) -> None:
        self._observed_cache: dict[tuple[str, str], tuple[pd.DataFrame, str | None]] = {}

    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        if request.timeframe not in self.supported_timeframes:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["UNSUPPORTED_TIMEFRAME"])
        if str(request.market or "").strip().upper() not in {"USA", "US", "UNITED STATES", "NASDAQ", "NYSE"}:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["UNSUPPORTED_MARKET"])
        observed, blocker = self._observed_path(request)
        if blocker:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=[blocker])
        start = _naive_utc(request.start)
        end = _naive_utc(request.end)
        observed = observed.loc[(observed.index >= start) & (observed.index <= end)]
        if observed.empty:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["NO_INTRADAY_HISTORY"])
        if request.timeframe == "1m":
            frame = observed.assign(Open=observed["Close"], High=observed["Close"], Low=observed["Close"], Volume=None)
        else:
            frequency = {"5m": "5min", "15m": "15min"}[request.timeframe]
            frame = observed["Close"].resample(frequency).agg(Open="first", High="max", Low="min", Close="last")
            frame["Volume"] = None
        return ProviderBars(self.name, normalize_replay_frame(frame), self.source_metadata, [])

    def _observed_path(self, request: ReplayDataRequest) -> tuple[pd.DataFrame, str | None]:
        cache_key = (request.source_symbol.upper(), str(request.market or "").upper())
        cached = self._observed_cache.get(cache_key)
        if cached is not None:
            return cached[0].copy(), cached[1]
        url = f"https://api.nasdaq.com/api/quote/{quote(request.source_symbol)}/chart"
        try:
            response = requests.get(
                url,
                params={"assetclass": "stocks"},
                headers=provider_headers(),
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            result = (pd.DataFrame(), "PROVIDER_UNAVAILABLE")
            self._observed_cache[cache_key] = result
            return result
        chart = (payload.get("data") or {}).get("chart") or []
        points = [row for row in chart if row.get("x") is not None and row.get("y") is not None]
        if not points:
            result = (pd.DataFrame(), "NO_INTRADAY_HISTORY")
            self._observed_cache[cache_key] = result
            return result
        index = pd.to_datetime([row["x"] for row in points], unit="ms", utc=True)
        values = pd.to_numeric([row["y"] for row in points], errors="coerce")
        observed = pd.DataFrame({"Close": values}, index=index).dropna(subset=["Close"])
        if observed.empty:
            result = (pd.DataFrame(), "NO_INTRADAY_HISTORY")
            self._observed_cache[cache_key] = result
            return result
        eastern = observed.index.tz_convert("America/New_York")
        regular_session = (eastern.time >= clock_time(9, 30)) & (eastern.time <= clock_time(16, 0))
        observed = observed.loc[regular_session]
        if observed.empty:
            result = (pd.DataFrame(), "MARKET_SESSION_UNAVAILABLE")
            self._observed_cache[cache_key] = result
            return result
        observed.index = observed.index.tz_convert(None)
        result = (observed, None)
        self._observed_cache[cache_key] = result
        return observed.copy(), None


class YahooReplayDataProvider:
    name = "yahoo_chart"
    supported_timeframes = REPLAY_TIMEFRAMES
    source_metadata = {
        "source": "Yahoo Finance chart API",
        "license": "Public endpoint; downstream use remains subject to provider terms.",
        "intraday_retention": "Provider-defined and potentially shorter than the requested range.",
    }

    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        if request.timeframe not in self.supported_timeframes:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["UNSUPPORTED_TIMEFRAME"])
        start, end = provider_request_window(request)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(request.source_symbol)}"
        params = {
            "period1": int(_as_utc(start).timestamp()),
            "period2": int(_as_utc(end).timestamp()) + 1,
            "interval": request.timeframe,
            "includePrePost": "false",
            "events": "div,splits",
        }
        try:
            headers = {**provider_headers(), "User-Agent": "Mozilla/5.0"}
            response = requests.get(url, params=params, headers=headers, timeout=12)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["PROVIDER_UNAVAILABLE"])
        result = payload.get("chart", {}).get("result") or []
        if not result:
            error = payload.get("chart", {}).get("error") or {}
            blocker = "NO_INTRADAY_HISTORY" if request.timeframe != "1d" else "COVERAGE_INCOMPLETE"
            metadata = {**self.source_metadata, "provider_error": error}
            return ProviderBars(self.name, source_metadata=metadata, blockers=[blocker])
        data = result[0]
        timestamps = data.get("timestamp") or []
        quotes = (data.get("indicators", {}).get("quote") or [{}])[0]
        if not timestamps or not quotes:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["COVERAGE_INCOMPLETE"])
        frame = pd.DataFrame(
            {
                "Open": quotes.get("open", []),
                "High": quotes.get("high", []),
                "Low": quotes.get("low", []),
                "Close": quotes.get("close", []),
                "Volume": quotes.get("volume", []),
            },
            index=pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None),
        )
        normalized = normalize_replay_frame(frame)
        metadata = dict(self.source_metadata)
        # Yahoo can append regularMarketTime as an extra live quote row. It is
        # not a candle opening; repeated polls otherwise create phantom bars.
        from app.services.market_bar_clock import canonical_open, available_at
        from app.services.executable_strategy import normalize_market

        market = normalize_market(request.market)
        if market in {"USA", "FOREX"}:
            keep = [
                canonical_open(t.to_pydatetime(), request.timeframe, market)
                for t in normalized.index
            ]
            metadata["rejected_off_grid_rows"] = len(keep) - sum(keep)
            metadata["candle_clock_policy"] = "declared-open-grid-v2"
            normalized = normalized.loc[keep]
            cutoff = min(datetime.now(timezone.utc).replace(tzinfo=None), _naive_utc(request.end))
            closed = [available_at(t.to_pydatetime(), request.timeframe, market) <= cutoff for t in normalized.index]
            metadata["rejected_unclosed_rows"] = len(closed) - sum(closed)
            metadata["closed_candles_only"] = True
            normalized = normalized.loc[closed]
        return ProviderBars(self.name, normalized, metadata, [])


class YFinanceReplayDataProvider:
    name = "yfinance"
    supported_timeframes = REPLAY_TIMEFRAMES
    source_metadata = {
        "source": "yfinance",
        "license": "Open-source adapter; underlying market data remains subject to source terms.",
    }

    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        start, end = provider_request_window(request)
        try:
            frame = yf.download(
                request.source_symbol,
                start=start,
                end=end,
                interval=request.timeframe,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["PROVIDER_UNAVAILABLE"])
        if frame is None or frame.empty:
            blocker = "NO_INTRADAY_HISTORY" if request.timeframe != "1d" else "COVERAGE_INCOMPLETE"
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=[blocker])
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        return ProviderBars(self.name, normalize_replay_frame(frame), self.source_metadata, [])


class DailyProviderReplayAdapter:
    supported_timeframes = frozenset({"1d"})

    def __init__(self, provider):
        self.provider = provider
        self.name = provider.name
        self.source_metadata = {
            "source": provider.name,
            "license": "Public daily history; use subject to source terms.",
        }

    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        if request.timeframe != "1d":
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["UNSUPPORTED_TIMEFRAME"])
        years = max(1, int((request.end - request.start).days / 365.25) + 1)
        try:
            frames = self.provider.download_history([request.source_symbol], period=f"{years}y", interval="1d")
        except Exception:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["PROVIDER_UNAVAILABLE"])
        frame = frames.get(request.source_symbol)
        if frame is None or frame.empty:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["COVERAGE_INCOMPLETE"])
        normalized = normalize_replay_frame(frame)
        mask = (normalized.index >= _naive_utc(request.start)) & (normalized.index <= _naive_utc(request.end))
        return ProviderBars(self.name, normalized.loc[mask], self.source_metadata, [])


def default_replay_providers(*, include_yfinance: bool = True) -> list[ReplayDataProvider]:
    providers: list[ReplayDataProvider] = [YahooReplayDataProvider()]
    if include_yfinance:
        providers.append(YFinanceReplayDataProvider())
    providers.append(NasdaqChartReplayDataProvider())
    providers.extend([DailyProviderReplayAdapter(StooqProvider()), DailyProviderReplayAdapter(NasdaqHistoricalProvider())])
    return providers


def normalize_replay_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    required = ["Open", "High", "Low", "Close", "Volume"]
    for column in required:
        if column not in output:
            output[column] = None
    output = output[required].apply(pd.to_numeric, errors="coerce")
    output = output.dropna(subset=["Close"])
    index = pd.to_datetime(output.index, errors="coerce", utc=True)
    output.index = index.tz_convert(None)
    output = output[~output.index.isna()]
    output = output[~output.index.duplicated(keep="last")].sort_index()
    invalid = (
        (output["High"].notna() & output["Low"].notna() & (output["High"] < output["Low"]))
        | (output["Open"].notna() & output["High"].notna() & (output["Open"] > output["High"]))
        | (output["Close"].notna() & output["Low"].notna() & (output["Close"] < output["Low"]))
    )
    return output.loc[~invalid]


def provider_request_window(request: ReplayDataRequest) -> tuple[datetime, datetime]:
    """Clamp intraday requests to the retention windows exposed by Yahoo sources."""

    retention_days = INTRADAY_RETENTION_DAYS.get(request.timeframe)
    if retention_days is None:
        return request.start, request.end
    return max(request.start, request.end - timedelta(days=retention_days)), request.end


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    return _as_utc(value).replace(tzinfo=None)
