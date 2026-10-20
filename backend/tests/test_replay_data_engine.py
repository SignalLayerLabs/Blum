from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, PriceHistory, ReplayMarketBar
from app.providers.replay_data_provider import (
    NasdaqChartReplayDataProvider,
    ProviderBars,
    ReplayDataRequest,
    YahooReplayDataProvider,
    YFinanceReplayDataProvider,
    default_replay_providers,
)
from app.services.replay_data import MultiProviderReplayDataService


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_asset(db: Session, ticker: str = "NVDA", market: str = "USA") -> Asset:
    asset = Asset(
        ticker=ticker,
        name=ticker,
        category="Stock",
        sector="Technology",
        country=market,
        asset_type="Stock",
        currency="USD" if market == "USA" else "EUR",
        exchange="NASDAQ" if market == "USA" else "MIL",
        is_active=True,
    )
    db.add(asset)
    db.flush()
    return asset


def replay_bar_values(asset_id: int) -> dict:
    return {
        "asset_id": asset_id,
        "source_symbol": "NVDA",
        "normalized_symbol": "NVDA",
        "market": "USA",
        "timeframe": "1m",
        "bar_timestamp": datetime(2026, 7, 10, 14, 31),
        "open": 160.0,
        "high": 161.0,
        "low": 159.5,
        "close": 160.5,
        "volume": 250_000,
        "provider": "test",
        "acquired_at": datetime(2026, 7, 10, 18, 0),
        "data_quality_score": 98.0,
        "source_metadata": {"license": "test fixture"},
    }


def test_replay_bar_keeps_intraday_timestamp_and_timeframe():
    with setup_db() as db:
        asset = seed_asset(db)
        timestamp = replay_bar_values(asset.id)["bar_timestamp"]
        db.add(ReplayMarketBar(**replay_bar_values(asset.id)))
        db.commit()
        row = db.scalar(select(ReplayMarketBar))

    assert row is not None
    assert row.bar_timestamp == timestamp
    assert row.timeframe == "1m"


def test_replay_bar_unique_key_prevents_duplicate_provider_bar():
    with setup_db() as db:
        asset = seed_asset(db)
        values = replay_bar_values(asset.id)
        db.add(ReplayMarketBar(**values))
        db.commit()
        db.add(ReplayMarketBar(**values))
        with pytest.raises(IntegrityError):
            db.commit()


class RecordingProvider:
    name = "recording"
    supported_timeframes = frozenset({"1m", "5m", "15m", "1d"})
    source_metadata = {"license": "test"}

    def __init__(self, bars: pd.DataFrame | None = None, blocker: str | None = None):
        self.bars = bars if bars is not None else pd.DataFrame()
        self.blocker = blocker
        self.requests: list[ReplayDataRequest] = []

    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        self.requests.append(request)
        return ProviderBars(
            provider=self.name,
            frame=self.bars,
            source_metadata=self.source_metadata,
            blockers=[self.blocker] if self.blocker else [],
        )


class RaisingProvider(RecordingProvider):
    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        self.requests.append(request)
        raise RuntimeError("provider transport failed")


def frame(start: datetime, periods: int, frequency: str) -> pd.DataFrame:
    index = pd.date_range(start=start, periods=periods, freq=frequency)
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(periods)],
            "High": [101.0 + i for i in range(periods)],
            "Low": [99.0 + i for i in range(periods)],
            "Close": [100.5 + i for i in range(periods)],
            "Volume": [1000.0 + i for i in range(periods)],
        },
        index=index,
    )


class FakeYahooResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "chart": {
                "result": [
                    {
                        "timestamp": [1_752_657_600],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0],
                                    "high": [101.0],
                                    "low": [99.0],
                                    "close": [100.5],
                                    "volume": [1_000_000],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }


class FakeNasdaqResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        start = datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc)
        return {
            "data": {
                "symbol": "NVDA",
                "chart": [
                    {
                        "x": int((start + timedelta(minutes=index)).timestamp() * 1000),
                        "y": 170.0 + index / 10,
                    }
                    for index in range(31)
                ],
            }
        }


