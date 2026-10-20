from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.services.information.contracts import (
    EvidenceLink,
    ProviderResult,
    SourceEvidence,
)
from app.services.information.repository import InformationRepository

NOW = datetime(2026, 10, 20, 12)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def evidence(
    *, payload=None, published=NOW, observed=NOW, available=NOW, verified=False
):
    return SourceEvidence.create(
        provider="official",
        canonical_url="https://example.org/release#section",
        payload=payload or {"title": "Release", "value": 3.0},
        language="en",
        published_at=published,
        observed_at=observed,
        available_at=available,
        historical_availability_verified=verified,
        extraction_version="v1",
    )


def ingest(db, item, *, status="AVAILABLE", observed=NOW, cursor="page2", links=None):
    return InformationRepository().ingest(
        db,
        ProviderResult(
            provider="official",
            status=status,
            evidence=(item,) if item else (),
            links=(
                tuple(
                    links
                    if links is not None
                    else [
                        EvidenceLink(
                            item.evidence_id,
                            "AAPL",
                            "issuer",
                            1.0,
                            "exact issuer",
                            "v1",
                        )
                    ]
                )
                if item
                else ()
            ),
            observed_at=observed,
            cursor=cursor,
        ),
    )


def test_information_missing_publication_is_preserved_and_not_eligible(db):
    from app.models import InformationEvidence

    item = evidence(published=None)
    ingest(db, item)
    assert db.get(InformationEvidence, item.evidence_id).published_at is None
    assert (
        InformationRepository().eligible(
            db, market_family="equity", asset_key="AAPL", as_of=NOW
        )
        == ()
    )


def test_information_duplicate_and_changed_content_preserve_immutable_revision(db):
    from app.models import InformationEvidence, InformationLink

    first = evidence()
    ingest(db, first)
    ingest(db, first)
    revised = evidence(
        payload={"title": "Release", "value": 4.0},
        observed=NOW + timedelta(minutes=5),
        available=NOW + timedelta(minutes=5),
    )
    ingest(db, revised, observed=revised.observed_at)
    rows = db.scalars(select(InformationEvidence)).all()
    assert len(rows) == 2
    assert (
        db.get(InformationEvidence, revised.evidence_id).revision_of
        == first.evidence_id
    )
    assert db.get(InformationEvidence, first.evidence_id).payload["value"] == 3.0
    assert len(db.scalars(select(InformationLink)).all()) == 2
    before = InformationRepository().eligible(
        db, market_family="equity", asset_key="AAPL", as_of=NOW
    )
    after = InformationRepository().eligible(
        db, market_family="equity", asset_key="AAPL", as_of=revised.observed_at
    )
    assert [x.evidence_id for x in before] == [first.evidence_id]
    assert [x.evidence_id for x in after] == [revised.evidence_id]


def test_information_late_acquisition_and_current_macro_cannot_leak_into_history(db):
    item = evidence(
        published=NOW - timedelta(days=10),
        observed=NOW,
        available=NOW - timedelta(days=10),
    )
    ingest(db, item)
    repo = InformationRepository()
    assert (
        repo.eligible(
            db, market_family="equity", asset_key="AAPL", as_of=NOW - timedelta(days=1)
        )
        == ()
    )
    assert (
        repo.eligible(
            db, market_family="equity", asset_key="AAPL", as_of=NOW, historical=True
        )
        == ()
    )
    assert (
        len(repo.eligible(db, market_family="equity", asset_key="AAPL", as_of=NOW)) == 1
    )


