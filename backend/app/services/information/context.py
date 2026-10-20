from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
import math
import re
import unicodedata

from sqlalchemy import select

from app.models import Asset, InformationLink
from app.services.market_clock import utc_naive, bar_available_at
from .contracts import EvidenceLink, OpportunityContext, digest, thaw
from .providers import parse_time
from .repository import InformationRepository

SCHEMA_VERSION = "information-v2"
FEATURE_UNITS = {
    "event_novelty": "distinct_event_families_24h",
    "issuer_sentiment": "signed_model_score_-1_1",
    "sector_sentiment": "signed_model_score_-1_1",
    "etf_exposure_sentiment": "signed_model_score_-1_1",
    "base_currency_policy_delta_bps": "basis_points",
    "quote_currency_policy_delta_bps": "basis_points",
    "policy_differential_change_bps": "basis_points",
    "release_age_seconds": "seconds",
    "information_coverage": "fraction_of_declared_capabilities",
    "calendar_known": "boolean_0_1",
    "event_window": "boolean_0_1_or_unknown",
    "consensus_surprise_z": "standard_deviations_or_unknown",
    **{
        f"macro_{name}_{unit}": unit
        for name, unit in (
            ("DGS10", "percent"),
            ("DGS2", "percent"),
            ("T10Y2Y", "percent"),
            ("FEDFUNDS", "percent"),
            ("CPIAUCSL", "index"),
            ("VIXCLS", "index"),
            ("DCOILWTICO", "USD"),
        )
    },
}
FEATURE_SCHEMA_HASH = digest({"version": SCHEMA_VERSION, "units": FEATURE_UNITS})


