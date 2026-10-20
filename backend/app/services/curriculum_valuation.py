"""Report-only bar-close valuation of frozen curriculum execution outcomes.

Inspired by LEAN's separation of portfolio equity and trade statistics; this is
independent Python logic, not copied LEAN source. No strategy/model/checkpoint
updates or execution authority. Quote units are local to one research lane.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import math

from app.services.market_bar_clock import (
    available_at,
    canonical_open,
    consecutive,
    first_execution_start,
)
from app.services.realistic_execution import (
    ExecutionOrderRequest,
    RealisticExecutionEngine,
)
from app.services import trading_curriculum as kernel

VERSION = "curriculum-valuation-v1"


def _hash(value) -> str:
    # Invalid source values still receive an auditable fingerprint; they never
    # become report numbers or usable valuation observations.
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=True
        ).encode()
    ).hexdigest()


def _time(value) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if result.tzinfo is not None:
        raise ValueError("UTC-naive clocks required")
    return result


def _number(value, *, positive=False) -> float:
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("invalid economic value")
    return result


def _visible(bars, *, market, timeframe, start, end, as_of):
    visible = []
    try:
        if market not in {"USA", "FOREX"} or timeframe not in {
            "1m",
            "5m",
            "15m",
            "1h",
            "1d",
        }:
            return visible, "UNSUPPORTED_LANE"
        if not 0 <= start < end <= len(bars):
            return visible, "INVALID_WINDOW"
        for bar in bars[start:end]:
            if _time(bar["available"]) > as_of:
                continue
            visible.append(bar)
            opening = _time(bar["start"])
            if (
                not kernel.valid_bar(bar)
                or not canonical_open(opening, timeframe, market)
                or available_at(opening, timeframe, market) != _time(bar["available"])
            ):
                return visible, "INVALID_MARK_BAR"
            if len(visible) > 1 and not consecutive(
                _time(visible[-2]["start"]), opening, timeframe, market
            ):
                return visible, "INCOMPLETE_MARK_PATH"
        return visible, None if visible else "NO_OBSERVED_MARKS"
    except (KeyError, TypeError, ValueError, OverflowError):
        return visible, "INVALID_MARK_PATH"


def _events(trades, as_of):
    """Project frozen outcomes to events visible at this clock, never future P/L."""
    result = []
    for trade in trades:
        if _time(trade["decision_at"]) > as_of:
            continue
        if "entry_at" not in trade:
            if trade["status"] == "UNFILLED":
                if trade.get("reason") == "MISSING_FIRST_EXECUTION_BAR":
                    raise ValueError("MISSING_FIRST_EXECUTION_BAR")
                continue
            raise ValueError("UNVERIFIED_ENTRY_PATH")
        entered = _time(trade["entry_at"])
        if entered > as_of:
            continue
        if entered <= _time(trade["decision_at"]):
            raise ValueError("INVALID_ENTRY_CLOCK")
        quantity = _number(trade["quantity"], positive=True)
        price = _number(trade["entry_price"], positive=True)
        commission = _number(trade["entry_commission"])
        before = _number(trade["cash_before"])
        after = _number(trade["cash_after_entry"])
        if (
            commission < 0
            or after < -1e-6
            or not math.isclose(
                after, before - quantity * price - commission, abs_tol=1e-5
            )
        ):
            raise ValueError("INCONSISTENT_ENTRY_CASH")
        identity = len(result)
        result.append(
            dict(
                kind="entry",
                timestamp=entered.isoformat(),
                identity=identity,
                quantity=quantity,
                price=price,
                commission=commission,
                cash_before=before,
                cash_after=after,
            )
        )
        if trade.get("exit_at") is not None:
            exited = _time(trade["exit_at"])
            if exited <= entered:
                raise ValueError("INVALID_EXIT_CLOCK")
            if exited <= as_of:
                exit_price = _number(trade["exit_price"], positive=True)
                exit_fee = _number(trade["exit_commission"])
                pnl = _number(trade["pnl"])
                if (
                    trade["status"] != "CLOSED"
                    or exit_fee < 0
                    or not math.isclose(
                        pnl,
                        quantity * (exit_price - price) - commission - exit_fee,
                        abs_tol=1e-5,
                    )
                ):
                    raise ValueError("INCONSISTENT_EXIT_CASH")
                result.append(
                    dict(
                        kind="exit",
                        timestamp=exited.isoformat(),
                        identity=identity,
                        price=exit_price,
                        commission=exit_fee,
                        pnl=pnl,
                    )
                )
        elif trade["status"] == "CLOSED":
            raise ValueError("MISSING_EXIT_CLOCK")
    return sorted(
        result, key=lambda event: (event["timestamp"], event["kind"] == "entry")
    )


def _liquidation(cash, quantity, bar, market):
    if not quantity:
        return cash
    market_bar = kernel._execution_bar(bar, closed=True)
    # A close-priced hypothetical liquidation estimate, never a frozen sell.
    market_bar = replace(
        market_bar, open=market_bar.close, high=market_bar.close, low=market_bar.close
    )
    result = RealisticExecutionEngine().evaluate(
        ExecutionOrderRequest(
            "valuation-estimate",
            "curriculum",
            "SELL",
            "MARKET",
            market_bar.timestamp - timedelta(microseconds=1),
            market_bar.close,
            quantity,
            commission_bps=kernel.COMMISSION_BPS,
            liquidity_basis=(
                "otc_quote_capacity" if market == "FOREX" else "reported_volume"
            ),
            quote_capacity_units=100_000 if market == "FOREX" else None,
        ),
        [market_bar],
    )
    if result.filled_quantity < quantity - 1e-8:
        return None
    return cash + quantity * result.average_fill_price - result.costs.commission_cost


def _drawdown(values, capital):
    peak, worst = capital, 0.0
    for value in values:
        peak = max(peak, value)
        worst = max(worst, 1 - value / peak)
    return worst


def _finish(points, *, observed, events, as_of, capital, reason=None):
    path_complete = bool(points) and all(
        p["net_liquidation_estimate_quote_units"] is not None for p in points
    )
    last = points[-1] if points else {}
    nav = last.get("nav_quote_units") if reason is None else None
    liquidation = (
        last.get("net_liquidation_estimate_quote_units") if reason is None else None
    )
    sampled = (
        points
        if len(points) <= 128
        else [points[i * (len(points) - 1) // 127] for i in range(128)]
    )
    return dict(
        version=VERSION,
        status="WITHHELD" if reason else "COMPLETE",
        reason=reason,
        as_of=as_of.isoformat(),
        valuation_basis="bar_close",
        capital_quote_units=capital,
        nav_quote_units=nav,
        net_return=nav / capital - 1 if nav is not None else None,
        max_bar_close_drawdown=(
            _drawdown([p["nav_quote_units"] for p in points], capital)
            if nav is not None
            else None
        ),
        net_liquidation_status="ESTIMATE" if liquidation is not None else "WITHHELD",
        net_liquidation_reason=(
            None if liquidation is not None else (reason or "EXIT_CAPACITY_UNVERIFIED")
        ),
        net_liquidation_estimate_quote_units=liquidation,
        net_liquidation_return=(
            liquidation / capital - 1 if liquidation is not None else None
        ),
        net_liquidation_path_complete=path_complete and reason is None,
        max_bar_close_net_liquidation_drawdown=(
            _drawdown(
                [p["net_liquidation_estimate_quote_units"] for p in points], capital
            )
            if path_complete and reason is None
            else None
        ),
        sample_exposure_fraction=(
            sum(p["position_quantity"] > 0 for p in points) / len(points)
            if points and reason is None
            else None
        ),
        average_gross_exposure_fraction=(
            sum(p["gross_exposure_fraction"] for p in points) / len(points)
            if points and reason is None
            else None
        ),
        sample_count=len(points),
        curve=sampled,
        curve_hash=_hash(points),
        bars_hash=_hash(observed),
        fills_hash=_hash(events),
        cost_version=kernel.COST_VERSION,
        exposure_basis="bar_sample_fraction_not_calendar_time",
    )


def value_frozen_trades(
    bars, trades, *, market, timeframe, start, end, as_of, capital=10_000.0
):
    """Value actual frozen entries/exits on available closed bars, without resolving trades."""
    as_of = _time(as_of)
    capital = _number(capital, positive=True)
    observed, reason = _visible(
        bars, market=market, timeframe=timeframe, start=start, end=end, as_of=as_of
    )
    points, events = [], []
    try:
        events = _events(trades, as_of)
        cash, quantity, entry_cash, identity, cursor = capital, 0.0, None, None, 0
        # A visible bad/gapped bar cannot be used; retaining no curve is safer
        # than presenting the last known cash balance as the current portfolio.
        if reason:
            return _finish(
                points,
                observed=observed,
                events=events,
                as_of=as_of,
                capital=capital,
                reason=reason,
            )
        for bar in observed:
            clock = _time(bar["available"])
            while cursor < len(events) and _time(events[cursor]["timestamp"]) <= clock:
                event = events[cursor]
                if event["kind"] == "entry":
                    if quantity or not math.isclose(
                        cash, event["cash_before"], abs_tol=1e-5
                    ):
                        raise ValueError("OVERLAPPING_OR_REUSED_CAPITAL")
                    entry_cash, identity = cash, event["identity"]
                    cash, quantity = event["cash_after"], event["quantity"]
                else:
                    if not quantity or event["identity"] != identity:
                        raise ValueError("UNMATCHED_EXIT")
                    cash, quantity = entry_cash + event["pnl"], 0.0
                cursor += 1
            mark = float(bar["close"])
            nav = cash + quantity * mark
            if nav <= 0:
                raise ValueError("NONPOSITIVE_NAV")
            points.append(
                dict(
                    timestamp=clock.isoformat(),
                    cash_quote_units=cash,
                    position_quantity=quantity,
                    mark_price=mark,
                    nav_quote_units=nav,
                    net_liquidation_estimate_quote_units=_liquidation(
                        cash, quantity, bar, market
                    ),
                    gross_exposure_fraction=quantity * mark / nav,
                )
            )
        if cursor < len(events):
            reason = "EVENT_AFTER_LAST_OBSERVED_MARK"
        elif quantity:
            next_start = first_execution_start(
                _time(observed[-1]["start"]), timeframe, market
            )
            if available_at(next_start, timeframe, market) <= as_of:
                reason = "MISSING_TRAILING_MARK_BAR"
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        reason = (
            str(error) if isinstance(error, ValueError) else "MALFORMED_FROZEN_OUTCOME"
        )
    return _finish(
        points,
        observed=observed,
        events=events,
        as_of=as_of,
        capital=capital,
        reason=reason,
    )


def modeled_hold(bars, *, market, timeframe, start, end, as_of, capital=10_000.0):
    """One delayed-opening modeled buy, then marks; final liquidation stays an estimate.

    Matches curriculum commission, prior-bar spread/volatility, 5% participation
    and declared Forex OTC capacity. A 10bp opening collar bounds cash spending.
    No stops, targets, dividends, interest or verified final sell are invented.
    """
    as_of = _time(as_of)
    capital = _number(capital, positive=True)
    observed, reason = _visible(
        bars, market=market, timeframe=timeframe, start=start, end=end, as_of=as_of
    )
    trades, entry_status, position_status, requested = [], "WAITING_ENTRY", "CASH", None
    if not reason:
        decision = _time(observed[0]["available"])
        expected = first_execution_start(decision, timeframe, market)
        first = next((bar for bar in observed if _time(bar["start"]) > decision), None)
        if first is None and expected <= as_of:
            reason = "ENTRY_OPENED_WITHOUT_OBSERVED_MARK"
            position_status = "UNKNOWN"
        elif first and _time(first["start"]) != expected:
            reason = "MISSING_FIRST_EXECUTION_BAR"
        elif first:
            prior = [bar for bar in bars[:end] if _time(bar["available"]) <= decision]
            if not prior or any(not kernel.valid_bar(bar) for bar in prior[-20:]):
                reason = "INVALID_ENTRY_CONTEXT"
            else:
                volatility = sum(
                    (bar["high"] - bar["low"]) / bar["close"] * 10_000
                    for bar in prior[-20:]
                ) / len(prior[-20:])
                limit = float(first["open"]) * 1.001
                requested = capital / (limit * (1 + kernel.COMMISSION_BPS / 10_000))
                opening = replace(
                    kernel._execution_bar(first),
                    volatility_bps=volatility,
                    spread_bps=max(2, min(25, volatility * 0.03)),
                )
                fill = RealisticExecutionEngine().evaluate(
                    ExecutionOrderRequest(
                        "hold-entry",
                        "curriculum",
                        "BUY",
                        "LIMIT",
                        decision,
                        first["open"],
                        requested,
                        limit_price=limit,
                        commission_bps=kernel.COMMISSION_BPS,
                        liquidity_basis=(
                            "otc_quote_capacity"
                            if market == "FOREX"
                            else "reported_volume"
                        ),
                        quote_capacity_units=100_000 if market == "FOREX" else None,
                    ),
                    [opening],
                )
                quantity, price = fill.filled_quantity, fill.average_fill_price
                if quantity:
                    entry_status = (
                        "PARTIALLY_FILLED" if quantity < requested - 1e-8 else "FILLED"
                    )
                    position_status = "OPEN_MARKED"
                    trades = [
                        dict(
                            status="OPEN",
                            decision_at=decision.isoformat(),
                            entry_at=first["start"],
                            entry_price=price,
                            quantity=quantity,
                            entry_commission=fill.costs.commission_cost,
                            cash_before=capital,
                            cash_after_entry=capital
                            - quantity * price
                            - fill.costs.commission_cost,
                        )
                    ]
                else:
                    entry_status = "UNFILLED"
    result = (
        value_frozen_trades(
            bars,
            trades,
            market=market,
            timeframe=timeframe,
            start=start,
            end=end,
            as_of=as_of,
            capital=capital,
        )
        if not reason
        else _finish(
            [],
            observed=observed,
            events=[],
            as_of=as_of,
            capital=capital,
            reason=reason,
        )
    )
    result.update(
        entry_status=entry_status,
        position_status=position_status,
        requested_quantity=requested,
        liquidity_basis=(
            "otc_quote_capacity" if market == "FOREX" else "reported_volume"
        ),
        quote_capacity_units=100_000 if market == "FOREX" else None,
        baseline_basis="delayed_open_hold_with_costs_and_capacity_no_verified_exit",
    )
    return result
