from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.services.ascent.evaluation import freeze_split, validate_candidate
from app.services.ascent.kernel import IDENTITY_SOURCE, generate_candidates
from app.services.trading_ml.contracts import TradingMLExample
from app.services.trading_ml.validation import score_frozen_predictions


def evidence(count=600):
    """Deterministic test evidence; never presented as market performance."""
    start = datetime(2020, 1, 1)
    return tuple(TradingMLExample(
        source_object_type="test_fixture", source_object_id=str(i), market_family="equity",
        evidence_lane="REPLAY_EVIDENCE", decision_timestamp=start + timedelta(days=i),
        outcome_timestamp=start + timedelta(days=i + 1), asset_key=("A", "B", "C")[i % 3],
        setup_type="test", regime=("up", "down")[(i // 3) % 2], features={"confidence": 90.0,
        "data_quality_score": 90.0, "expected_cost": 0.01}, realized_net_r=1.0 if i % 2 else -1.0,
        label_positive_r=i % 2, benchmark_excess=0.1 if i % 2 else -0.1, sample_weight=1.0,
    ) for i in range(count))


def test_split_purges_labels_and_keeps_timestamp_ties_together():
    original = evidence()
    tied = replace(original[-151], source_object_id="tied", asset_key="TIED")
    split = freeze_split((*original, tied), as_of=datetime(2026, 1, 1))
    assert max(r.outcome_timestamp for r in split.development) < min(
        r.decision_timestamp for r in split.holdout) - timedelta(days=2)
    assert set(r.decision_timestamp for r in split.development).isdisjoint(
        r.decision_timestamp for r in split.holdout)


@pytest.mark.parametrize("mutation", [
    lambda rows: (*rows, rows[0]),
    lambda rows: (*rows, replace(rows[0], source_object_id="duplicate-economic-decision")),
    lambda rows: (replace(rows[0], evidence_lane="PAPER_FORWARD"), *rows[1:]),
    lambda rows: (replace(rows[0], outcome_timestamp=datetime(2030, 1, 1)), *rows[1:]),
    lambda rows: (replace(rows[0], features={"confidence": float("nan")}), *rows[1:]),
    lambda rows: (replace(rows[0], outcome_timestamp=rows[0].decision_timestamp), *rows[1:]),
    lambda rows: tuple(replace(row, features={"confidence": 80}) for row in rows),
])
def test_contaminated_or_incomplete_evidence_cannot_be_frozen(mutation):
    with pytest.raises(ValueError):
        freeze_split(mutation(evidence()), as_of=datetime(2026, 1, 1))


def test_existing_metrics_score_all_frozen_holdout_rows():
    rows = evidence(10)
    predictions = {f"test_fixture:{i}": 0.5 for i in range(10)}
    metrics = score_frozen_predictions(rows, predictions)
    assert metrics.sample_size == 10
    assert metrics.brier_score == pytest.approx(0.25)
    assert metrics.net_expectancy == pytest.approx(0)
    assert metrics.benchmark_excess == pytest.approx(0)


def test_calibration_gain_does_not_claim_trading_profit_or_production_promotion():
    rows = freeze_split(evidence(), as_of=datetime(2026, 1, 1)).holdout
    result = validate_candidate(rows, source=generate_candidates(prior=0.5)[0],
        champion_source=IDENTITY_SOURCE, prior=0.5, trial_number=0)
    assert result["research_eligible"] is True
    assert result["production_eligible"] is False
    assert result["candidate"]["brier_score"] == pytest.approx(0.25)
    assert result["champion"]["brier_score"] == pytest.approx(0.41)
    assert result["candidate"]["net_expectancy"] == result["champion"]["net_expectancy"]
    assert result["financial_effect"] == "UNCHANGED_DECISIONS"
    assert result["independent_recheck"] is True


def test_identity_is_rejected_even_when_metrics_are_valid():
    rows = freeze_split(evidence(), as_of=datetime(2026, 1, 1)).holdout
    result = validate_candidate(rows, source=IDENTITY_SOURCE, champion_source=IDENTITY_SOURCE,
        prior=0.5, trial_number=0)
    assert not result["research_eligible"]
    assert "NO_CONFIRMED_CALIBRATION_GAIN" in result["blockers"]


def test_one_asset_cannot_establish_generalization():
    rows = tuple(replace(row, asset_key="A") for row in evidence())
    split = freeze_split(rows, as_of=datetime(2026, 1, 1))
    result = validate_candidate(split.holdout, source=generate_candidates(prior=0.5)[0],
        champion_source=IDENTITY_SOURCE, prior=0.5, trial_number=0)
    assert not result["research_eligible"]
    assert "INSUFFICIENT_ASSET_COVERAGE" in result["blockers"]


def test_uncertainty_blocks_cover_the_outcome_horizon():
    rows = tuple(replace(row, outcome_timestamp=row.decision_timestamp + timedelta(days=20)) for row in evidence())
    split = freeze_split(rows, as_of=datetime(2026, 1, 1))
    result = validate_candidate(split.holdout, source=generate_candidates(prior=0.5)[0],
        champion_source=IDENTITY_SOURCE, prior=0.5, trial_number=0)
    assert result["uncertainty"]["block_days"] >= 21
    assert result["uncertainty"]["blocks"] > 0
    assert not result["research_eligible"]  # Too few independent long-horizon blocks.