def test_information_clock_normalization_and_deep_immutability(db):
    payload = {"title": "Release", "nested": {"values": [1, 2]}}
    item = evidence(payload=payload, observed=NOW.replace(tzinfo=timezone.utc))
    payload["nested"]["values"].append(99)
    assert item.payload["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        item.payload["title"] = "mutated"
    assert item.observed_at == NOW
    with pytest.raises(ValueError):
        replace(item, content_hash="0" * 64)
    ingest(db, item)
    (loaded,) = InformationRepository().eligible(
        db, market_family="equity", asset_key="AAPL", as_of=NOW
    )
    assert loaded == item


def test_information_failure_keeps_cursor_success_and_explicit_provider_state(db):
    from app.models import InformationProviderState

    ingest(db, evidence())
    repo = InformationRepository()
    repo.ingest(
        db,
        ProviderResult(
            "official",
            "QUOTA_LIMITED",
            (),
            observed_at=NOW + timedelta(minutes=1),
            retry_at=NOW + timedelta(minutes=5),
            error_code="HTTP_429",
        ),
    )
    state = db.get(InformationProviderState, "official")
    assert state.cursor == "page2" and state.last_success_at == NOW
    assert state.status == "QUOTA_LIMITED" and state.retries == 1
    repo.ingest(
        db,
        ProviderResult(
            "official",
            "EMPTY",
            (),
            observed_at=NOW - timedelta(minutes=1),
            cursor="old",
        ),
    )
    assert state.status == "QUOTA_LIMITED" and state.cursor == "page2"


def test_information_historical_proof_and_currency_links_are_explicit(db):
    item = evidence(verified=True)
    ingest(
        db,
        item,
        links=[EvidenceLink(item.evidence_id, "EUR", "currency", 0.95, "ECB", "v1")],
    )
    repo = InformationRepository()
    assert (
        len(
            repo.eligible(
                db,
                market_family="forex",
                asset_key="EURUSD=X",
                as_of=NOW,
                historical=True,
            )
        )
        == 1
    )
    assert (
        repo.eligible(db, market_family="forex", asset_key="GBPJPY=X", as_of=NOW) == ()
    )
    with pytest.raises(ValueError):
        EvidenceLink(item.evidence_id, "EUR", "issuer", 2.0, "bad", "v1")


def test_information_concurrent_same_content_has_one_identity(tmp_path):
    from app.models import InformationEvidence, InformationLink

    engine = create_engine(
        f"sqlite:///{tmp_path/'concurrent.db'}", connect_args={"timeout": 10}
    )
    Base.metadata.create_all(engine)
    item = evidence()

    def write(_):
        with Session(engine) as session:
            ingest(session, item)
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, range(2)))
    with Session(engine) as session:
        assert len(session.scalars(select(InformationEvidence)).all()) == 1
        assert len(session.scalars(select(InformationLink)).all()) == 1


def test_information_rejects_mixed_provider_and_unbounded_queries(db):
    with pytest.raises(ValueError):
        InformationRepository().ingest(
            db, ProviderResult("other", "AVAILABLE", (evidence(),), observed_at=NOW)
        )
    with pytest.raises(ValueError):
        InformationRepository().eligible(
            db, market_family="crypto", asset_key="BTC", as_of=NOW
        )


def test_information_verified_historical_reconstruction_is_not_live_first_observed(db):
    past = NOW - timedelta(days=10)
    item = evidence(published=past, observed=NOW, available=past, verified=True)
    ingest(db, item)
    repo = InformationRepository()
    assert repo.eligible(db, market_family="equity", asset_key="AAPL", as_of=past) == ()
    (historical,) = repo.eligible(
        db, market_family="equity", asset_key="AAPL", as_of=past, historical=True
    )
    assert historical.evidence_id == item.evidence_id
    assert historical.observed_at == NOW  # Acquisition clock must never be backdated.


def test_information_future_publication_or_availability_stays_ineligible(db):
    item = evidence(published=NOW + timedelta(minutes=1))
    ingest(db, item)
    assert (
        InformationRepository().eligible(
            db, market_family="equity", asset_key="AAPL", as_of=NOW
        )
        == ()
    )


def test_information_loading_an_older_vintage_later_does_not_replace_newer_public_revision(
    db,
):
    latest = evidence(verified=True)
    ingest(db, latest)
    past = NOW - timedelta(days=10)
    archived = evidence(
        payload={"title": "Release", "value": 2.0},
        published=past,
        observed=NOW + timedelta(minutes=1),
        available=past,
        verified=True,
    )
    ingest(db, archived, observed=archived.observed_at)
    (selected,) = InformationRepository().eligible(
        db,
        market_family="equity",
        asset_key="AAPL",
        as_of=archived.observed_at,
        historical=True,
    )
    assert selected.evidence_id == latest.evidence_id
