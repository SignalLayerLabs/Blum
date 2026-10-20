"""Economic regressions for report-only frozen curriculum valuation."""

from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest

from app.services import curriculum_valuation as valuation


def bars(closes=(100, 100, 80, 110), volume=100_000):
    opening = datetime(2026, 7, 20, 9)
    result = []
    for index, close in enumerate(closes):
        start = opening + timedelta(minutes=5 * index)
        result.append(
            dict(
                start=start.isoformat(),
                available=(start + timedelta(minutes=6)).isoformat(),
                open=100.0,
                high=max(100.0, close),
                low=min(100.0, close),
                close=float(close),
                volume=float(volume),
            )
        )
    return result


def trade(**updates):
    # Ten units at 100, entry commission .10; exit at 110 with .11 commission.
    result = dict(
        status="CLOSED",
        decision_at="2026-07-20T09:06:00",
        entry_at="2026-07-20T09:10:00",
        entry_price=100.0,
        quantity=10.0,
        entry_notional=1000.0,
        entry_commission=0.1,
        cash_before=10000.0,
        cash_after_entry=8999.9,
        exit_at="2026-07-20T09:21:00",
        exit_price=110.0,
        exit_commission=0.11,
        pnl=99.79,
    )
    result.update(updates)
    return result


def report(data=None, trades=None, as_of="2026-07-20T09:21:00"):
    data = data if data is not None else bars()
    return valuation.value_frozen_trades(
        data,
        trades if trades is not None else [trade()],
        market="FOREX",
        timeframe="5m",
        start=0,
        end=len(data),
        as_of=datetime.fromisoformat(as_of),
    )


def test_open_loss_is_visible_before_frozen_winning_exit():
    # Catches closed-trade-only equity and booking the eventual winner too early.
    result = report(as_of="2026-07-20T09:16:00")
    assert result["status"] == "COMPLETE"
    assert result["nav_quote_units"] == pytest.approx(9799.9)
    assert result["net_return"] == pytest.approx(-0.02001)
    assert result["max_bar_close_drawdown"] == pytest.approx(0.02001)
    assert result["curve"][-1]["position_quantity"] == 10


def test_entry_commission_is_deducted_once_until_actual_exit_clock():
    result = report(bars((100, 100, 100, 110)), as_of="2026-07-20T09:16:00")
    assert result["nav_quote_units"] == pytest.approx(9999.9)
    closed = report()
    assert closed["nav_quote_units"] == pytest.approx(10099.79)
    assert closed["curve"][-1]["position_quantity"] == 0
    assert closed["max_bar_close_drawdown"] == pytest.approx(0.02001)


def test_restart_replay_does_not_mutate_or_change_valuation():
    data, trades = bars(), [trade()]
    before = deepcopy((data, trades))
    first = report(data, trades)
    assert (data, trades) == before
    assert report(json.loads(json.dumps(data)), json.loads(json.dumps(trades))) == first


def test_future_prices_and_future_exit_economics_do_not_change_prefix():
    data, trades = bars(), [trade()]
    expected = report(data, trades, as_of="2026-07-20T09:16:00")
    data[-1].update(close=999.0, high=999.0, volume=1.0)
    trades[0].update(exit_price=999.0, exit_commission=9.99, pnl=8989.91)
    assert report(data, trades, as_of="2026-07-20T09:16:00") == expected


@pytest.mark.parametrize(
    "problem", ["missing", "invalid", "overlap", "missing_fill", "inconsistent_cash"]
)
def test_incomplete_or_inconsistent_paths_withhold_current_equity(problem):
    data, trades = bars(), [trade()]
    if problem == "missing":
        data.pop(2)
    elif problem == "invalid":
        data[2]["close"] = float("nan")
    elif problem == "overlap":
        trades.append(trade())
    elif problem == "missing_fill":
        del trades[0]["quantity"]
    else:
        trades[0]["cash_after_entry"] = 10000
    result = report(data, trades)
    assert result["status"] == "WITHHELD"
    assert result["nav_quote_units"] is None
    assert result["net_return"] is None
    assert result["max_bar_close_drawdown"] is None


def test_cash_stays_flat_without_any_trades():
    result = report(trades=[])
    assert result["nav_quote_units"] == 10000
    assert result["net_liquidation_estimate_quote_units"] == 10000
    assert result["max_bar_close_drawdown"] == 0
    assert result["sample_exposure_fraction"] == 0
    assert result["average_gross_exposure_fraction"] == 0


def test_unknown_exit_capacity_preserves_mark_nav():
    data = bars(volume=10)
    result = report(data, as_of="2026-07-20T09:16:00")
    assert result["status"] == "COMPLETE"
    assert result["nav_quote_units"] == pytest.approx(9799.9)
    assert result["net_liquidation_status"] == "WITHHELD"
    assert result["net_liquidation_estimate_quote_units"] is None
    assert result["net_liquidation_return"] is None
    assert result["max_bar_close_net_liquidation_drawdown"] is None


def test_cost_adjusted_liquidation_is_distinct_from_mark_nav():
    result = report(as_of="2026-07-20T09:16:00")
    assert result["net_liquidation_status"] == "ESTIMATE"
    assert result["net_liquidation_estimate_quote_units"] < result["nav_quote_units"]
    assert result["net_liquidation_return"] < result["net_return"]


