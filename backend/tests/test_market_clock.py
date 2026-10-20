from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def test_dst_holiday_and_half_day_session():
    from app.services.market_clock import MarketClock

    clock = MarketClock()
    assert clock.session("USA", datetime(2026, 11, 26, 16)) == "closed"
    assert clock.session("USA", datetime(2026, 11, 27, 17, 59)) == "regular"
    assert clock.session("USA", datetime(2026, 11, 27, 18)) == "closed"
    assert clock.session("USA", datetime(2026, 7, 13, 13, 29)) == "closed"
    assert clock.session("USA", datetime(2026, 7, 13, 13, 30)) == "regular"
    assert clock.session("USA", datetime(2026, 1, 12, 14, 29)) == "closed"
    assert (
        clock.session("USA", datetime(2026, 1, 12, 14, 30, tzinfo=timezone.utc))
        == "regular"
    )
    assert clock.session("FOREX", datetime(2026, 10, 17, 12)) == "closed"
    assert clock.session("FOREX", datetime(2026, 10, 18, 21)) == "regular"


def test_eligible_bar_requires_closed_and_acquired_context():
    from app.services.market_clock import eligible_bar

    at = datetime(2026, 10, 20, 14, 2)
    row = SimpleNamespace(
        bar_timestamp=at - timedelta(minutes=1),
        timeframe="1m",
        market="USA",
        acquired_at=at,
        source_metadata={},
    )
    assert not eligible_bar(row, decision_at=None, as_of=at, mode="context")
    assert eligible_bar(
        row, decision_at=None, as_of=at + timedelta(minutes=1), mode="context"
    )
    row.acquired_at = at + timedelta(minutes=5)
    assert not eligible_bar(
        row, decision_at=None, as_of=at + timedelta(minutes=1), mode="context"
    )


def test_gateway_ignores_future_acquired_bars():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.database import Base
    from app.models import Asset, ReplayMarketBar
    from app.services.intraday_market_data import StrictIntradayDataGateway

    at = datetime(2026, 10, 20, 14, 30)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        asset = Asset(
            ticker="AAPL",
            name="Apple",
            category="Stock",
            sector="Technology",
            asset_type="Stock",
            country="USA",
        )
        db.add(asset)
        db.flush()
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol="AAPL",
                normalized_symbol="AAPL",
                market="USA",
                timeframe="1m",
                bar_timestamp=at - timedelta(minutes=3),
                acquired_at=at + timedelta(minutes=1),
                close=100,
                provider="fixture",
                data_quality_score=95,
                source_metadata={},
            )
        )
        db.commit()
        result = StrictIntradayDataGateway(refresh_missing=False).load(
            db, asset=asset, now=at
        )
        assert result.bars["1m"] == ()
