from __future__ import annotations

from datetime import date, datetime
from io import StringIO
import time

import pandas as pd
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import MacroSnapshot


FRED_SERIES = {
    "DGS10": {"label": "US 10Y Treasury yield", "unit": "percent"},
    "DGS2": {"label": "US 2Y Treasury yield", "unit": "percent"},
    "T10Y2Y": {"label": "10Y minus 2Y Treasury spread", "unit": "percent"},
    "FEDFUNDS": {"label": "Effective Fed Funds rate", "unit": "percent"},
    "CPIAUCSL": {"label": "US CPI index", "unit": "index"},
    "VIXCLS": {"label": "CBOE VIX", "unit": "index"},
    "DCOILWTICO": {"label": "WTI crude oil", "unit": "USD"},
}


def update_macro_snapshots(db: Session, limit_per_series: int = 420) -> dict:
    inserted = 0
    diagnostics = []
    for indicator, meta in FRED_SERIES.items():
        rows = fetch_fred_series(indicator, limit_per_series=limit_per_series)
        if not rows:
            diagnostics.append({"indicator": indicator, "status": "source_unavailable"})
            continue
        for row in rows:
            existing = db.scalar(
                select(MacroSnapshot)
                .where(MacroSnapshot.indicator == indicator, MacroSnapshot.date == row["date"], MacroSnapshot.provider == "fred")
                .limit(1)
            )
            details = {"label": meta["label"], "unit": meta["unit"], "source": "FRED public CSV",
                       "source_capability": "current_state", "historical_availability_verified": False}
            if existing:
                existing.value = row["value"]
                existing.details = details
                existing.created_at = datetime.utcnow()
            else:
                db.add(MacroSnapshot(indicator=indicator, date=row["date"], value=row["value"], provider="fred", details=details))
                inserted += 1
        diagnostics.append({"indicator": indicator, "status": "ok", "rows": len(rows), "latest_date": str(rows[-1]["date"])})
    db.commit()
    return {"inserted_or_updated": inserted, "series_checked": len(FRED_SERIES), "diagnostics": diagnostics}


def macro_overview(db: Session) -> dict:
    latest = {}
    indicators = []
    for indicator, meta in FRED_SERIES.items():
        row = db.scalar(
            select(MacroSnapshot)
            .where(MacroSnapshot.indicator == indicator)
            .order_by(desc(MacroSnapshot.date), desc(MacroSnapshot.created_at))
            .limit(1)
        )
        latest[indicator] = {
            "label": meta["label"],
            "unit": meta["unit"],
            "date": row.date.isoformat() if row else None,
            "value": row.value if row else None,
            "status": "ready" if row else "missing",
        }
        observations = int(db.scalar(select(func.count(MacroSnapshot.id)).where(MacroSnapshot.indicator == indicator)) or 0)
        indicators.append(
            {
                "indicator": indicator,
                "description": meta["label"],
                "unit": meta["unit"],
                "latest_date": row.date.isoformat() if row else None,
                "latest_value": row.value if row else None,
                "observations": observations,
                "status": "ready" if row else "missing",
            }
        )
    regime = macro_regime(latest)
    ready_count = sum(1 for item in latest.values() if item["status"] == "ready")
    return {
        "data_policy": "FRED public macro series only. Missing values are not interpolated for live reasoning.",
        "provider": "fred",
        "series_count": ready_count,
        "series": latest,
        "indicators": indicators,
        "regime": regime,
        "coverage_score": round(ready_count / max(1, len(latest)) * 100, 1),
    }


def fetch_fred_series(series_id: str, limit_per_series: int, *, fetcher=None) -> list[dict]:
    from app.services.information.fetch import PublicEvidenceFetcher
    if series_id not in FRED_SERIES:
        return []
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        response = (fetcher or PublicEvidenceFetcher()).fetch(url, deadline=time.monotonic()+10)
        if response.status != "AVAILABLE":
            return []
        frame = pd.read_csv(StringIO(response.body.decode("utf-8-sig")))
    except Exception:
        return []
    if frame.empty or "observation_date" not in frame or series_id not in frame:
        return []
    frame["date"] = pd.to_datetime(frame["observation_date"], errors="coerce").dt.date
    frame["value"] = pd.to_numeric(frame[series_id].replace(".", pd.NA), errors="coerce")
    frame = frame.dropna(subset=["date", "value"]).tail(limit_per_series)
    return [{"date": item.date, "value": float(item.value)} for item in frame.itertuples()]


def macro_regime(series: dict) -> dict:
    ten = value(series, "DGS10")
    two = value(series, "DGS2")
    spread = value(series, "T10Y2Y")
    vix = value(series, "VIXCLS")
    oil = value(series, "DCOILWTICO")
    labels = []
    if spread is not None and spread < 0:
        labels.append("inverted_curve")
    if vix is not None and vix >= 25:
        labels.append("elevated_volatility")
    if ten is not None and two is not None and ten > two and ten >= 4:
        labels.append("restrictive_rates")
    if oil is not None and oil >= 90:
        labels.append("energy_pressure")
    return {
        "labels": labels or ["macro_neutral"],
        "interpretation": " | ".join(labels) if labels else "No major public macro stress label from stored FRED series.",
    }


def value(series: dict, key: str) -> float | None:
    item = series.get(key) or {}
    return item.get("value")
