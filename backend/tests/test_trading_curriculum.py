from datetime import datetime, timedelta

import pytest

from app.services import trading_curriculum as curriculum


def bars(count=600, start=datetime(2020, 1, 1), step=0.15):
    from app.services.market_bar_clock import nyse_calendar

    sessions = nyse_calendar().sessions_in_range(
        start.date(), (start + timedelta(days=count * 2 + 30)).date()
    )[:count]
    return [
        dict(
            start=curriculum.session_start(
                sessions[i].to_pydatetime(), "1d", "USA"
            ).isoformat(),
            available=curriculum.available_at(
                sessions[i].to_pydatetime(), "1d", "USA"
            ).isoformat(),
            open=100 + i * step,
            high=101 + i * step,
            low=99.8 + i * step,
            close=100.5 + i * step,
            volume=1_000_000,
        )
        for i in range(count)
    ]


def test_missing_kernel_is_available():
    assert curriculum.VERSION == "curriculum-v1"


def test_daily_equity_close_observes_new_york_dst():
    assert curriculum.available_at(datetime(2025, 7, 7), "1d", "USA") == datetime(
        2025, 7, 7, 20, 1
    )
    assert curriculum.available_at(datetime(2025, 1, 7), "1d", "USA") == datetime(
        2025, 1, 7, 21, 1
    )
    assert curriculum.available_at(datetime(2025, 7, 7, 12), "5m", "FOREX") == datetime(
        2025, 7, 7, 12, 6
    )


def test_random_training_blocks_are_disjoint_and_confirmation_is_reserved():
    plan = curriculum.partition(1000)
    windows = curriculum.training_windows(1000, seed=7)
    assert windows != curriculum.training_windows(1000, seed=8)
    used = set()
    for start, end in windows:
        assert start >= 60 and end <= plan["train_end"]
        assert not used.intersection(range(start, end))
        used.update(range(start, end))
    assert (
        plan["train_end"]
        < plan["development_start"]
        < plan["development_end"]
        < plan["confirmation_start"]
    )


def test_simulation_uses_cash_and_never_future_features():
    source = bars()
    result = curriculum.simulate(
        source,
        market="USA",
        timeframe="1d",
        start=60,
        end=160,
        expert=curriculum.catalogue("1d", "USA")[0],
    )
    assert result["trades"]
    assert result["minimum_cash"] >= 0
    for trade in result["trades"]:
        assert (
            trade["feature_latest"]
            <= trade["decision_at"]
            < trade["entry_at"]
            <= trade["exit_at"]
        )
        assert (
            trade["entry_notional"] + trade["entry_commission"]
            <= trade["cash_before"] + 1e-6
        )
        assert trade["pnl"] == pytest.approx(
            trade["quantity"] * (trade["exit_price"] - trade["entry_price"])
            - trade["entry_commission"]
            - trade["exit_commission"]
        )
    altered = source[:160] + [{**b, "close": 1e9} for b in source[160:]]
    assert (
        curriculum.simulate(
            altered,
            market="USA",
            timeframe="1d",
            start=60,
            end=160,
            expert=curriculum.catalogue("1d", "USA")[0],
        )
        == result
    )


def test_selector_learns_outcomes_and_checkpoint_roundtrips_without_eval_learning():
    specs = curriculum.catalogue("5m", "FOREX")
    model = curriculum.Selector({})
    context = [1, 0.01, 0.02, 0.005, 0.01]
    for _ in range(12):
        model.learn(specs[0].fingerprint, context, -1)
        model.learn(specs[1].fingerprint, context, 2)
    assert model.score(specs[1].fingerprint, context) > model.score(
        specs[0].fingerprint, context
    )
    frozen = model.payload()
    replay = curriculum.Selector(frozen)
    assert replay.payload() == frozen
    curriculum.simulate(
        bars(), market="FOREX", timeframe="5m", start=60, end=160, model=replay
    )
    assert replay.payload() == frozen


def test_frozen_forward_proposal_cannot_be_replaced_by_future_context():
    source = bars()
    proposal = curriculum.propose(
        source[:80],
        market="USA",
        timeframe="1d",
        model=curriculum.Selector({}),
        decision_at=datetime.fromisoformat(source[79]["available"]),
    )
    assert proposal is not None
    assert proposal["input_hash"]
    assert proposal["feature_latest"] <= proposal["decision_at"]
    outcome = curriculum.resolve(proposal, source[80:100], market="USA", complete=True)
    assert outcome is not None
    assert outcome["entry_at"] > proposal["decision_at"]
    assert proposal["input_hash"] == outcome["input_hash"]


def test_invalid_bars_and_zero_reported_volume_are_not_silently_fixed():
    assert not curriculum.valid_bar({**bars(1)[0], "high": 10})
    result = curriculum.simulate(
        [{**b, "volume": 0} for b in bars()],
        market="USA",
        timeframe="1d",
        start=60,
        end=160,
    )
    assert result["trade_count"] == 0
    assert result["win_rate"] is None


def test_pending_forward_position_reports_fill_without_pretending_it_is_closed():
    source = bars()
    proposal = curriculum.propose(
        source[:80],
        market="USA",
        timeframe="1d",
        model=curriculum.Selector({}),
        decision_at=datetime.fromisoformat(source[79]["available"]),
    )
    trade = curriculum.resolve(proposal, source[80:81], market="USA", complete=False)
    assert trade["status"] == "OPEN"
    assert trade["entry_at"] > proposal["decision_at"]
    assert trade["cash_after_entry"] >= 0
    assert "pnl" not in trade


