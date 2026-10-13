from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.trading_ml.feature_store import TradingMLFeatureStoreProjector
from app.services.trading_ml.forex_history import (
    KAGGLE_FOREX_SOURCE_URL,
    ForexHistoricalDatasetService,
    ForexHistoricalKnowledgeService,
    bundled_forex_history_path,
)


SOURCE_URL = (
    "https://www.kaggle.com/datasets/jeleeladekunlefijabi/"
    "forex-trading-dataset-with-ema-rsi-and-atr"
)


def _write_dataset(path: Path, *, future_multiplier: float = 1.0) -> None:
    rows = [
        "Timestamp,Pair,Rate,High,Low,Daily_Range,Close,EMA_10,EMA_50,RSI,"
        "RSI_Category,ATR,Support,Resistance"
    ]
    start = datetime(2025, 1, 1, tzinfo=UTC)
    dates = []
    cursor = start
    while len(dates) < 90:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor += timedelta(days=1)
    pairs = {
        "EUR/USD": 1.05,
        "GBP/USD": 1.24,
        "USD/JPY": 145.0,
    }
    for pair, base in pairs.items():
        for index in range(90):
            trend = 1.0 + (index * 0.0008)
            close = base * trend
            if index >= 75:
                close *= future_multiplier
            opened = close * 0.9995
            high = max(opened, close) * 1.001
            low = min(opened, close) * 0.999
            stamp = dates[index].strftime("%-m/%-d/%Y")
            rows.append(
                f"{stamp},{pair},{opened:.8f},{high:.8f},{low:.8f},0.01,"
                f"{close:.8f},999,999,99,Overbought,999,0,999"
            )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _service(path: Path) -> ForexHistoricalDatasetService:
    return ForexHistoricalDatasetService(
        source_path=path,
        source_url=SOURCE_URL,
        license_name="CC BY-SA 4.0",
        source_version="1",
        horizon_bars=1,
        minimum_warmup_bars=50,
        sample_weight=0.25,
    )


def test_import_recomputes_indicators_and_creates_point_in_time_outcomes(tmp_path):
    source = tmp_path / "forex.csv"
    _write_dataset(source)

    bundle = _service(source).prepare()

    assert bundle.examples
    assert bundle.provenance["license"] == "CC BY-SA 4.0"
    assert bundle.provenance["source_sha256"]
    assert bundle.provenance["rows_read"] == 270
    assert set(bundle.provenance["pairs"]) == {"EURUSD=X", "GBPUSD=X", "USDJPY=X"}
    assert all(example.outcome_timestamp > example.decision_timestamp for example in bundle.examples)
    assert all(example.evidence_lane == "external_historical_replay" for example in bundle.examples)
    assert all(example.sample_weight == 0.25 for example in bundle.examples)
    assert all(example.features["trend_score"] != 999 for example in bundle.examples)
    assert all(example.features["volatility"] != 999 for example in bundle.examples)
    assert "EURUSD=X" in bundle.knowledge["correlation_matrix"]


def test_conflicting_duplicate_date_rows_are_quarantined_without_inventing_a_bar(tmp_path):
    source = tmp_path / "forex.csv"
    _write_dataset(source)
    rows = source.read_text(encoding="utf-8").splitlines()
    duplicate = rows[1].split(",")
    duplicate[2] = "1.06000000"
    duplicate[3] = "1.07000000"
    duplicate[4] = "1.04000000"
    duplicate[6] = "1.06500000"
    source.write_text("\n".join([*rows, ",".join(duplicate)]) + "\n", encoding="utf-8")

    bundle = _service(source).prepare()

    assert bundle.provenance["conflicting_groups_quarantined"] == 1
    assert bundle.provenance["conflicting_rows_quarantined"] == 2
    assert all(bar["date"] != "2025-01-01" or bar["pair"] != "EURUSD=X"
               for bar in bundle.provenance["accepted_keys"])


def test_bundled_forex_only_accepts_unambiguous_weekday_snapshots():
    bundle = _service(bundled_forex_history_path()).prepare()
    assert bundle.provenance["daily_bars_created"] == 71
    assert bundle.provenance["conflicting_rows_quarantined"] == 632
    assert bundle.provenance["weekend_rows_quarantined"] == 223
    assert len(bundle.examples) == 1  # One continuous causal window; far below validation minimums.


