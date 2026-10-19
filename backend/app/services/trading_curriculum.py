"""Frozen, long-only research episodes. No broker authority or native P/L writes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import math
import random
from types import SimpleNamespace
from app.services.market_bar_clock import available_at, session_start

import numpy as np

from app.services.executable_strategy import (
    canonical_strategy_spec,
    StrategySignalEvaluator,
)
from app.services.realistic_execution import (
    ExecutionMarketBar,
    ExecutionOrderRequest,
    RealisticExecutionEngine,
)

VERSION = "curriculum-v1"
COST_VERSION = "curriculum-limit-collar-v1"
WARMUP = 60
BLOCK = 96
CAPITAL = 10_000.0
COMMISSION_BPS = 1.0
HOLD = 12


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def valid_bar(bar: dict) -> bool:
    try:
        o, h, l, c, v = (
            float(bar[k]) for k in ("open", "high", "low", "close", "volume")
        )
        return (
            all(math.isfinite(x) for x in (o, h, l, c, v))
            and 0 < l <= min(o, c) <= max(o, c) <= h
            and v >= 0
            and bar["start"] < bar["available"]
        )
    except (KeyError, TypeError, ValueError):
        return False


def catalogue(timeframe: str, market: str):
    # Explicit single-frame adaptations, not replicas of the multi-frame originals.
    families = ("swing_breakout", "intraday_trend", "mean_reversion", "pullback")
    return tuple(
        replace(
            canonical_strategy_spec(family),
            setup_type=f"curriculum_{family}_v1",
            required_timeframes=(timeframe,),
            execution_timeframe=timeframe,
            lookback=lookback,
            minimum_relative_volume=0.0,
            minimum_stop_percent=0.0005 if market == "FOREX" else 0.005,
            stop_atr_multiple=1.5,
            maximum_holding_bars=HOLD,
        )
        for family in families
        for lookback in (10, 30)
    )


def partition(count: int) -> dict:
    train_end, dev_end = int(count * 0.6), int(count * 0.8)
    return dict(
        train_end=train_end,
        development_start=train_end + HOLD + 2,
        development_end=dev_end,
        confirmation_start=dev_end + HOLD + 2,
        confirmation_end=count,
    )


def training_windows(count: int, seed: int) -> list[tuple[int, int]]:
    windows = [
        (i, i + BLOCK)
        for i in range(WARMUP, partition(count)["train_end"] - BLOCK + 1, BLOCK)
    ]
    random.Random(seed).shuffle(windows)
    return windows


class Selector:
    """Per-expert ridge sufficient statistics; bounded net-R targets, no probability claim."""

    def __init__(self, payload: dict):
        self.state = deepcopy(payload)

    def score(self, expert: str, context: list[float]) -> float:
        entry = self.state.get(expert)
        if not entry or entry["n"] < 5:
            return 0.0  # frozen seeded ordering until there are outcomes
        a = np.asarray(entry["a"]) + np.eye(5) * 0.1
        return float(np.dot(np.linalg.solve(a, np.asarray(entry["b"])), context))

    def learn(self, expert: str, context: list[float], net_r: float):
        entry = self.state.setdefault(
            expert, dict(a=np.zeros((5, 5)).tolist(), b=[0.0] * 5, n=0)
        )
        x = np.asarray(context)
        entry["a"] = (np.asarray(entry["a"]) + np.outer(x, x)).tolist()
        entry["b"] = (np.asarray(entry["b"]) + x * max(-5, min(5, net_r))).tolist()
        entry["n"] += 1

    def payload(self):
        return deepcopy(self.state)


def merge_models(historical: dict, live: dict) -> dict:
    result = deepcopy(historical)
    for expert, entry in live.items():
        prior = result.get(expert)
        result[expert] = (
            deepcopy(entry)
            if prior is None
            else dict(
                a=(np.asarray(prior["a"]) + np.asarray(entry["a"])).tolist(),
                b=(np.asarray(prior["b"]) + np.asarray(entry["b"])).tolist(),
                n=prior["n"] + entry["n"],
            )
        )
    return result


def features(history: list[dict]) -> list[float]:
    closes = [float(b["close"]) for b in history[-30:]]
    current = closes[-1]
    returns = np.diff(closes) / np.asarray(closes[:-1])
    return [
        1.0,
        max(-1, min(1, (current / closes[-6] - 1) * 20)),
        max(-1, min(1, (current / closes[-21] - 1) * 10)),
        min(1, float(np.std(returns)) * 100),
        min(
            1,
            float(np.mean([(b["high"] - b["low"]) / b["close"] for b in history[-20:]]))
            * 50,
        ),
    ]


def propose(
    history: list[dict],
    *,
    market: str,
    timeframe: str,
    model: Selector,
    decision_at: datetime,
    expert=None,
) -> dict | None:
    closed = [
        b
        for b in history
        if valid_bar(b) and datetime.fromisoformat(b["available"]) <= decision_at
    ]
    if len(closed) < WARMUP:
        return None
    context = features(closed)
    rows = [
        SimpleNamespace(
            **{k: b[k] for k in ("open", "high", "low", "close", "volume")},
            bar_timestamp=datetime.fromisoformat(b["available"]),
        )
        for b in closed[-WARMUP:]
    ]
    evaluator = StrategySignalEvaluator()
    spec = expert or max(
        catalogue(timeframe, market), key=lambda s: model.score(s.fingerprint, context)
    )
    evaluation = evaluator.evaluate(
        spec, {timeframe: rows}, as_of=decision_at, market=market
    )
    if evaluation.status != "triggered":
        return None
    geometry = evaluator.geometry(
        spec, entry_price=closed[-1]["close"], execution_history=rows
    )
    if geometry.stop_price <= 0:
        return None
    return dict(
        version=VERSION,
        cost_version=COST_VERSION,
        expert=spec.fingerprint,
        strategy=spec.to_payload(),
        context=context,
        decision_at=decision_at.isoformat(),
        feature_latest=closed[-1]["available"],
        input_hash=digest(closed[-WARMUP:]),
        model_hash=digest(model.payload()),
        entry=geometry.entry_price,
        stop=geometry.stop_price,
        target=geometry.target_price,
        limit=geometry.entry_price * 1.001,
        maximum_holding_bars=HOLD,
        entry_volatility_bps=float(
            np.mean(
                [(b["high"] - b["low"]) / b["close"] * 10_000 for b in closed[-20:]]
            )
        ),
    )


def _execution_bar(bar: dict, *, closed: bool = False) -> ExecutionMarketBar:
    volatility = (bar["high"] - bar["low"]) / bar["close"] * 10_000
    return ExecutionMarketBar(
        timestamp=datetime.fromisoformat(bar["available"] if closed else bar["start"]),
        open=bar["open"],
        high=bar["high"],
        low=bar["low"],
        close=bar["close"],
        volume=bar["volume"],
        spread_bps=max(2, min(25, volatility * 0.03)),
        volatility_bps=volatility,
    )


def resolve(
    proposal: dict,
    future: list[dict],
    *,
    market: str,
    complete: bool,
    cash: float = CAPITAL,
) -> dict | None:
    eligible = [
        b for b in future if valid_bar(b) and b["start"] > proposal["decision_at"]
    ]
    if not eligible:
        return None
    first = eligible[0]
    base = {**proposal, "cash_before": cash}
    # Cancel at the first later open, before consulting that bar's high/low/close.
    if not proposal["stop"] < first["open"] <= proposal["limit"]:
        return {**base, "status": "UNFILLED", "reason": "OPEN_OUTSIDE_ENTRY_COLLAR"}
    quantity = min(
        cash * 0.005 / max(proposal["entry"] - proposal["stop"], 0.00000001),
        cash / (proposal["limit"] * (1 + COMMISSION_BPS / 10_000)),
    )
    engine = RealisticExecutionEngine()
    request = ExecutionOrderRequest(
        order_key=digest(proposal),
        ticker="curriculum",
        side="BUY",
        order_type="LIMIT",
        decision_timestamp=datetime.fromisoformat(proposal["decision_at"]),
        theoretical_price=proposal["entry"],
        quantity=quantity,
        limit_price=proposal["limit"],
        commission_bps=COMMISSION_BPS,
        liquidity_basis=(
            "otc_quote_capacity" if market == "FOREX" else "reported_volume"
        ),
        quote_capacity_units=100_000 if market == "FOREX" else None,
    )
    opening = _execution_bar(first)
    prior_volatility = proposal["entry_volatility_bps"]
    opening = replace(
        opening,
        volatility_bps=prior_volatility,
        spread_bps=max(2, min(25, prior_volatility * 0.03)),
    )
    entry = engine.evaluate(request, [opening])
    if entry.filled_quantity <= 0:
        return {**base, "status": "UNFILLED", "reason": entry.reason}
    price, quantity = entry.average_fill_price, entry.filled_quantity
    entry_data = dict(
        entry_at=first["start"],
        entry_price=price,
        quantity=quantity,
        entry_notional=price * quantity,
        entry_commission=entry.costs.commission_cost,
        cash_after_entry=cash - price * quantity - entry.costs.commission_cost,
    )
    observed = eligible[:HOLD]
    exit_result = engine.evaluate_exit(
        side="LONG",
        quantity=quantity,
        entry_price=price,
        stop_price=proposal["stop"],
        target_price=proposal["target"],
        decision_timestamp=datetime.fromisoformat(first["start"]),
        bars=[_execution_bar(b, closed=True) for b in observed],
        commission_bps=COMMISSION_BPS,
    )
    if exit_result.status != "CLOSED":
        if not complete and len(observed) < HOLD:
            return {**base, **entry_data, "status": "OPEN"}
        last = observed[-1]
        bar = _execution_bar(last, closed=True)
        close_bar = replace(bar, open=bar.close, high=bar.close, low=bar.close)
        exit_result = engine.evaluate(
            ExecutionOrderRequest(
                "time-exit",
                "curriculum",
                "SELL",
                "MARKET",
                datetime.fromisoformat(first["start"]),
                price,
                quantity,
                commission_bps=COMMISSION_BPS,
                liquidity_basis=request.liquidity_basis,
                quote_capacity_units=request.quote_capacity_units,
            ),
            [close_bar],
        )
    if exit_result.filled_quantity < quantity:
        # Exit capacity is not a verified broker fill. Never manufacture missing units.
        return {
            **base,
            **entry_data,
            "status": "BLOCKED",
            "reason": "EXIT_CAPACITY_UNAVAILABLE",
        }
    exit_bar = next(
        b
        for b in observed
        if b["available"] == exit_result.fills[-1].timestamp.isoformat()
    )
    capacity = (exit_bar["volume"] or (100_000 if market == "FOREX" else 0)) * 0.05
    if quantity > capacity + 1e-8:
        return {
            **base,
            **entry_data,
            "status": "BLOCKED",
            "reason": "EXIT_CAPACITY_UNVERIFIED",
        }
    exit_price = exit_result.average_fill_price
    pnl = (
        quantity * (exit_price - price)
        - entry.costs.commission_cost
        - exit_result.costs.commission_cost
    )
    initial_risk = quantity * (proposal["entry"] - proposal["stop"])
    return {
        **base,
        "status": "CLOSED",
        "entry_at": first["start"],
        "exit_at": exit_result.fills[-1].timestamp.isoformat(),
        "entry_price": price,
        "exit_price": exit_price,
        "quantity": quantity,
        "entry_notional": price * quantity,
        "entry_commission": entry.costs.commission_cost,
        "exit_commission": exit_result.costs.commission_cost,
        "cash_after_entry": cash - price * quantity - entry.costs.commission_cost,
        "pnl": pnl,
        "net_r": pnl / initial_risk if initial_risk > 0 else 0,
        "reason": exit_result.reason,
    }


def metrics(trades: list[dict], capital: float = CAPITAL) -> dict:
    closed = [t for t in trades if t["status"] == "CLOSED"]
    wins = sum(t["pnl"] > 0 for t in closed)
    n = len(closed)
    p = wins / n if n else 0
    z = 1.96
    center = (p + z * z / (2 * n)) / (1 + z * z / n) if n else 0
    half = (
        z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        if n
        else 0
    )
    gain = sum(max(0, t["pnl"]) for t in closed)
    loss = sum(max(0, -t["pnl"]) for t in closed)
    equity = peak = capital
    drawdown = 0.0
    for trade in closed:
        equity += trade["pnl"]
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
    return dict(
        trade_count=n,
        win_rate=p if n else None,
        win_rate_interval=[max(0, center - half), min(1, center + half)] if n else None,
        net_return=(
            None
            if any(t["status"] == "BLOCKED" for t in trades)
            else equity / capital - 1
        ),
        blocked_count=sum(t["status"] == "BLOCKED" for t in trades),
        max_closed_trade_drawdown=drawdown,
        profit_factor=gain / loss if loss else None,
        expectancy_r=sum(t["net_r"] for t in closed) / n if n else None,
        minimum_cash=min([capital] + [t["cash_after_entry"] for t in closed]),
        unfilled_count=sum(t["status"] == "UNFILLED" for t in trades),
        trades=trades,
    )


def simulate(
    bars: list[dict],
    *,
    market: str,
    timeframe: str,
    start: int,
    end: int,
    model: Selector | None = None,
    expert=None,
) -> dict:
    model = model or Selector({})
    trades, cash, i = [], CAPITAL, start
    while i < min(end, len(bars)) - 2:
        proposal = propose(
            bars[max(0, i - WARMUP + 1) : i + 1],
            market=market,
            timeframe=timeframe,
            model=model,
            decision_at=datetime.fromisoformat(bars[i]["available"]),
            expert=expert,
        )
        if not proposal or cash <= 0:
            i += 1
            continue
        trade = resolve(
            proposal,
            bars[i + 1 : min(end, len(bars))],
            market=market,
            complete=True,
            cash=cash,
        )
        if trade is None:
            break
        trades.append(trade)
        if trade["status"] == "CLOSED":
            cash += trade["pnl"]
            exit_at = trade["exit_at"]
            i = (
                next(
                    (j for j in range(i + 1, end) if bars[j]["available"] >= exit_at),
                    end,
                )
                + 1
            )
        elif trade["status"] == "BLOCKED":
            break
        else:
            i += 2
    return metrics(trades)