def test_unfavorable_open_cancels_even_when_later_low_would_fill_limit():
    source = bars()
    proposal = curriculum.propose(
        source[:80],
        market="USA",
        timeframe="1d",
        model=curriculum.Selector({}),
        decision_at=datetime.fromisoformat(source[79]["available"]),
    )
    bar = {
        **source[80],
        "open": proposal["limit"] * 1.1,
        "high": proposal["limit"] * 1.2,
        "low": proposal["entry"],
        "close": proposal["limit"] * 1.1,
    }
    assert (
        curriculum.resolve(proposal, [bar], market="USA", complete=True)["status"]
        == "UNFILLED"
    )


def test_entry_costs_are_frozen_before_the_future_bar_range_is_known():
    source = bars()
    proposal = curriculum.propose(
        source[:80],
        market="USA",
        timeframe="1d",
        model=curriculum.Selector({}),
        decision_at=datetime.fromisoformat(source[79]["available"]),
    )
    calm = curriculum.resolve(proposal, source[80:81], market="USA", complete=False)
    changed = [{**source[80], "high": source[80]["high"] * 2}]
    volatile = curriculum.resolve(proposal, changed, market="USA", complete=False)
    assert calm["entry_price"] == volatile["entry_price"]


def test_insufficient_exit_capacity_blocks_account_without_fabricated_profit():
    source = bars()
    source[81] = {**source[81], "low": 1, "volume": 0.0001}
    result = curriculum.simulate(
        source,
        market="USA",
        timeframe="1d",
        start=79,
        end=160,
        expert=curriculum.catalogue("1d", "USA")[0],
    )
    assert result["blocked_count"] == 1
    assert result["net_return"] is None
    assert result["trade_count"] == 0
    assert len(result["trades"]) == 1


def test_live_outcomes_adapt_future_selector_without_changing_historical_checkpoint():
    expert = curriculum.catalogue("1d", "USA")[0].fingerprint
    historical = curriculum.Selector({})
    live = curriculum.Selector({})
    x = [1, 0.1, 0.2, 0.3, 0.4]
    for _ in range(5):
        historical.learn(expert, x, 1)
        live.learn(expert, x, -2)
    frozen = historical.payload()
    combined = curriculum.Selector(curriculum.merge_models(frozen, live.payload()))
    assert combined.score(expert, x) < historical.score(expert, x)
    assert historical.payload() == frozen


def test_learned_expert_choice_changes_behavior_instead_of_only_ranking_identical_trades():
    source = bars()
    model = curriculum.Selector({})
    context = curriculum.features(source[:80])
    reversion = curriculum.catalogue("1d", "USA")[4]
    for _ in range(10):
        model.learn(reversion.fingerprint, context, 2)
    seeded = curriculum.propose(
        source[:80],
        market="USA",
        timeframe="1d",
        model=curriculum.Selector({}),
        decision_at=datetime.fromisoformat(source[79]["available"]),
    )
    learned = curriculum.propose(
        source[:80],
        market="USA",
        timeframe="1d",
        model=model,
        decision_at=datetime.fromisoformat(source[79]["available"]),
    )
    assert seeded is not None
    assert learned is None  # chosen reversion expert correctly waits in a rising market


def test_daily_open_is_an_exchange_session_time_not_midnight():
    assert curriculum.session_start(datetime(2025, 7, 7), "1d", "USA") == datetime(
        2025, 7, 7, 13, 30
    )
    assert curriculum.session_start(datetime(2025, 1, 7), "1d", "USA") == datetime(
        2025, 1, 7, 14, 30
    )


def test_daily_forex_bar_starting_at_23utc_does_not_become_available_one_hour_later():
    start = datetime(2025, 7, 7, 23)
    assert curriculum.available_at(start, "1d", "FOREX") >= start + timedelta(hours=24)


def test_invalid_stop_bar_cannot_disappear_into_a_later_winner():
    source = bars()
    proposal = curriculum.propose(
        source[:80],
        market="USA",
        timeframe="1d",
        model=curriculum.Selector({}),
        decision_at=datetime.fromisoformat(source[79]["available"]),
    )
    broken = {**source[81], "high": 1, "low": proposal["stop"] - 1}
    outcome = curriculum.resolve(
        proposal,
        [source[80], broken, {**source[82], "high": proposal["target"] + 1}],
        market="USA",
        complete=True,
    )
    assert outcome["status"] == "BLOCKED"
    assert "pnl" not in outcome


def test_calendar_detects_missing_session_without_treating_christmas_as_a_gap():
    assert curriculum.consecutive(
        datetime(2025, 12, 24, 14, 30), datetime(2025, 12, 26, 14, 30), "1d", "USA"
    )
    assert not curriculum.consecutive(
        datetime(2025, 12, 23, 14, 30), datetime(2025, 12, 26, 14, 30), "1d", "USA"
    )
    assert curriculum.consecutive(
        datetime(2025, 7, 3, 16, 55), datetime(2025, 7, 7, 13, 30), "5m", "USA"
    )
    assert not curriculum.consecutive(
        datetime(2025, 7, 7, 13, 30), datetime(2025, 7, 7, 13, 40), "5m", "USA"
    )


def test_missing_first_execution_session_does_not_select_a_later_favorable_open():
    source = bars()
    proposal = curriculum.propose(
        source[:80],
        market="USA",
        timeframe="1d",
        model=curriculum.Selector({}),
        decision_at=datetime.fromisoformat(source[79]["available"]),
    )
    outcome = curriculum.resolve(proposal, source[81:100], market="USA", complete=True)
    assert outcome["status"] == "UNFILLED"
    assert outcome["reason"] == "MISSING_FIRST_EXECUTION_BAR"
