from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset, PriceHistory, ReplayDataCoverage, ReplayMarketBar
from app.providers.replay_data_provider import (
    ReplayDataProvider,
    ReplayDataRequest,
    default_replay_providers,
    normalize_replay_frame,
)


@dataclass
class ReplayCoverageResult:
    status: str
    timeframe: str
    rows_available: int
    provider: str | None
    coverage_percent: float
    data_quality_score: float
    blockers: list[str] = field(default_factory=list)
    provider_attempts: list[dict] = field(default_factory=list)
    available_start: datetime | None = None
    available_end: datetime | None = None


class MultiProviderReplayDataService:
    def __init__(self, providers: list[ReplayDataProvider] | None = None):
        self.providers = providers or default_replay_providers()

    def ensure_coverage(
        self,
        db: Session,
        *,
        asset: Asset,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> ReplayCoverageResult:
        local = self._coverage(db, asset.id, timeframe, start, end)
        if local["complete"]:
            return ReplayCoverageResult(
                status="READY",
                timeframe=timeframe,
                rows_available=local["rows"],
                provider="local_db",
                coverage_percent=100.0,
                data_quality_score=local["quality"],
                available_start=local["start"],
                available_end=local["end"],
            )

        if timeframe == "1d":
            imported = self._import_price_history(db, asset=asset, start=start, end=end)
            if imported:
                local = self._coverage(db, asset.id, timeframe, start, end)
                if local["complete"]:
                    return ReplayCoverageResult(
                        status="READY",
                        timeframe=timeframe,
                        rows_available=local["rows"],
                        provider="price_history_bridge",
                        coverage_percent=100.0,
                        data_quality_score=local["quality"],
                        available_start=local["start"],
                        available_end=local["end"],
                    )

        attempts: list[dict] = []
        selected_provider: str | None = None
        selected_metadata: dict = {}
        blockers: list[str] = []
        for provider in self.providers:
            if timeframe not in provider.supported_timeframes:
                attempts.append({"provider": provider.name, "status": "blocked", "blockers": ["UNSUPPORTED_TIMEFRAME"]})
                continue
            request = ReplayDataRequest(
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker.upper(),
                market=asset.country or asset.exchange or "UNKNOWN",
                timeframe=timeframe,
                start=start,
                end=end,
            )
            try:
                result = provider.fetch(request)
            except Exception as exc:
                attempts.append(
                    {
                        "provider": provider.name,
                        "status": "blocked",
                        "rows": 0,
                        "blockers": ["PROVIDER_UNAVAILABLE"],
                        "error_type": type(exc).__name__,
                    }
                )
                blockers.append("PROVIDER_UNAVAILABLE")
                continue
            normalized = normalize_replay_frame(result.frame) if result.frame is not None and not result.frame.empty else pd.DataFrame()
            attempts.append(
                {
                    "provider": provider.name,
                    "status": "ready" if not normalized.empty else "blocked",
                    "rows": len(normalized),
                    "blockers": list(result.blockers),
                }
            )
            blockers.extend(code for code in result.blockers if not code.startswith("UNSUPPORTED_"))
            if normalized.empty:
                continue
            self._persist_bars(db, asset, timeframe, provider.name, normalized, result.source_metadata)
            selected_provider = provider.name
            selected_metadata = result.source_metadata
            break

        final = self._coverage(db, asset.id, timeframe, start, end)
        status = "READY" if final["complete"] else "PARTIAL" if final["rows"] else "DATA_BLOCKED"
        if not final["complete"]:
            blockers.append("COVERAGE_INCOMPLETE")
        quality = final["quality"]
        if final["rows"] and quality < 50:
            blockers.append("DATA_QUALITY_LOW")
        deduped_blockers = list(dict.fromkeys(blockers))
        self._persist_coverage(
            db,
            asset=asset,
            timeframe=timeframe,
            provider=selected_provider or (attempts[-1]["provider"] if attempts else "none"),
            start=start,
            end=end,
            coverage=final,
            status=status,
            blockers=deduped_blockers,
            metadata=selected_metadata,
        )
        db.flush()
        return ReplayCoverageResult(
            status=status,
            timeframe=timeframe,
            rows_available=final["rows"],
            provider=selected_provider,
            coverage_percent=100.0 if final["complete"] else self._coverage_percent(final, start, end),
            data_quality_score=quality,
            blockers=deduped_blockers,
            provider_attempts=attempts,
            available_start=final["start"],
            available_end=final["end"],
        )

    def load_bars(self, db: Session, *, asset_id: int, timeframe: str, start: datetime, end: datetime) -> list[ReplayMarketBar]:
        return db.scalars(
            select(ReplayMarketBar)
            .where(
                ReplayMarketBar.asset_id == asset_id,
                ReplayMarketBar.timeframe == timeframe,
                ReplayMarketBar.bar_timestamp >= start,
                ReplayMarketBar.bar_timestamp <= end,
            )
            .order_by(ReplayMarketBar.bar_timestamp)
        ).all()

    @staticmethod
    def _coverage(db: Session, asset_id: int, timeframe: str, start: datetime, end: datetime) -> dict:
        row = db.execute(
            select(
                func.count(ReplayMarketBar.id),
                func.min(ReplayMarketBar.bar_timestamp),
                func.max(ReplayMarketBar.bar_timestamp),
                func.avg(ReplayMarketBar.data_quality_score),
            ).where(
                ReplayMarketBar.asset_id == asset_id,
                ReplayMarketBar.timeframe == timeframe,
                ReplayMarketBar.bar_timestamp >= start,
                ReplayMarketBar.bar_timestamp <= end,
            )
        ).one()
        count, available_start, available_end, quality = row
        complete = bool(count and available_start <= start and available_end >= end)
        return {"rows": int(count or 0), "start": available_start, "end": available_end, "quality": float(quality or 0.0), "complete": complete}

    @staticmethod
    def _persist_bars(db: Session, asset: Asset, timeframe: str, provider: str, frame: pd.DataFrame, metadata: dict) -> None:
        timestamps = [pd.Timestamp(value).to_pydatetime().replace(tzinfo=None) for value in frame.index]
        existing = {
            row.bar_timestamp: row
            for row in db.scalars(
                select(ReplayMarketBar).where(
                    ReplayMarketBar.asset_id == asset.id,
                    ReplayMarketBar.timeframe == timeframe,
                    ReplayMarketBar.bar_timestamp.in_(timestamps),
                )
            ).all()
        }
        provider_quality = metadata.get("data_quality_score") if isinstance(metadata, dict) else None
        quality = _number(provider_quality) if provider_quality is not None else _frame_quality(frame)
        quality = max(0.0, min(100.0, float(quality or 0.0)))
        acquired_at = datetime.utcnow()
        for timestamp, (_, row) in zip(timestamps, frame.iterrows()):
            persisted = existing.get(timestamp)
            if persisted is not None:
                old_quality = float(persisted.data_quality_score or 0.0)
                finalized_legacy = (
                    quality >= old_quality
                    and metadata.get("closed_candles_only") is True
                    and (persisted.source_metadata or {}).get("closed_candles_only") is not True
                )
                if quality > old_quality or finalized_legacy:
                    persisted.open = _number(row.get("Open"))
                    persisted.high = _number(row.get("High"))
                    persisted.low = _number(row.get("Low"))
                    persisted.close = float(row.get("Close"))
                    persisted.volume = _number(row.get("Volume"))
                    persisted.provider = provider
                    persisted.acquired_at = acquired_at
                    persisted.data_quality_score = quality
                    persisted.source_metadata = metadata
                continue
            db.add(
                ReplayMarketBar(
                    asset_id=asset.id,
                    source_symbol=asset.ticker,
                    normalized_symbol=asset.ticker.upper(),
                    market=asset.country or asset.exchange or "UNKNOWN",
                    timeframe=timeframe,
                    bar_timestamp=timestamp,
                    open=_number(row.get("Open")),
                    high=_number(row.get("High")),
                    low=_number(row.get("Low")),
                    close=float(row.get("Close")),
                    volume=_number(row.get("Volume")),
                    provider=provider,
                    acquired_at=acquired_at,
                    data_quality_score=quality,
                    source_metadata=metadata,
                )
            )
        db.flush()

    @staticmethod
    def _import_price_history(db: Session, *, asset: Asset, start: datetime, end: datetime) -> int:
        prices = db.scalars(
            select(PriceHistory)
            .where(
                PriceHistory.asset_id == asset.id,
                PriceHistory.date >= start.date(),
                PriceHistory.date <= end.date(),
            )
            .order_by(PriceHistory.date)
        ).all()
        if not prices:
            return 0
        timestamps = [datetime.combine(price.date, datetime.min.time()) for price in prices]
        existing = set(
            db.scalars(
                select(ReplayMarketBar.bar_timestamp).where(
                    ReplayMarketBar.asset_id == asset.id,
                    ReplayMarketBar.timeframe == "1d",
                    ReplayMarketBar.bar_timestamp.in_(timestamps),
                )
            ).all()
        )
        acquired_at = datetime.utcnow()
        imported = 0
        for price, timestamp in zip(prices, timestamps):
            if timestamp in existing:
                continue
            db.add(
                ReplayMarketBar(
                    asset_id=asset.id,
                    source_symbol=asset.ticker,
                    normalized_symbol=asset.ticker.upper(),
                    market=asset.country or asset.exchange or "UNKNOWN",
                    timeframe="1d",
                    bar_timestamp=timestamp,
                    open=price.open,
                    high=price.high,
                    low=price.low,
                    close=price.close,
                    volume=price.volume,
                    provider="price_history_bridge",
                    acquired_at=acquired_at,
                    data_quality_score=95.0,
                    source_metadata={
                        "source_table": "price_history",
                        "original_provider": price.provider,
                        "point_in_time": True,
                    },
                )
            )
            imported += 1
        db.flush()
        return imported

    @staticmethod
    def _persist_coverage(db: Session, *, asset: Asset, timeframe: str, provider: str, start: datetime, end: datetime, coverage: dict, status: str, blockers: list[str], metadata: dict) -> None:
        row = db.scalar(
            select(ReplayDataCoverage).where(
                ReplayDataCoverage.asset_id == asset.id,
                ReplayDataCoverage.timeframe == timeframe,
                ReplayDataCoverage.provider == provider,
            )
        )
        if row is None:
            row = ReplayDataCoverage(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker.upper(),
                market=asset.country or asset.exchange or "UNKNOWN",
                timeframe=timeframe,
                provider=provider,
            )
            db.add(row)
        row.requested_start = start
        row.requested_end = end
        row.available_start = coverage["start"]
        row.available_end = coverage["end"]
        row.rows_available = coverage["rows"]
        row.coverage_percent = MultiProviderReplayDataService._coverage_percent(coverage, start, end)
        row.data_quality_score = coverage["quality"]
        row.status = status
        row.missing_intervals = [] if coverage["complete"] else [{"start": start.isoformat(), "end": end.isoformat()}]
        row.blockers = blockers
        row.source_metadata = metadata
        row.acquired_at = datetime.utcnow() if coverage["rows"] else None
        row.updated_at = datetime.utcnow()

    @staticmethod
    def _coverage_percent(coverage: dict, start: datetime, end: datetime) -> float:
        if coverage["complete"]:
            return 100.0
        if not coverage["start"] or not coverage["end"] or end <= start:
            return 0.0
        covered = max(0.0, (min(end, coverage["end"]) - max(start, coverage["start"])).total_seconds())
        return round(min(100.0, covered / (end - start).total_seconds() * 100), 2)


def _frame_quality(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    completeness = float(frame[["Open", "High", "Low", "Close"]].notna().mean().mean())
    volume = float(frame["Volume"].notna().mean())
    return round(min(100.0, completeness * 85 + volume * 15), 2)


def _number(value) -> float | None:
    try:
        return None if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return None
