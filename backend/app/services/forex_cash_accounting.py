"""Versioned paper cash ledger. Fill costs are embedded; fees/swap are cash.

Conversions use current executable bid/ask, with at most two observed legs.
An exit can complete before FX settlement; missing rates never become money.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from math import isfinite

from app.services.forex_contracts import ForexDirection, ForexOrderRequest, pair_config

VERSION = "forex-cashflow-v2"


def _utc(value):
    return (
        value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    )


def fresh(quote, now):
    return (
        quote is not None
        and 0 <= (_utc(now) - _utc(quote.timestamp)).total_seconds() <= 180
    )


def convert_cash(amount, source, target, quotes, *, now):
    """Convert a credit at bid / inverse ask, a debit at ask / inverse bid."""
    if not isfinite(amount):
        return None
    if source == target or amount == 0:
        return {
            "amount": amount,
            "rate": 1.0,
            "source_currency": source,
            "account_currency": target,
            "legs": [],
            "at": now.isoformat(),
        }
    edges = {}
    for pair, quote in sorted(quotes.items()):
        if not fresh(quote, now) or not quote.source:
            continue
        config = pair_config(pair)
        for start, end, rate in (
            (
                config.base_currency,
                config.quote_currency,
                quote.bid if amount >= 0 else quote.ask,
            ),
            (
                config.quote_currency,
                config.base_currency,
                1 / (quote.ask if amount >= 0 else quote.bid),
            ),
        ):
            edges.setdefault(start, []).append(
                (
                    end,
                    rate,
                    {
                        "pair": pair,
                        "from": start,
                        "to": end,
                        "bid": quote.bid,
                        "ask": quote.ask,
                        "rate": rate,
                        "quote_at": quote.timestamp.isoformat(),
                        "provider": quote.source,
                    },
                )
            )
    queue = [(source, 1.0, [], {source})]
    for currency, rate, legs, seen in queue:
        if len(legs) >= 2:
            continue
        for next_currency, leg_rate, leg in edges.get(currency, []):
            if next_currency in seen:
                continue
            combined = rate * leg_rate
            if next_currency == target:
                return {
                    "amount": amount * combined,
                    "rate": combined,
                    "source_currency": source,
                    "account_currency": target,
                    "legs": [*legs, leg],
                    "at": now.isoformat(),
                }
            queue.append(
                (next_currency, combined, [*legs, leg], seen | {next_currency})
            )
    return None


class ForexCashAccounting:
    def manage(self, position, quotes, broker, execution, *, now):
        was_open = position.status == "OPEN"
        contract = deepcopy(position.contract_json)
        ledger = contract["accounting"]
        currency = contract["account_currency"]
        config = pair_config(position.pair)
        original = ledger["original_quantity_lots"]
        remaining = ledger["remaining_quantity_lots"]
        margin_released = 0.0
        quote = quotes.get(position.pair)
        if remaining > 1e-9 and fresh(quote, now):
            side = ForexDirection(position.direction)
            current = quote.bid if side == ForexDirection.LONG else quote.ask
            position.current_price = current
            position.last_managed_at = now
            request = ForexOrderRequest(
                position.pair,
                side,
                "MARKET",
                remaining,
                current,
                position.stop_price,
                position.target_price,
                session=contract.get("session", "UNKNOWN"),
                liquidity_score=contract.get("liquidity_score", 0.5),
                volatility_score=contract.get("volatility_score", 0.5),
                event_impact=contract.get("event_impact", "LOW_IMPACT"),
                account_conversion=convert_cash(
                    -1, config.quote_currency, currency, quotes, now=now
                )
                or {},
            )
            last_swap = date.fromisoformat(ledger["swap_date"])
            for offset in range(max(0, (now.date() - last_swap).days)):
                weekday = (last_swap + timedelta(days=offset + 1)).weekday()
                cash = execution.accrue_swap(request, broker, nights=1, weekday=weekday)
                ledger["swap_remaining"] += cash
                position.swap_accrued += cash
            ledger["swap_date"] = now.date().isoformat()
            valuation = execution.close(
                request, quote, broker, reason="VALUATION", now=now
            )
            mark = None
            if (
                valuation.fill_price is not None
                and valuation.filled_quantity_lots >= remaining - 1e-9
            ):
                mark = convert_cash(
                    (valuation.fill_price - position.entry_price)
                    * 100_000
                    * remaining
                    * (1 if side == ForexDirection.LONG else -1),
                    config.quote_currency,
                    currency,
                    quotes,
                    now=now,
                )
            net_mark = (
                (
                    mark["amount"]
                    - ledger["entry_commission"] * remaining / original
                    - valuation.commission
                    + ledger["swap_remaining"]
                )
                if mark
                else None
            )
            contract["valuation"] = {
                "timestamp": now.isoformat(),
                "bid": quote.bid,
                "ask": quote.ask,
                "unrealized_gross_pnl": mark["amount"] if mark else None,
                "unrealized_net_pnl": net_mark,
                "unrealized_cash_pnl": (
                    net_mark + ledger["entry_commission"] * remaining / original
                    if net_mark is not None and ledger.get("entry_cash_posted")
                    else net_mark
                ),
                "current_r": (
                    net_mark / ledger["initial_risk_account"]
                    if net_mark is not None and ledger["initial_risk_account"] > 0
                    else None
                ),
                "remaining_quantity_lots": remaining,
                "source": quote.source,
                "conversion": mark,
                "mark_policy": "Observed quote and modeled slippage; liquidation liquidity is not guaranteed.",
            }
            stop = (
                quote.bid <= position.stop_price
                if side == ForexDirection.LONG
                else quote.ask >= position.stop_price
            )
            target = (
                quote.bid >= position.target_price
                if side == ForexDirection.LONG
                else quote.ask <= position.target_price
            )
            reason = ledger.get("exit_reason") or (
                "STOP_HIT"
                if stop
                else (
                    "TARGET_HIT"
                    if target
                    else (
                        "TIME_STOP"
                        if (now - position.opened_at).total_seconds()
                        >= contract.get("expected_holding_minutes", 30) * 60
                        else None
                    )
                )
            )
            stamp = quote.timestamp.isoformat()
            if reason and stamp != ledger.get("last_exit_quote_at"):
                fill = execution.close(request, quote, broker, reason=reason, now=now)
                ledger["last_exit_attempt"] = {
                    "at": now.isoformat(),
                    "status": fill.status,
                    "reason": fill.rejection_reason,
                }
                if (
                    fill.status in {"FILLED", "PARTIALLY_FILLED"}
                    and fill.fill_price is not None
                    and fill.filled_quantity_lots > 0
                ):
                    quantity = min(remaining, fill.filled_quantity_lots)
                    allocated_swap = ledger["swap_remaining"] * quantity / remaining
                    ledger["closes"].append(
                        {
                            "at": now.isoformat(),
                            "quote_at": stamp,
                            "provider": quote.source,
                            "quantity_lots": quantity,
                            "price": fill.fill_price,
                            "gross_quote": (fill.fill_price - position.entry_price)
                            * 100_000
                            * quantity
                            * (1 if side == ForexDirection.LONG else -1),
                            "entry_commission": ledger["entry_commission"]
                            * quantity
                            / original,
                            "exit_commission": fill.commission,
                            "swap": allocated_swap,
                            "conversion": None,
                        }
                    )
                    ledger["swap_remaining"] -= allocated_swap
                    ledger["remaining_quantity_lots"] = max(0.0, remaining - quantity)
                    ledger["exit_reason"] = reason
                    ledger["last_exit_quote_at"] = stamp
                    margin_released = position.margin_used * quantity / remaining
                    position.margin_used = max(
                        0.0, position.margin_used - margin_released
                    )
                    position.commission += fill.commission
                    if fill.spread_cost is not None:
                        position.spread_cost += fill.spread_cost
                    if fill.slippage_cost is not None:
                        position.slippage_cost += fill.slippage_cost
                    total = sum(row["quantity_lots"] for row in ledger["closes"])
                    position.exit_price = (
                        sum(
                            row["price"] * row["quantity_lots"]
                            for row in ledger["closes"]
                        )
                        / total
                    )
                    position.exit_reason = reason
                    if ledger["remaining_quantity_lots"] <= 1e-9:
                        position.closed_at = now
        for row in ledger["closes"]:
            if row["conversion"] is None:
                row["conversion"] = convert_cash(
                    row["gross_quote"], config.quote_currency, currency, quotes, now=now
                )
        settled = [row for row in ledger["closes"] if row["conversion"] is not None]
        position.gross_pnl = sum(row["conversion"]["amount"] for row in settled)
        position.net_pnl = sum(
            row["conversion"]["amount"]
            - row["entry_commission"]
            - row["exit_commission"]
            + row["swap"]
            for row in settled
        )
        cash_net = (
            (
                sum(row["conversion"]["amount"] for row in settled)
                - ledger["entry_commission"]
                - sum(row["exit_commission"] for row in ledger["closes"])
                + position.swap_accrued
            )
            if ledger.get("entry_cash_posted")
            else position.net_pnl
        )
        delta = cash_net - ledger.get("posted_net", 0)
        ledger["posted_net"] = cash_net
        ledger["reconciled"] = len(settled) == len(ledger["closes"]) and bool(settled)
        ledger["explicit_costs"] = sum(
            row["entry_commission"] + row["exit_commission"] - row["swap"]
            for row in settled
        )
        if ledger["remaining_quantity_lots"] <= 1e-9:
            position.status = "CLOSED" if ledger["reconciled"] else "SETTLEMENT_PENDING"
            if position.status == "CLOSED":
                ledger["settled_at"] = now.isoformat()
                position.realized_r = (
                    position.net_pnl / ledger["initial_risk_account"]
                    if ledger["initial_risk_account"] > 0
                    else None
                )
        position.contract_json = contract
        return {
            "completed": position.status == "CLOSED",
            "cash_delta": delta,
            "margin_released": margin_released,
            "exited_now": was_open and ledger["remaining_quantity_lots"] <= 1e-9,
        }

    def apply_fill(
        self,
        db,
        *,
        fill_uid: str,
        position_id: int,
        delta_lots: float,
        executed_price: float,
        commission: float,
        conversion: dict,
    ) -> dict:
        from sqlalchemy import select, desc
        from app.models import ForexPosition, LiveForwardPaperGame

        position = db.scalar(
            select(ForexPosition)
            .where(ForexPosition.id == position_id)
            .with_for_update()
        )
        contract = deepcopy(position.contract_json)
        ledger = contract.get("accounting") or {}
        if fill_uid in ledger.get("applied_fill_uids", []):
            return {"applied": False}
        if (
            delta_lots <= 0
            or executed_price <= 0
            or conversion.get("rate", 0) <= 0
            or not conversion.get("at")
        ):
            raise ValueError("INVALID_FILL_ACCOUNTING")
        previous = float(position.quantity_lots or 0)
        total = previous + delta_lots
        position.entry_price = (
            position.entry_price * previous + executed_price * delta_lots
        ) / total
        position.quantity_lots = total
        position.current_price = executed_price
        position.commission += commission
        position.margin_used += conversion["margin_required"]
        ledger = {
            **ledger,
            "version": VERSION,
            "original_quantity_lots": total,
            "remaining_quantity_lots": total,
            "entry_commission": ledger.get("entry_commission", 0) + commission,
            "initial_risk_account": ledger.get("initial_risk_account", 0)
            + conversion["risk_account"],
            "initial_margin": ledger.get("initial_margin", 0)
            + conversion["margin_required"],
            "entry_notional_account": ledger.get("entry_notional_account", 0)
            + conversion["notional_account"],
            "closes": ledger.get("closes", []),
            "posted_net": ledger.get("posted_net", 0) - commission,
            "entry_cash_posted": True,
            "swap_remaining": ledger.get("swap_remaining", 0),
            "swap_date": ledger.get("swap_date", position.opened_at.date().isoformat()),
            "applied_fill_uids": [*ledger.get("applied_fill_uids", []), fill_uid],
            "entry_conversions": [*ledger.get("entry_conversions", []), conversion],
        }
        position.contract_json = {**contract, "accounting": ledger}
        game = (
            db.scalar(
                select(LiveForwardPaperGame)
                .where(LiveForwardPaperGame.game_id == contract["account_id"])
                .with_for_update()
            )
            if contract.get("account_id")
            else db.scalar(
                select(LiveForwardPaperGame)
                .where(LiveForwardPaperGame.status == "active")
                .order_by(desc(LiveForwardPaperGame.started_at))
                .limit(1)
                .with_for_update()
            )
        )
        if (
            game
            and (game.configuration or {}).get("account_currency", "EUR")
            == contract["account_currency"]
        ):
            game.cash -= conversion["margin_required"] + commission
            game.current_capital -= commission
            game.realized_pl -= commission
            game.exposure += conversion["margin_required"]
            game.open_positions += int(previous == 0)
        db.flush()
        return {"applied": True, "quantity_lots": total}

    def reconcile(self, db, *, account_id: str, as_of: datetime) -> dict:
        from sqlalchemy import select
        from app.models import ForexPosition, LiveForwardPaperGame

        game = db.scalar(
            select(LiveForwardPaperGame).where(
                LiveForwardPaperGame.game_id == account_id
            )
        )
        if game is None:
            return {"status": "ACCOUNT_UNAVAILABLE", "nav": None}
        currency = (game.configuration or {}).get("account_currency", "EUR")
        positions = db.scalars(
            select(ForexPosition).where(
                ForexPosition.status.in_(["OPEN", "SETTLEMENT_PENDING"])
            )
        ).all()
        marks = []
        for position in positions:
            contract = position.contract_json or {}
            if (
                contract.get("account_currency") != currency
                or contract.get("account_id") != account_id
            ):
                continue
            value = contract.get("valuation") or {}
            if (
                position.status == "SETTLEMENT_PENDING"
                or value.get("unrealized_cash_pnl") is None
            ):
                return {"status": "INCOMPLETE_MARKS", "nav": None}
            stamp = datetime.fromisoformat(value["timestamp"])
            if not 0 <= (_utc(as_of) - _utc(stamp)).total_seconds() <= 180:
                return {"status": "STALE_MARKS", "nav": None}
            marks.append(value["unrealized_cash_pnl"])
        return {
            "status": "RECONCILED",
            "nav": game.cash + game.exposure + sum(marks),
            "cash": game.cash,
            "reserved_margin": game.exposure,
            "unrealized": sum(marks),
        }

    def margin_state(
        self, db, *, account_id: str, quotes: dict, broker, now: datetime
    ) -> dict:
        """Broker mark-to-quote equity; liquidation still obeys actual fill capacity."""
        from sqlalchemy import select
        from app.models import (
            ForexPosition,
            LiveForwardPaperGame,
            LiveForwardPaperTrade,
        )

        game = db.scalar(
            select(LiveForwardPaperGame).where(
                LiveForwardPaperGame.game_id == account_id
            )
        )
        if game is None:
            return {"status": "ACCOUNT_UNAVAILABLE", "breached": False}
        if db.scalar(
            select(LiveForwardPaperTrade.id)
            .where(
                LiveForwardPaperTrade.game_id == game.id,
                LiveForwardPaperTrade.status == "OPEN",
            )
            .limit(1)
        ):
            return {"status": "MIXED_ACCOUNT_MARKS_REQUIRED", "breached": False}
        equity = float(game.current_capital)
        used_margin = 0.0
        for position in db.scalars(
            select(ForexPosition).where(ForexPosition.status == "OPEN")
        ):
            contract = position.contract_json or {}
            if contract.get("account_id") != account_id:
                continue
            quote = quotes.get(position.pair)
            if not fresh(quote, now):
                return {"status": "QUOTE_UNAVAILABLE", "breached": False}
            ledger = contract["accounting"]
            remaining = ledger["remaining_quantity_lots"]
            price = quote.bid if position.direction == "LONG" else quote.ask
            gross = (
                (price - position.entry_price)
                * 100_000
                * remaining
                * (1 if position.direction == "LONG" else -1)
            )
            converted = convert_cash(
                gross,
                pair_config(position.pair).quote_currency,
                contract["account_currency"],
                quotes,
                now=now,
            )
            if converted is None:
                return {"status": "CONVERSION_UNAVAILABLE", "breached": False}
            equity += converted["amount"] + ledger["swap_remaining"]
            if not ledger.get("entry_cash_posted"):
                equity -= (
                    ledger["entry_commission"]
                    * remaining
                    / ledger["original_quantity_lots"]
                )
            used_margin += position.margin_used
        return {
            "status": "KNOWN",
            "equity": equity,
            "used_margin": used_margin,
            "breached": used_margin > 0
            and equity / used_margin <= broker.stop_out_level,
        }
