"""Independent cash/lot arithmetic: rounding must never enlarge declared risk."""

from dataclasses import replace

import pytest

from app.services.forex_broker import BlumForexBrokerProfileService
from app.services.forex_risk import BlumForexPortfolioRiskEngine, ForexPortfolioState
from test_forex_trader_core import market_input, strategy
from app.services.forex_trader import BlumForexTraderCore


def proposal():
    original = (
        BlumForexTraderCore()
        .evaluate_input(market_input(), strategy=strategy())
        .proposal
    )
    return replace(
        original,
        entry=1.10,
        stop=1.099,
        target=1.103,
        confidence=1,
        expected_gross_pips=10,
        expected_net_pips=10,
    )


def test_lot_rounding_cannot_exceed_the_cash_risk_budget():
    broker = replace(BlumForexBrokerProfileService().get(), account_currency="USD")
    result = BlumForexPortfolioRiskEngine().evaluate(
        proposal(), ForexPortfolioState(equity=3320), broker
    )
    assert result.decision == "APPROVE_FULL_SIZE"
    # 10 pips * USD10 per lot, budget USD16.60: at most 0.16 lots.
    assert result.quantity_lots == pytest.approx(0.16)
    assert result.quantity_lots * 100 <= 16.60
    assert result.risk_amount == pytest.approx(16)
    assert result.risk_percent == pytest.approx(16 / 3320 * 100)


def test_reduced_size_reports_its_actual_margin_exposure_and_risk():
    broker = replace(BlumForexBrokerProfileService().get(), account_currency="USD")
    state = ForexPortfolioState(equity=3320, pair_correlations={"EURUSD=X": 0.9})
    result = BlumForexPortfolioRiskEngine().evaluate(proposal(), state, broker)
    assert result.decision == "APPROVE_REDUCED_SIZE"
    assert result.quantity_lots == pytest.approx(0.04)
    assert result.risk_amount == pytest.approx(4)
    assert result.risk_percent == pytest.approx(4 / 3320 * 100)
    assert result.margin_required == pytest.approx(1.10 * 0.04 * 100_000 / 30)
    assert result.exposure_by_currency == pytest.approx({"EUR": 4400, "USD": -4400})


def test_size_must_satisfy_both_pair_and_broker_lot_steps():
    broker = replace(
        BlumForexBrokerProfileService().get(), account_currency="USD", lot_step=0.025
    )
    result = BlumForexPortfolioRiskEngine().evaluate(
        proposal(), ForexPortfolioState(equity=3320), broker
    )
    # Pair .01 and broker .025 steps intersect at .05. USD16.60 allows .15.
    assert result.quantity_lots == pytest.approx(0.15)
    assert result.risk_amount == pytest.approx(15)


def test_reduction_cannot_submit_a_quantity_below_the_broker_minimum():
    broker = replace(
        BlumForexBrokerProfileService().get(), account_currency="USD", minimum_lot=0.05
    )
    state = ForexPortfolioState(equity=2000, pair_correlations={"EURUSD=X": 0.9})
    result = BlumForexPortfolioRiskEngine().evaluate(proposal(), state, broker)
    assert result.decision == "REJECT_CORRELATION"
    assert result.quantity_lots == 0


def test_missing_account_conversion_cannot_authorize_cross_currency_risk():
    value = replace(proposal(), pair="AUDJPY=X", entry=100, stop=99.9, target=100.3)
    result = BlumForexPortfolioRiskEngine().evaluate(
        value, ForexPortfolioState(equity=10_000), BlumForexBrokerProfileService().get()
    )
    assert result.decision == "REJECT_ACCOUNT_CONVERSION"
    assert result.quantity_lots == 0
