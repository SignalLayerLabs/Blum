"""Causal publication clocks and explicit scope for retained legacy memory."""

from datetime import date, datetime, time

from app.services.market_clock import utc_naive


def clock(value):
    if isinstance(value, datetime):
        return utc_naive(value)
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        try:
            return utc_naive(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            pass
    return None


def decision_clock(context):
    return clock(
        context.get("decision_timestamp")
        or context.get("market_timestamp")
        or context.get("analysis_date")
    )


def state_available(row, metadata, as_of):
    if as_of is None or not isinstance(metadata, dict):
        return False
    created = clock(row.created_at)
    updated = clock(getattr(row, "updated_at", row.created_at))
    published = clock(metadata.get("available_at"))
    outcome = clock(metadata.get("outcome_cutoff"))
    return (
        all(
            value is not None and value <= as_of
            for value in (created, updated, published, outcome)
        )
        and outcome < as_of
    )


def scope_matches(metadata, context):
    scope = metadata.get("scope") if isinstance(metadata, dict) else None
    if (
        not isinstance(scope, dict)
        or not context.get("timeframe")
        or type(context.get("holding_horizon")) is not int
    ):
        return False
    asset = (context.get("asset") or {}).get("ticker")
    owner_matches = scope.get("asset_key") == asset and bool(asset)
    pooled = scope.get("pooled_group")
    owner_matches = owner_matches or bool(
        pooled
        and scope.get("pool_justification")
        and pooled == context.get("pooled_group")
    )
    return owner_matches and all(
        scope.get(name) == value
        for name, value in {
            "timeframe": context["timeframe"],
            "holding_horizon": context["holding_horizon"],
            "setup_type": context.get("setup_type") or "legacy_direction_forecast",
            "regime": (context.get("market_context") or {}).get("market_regime"),
            "strategy_fingerprint": context.get("strategy_fingerprint")
            or "legacy-direction-v1",
        }.items()
    )


def scoped_predicates(model, context):
    """Select eligible scope before LIMIT; unrelated high-score rows cannot hide it."""
    from sqlalchemy import or_, and_

    at = decision_clock(context)
    asset = (context.get("asset") or {}).get("ticker")
    if (
        at is None
        or not asset
        or not context.get("timeframe")
        or type(context.get("holding_horizon")) is not int
    ):
        return None
    scope = model.evidence["scope"]
    owners = [scope["asset_key"].as_string() == asset]
    if context.get("pooled_group"):
        owners.append(
            and_(
                scope["pooled_group"].as_string() == context["pooled_group"],
                scope["pool_justification"].as_string().is_not(None),
            )
        )
    return (
        model.created_at <= at,
        model.updated_at <= at,
        model.evidence["available_at"].as_string() <= at.isoformat(),
        model.evidence["outcome_cutoff"].as_string() < at.isoformat(),
        or_(*owners),
        scope["timeframe"].as_string() == context["timeframe"],
        scope["holding_horizon"].as_integer() == context["holding_horizon"],
        scope["setup_type"].as_string()
        == (context.get("setup_type") or "legacy_direction_forecast"),
        scope["regime"].as_string()
        == (context.get("market_context") or {}).get("market_regime"),
        scope["strategy_fingerprint"].as_string()
        == (context.get("strategy_fingerprint") or "legacy-direction-v1"),
    )
