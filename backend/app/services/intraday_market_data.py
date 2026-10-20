from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Asset, ReplayMarketBar
from app.services.intraday_contracts import IntradayDataBundle, INTRADAY_DATA_BLOCKED, REQUIRED_INTRADAY_TIMEFRAMES
from app.services.replay_data import MultiProviderReplayDataService
from app.services.market_clock import eligible_bar


class StrictIntradayDataGateway:
    def __init__(
        self,
        *,
        data_service: MultiProviderReplayDataService | None = None,
        refresh_missing: bool = True,
        max_one_minute_age: timedelta = timedelta(minutes=3),
    ):
        self.data_service = data_service or MultiProviderReplayDataService()
        self.refresh_missing = refresh_missing
        self.max_age = {
            "1d": timedelta(days=4),
            "15m": timedelta(minutes=45),
            "5m": timedelta(minutes=15),
            "1m": max_one_minute_age,
        }
        self.minimum_rows = {"1d": 20, "15m": 20, "5m": 20, "1m": 20}

    def load(self, db: Session, *, asset: Asset, now: datetime) -> IntradayDataBundle:
        ranges = {
            "1d": (now - timedelta(days=400), now),
            "15m": (now - timedelta(days=10), now),
            "5m": (now - timedelta(days=5), now),
            "1m": (now - timedelta(days=2), now),
        }
        attempts: list[dict] = []
        if self.refresh_missing:
            for timeframe in REQUIRED_INTRADAY_TIMEFRAMES:
                start, end = ranges[timeframe]
                result = self.data_service.ensure_coverage(db, asset=asset, timeframe=timeframe, start=start, end=end)
                attempts.append(
                    {
                        "timeframe": timeframe,
                        "status": result.status,
                        "provider": result.provider,
                        "rows": result.rows_available,
                        "blockers": list(result.blockers),
                    }
                )

        bars: dict[str, tuple[ReplayMarketBar, ...]] = {}
        latest: dict[str, datetime | None] = {}
        providers: dict[str, str | None] = {}
        quality: dict[str, float] = {}
        blockers: list[str] = []
        for timeframe in REQUIRED_INTRADAY_TIMEFRAMES:
            rows = tuple(
                reversed(
                    db.scalars(
                        select(ReplayMarketBar)
                        .where(
                            ReplayMarketBar.asset_id == asset.id,
                            ReplayMarketBar.timeframe == timeframe,
                            ReplayMarketBar.bar_timestamp <= now,
                        )
                        .order_by(desc(ReplayMarketBar.bar_timestamp))
                        .limit(260)
                    ).all()
                )
            )
            rows = tuple(row for row in rows if eligible_bar(row, decision_at=None, as_of=now, mode="context"))
            bars[timeframe] = rows
            latest_row = rows[-1] if rows else None
            latest[timeframe] = latest_row.bar_timestamp if latest_row else None
            providers[timeframe] = latest_row.provider if latest_row else None
            quality[timeframe] = min((float(row.data_quality_score or 0.0) for row in rows), default=0.0)
            if len(rows) < self.minimum_rows[timeframe]:
                blockers.append(f"MISSING_{timeframe.upper()}_DATA")
                continue
            if latest_row and now - latest_row.bar_timestamp > self.max_age[timeframe]:
                blockers.append(f"STALE_{timeframe.upper()}_DATA")
            if quality[timeframe] < 35.0:
                blockers.append(f"LOW_QUALITY_{timeframe.upper()}_DATA")
            if any(row.close is None or float(row.close) <= 0 for row in rows):
                blockers.append(f"INVALID_{timeframe.upper()}_PRICE")

        deduped = tuple(dict.fromkeys(blockers))
        context = None
        if not deduped:
            from app.services.information.context import OpportunityContextBuilder, price_reference
            context = OpportunityContextBuilder().build(
                db, market_family="equity", asset_key=asset.ticker, decision_at=now,
                price_refs=tuple(price_reference(rows[-1], rows) for rows in bars.values() if rows),
            )
        return IntradayDataBundle(
            status=INTRADAY_DATA_BLOCKED if deduped else "READY",
            ticker=asset.ticker,
            market=asset.country or asset.exchange or "UNKNOWN",
            as_of=now,
            bars=bars,
            latest_timestamps=latest,
            providers=providers,
            quality_scores=quality,
            blockers=deduped,
            provider_attempts=tuple(attempts),
            information_context=context,
        )