def test_full_resolution_drawdown_survives_curve_compaction():
    data = bars([100.0] * 200)
    data[101].update(close=50.0, low=50.0)
    pending = trade(status="OPEN")
    for field in ("exit_at", "exit_price", "exit_commission", "pnl"):
        pending.pop(field)
    result = report(data, [pending], as_of=data[-1]["available"])
    assert result["sample_count"] == 200
    assert len(result["curve"]) <= 128
    assert result["max_bar_close_drawdown"] == pytest.approx(0.05001)
    assert result["sample_exposure_fraction"] == pytest.approx(199 / 200)
    assert len(result["curve_hash"]) == 64


def test_modeled_hold_partial_entry_keeps_remaining_cash_and_never_claims_exit():
    data = bars((100, 100, 100, 110), volume=20)
    for bar in data:
        for key in ("start", "available"):
            bar[key] = (
                datetime.fromisoformat(bar[key]) + timedelta(hours=4, minutes=30)
            ).isoformat()
    result = valuation.modeled_hold(
        data,
        market="USA",
        timeframe="5m",
        start=0,
        end=4,
        as_of=datetime.fromisoformat(data[-1]["available"]),
    )
    assert result["status"] == "COMPLETE"
    assert result["entry_status"] == "PARTIALLY_FILLED"
    assert result["position_status"] == "OPEN_MARKED"
    assert result["curve"][-1]["position_quantity"] == 1.0
    assert 9899 < result["curve"][-1]["cash_quote_units"] < 9900
    assert 10009 < result["nav_quote_units"] < 10010


def test_modeled_hold_zero_reported_volume_is_unfilled_cash_not_full_investment():
    data = bars((100, 100, 100, 110), volume=0)
    for bar in data:
        for key in ("start", "available"):
            bar[key] = (
                datetime.fromisoformat(bar[key]) + timedelta(hours=4, minutes=30)
            ).isoformat()
    result = valuation.modeled_hold(
        data,
        market="USA",
        timeframe="5m",
        start=0,
        end=4,
        as_of=datetime.fromisoformat(data[-1]["available"]),
    )
    assert result["entry_status"] == "UNFILLED"
    assert result["nav_quote_units"] == 10000
    assert result["net_liquidation_estimate_quote_units"] == 10000
    assert result["sample_exposure_fraction"] == 0


def test_forex_hold_declares_otc_capacity_instead_of_using_zero_observed_volume():
    data = bars((100, 100, 100, 110), volume=0)
    # Forex intentionally uses the declared OTC scenario even when volume is zero.
    result = valuation.modeled_hold(
        data,
        market="FOREX",
        timeframe="5m",
        start=0,
        end=4,
        as_of=datetime.fromisoformat(data[-1]["available"]),
    )
    assert result["entry_status"] in {"PARTIALLY_FILLED", "FILLED"}
    assert result["position_status"] == "OPEN_MARKED"
    assert result["net_liquidation_estimate_quote_units"] < result["nav_quote_units"]


def test_hold_does_not_call_unobserved_open_exposure_free_cash():
    # The scheduled entry opened at 09:10, but its bar is unavailable until 09:16.
    result = valuation.modeled_hold(
        bars(),
        market="FOREX",
        timeframe="5m",
        start=0,
        end=4,
        as_of=datetime(2026, 7, 20, 9, 11),
    )
    assert result["status"] == "WITHHELD"
    assert result["nav_quote_units"] is None
    assert result["net_return"] is None


def test_frozen_trade_open_after_last_mark_withholds_current_equity():
    result = report(as_of="2026-07-20T09:10:00")
    assert result["status"] == "WITHHELD"
    assert result["nav_quote_units"] is None


def test_source_clock_cannot_publish_a_bar_earlier_than_its_known_available_time():
    data = bars()
    data[2]["available"] = "2026-07-20T09:12:00"
    result = report(data, as_of="2026-07-20T09:12:00")
    assert result["status"] == "WITHHELD"
    assert result["nav_quote_units"] is None


def test_missing_first_execution_bar_does_not_certify_unexposed_cash():
    # The journal intentionally cannot verify the missed opening; the report
    # must not upgrade that missing execution path to a known cash-only account.
    data = bars()[2:]
    trade = {
        "decision_at": "2026-07-20T09:06:00",
        "status": "UNFILLED",
        "reason": "MISSING_FIRST_EXECUTION_BAR",
        "cash_before": 10000,
    }
    result = valuation.value_frozen_trades(
        data,
        [trade],
        market="FOREX",
        timeframe="5m",
        start=0,
        end=len(data),
        as_of=datetime.fromisoformat(data[-1]["available"]),
    )
    assert result["status"] == "WITHHELD"
    assert result["nav_quote_units"] is None
    assert result["max_bar_close_drawdown"] is None


def test_open_position_with_missing_trailing_closed_bar_is_not_current_nav():
    pending = trade(status="OPEN")
    for key in ("exit_at", "exit_price", "exit_commission", "pnl"):
        pending.pop(key)
    result = report(trades=[pending], as_of="2026-07-20T09:26:00")
    assert result["status"] == "WITHHELD"
    assert result["nav_quote_units"] is None
    assert result["max_bar_close_drawdown"] is None


def test_closed_cash_does_not_require_future_price_marks():
    result = report(as_of="2026-07-20T09:26:00")
    assert result["status"] == "COMPLETE"
    assert result["nav_quote_units"] == pytest.approx(10099.79)