def test_yahoo_replay_clamps_one_minute_request_to_provider_retention(monkeypatch):
    captured: dict = {}

    def fake_get(url, *, params, headers, timeout):
        captured.update(params)
        captured["headers"] = headers
        return FakeYahooResponse()

    monkeypatch.setattr("app.providers.replay_data_provider.requests.get", fake_get)
    end = datetime(2026, 7, 16, 12, 0)
    request = ReplayDataRequest("NVDA", "NVDA", "USA", "1m", end - timedelta(days=365), end)

    YahooReplayDataProvider().fetch(request)

    requested_start = datetime.utcfromtimestamp(captured["period1"])
    assert requested_start == end - timedelta(days=7)
    assert captured["headers"]["User-Agent"] == "Mozilla/5.0"


def test_yfinance_replay_clamps_five_minute_request_to_provider_retention(monkeypatch):
    captured: dict = {}

    def fake_download(symbol, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr("app.providers.replay_data_provider.yf.download", fake_download)
    end = datetime(2026, 7, 16, 12, 0)
    request = ReplayDataRequest("NVDA", "NVDA", "USA", "5m", end - timedelta(days=365), end)

    YFinanceReplayDataProvider().fetch(request)

    assert captured["start"] == end - timedelta(days=59)


def test_nasdaq_chart_provider_resamples_observed_price_path(monkeypatch):
    monkeypatch.setattr(
        "app.providers.replay_data_provider.requests.get",
        lambda *args, **kwargs: FakeNasdaqResponse(),
    )
    end = datetime(2026, 7, 16, 12, 0)

    result = NasdaqChartReplayDataProvider().fetch(
        ReplayDataRequest("NVDA", "NVDA", "USA", "15m", end - timedelta(days=10), end)
    )

    assert result.blockers == []
    assert len(result.frame) == 3
    assert result.frame.iloc[0]["Open"] == 170.0
    assert result.frame.iloc[0]["Close"] == 171.4
    assert result.source_metadata["bar_construction"] == "observed_last_sale_path"
    assert result.source_metadata["data_quality_score"] == 55.0


def test_nasdaq_chart_provider_never_returns_bars_after_requested_end(monkeypatch):
    monkeypatch.setattr(
        "app.providers.replay_data_provider.requests.get",
        lambda *args, **kwargs: FakeNasdaqResponse(),
    )
    end = datetime(2026, 7, 14, 20, 0)

    result = NasdaqChartReplayDataProvider().fetch(
        ReplayDataRequest("NVDA", "NVDA", "USA", "1m", end - timedelta(days=2), end)
    )

    assert result.frame.empty
    assert result.blockers == ["NO_INTRADAY_HISTORY"]


def test_nasdaq_chart_provider_reuses_one_price_path_for_all_timeframes(monkeypatch):
    request_count = 0

    def fake_get(*args, **kwargs):
        nonlocal request_count
        request_count += 1
        return FakeNasdaqResponse()

    monkeypatch.setattr("app.providers.replay_data_provider.requests.get", fake_get)
    provider = NasdaqChartReplayDataProvider()
    end = datetime(2026, 7, 16, 12, 0)
    for timeframe in ("1m", "5m", "15m"):
        provider.fetch(ReplayDataRequest("NVDA", "NVDA", "USA", timeframe, end - timedelta(days=10), end))

    assert request_count == 1


def test_replay_persistence_honors_provider_quality_override():
    start = datetime(2026, 7, 10, 8, 0)
    provider = RecordingProvider(frame(start, periods=5, frequency="15min"))
    provider.source_metadata = {"license": "test", "data_quality_score": 55.0}
    with setup_db() as db:
        asset = seed_asset(db)
        MultiProviderReplayDataService([provider]).ensure_coverage(
            db,
            asset=asset,
            timeframe="15m",
            start=start,
            end=start + timedelta(hours=1),
        )
        rows = db.scalars(select(ReplayMarketBar).where(ReplayMarketBar.asset_id == asset.id)).all()

    assert rows
    assert {row.data_quality_score for row in rows} == {55.0}


def test_default_replay_providers_prefer_complete_ohlcv_before_price_path_fallback():
    providers = default_replay_providers(include_yfinance=False)

    assert isinstance(providers[0], YahooReplayDataProvider)
    assert isinstance(providers[1], NasdaqChartReplayDataProvider)


def test_higher_quality_provider_upgrades_existing_replay_bar():
    start = datetime(2026, 7, 10, 8, 0)
    low_quality = RecordingProvider(frame(start, periods=4, frequency="15min"))
    low_quality.name = "price_path"
    low_quality.source_metadata = {"data_quality_score": 55.0}
    high_quality_frame = frame(start, periods=5, frequency="15min")
    high_quality_frame.loc[start, "Open"] = 99.25
    high_quality_frame.loc[start, "Volume"] = 2_500_000
    high_quality = RecordingProvider(high_quality_frame)
    high_quality.name = "complete_ohlcv"
    high_quality.source_metadata = {"data_quality_score": 100.0}

    with setup_db() as db:
        asset = seed_asset(db)
        MultiProviderReplayDataService([low_quality]).ensure_coverage(
            db,
            asset=asset,
            timeframe="15m",
            start=start,
            end=start + timedelta(hours=1),
        )
        MultiProviderReplayDataService([high_quality]).ensure_coverage(
            db,
            asset=asset,
            timeframe="15m",
            start=start,
            end=start + timedelta(hours=2),
        )
        upgraded = db.scalar(
            select(ReplayMarketBar).where(
                ReplayMarketBar.asset_id == asset.id,
                ReplayMarketBar.timeframe == "15m",
                ReplayMarketBar.bar_timestamp == start,
            )
        )

    assert upgraded is not None
    assert upgraded.provider == "complete_ohlcv"
    assert upgraded.data_quality_score == 100.0
    assert upgraded.open == 99.25
    assert upgraded.volume == 2_500_000


def test_unsupported_provider_does_not_pollute_successful_fallback_blockers():
    start = datetime(2026, 7, 10, 8, 0)
    unsupported = RecordingProvider()
    unsupported.supported_timeframes = frozenset({"1d"})
    fallback = RecordingProvider(frame(start, periods=5, frequency="15min"))
    fallback.name = "fallback"
    with setup_db() as db:
        asset = seed_asset(db)
        result = MultiProviderReplayDataService([unsupported, fallback]).ensure_coverage(
            db,
            asset=asset,
            timeframe="15m",
            start=start,
            end=start + timedelta(hours=1),
        )

    assert result.provider == "fallback"
    assert "UNSUPPORTED_TIMEFRAME" not in result.blockers


def seed_replay_bars(db: Session, asset: Asset, start: datetime, count: int, timeframe: str = "5m") -> None:
    for index in range(count):
        timestamp = start + timedelta(minutes=5 * index)
        values = replay_bar_values(asset.id)
        values.update(
            timeframe=timeframe,
            bar_timestamp=timestamp,
            provider="local",
            close=100.0 + index,
        )
        db.add(ReplayMarketBar(**values))
    db.commit()


def test_db_coverage_is_used_before_provider_fetch():
    provider = RecordingProvider()
    start = datetime(2026, 7, 10, 14, 30)
    with setup_db() as db:
        asset = seed_asset(db)
        seed_replay_bars(db, asset, start, count=4)
        result = MultiProviderReplayDataService([provider]).ensure_coverage(
            db,
            asset=asset,
            timeframe="5m",
            start=start,
            end=start + timedelta(minutes=15),
        )

    assert provider.requests == []
    assert result.status == "READY"
    assert result.rows_available == 4


def test_missing_range_uses_fallback_and_persists_real_bars():
    start = datetime(2026, 7, 10, 8, 0)
    primary = RecordingProvider(blocker="PROVIDER_UNAVAILABLE")
    fallback = RecordingProvider(frame(start, periods=5, frequency="15min"))
    fallback.name = "fallback"
    with setup_db() as db:
        asset = seed_asset(db, "ENI.MI", "ITALY")
        result = MultiProviderReplayDataService([primary, fallback]).ensure_coverage(
            db,
            asset=asset,
            timeframe="15m",
            start=start,
            end=start + timedelta(hours=1),
        )
        rows = db.scalars(select(ReplayMarketBar).where(ReplayMarketBar.asset_id == asset.id)).all()

    assert result.provider == "fallback"
    assert result.rows_available == 5
    assert len(rows) == 5
    assert result.provider_attempts[0]["blockers"] == ["PROVIDER_UNAVAILABLE"]


def test_provider_exception_is_isolated_and_fallback_still_runs():
    start = datetime(2026, 7, 10, 8, 0)
    primary = RaisingProvider()
    fallback = RecordingProvider(frame(start, periods=5, frequency="15min"))
    fallback.name = "fallback"
    with setup_db() as db:
        asset = seed_asset(db, "ENI.MI", "ITALY")
        result = MultiProviderReplayDataService([primary, fallback]).ensure_coverage(
            db,
            asset=asset,
            timeframe="15m",
            start=start,
            end=start + timedelta(hours=1),
        )

    assert result.provider == "fallback"
    assert result.provider_attempts[0]["blockers"] == ["PROVIDER_UNAVAILABLE"]


def test_daily_replay_imports_existing_price_history_before_provider_fetch():
    provider = RecordingProvider()
    start = datetime(2026, 7, 7)
    with setup_db() as db:
        asset = seed_asset(db)
        for offset in range(4):
            timestamp = start + timedelta(days=offset)
            db.add(
                PriceHistory(
                    asset_id=asset.id,
                    date=timestamp.date(),
                    open=100.0 + offset,
                    high=102.0 + offset,
                    low=99.0 + offset,
                    close=101.0 + offset,
                    volume=1_000_000 + offset,
                    provider="stored_history",
                )
            )
        db.commit()

        result = MultiProviderReplayDataService([provider]).ensure_coverage(
            db,
            asset=asset,
            timeframe="1d",
            start=start,
            end=start + timedelta(days=3),
        )
        rows = db.scalars(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == asset.id, ReplayMarketBar.timeframe == "1d")
            .order_by(ReplayMarketBar.bar_timestamp)
        ).all()

    assert provider.requests == []
    assert result.status == "READY"
    assert result.provider == "price_history_bridge"
    assert len(rows) == 4
    assert rows[-1].close == 104.0
    assert rows[-1].source_metadata["source_table"] == "price_history"


