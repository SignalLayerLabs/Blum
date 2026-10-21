"""Incremental immutable Polars/Parquet feature-store projection."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from typing import Iterable, Literal, Protocol
from uuid import uuid4

from filelock import FileLock, Timeout as FileLockTimeout
import polars as pl
from sqlalchemy.orm import Session

from .contracts import (
    CATEGORICAL_FEATURES,
    FeatureSchema,
    NUMERIC_FEATURES,
    TradingMLExample,
)
from .dataset import DatasetSlice, TradingMLDatasetRepository
from .forex_history import FOREX_HISTORY_TRANSFORM_VERSION

MarketFamily = Literal["equity", "forex"]
_MANIFEST_NAME = "manifest.json"
_MANIFEST_LOCK_NAME = ".manifest.lock"
_DEFAULT_MANIFEST_LOCK_TIMEOUT_SECONDS = 10.0
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class FeatureStoreLockTimeout(RuntimeError):
    """Raised before publication when the manifest commit lock is unavailable."""


class DatasetReader(Protocol):
    def read_slice(
        self,
        db: Session | None,
        *,
        market_family: MarketFamily,
        after_cursor: dict[str, object] | None,
        limit: int,
    ) -> DatasetSlice: ...


@dataclass(frozen=True)
class ProjectionResult:
    rows_written: int
    partitions_written: int
    dataset_hash: str
    source_cursor: dict[str, object] | None
    rows_considered: int
    rows_rejected: int
    is_exhausted: bool


class TradingMLFeatureStoreProjector:
    """Projects source-of-truth examples into immutable, append-only Parquet parts."""

    def __init__(
        self,
        *,
        root: Path | str,
        repository: DatasetReader | None = None,
        max_rows_per_projection: int = 5_000,
        max_partition_rows: int = 1_000,
        manifest_lock_timeout_seconds: float = _DEFAULT_MANIFEST_LOCK_TIMEOUT_SECONDS,
        schema: FeatureSchema | None = None,
    ) -> None:
        if max_rows_per_projection <= 0 or max_partition_rows <= 0:
            raise ValueError("projection and partition limits must be positive")
        if manifest_lock_timeout_seconds <= 0:
            raise ValueError("manifest lock timeout must be positive")
        self.root = Path(root)
        self.schema = schema or FeatureSchema.current()
        self._repository = repository or TradingMLDatasetRepository()
        self._max_rows_per_projection = max_rows_per_projection
        self._max_partition_rows = max_partition_rows
        self._manifest_lock_timeout_seconds = manifest_lock_timeout_seconds

    def project(
        self,
        db: Session | None,
        *,
        market_family: MarketFamily,
        limit: int | None = None,
    ) -> ProjectionResult:
        """Append one bounded source slice; never rehydrate historical store rows."""

        row_limit = min(
            max(1, limit or self._max_rows_per_projection),
            self._max_rows_per_projection,
        )
        source_manifest = self._load_manifest()
        cursor = self._cursor_for(source_manifest, market_family)
        dataset_slice = self._repository.read_slice(
            db,
            market_family=market_family,
            after_cursor=cursor,
            limit=row_limit,
        )
        unique_examples, rejected_duplicates = _deduplicate_examples(
            dataset_slice.examples
        )

        with _manifest_update_lock(
            self.root,
            timeout_seconds=self._manifest_lock_timeout_seconds,
        ):
            manifest = self._load_manifest()
            partitions = self._write_partitions(unique_examples, market_family)
            committed_partitions = _merge_partitions(manifest["partitions"], partitions)
            if dataset_slice.next_cursor is not None:
                current_cursor = self._cursor_for(manifest, market_family)
                manifest.setdefault("source_cursors", {})[market_family] = (
                    _merge_source_cursors(
                        current_cursor,
                        dataset_slice.next_cursor,
                    )
                )
            manifest["partitions"].extend(committed_partitions)
            manifest["evidence_lane_counts"] = self._evidence_lane_counts(
                manifest["partitions"]
            )
            manifest["dataset_hash"] = quality_adjusted_hash(
                self._dataset_hash(manifest["partitions"]), "all", manifest
            )
            self._write_manifest(manifest)
            committed_cursor = self._cursor_for(manifest, market_family)
        return ProjectionResult(
            rows_written=sum(partition["rows"] for partition in committed_partitions),
            partitions_written=len(committed_partitions),
            dataset_hash=manifest["dataset_hash"],
            source_cursor=committed_cursor,
            rows_considered=dataset_slice.rows_considered,
            rows_rejected=dataset_slice.rows_rejected + rejected_duplicates,
            is_exhausted=dataset_slice.exhausted,
        )

    def append_external(
        self,
        examples: tuple[TradingMLExample, ...],
        *,
        source_id: str,
        provenance: dict,
    ) -> ProjectionResult:
        """Append an immutable external research dataset without changing DB cursors."""

        if not source_id.strip():
            raise ValueError("external source_id is required")
        if any(example.market_family != "forex" for example in examples):
            raise ValueError("external Forex projection accepts only forex examples")
        source_sha256 = str(provenance.get("source_sha256") or "")
        if not source_sha256:
            raise ValueError("external source provenance requires source_sha256")
        unique_examples, rejected_duplicates = _deduplicate_examples(examples)
        with _manifest_update_lock(
            self.root,
            timeout_seconds=self._manifest_lock_timeout_seconds,
        ):
            manifest = self._load_manifest()
            external_sources = manifest.setdefault("external_sources", {})
            previous = external_sources.get(source_id)
            if previous is not None:
                if str(previous.get("source_sha256") or "") != source_sha256:
                    raise ValueError(
                        "external source content changed without a new source version"
                    )
                return ProjectionResult(
                    rows_written=0,
                    partitions_written=0,
                    dataset_hash=str(manifest["dataset_hash"]),
                    source_cursor=self._cursor_for(manifest, "forex"),
                    rows_considered=len(examples),
                    rows_rejected=rejected_duplicates,
                    is_exhausted=True,
                )
            partitions = self._write_partitions(unique_examples, "forex")
            committed_partitions = _merge_partitions(manifest["partitions"], partitions)
            manifest["partitions"].extend(committed_partitions)
            external_sources[source_id] = json.loads(
                json.dumps(provenance, default=str)
            )
            manifest["evidence_lane_counts"] = self._evidence_lane_counts(
                manifest["partitions"]
            )
            manifest["dataset_hash"] = quality_adjusted_hash(
                self._dataset_hash(manifest["partitions"]), "all", manifest
            )
            self._write_manifest(manifest)
        return ProjectionResult(
            rows_written=sum(partition["rows"] for partition in committed_partitions),
            partitions_written=len(committed_partitions),
            dataset_hash=str(manifest["dataset_hash"]),
            source_cursor=self._cursor_for(manifest, "forex"),
            rows_considered=len(examples),
            rows_rejected=rejected_duplicates,
            is_exhausted=True,
        )

    def scan(
        self,
        *,
        market_family: MarketFamily,
        columns: Iterable[str] | None = None,
        predicate: pl.Expr | None = None,
    ) -> pl.LazyFrame:
        """Return a lazy scan over requested columns only."""

        manifest = self._load_manifest()
        paths = [
            str(self.root / partition["path"])
            for partition in manifest["partitions"]
            if partition["market_family"] == market_family
        ]
        if not paths:
            frame = pl.LazyFrame(schema=_polars_schema(self.schema))
        else:
            frame = pl.scan_parquet(paths)
        # Keep old immutable files for audit while excluding their rejected data.
        frame = frame.filter(
            (pl.col("source_object_type") != "external_forex_history")
            | pl.col("source_object_id").str.contains(
                FOREX_HISTORY_TRANSFORM_VERSION, literal=True
            )
        )
        quarantined = list(manifest.get("quarantined_native_sources", {}))
        if quarantined:
            frame = frame.filter(~pl.col("source_uid").is_in(quarantined))
        if predicate is not None:
            frame = frame.filter(predicate)
        if columns is not None:
            frame = frame.select(list(columns))
        return frame

    def manifest(self) -> dict:
        """Return a defensive manifest copy for status and tests."""

        return json.loads(json.dumps(self._load_manifest()))

    def append_examples(
        self, examples, *, publication_uid: str, content_hash: str
    ) -> dict:
        """Idempotent publication from the committed native outcome outbox."""
        examples = tuple(examples)
        if (
            not examples
            or len(examples) > self._max_rows_per_projection
            or not publication_uid
            or not content_hash
        ):
            raise ValueError("A bounded identified native publication is required")
        families = {row.market_family for row in examples}
        if len(families) != 1:
            raise ValueError("Publish each market independently")
        with _manifest_update_lock(
            self.root, timeout_seconds=self._manifest_lock_timeout_seconds
        ):
            manifest = self._load_manifest()
            publications = manifest.setdefault("native_publications", {})
            if publication_uid in publications:
                if publications[publication_uid] != content_hash:
                    raise ValueError("NATIVE_PUBLICATION_CHANGED")
                return {"rows_written": 0}
            partitions = self._write_partitions(examples, next(iter(families)))
            committed = _merge_partitions(manifest["partitions"], partitions)
            manifest["partitions"].extend(committed)
            publications[publication_uid] = content_hash
            manifest["evidence_lane_counts"] = self._evidence_lane_counts(
                manifest["partitions"]
            )
            manifest["dataset_hash"] = quality_adjusted_hash(
                self._dataset_hash(manifest["partitions"]), "all", manifest
            )
            self._write_manifest(manifest)
            return {"rows_written": sum(row["rows"] for row in committed)}

    def quarantine_source(self, publication_uid, *, conflict_hash, market_family):
        with _manifest_update_lock(
            self.root, timeout_seconds=self._manifest_lock_timeout_seconds
        ):
            manifest = self._load_manifest()
            manifest.setdefault("quarantined_native_sources", {})[publication_uid] = {
                "conflict_hash": conflict_hash,
                "market_family": market_family,
            }
            manifest["dataset_hash"] = quality_adjusted_hash(
                self._dataset_hash(manifest["partitions"]), "all", manifest
            )
            self._write_manifest(manifest)

    def online_page(
        self, *, market_family: MarketFamily, cursor: dict | None, limit: int
    ) -> dict:
        """Consume bounded immutable parts in commit order, including old backlog."""
        if limit <= 0:
            raise ValueError("Online page limit must be positive")
        manifest = self._load_manifest()
        partitions = manifest["partitions"]
        quarantined = list(manifest.get("quarantined_native_sources", {}))
        index = int((cursor or {}).get("partition_index", 0))
        offset = int((cursor or {}).get("row_offset", 0))

        def anchor():
            prefix = [
                (row["path"], row["content_hash"])
                for row in partitions[: index + int(offset > 0)]
            ]
            return hashlib.sha256(
                json.dumps(prefix, separators=(",", ":")).encode()
            ).hexdigest()

        if (
            index < 0
            or index > len(partitions)
            or offset < 0
            or (index == len(partitions) and offset)
        ):
            raise ValueError("ONLINE_CURSOR_OUT_OF_RANGE")
        if cursor and cursor.get("anchor") != anchor():
            raise ValueError("ONLINE_CURSOR_PREFIX_CHANGED")
        rows = []
        considered = rejected = 0
        while index < len(partitions) and considered < limit:
            partition = partitions[index]
            if partition["market_family"] != market_family:
                index += 1
                offset = 0
                continue
            remaining = int(partition["rows"]) - offset
            if remaining < 0:
                raise ValueError("ONLINE_CURSOR_ROW_OUT_OF_RANGE")
            requested = min(limit - considered, remaining)
            raw = (
                pl.scan_parquet(self.root / partition["path"])
                .slice(offset, requested)
                .collect()
            )
            if raw.height != requested:
                raise ValueError("ONLINE_PARTITION_LENGTH_CHANGED")
            accepted = raw.filter(
                (pl.col("source_object_type") != "external_forex_history")
                | pl.col("source_object_id").str.contains(
                    FOREX_HISTORY_TRANSFORM_VERSION, literal=True
                )
            )
            if quarantined:
                accepted = accepted.filter(~pl.col("source_uid").is_in(quarantined))
            rows.extend(accepted.to_dicts())
            considered += raw.height
            rejected += raw.height - accepted.height
            offset += raw.height
            if offset == int(partition["rows"]):
                index += 1
                offset = 0
        return {
            "rows": rows,
            "rows_considered": considered,
            "rows_rejected": rejected,
            "exhausted": index >= len(partitions),
            "cursor": {
                "partition_index": index,
                "row_offset": offset,
                "anchor": anchor(),
            },
        }

    def market_dataset_hash(self, market_family: MarketFamily) -> str:
        manifest = self._load_manifest()
        partition_hash = self._dataset_hash(
            partition
            for partition in manifest["partitions"]
            if partition.get("market_family") == market_family
        )
        return quality_adjusted_hash(partition_hash, market_family, manifest)

    def _write_partitions(
        self, examples: tuple[TradingMLExample, ...], market_family: MarketFamily
    ) -> list[dict]:
        partitions: list[dict] = []
        for year, month, monthly_examples in _examples_by_month(examples):
            for start in range(0, len(monthly_examples), self._max_partition_rows):
                chunk = monthly_examples[start : start + self._max_partition_rows]
                rows = [
                    _row_from_example(example, schema=self.schema) for example in chunk
                ]
                content_hash = _content_hash(rows)
                directory = (
                    self.root
                    / "features"
                    / f"market_family={market_family}"
                    / f"year={year}"
                    / f"month={month:02d}"
                )
                directory.mkdir(parents=True, exist_ok=True)
                filename = f"part-{content_hash}.parquet"
                target = directory / filename
                if not target.exists():
                    temporary = directory / f".{filename}.{uuid4().hex}.tmp"
                    try:
                        _frame_from_rows(rows, schema=self.schema).write_parquet(
                            temporary, compression="zstd"
                        )
                        verified = pl.read_parquet(temporary)
                        if (
                            verified.height != len(rows)
                            or set(verified["source_uid"].to_list())
                            != {row["source_uid"] for row in rows}
                            or _content_hash(verified.to_dicts()) != content_hash
                        ):
                            raise RuntimeError(
                                "Parquet feature partition verification failed"
                            )
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                partitions.append(
                    {
                        "path": str(target.relative_to(self.root)),
                        "market_family": market_family,
                        "rows": len(rows),
                        "content_hash": content_hash,
                        "source_uid_hash": _source_uid_hash(rows),
                        "evidence_lane_counts": _lane_counts(rows),
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                )
        return partitions

    def _load_manifest(self) -> dict:
        path = self.root / _MANIFEST_NAME
        if not path.exists():
            return {
                "schema_version": self.schema.version,
                "schema_hash": self.schema.hash,
                "dataset_hash": _dataset_hash(()),
                "partitions": [],
                "source_cursors": {},
                "evidence_lane_counts": {},
                "external_sources": {},
            }
        with path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        if manifest.get("schema_hash") != self.schema.hash:
            raise RuntimeError(
                "Feature-store schema hash does not match the active feature contract"
            )
        manifest.setdefault("partitions", [])
        manifest.setdefault("source_cursors", {})
        manifest.setdefault("evidence_lane_counts", {})
        manifest.setdefault("external_sources", {})
        return manifest

    def _write_manifest(self, manifest: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{_MANIFEST_NAME}.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.root / _MANIFEST_NAME)

    @staticmethod
    def _cursor_for(
        manifest: dict, market_family: MarketFamily
    ) -> dict[str, object] | None:
        cursor = manifest.get("source_cursors", {}).get(market_family)
        return cursor if isinstance(cursor, dict) else None

    @staticmethod
    def _evidence_lane_counts(partitions: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for partition in partitions:
            for lane, count in partition.get("evidence_lane_counts", {}).items():
                counts[lane] = counts.get(lane, 0) + count
        return counts

    @staticmethod
    def _dataset_hash(partitions: Iterable[dict]) -> str:
        return _dataset_hash(partitions)


@contextmanager
def _manifest_update_lock(root: Path, *, timeout_seconds: float):
    root.mkdir(parents=True, exist_ok=True)
    root_key = str(root.resolve())
    with _THREAD_LOCKS_GUARD:
        thread_lock = _THREAD_LOCKS.setdefault(root_key, threading.RLock())
    deadline = time.monotonic() + timeout_seconds
    if not thread_lock.acquire(timeout=timeout_seconds):
        raise FeatureStoreLockTimeout(
            f"Timed out after {timeout_seconds:.3f}s waiting for the feature-store manifest lock"
        )
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FeatureStoreLockTimeout(
                f"Timed out after {timeout_seconds:.3f}s waiting for the feature-store manifest lock"
            )
        process_lock = FileLock(str(root / _MANIFEST_LOCK_NAME))
        try:
            with process_lock.acquire(timeout=remaining):
                yield
        except FileLockTimeout as error:
            raise FeatureStoreLockTimeout(
                f"Timed out after {timeout_seconds:.3f}s waiting for the feature-store manifest lock"
            ) from error
    finally:
        thread_lock.release()


def _merge_partitions(current: list[dict], incoming: list[dict]) -> list[dict]:
    committed_paths = {str(partition.get("path")) for partition in current}
    merged: list[dict] = []
    for partition in incoming:
        path = str(partition["path"])
        if path in committed_paths:
            continue
        committed_paths.add(path)
        merged.append(partition)
    return merged


def _merge_source_cursors(
    current: dict[str, object] | None, incoming: dict[str, object]
) -> dict[str, object]:
    if current is None:
        return json.loads(json.dumps(incoming))
    current_offsets = _cursor_offsets(current)
    incoming_offsets = _cursor_offsets(incoming)
    incoming_advanced = any(
        source_id > current_offsets.get(source, 0)
        for source, source_id in incoming_offsets.items()
    )
    merged_offsets = dict(current_offsets)
    for source, source_id in incoming_offsets.items():
        merged_offsets[source] = max(merged_offsets.get(source, 0), source_id)
    active_source = (
        str(incoming.get("source_table"))
        if incoming_advanced
        else str(current.get("source_table"))
    )
    if active_source not in merged_offsets:
        merged_offsets[active_source] = max(
            _cursor_last_id(incoming if incoming_advanced else current),
            merged_offsets.get(active_source, 0),
        )
    return {
        "source_table": active_source,
        "last_source_id": merged_offsets[active_source],
        "source_offsets": merged_offsets,
    }


def _cursor_offsets(cursor: dict[str, object]) -> dict[str, int]:
    offsets: dict[str, int] = {}
    raw_offsets = cursor.get("source_offsets")
    if isinstance(raw_offsets, dict):
        for source, source_id in raw_offsets.items():
            try:
                offsets[str(source)] = max(0, int(source_id))
            except (TypeError, ValueError):
                continue
    source_table = str(cursor.get("source_table"))
    offsets[source_table] = max(offsets.get(source_table, 0), _cursor_last_id(cursor))
    return offsets


def _cursor_last_id(cursor: dict[str, object]) -> int:
    try:
        return max(0, int(cursor.get("last_source_id", 0)))
    except (TypeError, ValueError):
        return 0


def _row_from_example(example: TradingMLExample, *, schema=None) -> dict:
    schema = schema or FeatureSchema.current()
    if (
        schema.source_schema_hash is not None
        and example.features.get("information_feature_schema_hash")
        != schema.source_schema_hash
    ):
        raise ValueError("INFORMATION_SCHEMA_REQUIRED")
    row: dict[str, object] = {
        "source_uid": _source_uid(example),
        "source_object_type": example.source_object_type,
        "source_object_id": example.source_object_id,
        "market_family": example.market_family,
        "evidence_lane": example.evidence_lane,
        "decision_timestamp": example.decision_timestamp,
        "outcome_timestamp": example.outcome_timestamp,
        "asset_key": example.asset_key,
        "setup_type": example.setup_type,
        "regime": example.regime,
        "realized_net_r": example.realized_net_r,
        "label_positive_r": example.label_positive_r,
        "benchmark_excess": example.benchmark_excess,
        "sample_weight": example.sample_weight,
        "feature_schema_version": schema.version,
        "feature_schema_hash": schema.hash,
        "feature_hash": _feature_hash(example),
    }
    for name in schema.feature_names:
        categorical = name in (*CATEGORICAL_FEATURES, "strategy_fingerprint")
        value = (
            example.features.get(name, "unknown")
            if categorical
            else example.features.get(name)
        )
        # Match the declared Parquet representation before content hashing.
        # Keep the historical v1 serialization unchanged for existing parts.
        row[name] = (
            float(value)
            if schema.source_schema_hash is not None
            and not categorical
            and value is not None
            else value
        )
    if schema.source_schema_hash is not None:
        row["information_feature_schema_hash"] = schema.source_schema_hash
    return row


def _source_uid(example: TradingMLExample) -> str:
    return f"{example.source_object_type}:{example.source_object_id}"


def _feature_hash(example: TradingMLExample) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(example.features), sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()


def _content_hash(rows: list[dict]) -> str:
    serialized = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: (
            value.isoformat() if isinstance(value, datetime) else str(value)
        ),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _source_uid_hash(rows: list[dict]) -> str:
    source_uids = sorted(str(row["source_uid"]) for row in rows)
    return hashlib.sha256("\n".join(source_uids).encode("utf-8")).hexdigest()


def _deduplicate_examples(
    examples: tuple[TradingMLExample, ...],
) -> tuple[tuple[TradingMLExample, ...], int]:
    seen: set[str] = set()
    unique: list[TradingMLExample] = []
    for example in examples:
        source_uid = _source_uid(example)
        if source_uid in seen:
            continue
        seen.add(source_uid)
        unique.append(example)
    return tuple(unique), len(examples) - len(unique)


def _dataset_hash(partitions: Iterable[dict]) -> str:
    payload = [
        {
            "content_hash": partition["content_hash"],
            "market_family": partition["market_family"],
            "path": partition["path"],
            "rows": partition["rows"],
        }
        for partition in partitions
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def quality_adjusted_hash(
    partition_hash: str, market_family: str, manifest: dict
) -> str:
    if market_family == "forex" and manifest.get("external_sources"):
        partition_hash = hashlib.sha256(
            f"{FOREX_HISTORY_TRANSFORM_VERSION}:{partition_hash}".encode()
        ).hexdigest()
    quarantined = sorted(
        (uid, record["conflict_hash"])
        for uid, record in manifest.get("quarantined_native_sources", {}).items()
        if market_family == "all" or record["market_family"] == market_family
    )
    if quarantined:
        return hashlib.sha256(
            json.dumps([partition_hash, quarantined], separators=(",", ":")).encode()
        ).hexdigest()
    return partition_hash


def _lane_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        lane = str(row["evidence_lane"])
        counts[lane] = counts.get(lane, 0) + 1
    return counts


def _examples_by_month(
    examples: tuple[TradingMLExample, ...],
) -> list[tuple[int, int, tuple[TradingMLExample, ...]]]:
    buckets: dict[tuple[int, int], list[TradingMLExample]] = {}
    for example in examples:
        bucket = (example.decision_timestamp.year, example.decision_timestamp.month)
        buckets.setdefault(bucket, []).append(example)
    return [
        (year, month, tuple(bucket_examples))
        for (year, month), bucket_examples in sorted(buckets.items())
    ]


_POLARS_SCHEMA = {
    "source_uid": pl.String,
    "source_object_type": pl.String,
    "source_object_id": pl.String,
    "market_family": pl.String,
    "evidence_lane": pl.String,
    "decision_timestamp": pl.Datetime,
    "outcome_timestamp": pl.Datetime,
    "asset_key": pl.String,
    "setup_type": pl.String,
    "regime": pl.String,
    "realized_net_r": pl.Float64,
    "label_positive_r": pl.Int8,
    "benchmark_excess": pl.Float64,
    "sample_weight": pl.Float64,
    "feature_schema_version": pl.String,
    "feature_schema_hash": pl.String,
    "feature_hash": pl.String,
    **{name: pl.Float64 for name in NUMERIC_FEATURES},
    **{name: pl.String for name in CATEGORICAL_FEATURES},
}


def _polars_schema(schema):
    result = dict(_POLARS_SCHEMA)
    for name in schema.feature_names:
        result[name] = (
            pl.String
            if name in (*CATEGORICAL_FEATURES, "strategy_fingerprint")
            else pl.Float64
        )
    if schema.source_schema_hash is not None:
        result["information_feature_schema_hash"] = pl.String
    return result


def _frame_from_rows(rows: list[dict], *, schema=None) -> pl.DataFrame:
    return pl.DataFrame(
        rows, schema=_polars_schema(schema or FeatureSchema.current()), strict=False
    )
