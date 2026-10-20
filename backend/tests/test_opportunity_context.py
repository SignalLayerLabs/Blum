from dataclasses import replace
from datetime import timedelta

import pytest

from app.models import Asset
from app.services.information.contracts import (
    EvidenceLink,
    ProviderResult,
    SourceEvidence,
)
from app.services.information.context import OpportunityContextBuilder
from app.services.information.repository import InformationRepository
from test_information_repository import db, NOW


def asset(db, ticker="AAPL", *, name="Apple Inc.", kind="stock", sector="Technology"):
    row = Asset(
        ticker=ticker,
        name=name,
        category="equities",
        sector=sector,
        asset_type=kind,
        country="USA",
        currency="USD",
    )
    db.add(row)
    db.flush()
    return row


def event(
    db,
    *,
    provider="official",
    url="https://example.org/1",
    key="AAPL",
    kind="issuer",
    title="Apple announces earnings",
    payload=None,
    published=None,
    observed=None,
    available=None,
    verified=False,
    reason="exact issuer",
    confidence=1.0,
):
    item = SourceEvidence.create(
        provider=provider,
        canonical_url=url,
        language="en",
        payload={"title": title, "source_capability": "news", **(payload or {})},
        published_at=published or NOW - timedelta(hours=1),
        observed_at=observed or NOW - timedelta(minutes=30),
        available_at=available or observed or NOW - timedelta(minutes=30),
        historical_availability_verified=verified,
    )
    InformationRepository().ingest(
        db,
        ProviderResult(
            provider,
            "AVAILABLE",
            (item,),
            observed_at=item.observed_at,
            links=(
                EvidenceLink(item.evidence_id, key, kind, confidence, reason, "v1"),
            ),
        ),
    )
    return item


def build(db, key="AAPL", *, market="equity", at=NOW, historical=False):
    return OpportunityContextBuilder().build(
        db,
        market_family=market,
        asset_key=key,
        decision_at=at,
        historical=historical,
        price_refs=(
            {
                "source_uid": "fixture:1",
                "timestamp": (at - timedelta(minutes=2)).isoformat(),
                "available_at": (at - timedelta(minutes=1)).isoformat(),
                "acquired_at": (at - timedelta(minutes=1)).isoformat(),
                "provider": "fixture",
                "close": 100.0,
                "timeframe": "1m",
            },
        ),
    )


def test_context_deduplicates_syndication_without_counting_publishers_as_novelty(db):
    asset(db)
    event(db, payload={"sentiment_score": 0.5, "sentiment_model": "fixture-nlp"})
    single = build(db)
    for i in (2, 3):
        event(
            db,
            provider=f"publisher{i}",
            url=f"https://example.org/{i}",
            payload={"sentiment_score": 0.5, "sentiment_model": "fixture-nlp"},
        )
    syndicated = build(db)
    assert syndicated.features["event_novelty"] == single.features["event_novelty"]
    assert (
        syndicated.features["issuer_sentiment"]
        == single.features["issuer_sentiment"]
        == 0.5
    )
    assert (
        len(syndicated.evidence_ids) == 3
        and len(syndicated.coverage["event_families"]) == 1
    )


def test_context_exact_issuer_is_not_a_substring_or_sector_heuristic(db):
    asset(db, "CAT", name="Caterpillar Inc.", sector="Industrials")
    event(
        db,
        key="CAT",
        title="Education outlook improves",
        payload={"sentiment_score": 1.0, "sentiment_model": "fixture"},
        reason="legacy heuristic asset linkage",
    )
    assert build(db, "CAT").features["issuer_sentiment"] is None
    event(
        db,
        url="https://example.org/exact",
        key="CAT",
        title="Caterpillar reports earnings",
        payload={"sentiment_score": -0.5, "sentiment_model": "fixture"},
        reason="legacy heuristic asset linkage",
    )
    assert build(db, "CAT").features["issuer_sentiment"] == -0.5


def test_context_etf_exposure_is_not_relabelled_as_issuer_news(db):
    asset(db, "SPY", name="SPDR S&P 500 ETF", kind="etf", sector="Broad Market")
    event(
        db,
        key="SPY",
        kind="etf_exposure",
        title="Apple earnings",
        payload={"sentiment_score": 0.8, "sentiment_model": "fixture"},
        reason="verified dated constituent exposure",
    )
    context = build(db, "SPY")
    assert context.features["issuer_sentiment"] is None
    assert context.features["etf_exposure_sentiment"] == 0.8
    assert context.links[0].kind == "etf_exposure"