def test_yahoo_daily_live_quote_tail_is_quarantined_instead_of_added_as_a_candle(
    monkeypatch,
):
    from zoneinfo import ZoneInfo

    regular = datetime(2026, 10, 15, tzinfo=ZoneInfo("Europe/London")).timestamp()
    live = datetime(2026, 10, 19, 10, 21, 50, tzinfo=timezone.utc).timestamp()

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketTime": int(live),
                                "exchangeTimezoneName": "Europe/London",
                            },
                            "timestamp": [int(regular), int(live)],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [1.1, 1.2],
                                        "high": [1.2, 1.3],
                                        "low": [1, 1.1],
                                        "close": [1.15, 1.25],
                                        "volume": [0, 0],
                                    }
                                ]
                            },
                        }
                    ]
                }
            }

    monkeypatch.setattr(
        "app.providers.replay_data_provider.requests.get", lambda *a, **k: Response()
    )
    result = YahooReplayDataProvider().fetch(
        ReplayDataRequest(
            "EURUSD=X",
            "EURUSD=X",
            "Forex",
            "1d",
            datetime(2026, 1, 1),
            datetime(2026, 10, 19, 12),
        )
    )
    assert len(result.frame) == 1
    assert result.frame.index[0] == pd.Timestamp(regular, unit="s")
    assert result.source_metadata["rejected_off_grid_rows"] == 1


