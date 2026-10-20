from dataclasses import replace
from datetime import timedelta
import json
import time

from app.core.config import get_settings
from app.models import InformationProviderState
from .contracts import ProviderResult
from .fetch import PublicEvidenceFetcher
from .providers import (
    CentralBankProvider,
    ExistingNewsProvider,
    FredVintageProvider,
    GdeltDiscoveryProvider,
    SecFilingsProvider,
)
from .repository import InformationRepository


class InformationWorker:
    """Bounded acquisition. Caller owns transaction and execution-priority scheduling."""

    ROTATION = "information:rotation"

    def __init__(self, providers=None):
        self.providers = providers

    @staticmethod
    def default_providers(db):
        from app.services.fundamentals import CIK_MAP
        from app.services.macro import FRED_SERIES

        settings = get_settings()
        providers = [
            ExistingNewsProvider(db),
            CentralBankProvider("fed"),
            CentralBankProvider("ecb"),
        ]
        providers.extend(FredVintageProvider(series) for series in FRED_SERIES)
        if settings.information_fred_vintage_date:
            providers.extend(
                FredVintageProvider(
                    series,
                    vintage_date=settings.information_fred_vintage_date,
                    api_key=settings.information_fred_api_key.get_secret_value(),
                )
                for series in FRED_SERIES
            )
        providers.extend(
            SecFilingsProvider(
                cik,
                ticker,
                fetcher=PublicEvidenceFetcher(user_agent=settings.sec_user_agent),
            )
            for ticker, cik in sorted(CIK_MAP.items())
        )
        providers.append(GdeltDiscoveryProvider())
        return providers

    def run_once(self, db, *, as_of, deadline, max_items=50):
        if not 1 <= max_items <= 200:
            raise ValueError("Information item budget must be 1..200")
        providers = list(
            self.providers if self.providers is not None else self.default_providers(db)
        )
        if len({p.provider for p in providers}) != len(providers):
            raise ValueError("Provider identities must be unique")
        repo = InformationRepository()
        rotation = db.get(InformationProviderState, self.ROTATION)
        names = [p.provider for p in providers]
        start = (
            (names.index(rotation.cursor) + 1) % len(names)
            if rotation and rotation.cursor in names
            else 0
        )
        providers = providers[start:] + providers[:start]
        inserted, attempted, consumed, diagnostics, last = 0, 0, 0, [], None
        for provider in providers:
            if time.monotonic() >= deadline or consumed >= max_items:
                break
            state = db.get(InformationProviderState, provider.provider)
            last = provider.provider
            if state and state.retry_at and state.retry_at > as_of:
                diagnostics.append(
                    {
                        "provider": provider.provider,
                        "status": "BACKOFF",
                        "retry_at": state.retry_at.isoformat(),
                    }
                )
                continue
            attempted += 1
            try:
                cursor = json.loads(state.cursor) if state and state.cursor else {}
                cursor["_limit"] = max_items - consumed
                result = provider.fetch(cursor=cursor, as_of=as_of, deadline=deadline)
                if (
                    result.provider != provider.provider
                    or len(result.evidence) > max_items - consumed
                ):
                    raise ValueError("Invalid provider identity or item budget")
            except Exception:
                # Exception text can contain a credential-bearing request URL.
                result = ProviderResult(
                    provider.provider,
                    "UNAVAILABLE",
                    (),
                    observed_at=as_of,
                    error_code="ADAPTER_FAILED",
                )
            if result.retry_at is None:
                failures = state.retries if state else 0
                seconds = (
                    60
                    if result.status in {"AVAILABLE", "EMPTY"}
                    else min(3600, 30 * 2 ** min(failures, 7))
                )
                if result.status == "ENTITLEMENT_REQUIRED":
                    seconds = 3600
                result = replace(
                    result,
                    retry_at=max(as_of, result.observed_at)
                    + timedelta(seconds=seconds),
                )
            stored = repo.ingest(db, result)
            inserted += stored["inserted"]
            consumed += len(result.evidence)
            diagnostics.append(
                {
                    "provider": result.provider,
                    "status": result.status,
                    "accepted": len(result.evidence),
                    "error_code": result.error_code,
                }
            )
        if last:
            repo.ingest(
                db,
                ProviderResult(
                    self.ROTATION, "EMPTY", (), observed_at=as_of, cursor=last
                ),
            )
        return {
            "inserted": inserted,
            "consumed": consumed,
            "attempted": attempted,
            "providers": diagnostics,
            "budget_exhausted": consumed >= max_items or time.monotonic() >= deadline,
        }