def test_context_fx_aligns_both_currency_policy_changes_in_basis_points_only(db):
    event(
        db,
        provider="ecb",
        key="EUR",
        kind="currency",
        payload={
            "policy_delta": {"currency": "EUR", "value": 25.0, "unit": "basis_points"}
        },
    )
    event(
        db,
        provider="fed",
        key="USD",
        kind="currency",
        payload={
            "policy_delta": {
                "currency": "USD",
                "value": 0.5,
                "unit": "percentage_points",
            },
            "employment_count": 200000,
        },
    )
    context = build(db, "EURUSD=X", market="forex")
    assert context.features["base_currency_policy_delta_bps"] == 25
    assert context.features["quote_currency_policy_delta_bps"] == 50
    assert context.features["policy_differential_change_bps"] == -25
    assert "employment_count" not in context.features
    assert (
        context.features["consensus_surprise_z"] is None
        and context.calendar_state == "UNKNOWN"
    )


def test_context_late_acquisition_and_future_revision_do_not_change_a_frozen_snapshot(
    db,
):
    asset(db)
    first = event(db)
    frozen = build(db)
    event(
        db,
        url="https://example.org/late",
        observed=NOW + timedelta(seconds=1),
        payload={"sentiment_score": 1.0, "sentiment_model": "fixture"},
    )
    event(db, title="Corrected Apple earnings", observed=NOW + timedelta(minutes=1))
    rebuilt = build(db)
    assert rebuilt.hash == frozen.hash and rebuilt.evidence_ids == (first.evidence_id,)
    assert rebuilt.max_available_at <= NOW


def test_context_current_revised_macro_is_not_a_historical_feature(db):
    event(
        db,
        key="USD",
        kind="currency",
        payload={
            "source_capability": "current_state",
            "series_id": "DGS10",
            "value": 4.2,
            "unit": "percent",
            "period": "2026-10-19",
        },
    )
    live = build(db, "EURUSD=X", market="forex")
    historical = build(db, "EURUSD=X", market="forex", historical=True)
    assert live.features["macro_DGS10_percent"] == 4.2
    assert historical.features["macro_DGS10_percent"] is None


def test_context_unknown_calendar_is_not_clear_and_schedule_coverage_is_required(db):
    asset(db)
    unknown = build(db)
    assert (
        unknown.calendar_state == "UNKNOWN" and unknown.features["calendar_known"] == 0
    )
    event(
        db,
        key="USD",
        kind="currency",
        payload={
            "source_capability": "calendar_schedule",
            "calendar_coverage": {
                "start": (NOW - timedelta(days=1)).isoformat(),
                "end": (NOW + timedelta(days=1)).isoformat(),
                "complete": True,
                "events": [
                    {
                        "scheduled_at": (NOW + timedelta(minutes=20)).isoformat(),
                        "impact": "HIGH",
                    }
                ],
            },
        },
    )
    context = build(db)
    assert (
        context.calendar_state == "KNOWN_EVENT_WINDOW"
        and context.features["event_window"] == 1
    )


def test_context_prices_and_payload_are_immutable_and_as_of_checked(db):
    asset(db)
    ctx = build(db)
    with pytest.raises(TypeError):
        ctx.features["event_novelty"] = 99
    assert build(db).hash == ctx.hash
    ref = {
        "source_uid": "future",
        "timestamp": NOW.isoformat(),
        "available_at": (NOW + timedelta(seconds=1)).isoformat(),
        "provider": "fixture",
        "close": 100,
    }
    with pytest.raises(ValueError):
        OpportunityContextBuilder().build(
            db,
            market_family="equity",
            asset_key="AAPL",
            decision_at=NOW,
            price_refs=(ref,),
        )


def test_native_forex_macro_agent_uses_unit_aware_information_and_preserves_unknown_calendar(
    db,
):
    from app.services.forex_agents import BlumForexMacroAgent
    from app.services.forex_contracts import ForexDirection
    from test_forex_trader_core import market_input

    event(
        db,
        provider="ecb",
        key="EUR",
        kind="currency",
        payload={
            "policy_delta": {"currency": "EUR", "value": 25, "unit": "basis_points"}
        },
    )
    event(
        db,
        provider="fed",
        key="USD",
        kind="currency",
        payload={
            "policy_delta": {"currency": "USD", "value": 50, "unit": "basis_points"}
        },
    )
    ctx = build(db, "EURUSD=X", market="forex")
    market = replace(
        market_input(),
        as_of=NOW,
        information_context=ctx,
        macro_payload={"employment_surprise": 1000000},
    )
    result = BlumForexMacroAgent().analyze(market)
    assert (
        result.macro_bias == ForexDirection.SHORT
        and result.news_window_status == "UNKNOWN"
    )