def test_future_rows_cannot_change_earlier_historical_features(tmp_path):
    original = tmp_path / "original.csv"
    altered = tmp_path / "altered.csv"
    _write_dataset(original, future_multiplier=1.0)
    _write_dataset(altered, future_multiplier=1.5)

    first = _service(original).prepare()
    second = _service(altered).prepare()
    cutoff = datetime(2025, 4, 1)
    first_rows = {
        example.source_object_id: dict(example.features)
        for example in first.examples
        if example.decision_timestamp < cutoff
    }
    second_rows = {
        example.source_object_id: dict(example.features)
        for example in second.examples
        if example.decision_timestamp < cutoff
    }

    assert first_rows
    assert first_rows == second_rows


def test_external_projection_is_idempotent_and_records_provenance(tmp_path):
    source = tmp_path / "forex.csv"
    _write_dataset(source)
    bundle = _service(source).prepare()
    projector = TradingMLFeatureStoreProjector(root=tmp_path / "feature-store")

    first = projector.append_external(
        bundle.examples,
        source_id=bundle.provenance["source_id"],
        provenance=bundle.provenance,
    )
    second = projector.append_external(
        bundle.examples,
        source_id=bundle.provenance["source_id"],
        provenance=bundle.provenance,
    )

    assert first.rows_written == len(bundle.examples)
    assert second.rows_written == 0
    manifest = projector.manifest()
    assert manifest["external_sources"][bundle.provenance["source_id"]]["license"] == "CC BY-SA 4.0"
    assert manifest["evidence_lane_counts"]["external_historical_replay"] == len(bundle.examples)


def test_historical_knowledge_returns_bounded_explainable_context(tmp_path):
    source = tmp_path / "forex.csv"
    artifact = tmp_path / "knowledge.json"
    _write_dataset(source)
    bundle = _service(source).prepare()
    _service(source).write_knowledge(bundle, artifact)

    advice = ForexHistoricalKnowledgeService(artifact).advise(
        pair="EURUSD=X",
        closes=tuple(1.05 + index * 0.001 for index in range(60)),
    )

    assert advice.status == "AVAILABLE"
    assert advice.sample_size >= 10
    assert -0.03 <= advice.confidence_adjustment <= 0.03
    assert advice.source_sha256 == bundle.provenance["source_sha256"]
    assert "Chronological holdout" in advice.explanation[0]
    assert advice.explanation


def test_missing_history_artifact_is_neutral(tmp_path):
    advice = ForexHistoricalKnowledgeService(tmp_path / "missing.json").advise(
        pair="EURUSD=X",
        closes=tuple(1.0 + index * 0.001 for index in range(60)),
    )

    assert advice.status == "UNAVAILABLE"
    assert advice.confidence_adjustment == 0.0
    assert advice.sample_size == 0


def test_bundled_kaggle_source_is_pinned_and_prepares_without_fabrication():
    bundle = ForexHistoricalDatasetService(
        source_path=bundled_forex_history_path(),
        source_url=KAGGLE_FOREX_SOURCE_URL,
        license_name="CC BY-SA 4.0",
        source_version="1",
        sample_weight=0.25,
    ).prepare()

    assert bundle.provenance["source_sha256"] == (
        "def896b19b80b36fdd154a0de1ef001c05fd774769d5896a414959010896428c"
    )
    assert bundle.provenance["rows_read"] == 926
    assert bundle.provenance["daily_bars_created"] == 71
    assert bundle.provenance["duplicate_rows_observed"] == 657
    assert bundle.provenance["conflicting_groups_quarantined"] == 146
    assert len(bundle.examples) == 1


def test_rejected_old_external_rows_remain_auditable_but_cannot_train_either_reader(tmp_path):
    from dataclasses import replace
    from app.services.trading_ml.finrlx_runner import _load_feature_rows, _market_dataset_hash
    source = tmp_path / 'source.csv'
    _write_dataset(source)
    bundle = _service(source).prepare()
    store = TradingMLFeatureStoreProjector(root=tmp_path / 'store')
    old = tuple(replace(row, source_object_id='old:' + row.source_object_id.replace('blum-forex-daily-quality-v2:', ''))
                for row in bundle.examples)
    store.append_external(old, source_id='old-external', provenance={**bundle.provenance,'transformation_version':'blum-forex-daily-causal-v1'})
    assert store.manifest()['partitions']
    assert store.scan(market_family='forex').collect().is_empty()
    assert _load_feature_rows(store.root, 'forex', max_rows=1000) == []
    store.append_external(bundle.examples, source_id=bundle.provenance['source_id'], provenance=bundle.provenance)
    assert store.scan(market_family='forex').collect().height == len(bundle.examples)
    assert len(_load_feature_rows(store.root, 'forex', max_rows=1000)) == len(bundle.examples)
    assert _market_dataset_hash(store.root, 'forex') == store.market_dataset_hash('forex')
