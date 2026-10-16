import json
from dataclasses import replace

import pytest

from app.services.trading_ml.feature_store import TradingMLFeatureStoreProjector
from app.services.trading_ml.dataset import DatasetSlice
from test_trading_ml_training import examples


class Repository:
    def __init__(self, rows):
        self.rows = [
            replace(
                row,
                decision_timestamp=row.decision_timestamp.replace(tzinfo=None),
                outcome_timestamp=row.outcome_timestamp.replace(tzinfo=None),
            )
            for row in rows
        ]

    def read_slice(self, db, *, market_family, after_cursor, limit):
        offset = int((after_cursor or {}).get("last_source_id", 0))
        rows = tuple(self.rows[offset : offset + limit])
        return DatasetSlice(
            rows,
            {"last_source_id": offset + len(rows)},
            len(rows),
            0,
            offset + len(rows) >= len(self.rows),
        )


def test_online_pages_start_with_the_oldest_unread_partition_and_resume_after_restart(
    tmp_path,
):
    projector = TradingMLFeatureStoreProjector(
        root=tmp_path, repository=Repository(examples(20)), max_partition_rows=7
    )
    projector.project(None, market_family="equity", limit=20)
    first = projector.online_page(market_family="equity", cursor=None, limit=5)
    assert [row["source_object_id"] for row in first["rows"]] == [
        str(index) for index in range(5)
    ]
    restarted = TradingMLFeatureStoreProjector(root=tmp_path)
    second = restarted.online_page(
        market_family="equity", cursor=first["cursor"], limit=5
    )
    assert [row["source_object_id"] for row in second["rows"]] == [
        str(index) for index in range(5, 10)
    ]
    cursor = second["cursor"]
    seen = first["rows"] + second["rows"]
    for _ in range(5):
        page = restarted.online_page(market_family="equity", cursor=cursor, limit=5)
        assert page["rows_considered"] <= 5
        cursor = page["cursor"]
        seen.extend(page["rows"])
        if page["exhausted"]:
            break
    assert len(seen) == 20
    assert (
        restarted.online_page(market_family="equity", cursor=cursor, limit=5)["rows"]
        == []
    )


def test_changed_manifest_prefix_cannot_silently_skip_online_data(tmp_path):
    projector = TradingMLFeatureStoreProjector(
        root=tmp_path, repository=Repository(examples(20)), max_partition_rows=7
    )
    projector.project(None, market_family="equity", limit=20)
    first = projector.online_page(market_family="equity", cursor=None, limit=8)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["partitions"].reverse()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="CURSOR"):
        projector.online_page(market_family="equity", cursor=first["cursor"], limit=5)
