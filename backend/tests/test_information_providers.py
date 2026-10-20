from datetime import timedelta
import json
import time

from sqlalchemy import select

from app.services.information.fetch import FetchResult
from app.services.information.providers import (
    CentralBankProvider,
    FredVintageProvider,
    GdeltDiscoveryProvider,
    SecFilingsProvider,
)
from app.services.information.worker import InformationWorker
from app.services.information.repository import InformationRepository
from test_information_repository import db, NOW

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Fed</title><language>it</language>
<item><title>Decisione sui tassi</title><link>https://example.org/1</link><description>Inflazione e crescita</description><pubDate>Tue, 20 Oct 2026 11:00:00 GMT</pubDate></item>
<item><title>Data sconosciuta</title><link>https://example.org/2</link></item></channel></rss>"""


class Fetcher:
    def __init__(self, response):
        self.response, self.calls = response, []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def ok(body=RSS, kind="application/xml"):
    return Fetcher(
        FetchResult(
            "AVAILABLE", body, kind, "https://example.org/feed", {"etag": '"v1"'}, NOW
        )
    )


def test_information_central_bank_preserves_missing_date_utf8_and_currency_links():
    fetcher = ok()
    result = CentralBankProvider("fed", fetcher=fetcher).fetch(
        cursor={}, as_of=NOW, deadline=time.monotonic() + 1
    )
    assert result.status == "AVAILABLE" and len(result.evidence) == 2
    assert result.evidence[0].payload["title"] == "Decisione sui tassi"
    assert result.evidence[0].language == "it"
    assert result.evidence[1].published_at is None
    assert all(x.entity_key == "USD" and x.kind == "currency" for x in result.links)


def test_information_feed_cursor_drains_pending_without_losing_a_budgeted_item():
    fetcher = ok()
    adapter = CentralBankProvider("ecb", fetcher=fetcher)
    first = adapter.fetch(
        cursor={"_limit": 1}, as_of=NOW, deadline=time.monotonic() + 1
    )
    assert len(first.evidence) == 1
    second = adapter.fetch(
        cursor={**json.loads(first.cursor), "_limit": 1},
        as_of=NOW + timedelta(minutes=1),
        deadline=time.monotonic() + 1,
    )
    assert (
        len(second.evidence) == 1
        and second.evidence[0].evidence_id != first.evidence[0].evidence_id
    )
    assert len(fetcher.calls) == 1 and second.evidence[0].observed_at == NOW


def test_information_bad_xml_is_failure_not_empty_success():
    result = CentralBankProvider("fed", fetcher=ok(b"<html>denied", "text/html")).fetch(
        cursor={}, as_of=NOW, deadline=time.monotonic() + 1
    )
    assert result.status == "UNAVAILABLE" and result.error_code == "BAD_XML"


def test_information_failed_source_does_not_stop_other_providers_and_retry_survives_restart(
    db,
):
    from app.models import InformationEvidence, InformationProviderState

    limited = Fetcher(
        FetchResult(
            "QUOTA_LIMITED",
            observed_at=NOW,
            retry_at=NOW + timedelta(minutes=10),
            error_code="HTTP_429",
        )
    )
    quota = CentralBankProvider("fed", fetcher=limited)
    ecb = CentralBankProvider("ecb", fetcher=ok())
    run = InformationWorker([quota, ecb]).run_once(
        db, as_of=NOW, deadline=time.monotonic() + 1, max_items=10
    )
    assert (
        run["inserted"] == 2
        and db.get(InformationProviderState, quota.provider).status == "QUOTA_LIMITED"
    )
    db.commit()
    InformationWorker([quota, ecb]).run_once(
        db,
        as_of=NOW + timedelta(minutes=1),
        deadline=time.monotonic() + 1,
        max_items=10,
    )
    assert len(limited.calls) == 1
    assert len(db.scalars(select(InformationEvidence)).all()) == 2


def test_information_current_fred_is_live_state_without_invented_publication_or_vintage(
    db,
):
    fetcher = ok(
        b"observation_date,DGS10\n2026-10-16,4.1\n2026-10-19,4.2\n", "text/csv"
    )
    adapter = FredVintageProvider("DGS10", fetcher=fetcher)
    result = adapter.fetch(cursor={}, as_of=NOW, deadline=time.monotonic() + 1)
    (item,) = result.evidence
    assert item.published_at is None and not item.historical_availability_verified
    assert (
        item.payload["source_capability"] == "current_state"
        and item.payload["unit"] == "percent"
    )
    InformationRepository().ingest(db, result)
    assert (
        len(
            InformationRepository().eligible(
                db, market_family="forex", asset_key="EURUSD=X", as_of=NOW
            )
        )
        == 1
    )
    assert (
        InformationRepository().eligible(
            db, market_family="forex", asset_key="EURUSD=X", as_of=NOW, historical=True
        )
        == ()
    )


def test_information_fred_vintage_requires_key_and_never_calls_current_csv_a_vintage():
    adapter = FredVintageProvider("DGS10", vintage_date="2024-06-01", fetcher=ok())
    missing = adapter.fetch(cursor={}, as_of=NOW, deadline=time.monotonic() + 1)
    assert missing.status == "ENTITLEMENT_REQUIRED" and not adapter.fetcher.calls
    payload = {
        "observations": [
            {
                "date": "2024-05-31",
                "value": "4.5",
                "realtime_start": "2024-06-01",
                "realtime_end": "2024-06-01",
            }
        ]
    }
    fetcher = ok(json.dumps(payload).encode(), "application/json")
    verified = FredVintageProvider(
        "DGS10", vintage_date="2024-06-01", api_key="test-private-key", fetcher=fetcher
    ).fetch(cursor={}, as_of=NOW, deadline=time.monotonic() + 1)
    (item,) = verified.evidence
    assert (
        item.historical_availability_verified
        and item.available_at.isoformat() == "2024-06-02T00:00:00"
    )
    assert (
        "test-private-key" not in repr(item)
        and "test-private-key" not in verified.cursor
    )


