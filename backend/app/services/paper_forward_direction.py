"""Authoritative directional accounting for paper-forward trades."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable


LONG = "LONG"
SHORT = "SHORT"
CASH_BENCHMARK = "CASH"
ACCOUNTING_VERSION = "paper-forward-direction-v2"
ACCOUNTING_VALID = "VALID"
ACCOUNTING_RECOMPUTED = "RECOMPUTED"
PENDING_SIDE_VERIFICATION = "PENDING_SIDE_VERIFICATION"
INVALID_PENDING_RECOMPUTATION = "INVALID_PENDING_RECOMPUTATION"
TRUSTED_ACCOUNTING_STATUSES = {ACCOUNTING_VALID, ACCOUNTING_RECOMPUTED}

_SIDE_ALIASES = {
    "BUY": LONG,
    "BUY_LONG": LONG,
    "LONG": LONG,
    "BULL": LONG,
    "BULLISH": LONG,
    "SELL": SHORT,
    "SELL_SHORT": SHORT,
    "SHORT": SHORT,
    "BEAR": SHORT,
    "BEARISH": SHORT,
}


class DirectionalTradePlanError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DirectionalTradeMetrics:
    side: str
    price_change: float
    return_fraction: float
    gross_pnl: float
    net_pnl: float
    risk_distance: float
    risk_amount: float
    r_multiple: float | None


def normalize_side(value: Any) -> str | None:
    key = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    return _SIDE_ALIASES.get(key)


def recorded_account_currency(*accounting_contracts: Any) -> str | None:
    """Recover the immutable cash unit; conflicting or malformed records stay unknown."""
    if any(item is not None and not isinstance(item, dict) for item in accounting_contracts):
        return None
    values = [item['account_currency'] for item in accounting_contracts if isinstance(item, dict) and 'account_currency' in item]
    if not values:
        return 'EUR'  # Legacy named-EUR fields before currency contracts existed.
    value = values[0]
    if not all(item == value for item in values):
        return None
    return value if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isalpha() and value.isupper() else None


def direction_multiplier(side: Any) -> int:
    normalized = normalize_side(side)
    if normalized == LONG:
        return 1
    if normalized == SHORT:
        return -1
    raise ValueError(f"Unsupported trade side: {side!r}")


def recover_trade_side(payload: dict[str, Any] | None) -> str | None:
    source = payload if isinstance(payload, dict) else {}
    plan = source.get("trade_plan") if isinstance(source.get("trade_plan"), dict) else {}
    proposal = source.get("proposal") if isinstance(source.get("proposal"), dict) else {}
    strategy = source.get("strategy") if isinstance(source.get("strategy"), dict) else {}
    scanner = source.get("opportunity_scanner") if isinstance(source.get("opportunity_scanner"), dict) else {}
    candidates = (
        source.get("side"),
        source.get("direction"),
        source.get("action"),
        plan.get("side"),
        plan.get("direction"),
        plan.get("action"),
        proposal.get("side"),
        proposal.get("direction"),
        proposal.get("action"),
        strategy.get("side"),
        strategy.get("direction"),
        scanner.get("side"),
        scanner.get("direction"),
    )
    return next((side for value in candidates if (side := normalize_side(value))), None)


def is_forex_identity(*, ticker: Any, market: Any = None, asset_type: Any = None) -> bool:
    ticker_key = str(ticker or "").strip().upper()
    market_key = str(market or "").strip().upper()
    asset_type_key = str(asset_type or "").strip().upper()
    return (
        ticker_key.endswith("=X")
        or market_key in {"FOREX", "FX", "CURRENCY"}
        or "FOREX" in market_key
        or asset_type_key in {"FOREX", "FX", "CURRENCY", "CURRENCY_PAIR", "FOREX_PAIR"}
        or "FOREX" in asset_type_key
    )


def signed_price_change(side: Any, entry_price: float, exit_price: float) -> float:
    return direction_multiplier(side) * (float(exit_price) - float(entry_price))


def signed_return(side: Any, entry_price: float, exit_price: float) -> float:
    entry = float(entry_price)
    if entry <= 0:
        raise ValueError("entry_price must be positive")
    return direction_multiplier(side) * ((float(exit_price) / entry) - 1.0)


def risk_distance(side: Any, entry_price: float, stop_price: float) -> float:
    multiplier = direction_multiplier(side)
    distance = multiplier * (float(entry_price) - float(stop_price))
    if distance <= 0:
        raise DirectionalTradePlanError("invalid_trade_plan_geometry")
    return distance


def reward_distance(side: Any, entry_price: float, target_price: float) -> float:
    distance = signed_price_change(side, entry_price, target_price)
    if distance <= 0:
        raise DirectionalTradePlanError("invalid_trade_plan_geometry")
    return distance


def validate_trade_plan(
    side: Any,
    *,
    entry: float,
    stop: float,
    targets: Iterable[float | None],
) -> dict[str, float | list[float] | str]:
    normalized = normalize_side(side)
    if normalized is None:
        raise DirectionalTradePlanError("missing_trade_side")
    entry_value = float(entry)
    stop_value = float(stop)
    target_values = [float(value) for value in targets if value is not None]
    if entry_value <= 0 or stop_value <= 0 or not target_values or any(value <= 0 for value in target_values):
        raise DirectionalTradePlanError("missing_valid_trade_plan")
    risk = risk_distance(normalized, entry_value, stop_value)
    rewards = [reward_distance(normalized, entry_value, value) for value in target_values]
    return {
        "side": normalized,
        "risk_distance": risk,
        "reward_distances": rewards,
        "risk_reward": rewards[0] / risk,
    }


def exit_reason(
    side: Any,
    latest_price: float,
    *,
    stop: float | None = None,
    target_1: float | None = None,
    target_2: float | None = None,
    invalidation: float | None = None,
) -> str | None:
    normalized = normalize_side(side)
    if normalized is None:
        return None
    price = float(latest_price)
    if normalized == LONG:
        if stop is not None and price <= float(stop):
            return "STOP_HIT"
        if invalidation is not None and price <= float(invalidation):
            return "INVALIDATION_HIT"
        if target_2 is not None and price >= float(target_2):
            return "TARGET_2_HIT"
        if target_1 is not None and price >= float(target_1):
            return "TARGET_1_HIT"
    else:
        if stop is not None and price >= float(stop):
            return "STOP_HIT"
        if invalidation is not None and price >= float(invalidation):
            return "INVALIDATION_HIT"
        if target_2 is not None and price <= float(target_2):
            return "TARGET_2_HIT"
        if target_1 is not None and price <= float(target_1):
            return "TARGET_1_HIT"
    return None


def trade_metrics(
    *,
    side: Any,
    entry_price: float,
    exit_price: float,
    stop_price: float,
    quantity: float,
    costs: float,
    conversion_rate: float = 1.0,
    risk_amount: float | None = None,
) -> DirectionalTradeMetrics:
    normalized = normalize_side(side)
    if normalized is None:
        raise ValueError("A normalized LONG/SHORT side is required")
    conversion = max(0.000001, float(conversion_rate))
    change = signed_price_change(normalized, entry_price, exit_price)
    return_fraction = signed_return(normalized, entry_price, exit_price)
    gross = change * float(quantity) / conversion
    net = gross - max(0.0, float(costs))
    distance = risk_distance(normalized, entry_price, stop_price)
    calculated_risk = distance * float(quantity) / conversion
    effective_risk = float(risk_amount) if risk_amount is not None and float(risk_amount) > 0 else calculated_risk
    return DirectionalTradeMetrics(
        side=normalized,
        price_change=change,
        return_fraction=return_fraction,
        gross_pnl=gross,
        net_pnl=net,
        risk_distance=distance,
        risk_amount=effective_risk,
        r_multiple=net / effective_risk if effective_risk > 0 else None,
    )


def directional_excursions(
    *,
    side: Any,
    entry_price: float,
    high_price: float,
    low_price: float,
    current_mfe: float,
    current_mae: float,
    percent: bool,
) -> tuple[float, float]:
    favorable_price = float(high_price) if normalize_side(side) == LONG else float(low_price)
    adverse_price = float(low_price) if normalize_side(side) == LONG else float(high_price)
    favorable = signed_return(side, entry_price, favorable_price) if percent else signed_price_change(side, entry_price, favorable_price)
    adverse = signed_return(side, entry_price, adverse_price) if percent else signed_price_change(side, entry_price, adverse_price)
    scale = 100.0 if percent else 1.0
    mfe = max(float(current_mfe or 0.0), favorable * scale, 0.0)
    mae = min(float(current_mae or 0.0), adverse * scale, 0.0)
    return round(mfe, 8), round(mae, 8)


def paper_trade_evidence_is_eligible(trade: Any) -> bool:
    is_forex = is_forex_identity(
        ticker=getattr(trade, "ticker", None),
        market=getattr(trade, "market", None),
        asset_type=getattr(trade, "asset_type", None),
    )
    accounting_status = str(getattr(trade, "accounting_status", "") or "")
    if not is_forex:
        return accounting_status != INVALID_PENDING_RECOMPUTATION
    if accounting_status not in TRUSTED_ACCOUNTING_STATUSES:
        return False
    side = normalize_side(getattr(trade, "side", None))
    return side in {LONG, SHORT}


def finite_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None