def test_yahoo_forming_candle_is_excluded_even_when_its_open_is_on_grid(monkeypatch):
    start=datetime(2026,7,15,13,30)
    class Response:
        def raise_for_status(self):pass
        def json(self):
            return {'chart':{'result':[{'timestamp':[int(start.replace(tzinfo=timezone.utc).timestamp())],
                'indicators':{'quote':[{'open':[100],'high':[101],'low':[99],'close':[100.5],'volume':[1000]}]}}]}}
    monkeypatch.setattr('app.providers.replay_data_provider.requests.get',lambda *a,**k:Response())
    result=YahooReplayDataProvider().fetch(ReplayDataRequest('NVDA','NVDA','USA','5m',start-timedelta(days=1),start+timedelta(minutes=2)))
    assert result.frame.empty
    assert result.source_metadata['rejected_unclosed_rows'] == 1


def test_closed_candle_can_replace_a_legacy_partial_once_at_equal_quality():
    with setup_db() as db:
        asset=seed_asset(db)
        values=replay_bar_values(asset.id)
        values.update(data_quality_score=100,close=160,high=161)
        db.add(ReplayMarketBar(**values))
        db.flush()
        timestamp=values['bar_timestamp']
        source=frame(timestamp,1,'min')
        MultiProviderReplayDataService._persist_bars(db,asset,'1m','yahoo_chart',source,
            {'data_quality_score':100,'closed_candles_only':True})
        db.flush()
        row=db.scalar(select(ReplayMarketBar))
        assert row.close == 100.5
        assert row.source_metadata['closed_candles_only'] is True
