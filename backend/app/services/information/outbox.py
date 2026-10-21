"""Transactional consumption identities shared by retained learning views."""

from datetime import datetime
from sqlalchemy import select

from app.models import InformationFeedbackOutbox
from .contracts import digest
from .repository import insert_once


def claim_once(
    db, *, consumer_version, source_uid, decision_uid, payload, market_family="equity"
):
    if not source_uid or not decision_uid:
        return False
    content_hash = digest(payload)
    now = datetime.utcnow()
    inserted = insert_once(
        db,
        InformationFeedbackOutbox,
        {
            "consumer_version": consumer_version,
            "source_uid": source_uid,
            "decision_uid": decision_uid,
            "market_family": market_family,
            "content_hash": content_hash,
            "payload_json": payload,
            "status": "CONSUMED",
            "source_updated_at": now,
            "created_at": now,
        },
        ["consumer_version", "source_uid"],
    )
    row = db.scalar(
        select(InformationFeedbackOutbox)
        .where(
            InformationFeedbackOutbox.consumer_version == consumer_version,
            InformationFeedbackOutbox.source_uid == source_uid,
        )
        .with_for_update()
    )
    if row.content_hash != content_hash:
        row.status, row.conflict_hash = "QUARANTINED", content_hash
        return False
    return inserted and row.status != "QUARANTINED"
