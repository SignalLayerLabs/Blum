from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256

import polars as pl
import pytest

from app.services.trading_ml import daily_research


def bars(count=65):
    result = []
    for index in range(count):
        day = datetime(2023, 9, 1) + timedelta(days=index)
        opening = 100 + index * 0.1
        close = opening + (0.8 if index % 3 else -0.6)
        result.append(
            dict(
                symbol="ABC",
                datetime=day,
                open=opening,
                high=opening + 1,
                low=opening - 1,
                close=close,
                close_adj=close,
                volume=10000 + index,
                timeframe="1day",
                ret_1=9999,
                spy_logret_1=9999,
            )
        )
    return result


def test_daily_research_features_use_only_completed_prior_bars():
    source = bars()
    original = daily_research.examples_from_daily_bars(
        source, source_id="fixture", split="train"
    )
    modified = [dict(row) for row in source]
    modified[-1].update(open=200, high=220, low=190, close=210, close_adj=210)
    changed = daily_research.examples_from_daily_bars(
        modified, source_id="fixture", split="train"
    )
    assert original
    cutoff = source[-4]["datetime"]
    before = {r.source_object_id: r for r in original if r.decision_timestamp < cutoff}
    after = {r.source_object_id: r for r in changed if r.source_object_id in before}
    assert before == after
    sample = original[0]
    assert sample.features["recent_return"] != 9999
    assert sample.decision_timestamp.hour in (
        22,
        23,
    )  # 18:00 New York, UTC-naive store contract
    assert sample.outcome_timestamp > sample.decision_timestamp
    assert sample.evidence_lane == "external_daily_bar_research"
    assert sample.sample_weight == 0.15


def test_next_session_entry_price_cannot_change_previous_decision_features():
    source = bars()
    before = daily_research.examples_from_daily_bars(
        source, source_id="fixture", split="train"
    )
    changed = [dict(row) for row in source]
    changed[31]["open"] += 0.5
    after = daily_research.examples_from_daily_bars(
        changed, source_id="fixture", split="train"
    )
    decision = source[30]["datetime"].date()
    original = next(row for row in before if row.decision_timestamp.date() == decision)
    revised = next(row for row in after if row.decision_timestamp.date() == decision)
    assert original.features == revised.features
    assert original.realized_net_r != revised.realized_net_r


def test_future_large_moves_cannot_remove_a_decision_known_eligible_sample():
    source = bars()
    before = daily_research.examples_from_daily_bars(
        source, source_id="fixture", split="train"
    )
    changed = [dict(row) for row in source]
    for name in ("open", "high", "low", "close", "close_adj"):
        changed[31][name] *= 1.3
    after = daily_research.examples_from_daily_bars(
        changed, source_id="fixture", split="train"
    )
    decision = source[30]["datetime"].date()
    original = next(row for row in before if row.decision_timestamp.date() == decision)
    revised = next(
        row for row in after if row.source_object_id == original.source_object_id
    )
    assert original.features == revised.features


def test_split_assignment_follows_outcome_and_never_trains_on_validation_labels():
    source = bars(155)
    training = daily_research.examples_from_daily_bars(
        source, source_id="fixture", split="train"
    )
    validation = daily_research.examples_from_daily_bars(
        source, source_id="fixture", split="validation"
    )
    assert training and validation
    assert max(row.outcome_timestamp for row in training) < datetime(2024, 1, 1)
    assert min(row.outcome_timestamp for row in validation) >= datetime(2024, 1, 1)
    assert not {r.source_object_id for r in training} & {
        r.source_object_id for r in validation
    }
    assert training == daily_research.examples_from_daily_bars(
        list(reversed(source)), source_id="fixture", split="train"
    )


def test_duplicates_invalid_bars_and_unversioned_sources_fail_explicitly(tmp_path):
    source = bars()
    with pytest.raises(ValueError, match="DUPLICATE"):
        daily_research.examples_from_daily_bars(
            source + source[:1], source_id="fixture", split="train"
        )
    source[10]["high"] = 0.1
    with pytest.raises(ValueError, match="OHLC"):
        daily_research.examples_from_daily_bars(
            source, source_id="fixture", split="train"
        )
    path = tmp_path / "bars.parquet"
    pl.DataFrame(bars()).write_parquet(path)
    with pytest.raises(ValueError, match="SHA256"):
        daily_research.load_pinned_daily_bars(path, expected_sha256="0" * 64)


def test_adjustment_events_and_large_discontinuities_are_excluded():
    source = bars()
    regular = daily_research.examples_from_daily_bars(
        source, source_id="fixture", split="train"
    )
    changed = [dict(row) for row in source]
    for row in changed[40:]:
        row["close_adj"] *= 0.5
    adjusted = daily_research.examples_from_daily_bars(
        changed, source_id="fixture", split="train"
    )
    assert len(adjusted) < len(regular)
    # Once the event is observed the feature window is excluded; the prior
    # decision remains eligible regardless of a future adjustment event.
    event = source[40]["datetime"]
    assert not any(r.decision_timestamp.date() == event.date() for r in adjusted)
    prior_ids = {
        r.source_object_id
        for r in regular
        if r.outcome_timestamp.date() == event.date()
    }
    assert prior_ids.issubset({r.source_object_id for r in adjusted})


def test_research_labels_charge_declared_round_trip_cost_and_keep_the_final_test_separate():
    zero = daily_research.examples_from_daily_bars(
        bars(), source_id="fixture", split="train", cost_bps=0
    )
    costly = daily_research.examples_from_daily_bars(
        bars(), source_id="fixture", split="train", cost_bps=20
    )
    assert len(zero) == len(costly)
    assert all(a.realized_net_r > b.realized_net_r for a, b in zip(zero, costly))
    assert not daily_research.examples_from_daily_bars(
        bars(), source_id="fixture", split="test"
    )
    with pytest.raises(ValueError, match="cost"):
        daily_research.examples_from_daily_bars(
            bars(), source_id="fixture", split="train", cost_bps=-1
        )
