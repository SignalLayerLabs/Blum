"""Information must change actual native policy outputs with prices held fixed."""

from dataclasses import replace
from datetime import timedelta

import pytest

from test_forex_trader_core import db, NOW, market_input, strategy
from test_opportunity_context import asset, build, event


def context(db, family, *, informed=False):
    key = "NVDA" if family == "equity" else "EURUSD=X"
    from app.models import Asset
    from sqlalchemy import select

    if (
        family == "equity"
        and db.scalar(select(Asset.id).where(Asset.ticker == key)) is None
    ):
        asset(db, key)
    if informed:
        event(
            db,
            key=key if family == "equity" else "EUR",
            kind="issuer" if family == "equity" else "currency",
            published=NOW - timedelta(minutes=2),
            observed=NOW - timedelta(minutes=1),
            available=NOW - timedelta(minutes=1),
        )
    return build(db, key, market=family, at=NOW)


def equity_candidate():
    from app.services.intraday_contracts import (
        IntradayDecision,
        IntradayPositionSize,
        INTRADAY_TRADE_CANDIDATE,
    )
    from app.services.executable_strategy import canonical_strategy_spec

    spec = canonical_strategy_spec("intraday_breakout")
    return IntradayDecision(
        INTRADAY_TRADE_CANDIDATE,
        "APPROVED",
        "fixture",
        "NVDA",
        "USA",
        "growth",
        "SPY",
        "fixture",
        None,
        "intraday_breakout",
        NOW,
        entry_price=100,
        stop_price=95,
        target_price=110,
        confidence=70,
        edge_score=75,
        sizing=IntradayPositionSize(10, 1000, 50, 0.5, "fixture"),
        evidence={
            "executable_strategy": spec.to_payload(),
            "strategy_fingerprint": spec.fingerprint,
            "paper_risk_multiplier": 1.0,
        },
    )


@pytest.mark.parametrize("family", ["equity", "forex"])
def test_fixed_prices_eligible_event_changes_native_rank_without_fake_probability(
    db, family
):
    from app.services.information.native_policy import NativeInformationPolicy

    before = context(db, family)
    if family == "equity":
        baseline = equity_candidate()
        price_only = NativeInformationPolicy().equity(
            db, decision=baseline, context=None
        )
        empty = NativeInformationPolicy().equity(db, decision=baseline, context=before)
        after = context(db, family, informed=True)
        informed = NativeInformationPolicy().equity(
            db, decision=baseline, context=after
        )
        assert (
            informed.evidence["information_policy"]["rank"]
            > empty.evidence["information_policy"]["rank"]
        )
        assert informed.evidence["information_advice"]["probability_positive_r"] is None
        assert (
            informed.sizing.quantity == 1.25
        )  # 10 × research cap .25 × unknown-calendar .5
        assert price_only.sizing.quantity == 10
        assert (informed.entry_price, informed.stop_price, informed.target_price) == (
            100,
            95,
            110,
        )
    else:
        from app.services.forex_trader import BlumForexTraderCore

        market = market_input()
        baseline = BlumForexTraderCore().evaluate_input(market, strategy=strategy())
        price_only = NativeInformationPolicy().forex(
            db, evaluation=baseline, context=None
        )
        empty = NativeInformationPolicy().forex(db, evaluation=baseline, context=before)
        after = context(db, family, informed=True)
        informed = NativeInformationPolicy().forex(
            db, evaluation=baseline, context=after
        )
        assert (
            informed.proposal.information_policy["rank"]
            > empty.proposal.information_policy["rank"]
        )
        assert informed.proposal.information_advice["probability_positive_r"] is None
        assert informed.proposal.information_policy["risk_multiplier"] == 0.125
        assert price_only is baseline
        assert (
            informed.proposal.entry,
            informed.proposal.stop,
            informed.proposal.target,
        ) == (baseline.proposal.entry, baseline.proposal.stop, baseline.proposal.target)


def test_information_risk_reduction_reaches_native_forex_quantity(db):
    from app.services.information.native_policy import NativeInformationPolicy
    from app.services.forex_trader import BlumForexTraderCore
    from app.services.forex_risk import (
        BlumForexPortfolioRiskEngine,
        ForexPortfolioState,
    )
    from app.services.forex_broker import BlumForexBrokerProfileService

    market = market_input()
    baseline = BlumForexTraderCore().evaluate_input(market, strategy=strategy())
    informed = NativeInformationPolicy().forex(
        db, evaluation=baseline, context=context(db, "forex")
    )
    risk = BlumForexPortfolioRiskEngine()
    state = ForexPortfolioState(equity=100_000)
    kwargs = {
        "state": state,
        "broker": BlumForexBrokerProfileService().get(),
        "quotes": {market.pair: market.quote},
        "now": NOW,
    }
    control = risk.evaluate(baseline.proposal, **kwargs)
    changed = risk.evaluate(informed.proposal, **kwargs)
    assert control.decision.startswith("APPROVE") and changed.decision.startswith(
        "APPROVE"
    )
    assert 0 < changed.quantity_lots < control.quantity_lots * 0.13
    assert changed.risk_amount < control.risk_amount