def test_context_rejects_forged_hash_on_a_changed_feature_snapshot(db):
    asset(db)
    ctx = build(db)
    with pytest.raises(ValueError):
        replace(ctx, features={**ctx.features, "event_novelty": 999})


def test_context_old_policy_change_is_not_reported_as_current_information(db):
    past = NOW - timedelta(days=30)
    event(
        db,
        provider="fed",
        key="USD",
        kind="currency",
        published=past,
        observed=past,
        payload={
            "policy_delta": {"currency": "USD", "value": 50, "unit": "basis_points"}
        },
    )
    ctx = build(db, "EURUSD=X", market="forex")
    assert ctx.features["quote_currency_policy_delta_bps"] is None
    assert "quote_currency_context" in ctx.coverage["missing_capabilities"]


def test_native_forex_repository_joins_actual_information_instead_of_empty_bar_metadata(
    db,
):
    from app.models import ReplayMarketBar
    from app.services.forex_trader import ForexMarketInputRepository

    row = asset(
        db, "EURUSD=X", name="Euro / US Dollar", kind="Forex", sector="Currencies"
    )
    for tf, minutes in (("1h", 60), ("15m", 15), ("5m", 5), ("1m", 1)):
        for i in range(40):
            db.add(
                ReplayMarketBar(
                    asset_id=row.id,
                    source_symbol=row.ticker,
                    normalized_symbol=row.ticker,
                    market="FOREX",
                    timeframe=tf,
                    bar_timestamp=NOW - timedelta(minutes=(40 - i) * minutes + 2),
                    open=1.1,
                    high=1.101,
                    low=1.099,
                    close=1.1,
                    volume=0,
                    provider="fixture",
                    acquired_at=NOW - timedelta(minutes=1),
                    data_quality_score=0.95,
                    source_metadata={},
                )
            )
    event(
        db,
        provider="fed",
        key="USD",
        kind="currency",
        payload={
            "policy_delta": {"currency": "USD", "value": 25, "unit": "basis_points"}
        },
    )
    db.flush()
    markets, _ = ForexMarketInputRepository().load(db, now=NOW)
    assert (
        markets[0].information_context.features["quote_currency_policy_delta_bps"] == 25
    )
    assert markets[0].information_context.asset_key == "EURUSD=X"


def test_native_equity_gateway_attaches_a_source_attributed_context():
    from app.services.intraday_market_data import StrictIntradayDataGateway
    from test_live_intraday_paper_engine import (
        setup_db,
        seed_asset,
        seed_complete_stack,
        NOW as MARKET_NOW,
    )

    with setup_db() as db:
        row = seed_asset(db)
        seed_complete_stack(db, row)
        item = event(
            db,
            key="NVDA",
            title="NVDA announces earnings",
            published=MARKET_NOW - timedelta(hours=1),
            observed=MARKET_NOW - timedelta(minutes=1),
            payload={"sentiment_score": 0.6, "sentiment_model": "fixture"},
        )
        bundle = StrictIntradayDataGateway(refresh_missing=False).load(
            db, asset=row, now=MARKET_NOW
        )
        assert bundle.ready
        assert bundle.information_context.evidence_ids == (item.evidence_id,)
        assert bundle.information_context.features["issuer_sentiment"] == 0.6


def test_context_reuses_existing_nlp_only_after_the_analysis_was_available(db):
    from app.models import NewsArticle, NewsAssetLink, SentimentAnalysis
    from app.services.information.providers import ExistingNewsProvider

    row = asset(db)
    article = NewsArticle(
        source="fixture",
        source_url="https://example.org/feed",
        url="https://example.org/earnings",
        title="Apple cuts earnings guidance",
        summary="Apple warns",
        canonical_key="fixture",
        created_at=NOW - timedelta(minutes=1),
        published_at=NOW - timedelta(hours=1),
    )
    db.add(article)
    db.flush()
    db.add(NewsAssetLink(article_id=article.id, asset_id=row.id, relevance_score=1))
    db.add(
        SentimentAnalysis(
            article_id=article.id,
            model_name="fixture-finbert",
            label="negative",
            score=-0.7,
            confidence=0.7,
            created_at=NOW + timedelta(seconds=1),
        )
    )
    db.flush()
    adapter = ExistingNewsProvider(db)
    early = adapter.fetch(cursor={}, as_of=NOW, deadline=0)
    assert early.evidence[0].payload.get("sentiment_score") is None
    later = adapter.fetch(cursor={}, as_of=NOW + timedelta(minutes=1), deadline=0)
    assert later.evidence[0].payload["sentiment_score"] == -0.7
    InformationRepository().ingest(db, later)
    assert build(db, at=NOW + timedelta(minutes=1)).features["issuer_sentiment"] == -0.7