def test_information_sec_403_is_not_missing_api_key_or_success():
    adapter = SecFilingsProvider(
        "320193",
        "AAPL",
        fetcher=Fetcher(
            FetchResult("UNAVAILABLE", error_code="HTTP_403", observed_at=NOW)
        ),
    )
    result = adapter.fetch(cursor={}, as_of=NOW, deadline=time.monotonic() + 1)
    assert result.status == "UNAVAILABLE" and result.error_code == "HTTP_403"


def test_information_sec_uses_acceptance_clock_accession_and_exact_issuer():
    payload = {
        "name": "Apple",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000001"],
                "acceptanceDateTime": ["2026-10-20T11:30:00Z"],
                "form": ["8-K"],
                "primaryDocument": ["filing.htm"],
            }
        },
    }
    result = SecFilingsProvider(
        "320193", "AAPL", fetcher=ok(json.dumps(payload).encode(), "application/json")
    ).fetch(cursor={}, as_of=NOW, deadline=time.monotonic() + 1)
    (item,) = result.evidence
    assert item.published_at.hour == 11 and item.published_at.minute == 30
    assert "000032019326000001" in item.canonical_url
    assert result.links[0].entity_key == "AAPL" and result.links[0].confidence == 1


def test_information_gdelt_seen_time_is_not_fabricated_publication():
    payload = {
        "articles": [
            {
                "url": "https://example.org/story",
                "title": "Tassi 日本語",
                "seendate": "20261020T110000Z",
                "language": "Japanese",
            }
        ]
    }
    result = GdeltDiscoveryProvider(
        fetcher=ok(json.dumps(payload).encode(), "application/json")
    ).fetch(cursor={}, as_of=NOW, deadline=time.monotonic() + 1)
    (item,) = result.evidence
    assert (
        item.published_at is None and item.payload["source_capability"] == "discovery"
    )


def test_information_existing_news_uses_bounded_fetch_and_preserves_undated_items():
    from app.ingestion.news_ingestor import NewsIngestor

    ingestor = NewsIngestor(ai=object(), fetcher=ok())
    diagnostic, rows = ingestor._fetch_source(
        {"url": "https://example.org/feed", "name": "Feed", "tier": 1, "desk": "macro"},
        NOW - timedelta(days=1),
        10,
    )
    assert diagnostic["status"] == "ok" and len(rows) == 2
    assert rows[1]["published_at"] is None and rows[0]["created_at"] == NOW


def test_information_existing_news_content_revision_is_kept_before_legacy_dedup(db):
    from app.ingestion.news_ingestor import NewsIngestor
    from app.models import InformationEvidence

    ingestor = NewsIngestor(ai=object(), fetcher=ok())
    item = {
        "url": "https://example.org/story",
        "source_url": "https://example.org/feed",
        "source": "Feed",
        "title": "First release",
        "summary": "Original",
        "created_at": NOW,
        "published_at": NOW,
        "theme_tags": {},
    }
    ingestor._persist_source_evidence(db, item, [])
    ingestor._persist_source_evidence(
        db,
        {
            **item,
            "title": "Corrected release",
            "created_at": NOW + timedelta(minutes=1),
        },
        [],
    )
    rows = db.scalars(
        select(InformationEvidence).order_by(InformationEvidence.observed_at)
    ).all()
    assert len(rows) == 2 and rows[1].revision_of == rows[0].evidence_id
    assert rows[0].payload["title"] == "First release"


def test_information_legacy_macro_fetch_uses_the_bounded_retriever():
    from app.services.macro import fetch_fred_series

    rows = fetch_fred_series(
        "DGS10", 10, fetcher=ok(b"observation_date,DGS10\n2026-10-19,4.2\n", "text/csv")
    )
    assert len(rows) == 1 and rows[0]["value"] == 4.2


def test_information_worker_rotates_providers_when_one_fills_the_item_budget(db):
    fed, ecb = CentralBankProvider("fed", fetcher=ok()), CentralBankProvider(
        "ecb", fetcher=ok()
    )
    worker = InformationWorker([fed, ecb])
    first = worker.run_once(db, as_of=NOW, deadline=time.monotonic() + 1, max_items=1)
    second = InformationWorker([fed, ecb]).run_once(
        db, as_of=NOW + timedelta(minutes=2), deadline=time.monotonic() + 1, max_items=1
    )
    assert first["providers"][0]["provider"] == fed.provider
    assert second["providers"][0]["provider"] == ecb.provider


def test_information_configuration_bounds_and_credentials_are_explicit():
    import pytest
    from app.core.config import Settings

    settings = Settings(BLUM_INFORMATION_FRED_API_KEY="test-key")
    assert settings.information_fred_api_key.get_secret_value() == "test-key"
    assert "test-key" not in repr(settings)
    assert (
        settings.information_max_items == 50
        and settings.information_budget_seconds <= 10
    )
    with pytest.raises(ValueError):
        Settings(BLUM_INFORMATION_BUDGET_SECONDS=100)