def _number(value):
    return (
        float(value)
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def _normalized(text):
    return " ".join(
        re.findall(r"\w+", unicodedata.normalize("NFKC", str(text)).casefold())
    )


def _mentions(item, asset):
    from app.ingestion.news_ingestor import asset_aliases

    if item.provider.startswith("sec:"):
        return True  # The adapter supplies an exact CIK → instrument mapping.
    text = f"{item.payload.get('title', '')} {item.payload.get('text', '')}"
    ticker = re.escape(asset.ticker)
    if re.search(rf"(?<![A-Za-z0-9])\$?{ticker}(?![A-Za-z0-9])", text):
        return True
    normal = " " + _normalized(text) + " "
    return any(
        " " + _normalized(alias) + " " in normal for alias in asset_aliases(asset)
    )


def price_reference(row, history=()):
    def facts(bar):
        return {
            "source_uid": "replay:" + str(bar.id),
            "timestamp": utc_naive(bar.bar_timestamp).isoformat(),
            "available_at": utc_naive(bar_available_at(bar)).isoformat(),
            "acquired_at": utc_naive(bar.acquired_at).isoformat(),
            "provider": bar.provider,
            "timeframe": bar.timeframe,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "source_metadata": bar.source_metadata or {},
        }

    ref = facts(row)
    ref["history_sha256"] = digest([facts(bar) for bar in history] or [facts(row)])
    return ref


class OpportunityContextBuilder:
    def build(
        self, db, *, market_family, asset_key, decision_at, price_refs, historical=False
    ):
        if market_family not in {"equity", "forex"}:
            raise ValueError("Unsupported market family")
        at, key = utc_naive(decision_at), asset_key.upper()
        refs, clocks = [], []
        if not price_refs:
            raise ValueError("Context requires observed price references")
        for ref in price_refs:
            ref = thaw(ref)
            stamp, available = parse_time(ref.get("timestamp")), parse_time(
                ref.get("available_at")
            )
            acquired = parse_time(ref.get("acquired_at")) or available
            if (
                not ref.get("source_uid")
                or not ref.get("provider")
                or stamp is None
                or available is None
            ):
                raise ValueError("Price reference lacks identity or availability")
            if (
                stamp > at
                or available > at
                or (
                    acquired > at
                    and not (historical and ref.get("historical_availability_verified"))
                )
            ):
                raise ValueError("Future price reference")
            for name in ("close", "bid", "ask"):
                if name in ref and (_number(ref[name]) is None or ref[name] <= 0):
                    raise ValueError("Invalid referenced price")
            if not any(name in ref for name in ("close", "bid", "ask")):
                raise ValueError("Referenced price unavailable")
            ref.update(
                timestamp=stamp.isoformat(),
                available_at=available.isoformat(),
                acquired_at=acquired.isoformat(),
            )
            refs.append(ref)
            clocks.append(available)
        refs.sort(key=digest)
        repo = InformationRepository()
        asset = (
            db.scalar(select(Asset).where(Asset.ticker == key))
            if market_family == "equity"
            else None
        )
        if market_family == "equity" and asset is None:
            raise ValueError("Context equity asset must be registered")
        pair = key.removesuffix("=X").replace("/", "")
        if market_family == "forex" and (len(pair) != 6 or not pair.isalpha()):
            raise ValueError("Invalid currency pair")
        base, quote = (pair[:3], pair[3:]) if market_family == "forex" else (None, None)
        keys = {key}
        if asset:
            keys.update(
                filter(
                    None,
                    [
                        asset.sector.upper(),
                        "SECTOR:" + asset.sector.upper(),
                        asset.currency,
                    ],
                )
            )
        candidates = {
            item.evidence_id: item
            for entity in sorted(keys)
            for item in repo.eligible(
                db,
                market_family=market_family,
                asset_key=entity,
                as_of=at,
                historical=historical,
            )
        }
        rows = (
            db.scalars(
                select(InformationLink).where(
                    InformationLink.evidence_id.in_(candidates)
                )
            ).all()
            if candidates
            else []
        )
        linked, channels = [], {}
        currencies = {base, quote} if market_family == "forex" else {asset.currency}
        for row in rows:
            item = candidates[row.evidence_id]
            channel = None
            if row.kind == "currency" and row.entity_key in currencies:
                channel = "currency:" + row.entity_key
            elif (
                asset
                and row.kind == "sector"
                and row.entity_key
                in {asset.sector.upper(), "SECTOR:" + asset.sector.upper()}
            ):
                channel = "sector"
            elif asset and row.entity_key == key:
                if row.kind == "etf_exposure":
                    channel = "etf_exposure"
                elif row.kind == "issuer" and _mentions(item, asset):
                    channel = "issuer"
            if channel is not None and row.confidence > 0:
                linked.append(
                    EvidenceLink(
                        row.evidence_id,
                        row.entity_key,
                        row.kind,
                        row.confidence,
                        row.reason,
                        row.mapping_version,
                    )
                )
                channels.setdefault(row.evidence_id, set()).add(channel)
        items = [item for item in candidates.values() if item.evidence_id in channels]
        # Keep evidence citations even when aged; feature relevance is bounded below.
        items.sort(key=lambda e: (e.available_at, e.evidence_id))
        features = {name: None for name in FEATURE_UNITS}
        families, policy, macro, complete_scopes, known_window = (
            {},
            {},
            {},
            set(),
            False,
        )
        latest_release = None
        for item in items:
            clocks.append(item.available_at)
            payload = item.payload
            capability = payload.get("source_capability")
            if (
                item.published_at
                and at - item.published_at <= timedelta(days=1)
                and capability
                not in {
                    "current_state",
                    "vintage_state",
                    "calendar_schedule",
                    "discovery",
                }
            ):
                family = digest(
                    [
                        _normalized(payload.get("title", "")),
                        str(payload.get("event_reference", "")),
                    ]
                )
                families.setdefault(family, []).append(item)
                latest_release = (
                    max(latest_release, item.published_at)
                    if latest_release
                    else item.published_at
                )
            delta = payload.get("policy_delta")
            if (
                delta
                and item.published_at
                and at - item.published_at <= timedelta(days=3)
                and (
                    item.provider.startswith(("fed", "ecb"))
                    or capability == "central_bank_release"
                )
            ):
                number = _number(delta.get("value"))
                unit, currency = delta.get("unit"), delta.get("currency")
                if (
                    number is not None
                    and unit in {"basis_points", "percentage_points"}
                    and "currency:" + str(currency) in channels[item.evidence_id]
                ):
                    policy[currency] = number * (
                        100 if unit == "percentage_points" else 1
                    )
            series, number, unit = (
                payload.get("series_id"),
                _number(payload.get("value")),
                payload.get("unit"),
            )
            feature = f"macro_{series}_{unit}"
            if (
                feature in FEATURE_UNITS
                and number is not None
                and capability in {"current_state", "vintage_state"}
            ):
                period = parse_time(payload.get("period"))
                max_age = timedelta(
                    days=45 if series in {"FEDFUNDS", "CPIAUCSL"} else 7
                )
                if period and timedelta(0) <= at - period <= max_age:
                    macro[feature] = number
            schedule = payload.get("calendar_coverage")
            if capability == "calendar_schedule" and schedule:
                start, end = parse_time(schedule.get("start")), parse_time(
                    schedule.get("end")
                )
                if start and end and start <= at < end:
                    if schedule.get("complete") is True:
                        complete_scopes.update(
                            link.entity_key
                            for link in linked
                            if link.evidence_id == item.evidence_id
                        )
                    for event in schedule.get("events", ()):
                        stamp = parse_time(event.get("scheduled_at"))
                        if (
                            stamp
                            and event.get("impact") == "HIGH"
                            and abs((stamp - at).total_seconds()) <= 1800
                        ):
                            known_window = True
        features.update(macro)
        features["event_novelty"] = len(families)
        for channel, feature in (
            ("issuer", "issuer_sentiment"),
            ("sector", "sector_sentiment"),
            ("etf_exposure", "etf_exposure_sentiment"),
        ):
            family_scores = []
            for members in families.values():
                scores = [
                    score
                    for item in members
                    if channel in channels[item.evidence_id]
                    and item.payload.get("sentiment_model")
                    and (score := _number(item.payload.get("sentiment_score")))
                    is not None
                    and -1 <= score <= 1
                ]
                if scores:
                    family_scores.append(sum(scores) / len(scores))
            features[feature] = (
                sum(family_scores) / len(family_scores) if family_scores else None
            )
        features["base_currency_policy_delta_bps"] = policy.get(base)
        features["quote_currency_policy_delta_bps"] = policy.get(quote)
        if base in policy and quote in policy:
            features["policy_differential_change_bps"] = policy[base] - policy[quote]
        features["release_age_seconds"] = (
            (at - latest_release).total_seconds() if latest_release else None
        )
        required_scopes = currencies | ({key} if asset else set())
        calendar = (
            "KNOWN_EVENT_WINDOW"
            if known_window
            else "KNOWN_CLEAR" if required_scopes <= complete_scopes else "UNKNOWN"
        )
        features["calendar_known"] = int(calendar != "UNKNOWN")
        features["event_window"] = (
            1 if known_window else 0 if calendar == "KNOWN_CLEAR" else None
        )
        fresh_channels = (
            set().union(
                *(
                    channels[item.evidence_id]
                    for members in families.values()
                    for item in members
                )
            )
            if families
            else set()
        )
        required = (
            [
                (
                    "etf_exposure_event"
                    if asset.asset_type.lower() == "etf"
                    else "issuer_event"
                ),
                "sector_event",
                "macro_state",
                "calendar",
                "consensus",
            ]
            if asset
            else [
                "base_currency_context",
                "quote_currency_context",
                "calendar",
                "consensus",
            ]
        )
        available = set()
        if "issuer" in fresh_channels:
            available.add("issuer_event")
        if "sector" in fresh_channels:
            available.add("sector_event")
        if "etf_exposure" in fresh_channels:
            available.add("etf_exposure_event")
        if macro:
            available.add("macro_state")
        if "currency:" + str(base) in fresh_channels or (base == "USD" and macro):
            available.add("base_currency_context")
        if "currency:" + str(quote) in fresh_channels or (quote == "USD" and macro):
            available.add("quote_currency_context")
        if calendar != "UNKNOWN":
            available.add("calendar")
        features["information_coverage"] = len(set(required) & available) / len(
            required
        )
        coverage = {
            "required_capabilities": required,
            "available_capabilities": sorted(available),
            "missing_capabilities": sorted(set(required) - available),
            "event_families": sorted(families),
            "feature_units": FEATURE_UNITS,
            "feature_schema_hash": FEATURE_SCHEMA_HASH,
            "evidence_lane": "RECONSTRUCTED" if historical else "FIRST_OBSERVED",
        }
        ids = tuple(sorted(item.evidence_id for item in items))
        links = tuple(
            sorted(
                linked,
                key=lambda e: (e.evidence_id, e.entity_key, e.kind, e.mapping_version),
            )
        )
        maximum = max(clocks)
        snapshot = {
            "market_family": market_family,
            "asset_key": key,
            "decision_at": at.isoformat(),
            "price_refs": refs,
            "evidence_ids": ids,
            "links": [asdict(link) for link in links],
            "calendar_state": calendar,
            "features": features,
            "coverage": coverage,
            "schema_version": SCHEMA_VERSION,
            "max_available_at": maximum.isoformat(),
        }
        hashed = digest(snapshot)
        return OpportunityContext(
            "ctx:" + hashed,
            market_family,
            key,
            at,
            tuple(refs),
            ids,
            links,
            calendar,
            features,
            coverage,
            SCHEMA_VERSION,
            maximum,
            hashed,
        )
