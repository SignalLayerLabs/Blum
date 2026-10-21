from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Literal, Mapping
from urllib.parse import urlsplit, urlunsplit

from app.services.market_clock import utc_naive

MarketFamily = Literal["equity", "forex"]
ProviderStatus = Literal[
    "AVAILABLE", "EMPTY", "UNAVAILABLE", "QUOTA_LIMITED", "ENTITLEMENT_REQUIRED"
]


def thaw(value):
    if isinstance(value, Mapping):
        return {str(k): thaw(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(v) for v in value]
    return value


def freeze(value):
    # Canonical JSON validation also rejects NaN, bytes and arbitrary executable objects.
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("Information keys must be strings")
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(v) for v in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("Information must contain finite JSON values")


def digest(value) -> str:
    encoded = json.dumps(
        thaw(freeze(value)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme.lower() not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError("Evidence requires a public source URL without credentials")
    # Retrieval additionally validates destinations and redirects. Keep semantic query parameters.
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


@dataclass(frozen=True)
class SourceEvidence:
    evidence_id: str
    family_id: str
    provider: str
    canonical_url: str
    content_hash: str
    language: str
    published_at: datetime | None
    observed_at: datetime
    available_at: datetime
    revision_of: str | None
    historical_availability_verified: bool
    extraction_version: str
    payload: Mapping

    def __post_init__(self):
        object.__setattr__(self, "payload", freeze(self.payload))
        for name in ("published_at", "observed_at", "available_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, utc_naive(value))
        if self.content_hash != digest(self.payload):
            raise ValueError("Evidence content hash mismatch")
        if self.family_id != digest([self.provider, self.canonical_url]):
            raise ValueError("Evidence family mismatch")
        if self.evidence_id != digest(
            [self.provider, self.canonical_url, self.content_hash]
        ):
            raise ValueError("Evidence identity mismatch")
        if not self.provider or not self.extraction_version:
            raise ValueError("Provider and extraction version required")

    @classmethod
    def create(
        cls,
        *,
        provider,
        canonical_url: str,
        payload,
        language: str,
        published_at,
        observed_at,
        available_at,
        historical_availability_verified=False,
        extraction_version="v1",
        revision_of=None,
    ):
        url = globals()["canonical_url"](canonical_url)
        content = digest(payload)
        return cls(
            digest([provider, url, content]),
            digest([provider, url]),
            provider,
            url,
            content,
            language,
            published_at,
            observed_at,
            available_at,
            revision_of,
            historical_availability_verified,
            extraction_version,
            payload,
        )


@dataclass(frozen=True)
class EvidenceLink:
    evidence_id: str
    entity_key: str
    kind: str
    confidence: float
    reason: str
    mapping_version: str

    def __post_init__(self):
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Link confidence outside [0,1]")
        if self.kind not in {
            "issuer",
            "currency",
            "sector",
            "commodity",
            "etf_exposure",
        }:
            raise ValueError("Unsupported evidence linkage")
        if not self.reason or not self.mapping_version or not self.entity_key:
            raise ValueError("Link requires entity, reason and mapping version")
        object.__setattr__(self, "entity_key", self.entity_key.upper())


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    status: ProviderStatus
    evidence: tuple[SourceEvidence, ...]
    observed_at: datetime
    links: tuple[EvidenceLink, ...] = ()
    cursor: str | None = None
    retry_at: datetime | None = None
    source_at: datetime | None = None
    error_code: str | None = None
    coverage: Mapping = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in {
            "AVAILABLE",
            "EMPTY",
            "UNAVAILABLE",
            "QUOTA_LIMITED",
            "ENTITLEMENT_REQUIRED",
        }:
            raise ValueError("Unsupported provider status")
        if self.error_code and not re.fullmatch(r"[A-Z0-9_]{1,80}", self.error_code):
            raise ValueError(
                "Use a bounded error code, never raw headers or exception text"
            )
        if self.status != "AVAILABLE" and self.evidence:
            raise ValueError("Non-available provider result cannot carry evidence")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "links", tuple(self.links))
        object.__setattr__(self, "coverage", freeze(self.coverage))
        for name in ("observed_at", "source_at", "retry_at"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, utc_naive(getattr(self, name)))


@dataclass(frozen=True)
class OpportunityContext:
    context_uid: str
    market_family: MarketFamily
    asset_key: str
    decision_at: datetime
    price_refs: tuple[Mapping, ...]
    evidence_ids: tuple[str, ...]
    links: tuple[EvidenceLink, ...]
    calendar_state: str
    features: Mapping
    coverage: Mapping
    schema_version: str
    max_available_at: datetime
    hash: str

    def __post_init__(self):
        for name in ("price_refs", "features", "coverage"):
            object.__setattr__(self, name, freeze(getattr(self, name)))
        for name in ("decision_at", "max_available_at"):
            object.__setattr__(self, name, utc_naive(getattr(self, name)))
        object.__setattr__(self, "links", tuple(self.links))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        if self.max_available_at > self.decision_at:
            raise ValueError("Context contains future information")
        payload = self.to_payload()
        payload.pop("context_uid")
        payload.pop("hash")
        if self.hash != digest(payload) or self.context_uid != "ctx:" + self.hash:
            raise ValueError("Context hash mismatch")

    def to_payload(self):
        return {
            "context_uid": self.context_uid,
            "market_family": self.market_family,
            "asset_key": self.asset_key,
            "decision_at": self.decision_at.isoformat(),
            "price_refs": thaw(self.price_refs),
            "evidence_ids": list(self.evidence_ids),
            "links": [
                {
                    f: getattr(link, f)
                    for f in (
                        "evidence_id",
                        "entity_key",
                        "kind",
                        "confidence",
                        "reason",
                        "mapping_version",
                    )
                }
                for link in self.links
            ],
            "calendar_state": self.calendar_state,
            "features": thaw(self.features),
            "coverage": thaw(self.coverage),
            "schema_version": self.schema_version,
            "max_available_at": self.max_available_at.isoformat(),
            "hash": self.hash,
        }


@dataclass(frozen=True)
class MaturedAlphaOutcome:
    source_uid: str
    decision_uid: str
    market_family: MarketFamily
    asset_key: str
    decision_at: datetime
    outcome_at: datetime
    realized_net_r: float
    evidence_lane: str
    context: OpportunityContext
    executable_strategy: Mapping
    strategy_fingerprint: str
    checkpoint_hash: str | None
    cost_breakdown: Mapping
    benchmark_reference: Mapping
    account_return: float | None = None

    def __post_init__(self):
        from dataclasses import fields
        from math import isfinite
        from app.services.executable_strategy import ExecutableStrategySpec

        for name in ("decision_at", "outcome_at"):
            object.__setattr__(self, name, utc_naive(getattr(self, name)))
        if not self.source_uid or not self.decision_uid or not self.evidence_lane:
            raise ValueError(
                "Native source, decision and original evidence lane required"
            )
        if (
            self.outcome_at <= self.decision_at
            or isinstance(self.realized_net_r, bool)
            or not isfinite(self.realized_net_r)
        ):
            raise ValueError("Only terminal finite net outcomes can mature")
        if (
            self.context.decision_at,
            self.context.market_family,
            self.context.asset_key,
        ) != (self.decision_at, self.market_family, self.asset_key):
            raise ValueError("Outcome must match the exact frozen context")
        if any(
            field.name not in self.executable_strategy
            for field in fields(ExecutableStrategySpec)
        ):
            raise ValueError("Complete frozen executable strategy required")
        spec = ExecutableStrategySpec.from_payload(self.executable_strategy)
        if (
            spec.fingerprint != self.strategy_fingerprint
            or self.executable_strategy.get("strategy_fingerprint")
            != self.strategy_fingerprint
        ):
            raise ValueError("Frozen strategy fingerprint mismatch")
        if self.checkpoint_hash is not None and (
            len(self.checkpoint_hash) != 64
            or any(c not in "0123456789abcdef" for c in self.checkpoint_hash)
        ):
            raise ValueError("Checkpoint hash must identify the frozen artifact")
        for name in ("executable_strategy", "cost_breakdown", "benchmark_reference"):
            digest(getattr(self, name))
            object.__setattr__(self, name, freeze(getattr(self, name)))
