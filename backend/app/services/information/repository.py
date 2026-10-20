from __future__ import annotations

from dataclasses import fields
from datetime import datetime

from sqlalchemy import exists, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import aliased

from app.models import InformationEvidence, InformationLink, InformationProviderState
from app.services.market_clock import utc_naive
from .contracts import MarketFamily, ProviderResult, SourceEvidence, thaw


def insert_once(db, table, values, keys):
    dialect = db.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise ValueError("Information persistence requires SQLite or PostgreSQL")
    insert = sqlite_insert if dialect == "sqlite" else pg_insert
    result = db.execute(
        insert(table).values(**values).on_conflict_do_nothing(index_elements=keys)
    )
    return bool(result.rowcount)


class InformationRepository:
    """Append-only identities; transactions and commits belong to the caller."""

    MAX_BATCH = 200
    MAX_CONTEXT = 100

    def ingest(self, db, result: ProviderResult) -> dict:
        if (
            len(result.evidence) > self.MAX_BATCH
            or len(result.links) > self.MAX_BATCH * 20
        ):
            raise ValueError("Provider batch exceeds persistence budget")
        identities = {e.evidence_id for e in result.evidence}
        if any(e.provider != result.provider for e in result.evidence):
            raise ValueError("Mixed provider evidence")
        if any(link.evidence_id not in identities for link in result.links):
            raise ValueError("Link must refer to evidence in this batch")
        insert_once(
            db,
            InformationProviderState,
            {
                "provider": result.provider,
                "status": result.status,
                "retries": 0,
                "observed_at": datetime.min,
                "coverage": {},
            },
            ["provider"],
        )
        # Provider row serializes revisions/cursors across PostgreSQL workers. SQLite
        # holds its write transaction from insert_once; no unlocked check/insert race.
        state = db.scalar(
            select(InformationProviderState)
            .where(InformationProviderState.provider == result.provider)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        inserted = 0
        for item in sorted(
            result.evidence, key=lambda e: (e.observed_at, e.evidence_id)
        ):
            prior = db.scalar(
                select(InformationEvidence)
                .where(
                    InformationEvidence.family_id == item.family_id,
                    InformationEvidence.evidence_id != item.evidence_id,
                    InformationEvidence.observed_at <= item.observed_at,
                )
                .order_by(
                    InformationEvidence.observed_at.desc(),
                    InformationEvidence.evidence_id.desc(),
                )
                .limit(1)
            )
            values = {
                f.name: thaw(getattr(item, f.name)) for f in fields(SourceEvidence)
            }
            values["revision_of"] = prior.evidence_id if prior else None
            inserted += insert_once(db, InformationEvidence, values, ["evidence_id"])
        for link in result.links:
            insert_once(
                db,
                InformationLink,
                {f.name: getattr(link, f.name) for f in fields(link)},
                ["evidence_id", "entity_key", "kind", "mapping_version"],
            )
        if result.observed_at >= state.observed_at:
            success = result.status in {"AVAILABLE", "EMPTY"}
            state.status = result.status
            state.observed_at = result.observed_at
            if result.source_at is not None:
                state.source_at = result.source_at
            state.retry_at = result.retry_at
            state.error_code = result.error_code
            state.coverage = thaw(result.coverage)
            state.retries = 0 if success else state.retries + 1
            if success:
                state.last_success_at = result.observed_at
                if result.cursor is not None:
                    state.cursor = result.cursor
        db.flush()
        return {
            "inserted": inserted,
            "duplicates": len(result.evidence) - inserted,
            "status": state.status,
            "cursor": state.cursor,
        }

    def eligible(
        self,
        db,
        *,
        market_family: MarketFamily,
        asset_key: str,
        as_of: datetime,
        historical: bool = False,
    ) -> tuple[SourceEvidence, ...]:
        if market_family not in {"equity", "forex"}:
            raise ValueError("Unsupported market family")
        at = utc_naive(as_of)
        key = asset_key.upper()
        entities = {key}
        if market_family == "forex":
            pair = key.removesuffix("=X").replace("/", "")
            if len(pair) == 6 and pair.isalpha():
                entities.update((pair[:3], pair[3:]))

        def causal(row):
            state_types = (
                ("vintage_state",) if historical else ("current_state", "vintage_state")
            )
            clauses = [
                or_(
                    row.published_at <= at,
                    row.published_at.is_(None)
                    & row.payload["source_capability"].as_string().in_(state_types),
                ),
                row.available_at <= at,
            ]
            if historical:
                clauses.append(row.historical_availability_verified.is_(True))
            else:
                clauses.append(row.observed_at <= at)
            return clauses

        newer = aliased(InformationEvidence)
        newer_exists = exists(
            select(newer.evidence_id).where(
                newer.family_id == InformationEvidence.family_id,
                *causal(newer),
                (newer.available_at > InformationEvidence.available_at)
                | (
                    (newer.available_at == InformationEvidence.available_at)
                    & (
                        (newer.observed_at > InformationEvidence.observed_at)
                        | (
                            (newer.observed_at == InformationEvidence.observed_at)
                            & (newer.evidence_id > InformationEvidence.evidence_id)
                        )
                    )
                ),
            )
        )
        linked = exists(
            select(InformationLink.id).where(
                InformationLink.evidence_id == InformationEvidence.evidence_id,
                InformationLink.entity_key.in_(entities),
            )
        )
        rows = db.scalars(
            select(InformationEvidence)
            .where(
                *causal(InformationEvidence),
                linked,
                ~newer_exists,
            )
            .order_by(
                InformationEvidence.available_at.desc(), InformationEvidence.evidence_id
            )
            .limit(self.MAX_CONTEXT)
        ).all()
        return tuple(
            SourceEvidence(
                **{f.name: getattr(row, f.name) for f in fields(SourceEvidence)}
            )
            for row in rows
        )
