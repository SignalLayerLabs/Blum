from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
import time
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset, HyperbolicReplayRun, HyperbolicReplayTrade, ReplayMarketBar
from app.services.replay_data import MultiProviderReplayDataService
from app.services.replay_execution import ReplayExecutionModel, ReplayPositionSizer
from app.services.executable_strategy import (
    ExecutableStrategySpec,
    StrategySignalEvaluator,
    canonical_strategy_spec,
)


TIMEFRAME_ORDER = ("1d", "1h", "15m", "5m", "1m")
SETUP_REQUIREMENTS = {
    "intraday_breakout": ("1d", "15m", "5m", "1m"),
    "intraday_trend": ("1d", "15m", "5m", "1m"),
    "mean_reversion": ("15m", "5m"),
    "pullback": ("1d", "15m"),
    "swing_breakout": ("1d",),
}
SETUP_EXECUTION_TIMEFRAME = {
    "intraday_breakout": "1m",
    "intraday_trend": "5m",
    "mean_reversion": "5m",
    "pullback": "15m",
    "swing_breakout": "1d",
}
SETUP_PRIORITY = ("intraday_breakout", "intraday_trend", "mean_reversion", "pullback", "swing_breakout")
BENCHMARK_BY_MARKET = {
    "USA": "SPY",
    "US": "SPY",
    "UNITED STATES": "SPY",
    "ITALY": "FEZ",
    "GERMANY": "FEZ",
    "FRANCE": "FEZ",
    "EUROPE": "FEZ",
    "FOREX": "UUP",
    "FX": "UUP",
}


@dataclass(frozen=True)
class ReplayRunRequest:
    asset_ids: list[int] | None = None
    markets: list[str] | None = None
    timeframes: tuple[str, ...] = ("1d", "15m", "5m", "1m")
    max_assets: int = 10
    max_trades: int = 100
    max_seconds: float = 120.0
    start: datetime | None = None
    end: datetime | None = None
    fetch_missing: bool = True
    trigger: str = "manual"
    capital: float = 10_000.0
    after_asset_id: int | None = None
    priority_markets: tuple[str, ...] = ()
    market_cursors: dict[str, int] | None = None
    strategy_specs: tuple[dict, ...] | None = None


@dataclass(frozen=True)
class ReplayAssetSelection:
    assets: list[Asset]
    next_asset_id: int | None
    market_cursors: dict[str, int]


class BlumHyperbolicReplayEngine:
    def __init__(
        self,
        *,
        data_service: MultiProviderReplayDataService | None = None,
        execution_model: ReplayExecutionModel | None = None,
        position_sizer: ReplayPositionSizer | None = None,
    ):
        self.data_service = data_service or MultiProviderReplayDataService()
        self.execution_model = execution_model or ReplayExecutionModel()
        self.position_sizer = position_sizer or ReplayPositionSizer()
        self.signal_evaluator = StrategySignalEvaluator()

    def run_cycle(self, db: Session, request: ReplayRunRequest) -> dict:
        started = time.perf_counter()
        now = datetime.utcnow()
        run = HyperbolicReplayRun(
            run_id=f"replay-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            trigger=request.trigger,
            status="RUNNING",
            evidence_type="REPLAY_EVIDENCE",
            adaptive_state="RUNNING",
            started_at=now,
            resource_limits_json={
                "max_assets": max(1, request.max_assets),
                "max_trades": max(1, request.max_trades),
                "max_seconds": max(1.0, request.max_seconds),
            },
        )
        db.add(run)
        db.flush()
        selection = self._asset_selection(db, request)
        assets = selection.assets
        blockers: list[dict] = []
        used_timeframes: set[str] = set()
        markets: set[str] = set()
        generated = 0
        validated = 0
        for asset_index, asset in enumerate(assets):
            if generated >= request.max_trades or time.perf_counter() - started >= request.max_seconds:
                break
            markets.add(asset.country or asset.exchange or "UNKNOWN")
            available = self._available_timeframes(db, asset, request, blockers)
            used_timeframes.update(available)
            eligible_specs = self._eligible_strategy_specs(request, available)
            if not eligible_specs:
                blockers.append({"ticker": asset.ticker, "code": "COVERAGE_INCOMPLETE", "timeframe": "all"})
                continue
            bars_by_available_timeframe = {
                timeframe: self._bars(db, asset.id, timeframe, request)
                for timeframe in available
            }
            remaining_assets = len(assets) - asset_index
            asset_budget = max(1, ceil((request.max_trades - generated) / remaining_assets))
            asset_generated = 0
            for setup_index, strategy_spec in enumerate(eligible_specs):
                if (
                    generated >= request.max_trades
                    or asset_generated >= asset_budget
                    or time.perf_counter() - started >= request.max_seconds
                ):
                    break
                bars_by_timeframe = {
                    timeframe: bars_by_available_timeframe[timeframe]
                    for timeframe in strategy_spec.required_timeframes
                }
                bars = bars_by_timeframe[strategy_spec.execution_timeframe]
                remaining_setups = len(eligible_specs) - setup_index
                setup_budget = max(1, ceil((asset_budget - asset_generated) / remaining_setups))
                trades = self._replay_asset(
                    db,
                    run,
                    asset,
                    bars,
                    bars_by_timeframe,
                    strategy_spec,
                    min(setup_budget, request.max_trades - generated),
                    request.capital,
                )
                if not trades:
                    blockers.append(
                        {
                            "ticker": asset.ticker,
                            "code": "NO_NEW_REPLAY_EVIDENCE",
                            "timeframe": strategy_spec.execution_timeframe,
                            "setup_type": strategy_spec.setup_type,
                            "strategy_fingerprint": strategy_spec.fingerprint,
                        }
                    )
                asset_generated += len(trades)
                generated += len(trades)
                validated += sum(1 for trade in trades if trade.state == "REPLAY_EVALUATED")
        duration = time.perf_counter() - started
        run.assets_selected = len(assets)
        run.trades_generated = generated
        run.trades_validated = validated
        run.status = "COMPLETED" if generated else "DATA_BLOCKED"
        run.completed_at = datetime.utcnow()
        run.duration_seconds = round(duration, 4)
        run.markets_json = sorted(markets)
        run.timeframes_json = [timeframe for timeframe in TIMEFRAME_ORDER if timeframe in used_timeframes]
        run.blockers_json = blockers
        run.summary_json = {
            "lookahead_violations": 0,
            "evidence_type": "REPLAY_EVIDENCE",
            "policy": "Features use closed bars at or before the decision timestamp; entries use a later executable bar.",
        }
        next_cursor = {}
        if selection.next_asset_id is not None:
            next_cursor["asset_id"] = selection.next_asset_id
        if selection.market_cursors:
            next_cursor["market_cursors"] = selection.market_cursors
        run.cursor_json = next_cursor
        db.commit()
        return {
            "status": run.status,
            "run_id": run.run_id,
            "assets_selected": [asset.ticker for asset in assets],
            "markets_selected": sorted(markets),
            "timeframes_used": run.timeframes_json,
            "trades_generated": generated,
            "trades_validated": validated,
            "experiments_run": 0,
            "strategies_promoted": 0,
            "strategies_rejected": 0,
            "runtime_seconds": run.duration_seconds,
            "resource_limits_applied": run.resource_limits_json,
            "blockers": blockers,
            "lookahead_violations": 0,
            "next_cursor": next_cursor,
            "next_action": "Continue bounded replay coverage and walk-forward validation." if generated else "Acquire verified OHLCV coverage for eligible assets.",
            "strategy_fingerprints": sorted(
                {
                    ExecutableStrategySpec.from_payload(payload).fingerprint
                    for payload in (request.strategy_specs or ())
                }
            ),
        }

    @staticmethod
    def _eligible_strategy_specs(
        request: ReplayRunRequest,
        available: set[str],
    ) -> list[ExecutableStrategySpec]:
        if request.strategy_specs:
            requested = [ExecutableStrategySpec.from_payload(payload) for payload in request.strategy_specs]
        else:
            requested = [canonical_strategy_spec(setup_type) for setup_type, _ in _eligible_setups(available)]
        return [
            spec
            for spec in requested
            if set(spec.required_timeframes).issubset(available)
        ]

    @staticmethod
    def _assets(db: Session, request: ReplayRunRequest) -> list[Asset]:
        return BlumHyperbolicReplayEngine._asset_selection(db, request).assets

    @staticmethod
    def _asset_selection(db: Session, request: ReplayRunRequest) -> ReplayAssetSelection:
        max_assets = max(1, request.max_assets)
        requested_markets = {str(market).strip().upper() for market in (request.markets or []) if str(market).strip()}
        priority_markets = tuple(
            market
            for market in dict.fromkeys(str(value).strip().upper() for value in request.priority_markets)
            if market and (not requested_markets or market in requested_markets)
        )[:max_assets]

        if request.asset_ids or not priority_markets:
            rows = BlumHyperbolicReplayEngine._cursor_assets(db, request, limit=max_assets)
            next_asset_id = rows[-1].id if len(rows) >= max_assets else None
            return ReplayAssetSelection(assets=rows, next_asset_id=next_asset_id, market_cursors={})

        base_limit = max(0, max_assets - len(priority_markets))
        base_query = select(Asset).where(Asset.is_active.is_(True))
        if request.markets:
            base_query = base_query.where(func.upper(Asset.country).in_(requested_markets))
        base_query = base_query.where(~func.upper(Asset.country).in_(priority_markets))
        if request.after_asset_id is not None:
            base_query = base_query.where(Asset.id > request.after_asset_id)
        base_rows = db.scalars(base_query.order_by(Asset.id).limit(base_limit)).all() if base_limit else []
        if not base_rows and request.after_asset_id is not None and base_limit:
            restart = select(Asset).where(
                Asset.is_active.is_(True),
                ~func.upper(Asset.country).in_(priority_markets),
            )
            if request.markets:
                restart = restart.where(func.upper(Asset.country).in_(requested_markets))
            base_rows = db.scalars(restart.order_by(Asset.id).limit(base_limit)).all()

        market_cursors = dict(request.market_cursors or {})
        priority_rows: list[Asset] = []
        for market in priority_markets:
            query = select(Asset).where(
                Asset.is_active.is_(True),
                func.upper(Asset.country) == market,
            )
            market_cursor = market_cursors.get(market)
            if market_cursor is not None:
                query = query.where(Asset.id > market_cursor)
            row = db.scalar(query.order_by(Asset.id).limit(1))
            if row is None and market_cursor is not None:
                row = db.scalar(
                    select(Asset)
                    .where(Asset.is_active.is_(True), func.upper(Asset.country) == market)
                    .order_by(Asset.id)
                    .limit(1)
                )
            if row is not None:
                priority_rows.append(row)
                market_cursors[market] = row.id

        return ReplayAssetSelection(
            assets=[*base_rows, *priority_rows],
            next_asset_id=base_rows[-1].id if base_limit and len(base_rows) >= base_limit else None,
            market_cursors=market_cursors,
        )

    @staticmethod
    def _cursor_assets(db: Session, request: ReplayRunRequest, *, limit: int) -> list[Asset]:
        query = select(Asset).where(Asset.is_active.is_(True))
        if request.asset_ids:
            query = query.where(Asset.id.in_(request.asset_ids))
        if request.markets:
            query = query.where(func.upper(Asset.country).in_([market.upper() for market in request.markets]))
        if request.after_asset_id is not None:
            query = query.where(Asset.id > request.after_asset_id)
        rows = db.scalars(query.order_by(Asset.id).limit(limit)).all()
        if rows or request.after_asset_id is None:
            return rows
        restart = select(Asset).where(Asset.is_active.is_(True))
        if request.asset_ids:
            restart = restart.where(Asset.id.in_(request.asset_ids))
        if request.markets:
            restart = restart.where(func.upper(Asset.country).in_([market.upper() for market in request.markets]))
        return db.scalars(restart.order_by(Asset.id).limit(limit)).all()

    def _available_timeframes(self, db: Session, asset: Asset, request: ReplayRunRequest, blockers: list[dict]) -> set[str]:
        available: set[str] = set()
        end = request.end or datetime.utcnow()
        for timeframe in request.timeframes:
            start = request.start or end - (timedelta(days=365 * 5) if timeframe == "1d" else timedelta(days=365))
            count = len(self._bars(db, asset.id, timeframe, request))
            if count < 22 and request.fetch_missing:
                coverage = self.data_service.ensure_coverage(db, asset=asset, timeframe=timeframe, start=start, end=end)
                count = coverage.rows_available
                for code in coverage.blockers:
                    blockers.append({"ticker": asset.ticker, "code": code, "timeframe": timeframe})
            if count >= 22:
                available.add(timeframe)
            else:
                blockers.append({"ticker": asset.ticker, "code": "COVERAGE_INCOMPLETE", "timeframe": timeframe})
        return available

    @staticmethod
    def _bars(db: Session, asset_id: int, timeframe: str, request: ReplayRunRequest) -> list[ReplayMarketBar]:
        query = select(ReplayMarketBar).where(
            ReplayMarketBar.asset_id == asset_id,
            ReplayMarketBar.timeframe == timeframe,
        )
        if request.start:
            query = query.where(ReplayMarketBar.bar_timestamp >= request.start)
        if request.end:
            query = query.where(ReplayMarketBar.bar_timestamp <= request.end)
        return db.scalars(query.order_by(ReplayMarketBar.bar_timestamp)).all()

    def _replay_asset(
        self,
        db: Session,
        run: HyperbolicReplayRun,
        asset: Asset,
        bars: list[ReplayMarketBar],
        bars_by_timeframe: dict[str, list[ReplayMarketBar]],
        strategy_spec: ExecutableStrategySpec,
        limit: int,
        capital: float,
    ) -> list[HyperbolicReplayTrade]:
        setup_type = strategy_spec.setup_type
        timeframe = strategy_spec.execution_timeframe
        output: list[HyperbolicReplayTrade] = []
        existing_decisions = set(
            db.scalars(
                select(HyperbolicReplayTrade.decision_timestamp).where(
                    HyperbolicReplayTrade.asset_id == asset.id,
                    HyperbolicReplayTrade.strategy_fingerprint == strategy_spec.fingerprint,
                    HyperbolicReplayTrade.timeframe == timeframe,
                )
            ).all()
        )
        timestamps_by_timeframe = {
            timeframe: [row.bar_timestamp for row in timeframe_bars]
            for timeframe, timeframe_bars in bars_by_timeframe.items()
        }
        history_size = max(20, strategy_spec.lookback + 1, strategy_spec.atr_period + 1)
        for index in range(history_size, len(bars) - 1):
            if len(output) >= limit:
                break
            history = bars[max(0, index - history_size) : index]
            decision_bar = bars[index]
            if decision_bar.bar_timestamp in existing_decisions:
                continue
            context = _context_at(
                bars_by_timeframe,
                timestamps_by_timeframe,
                decision_bar.bar_timestamp,
                history_size=history_size,
            )
            signal = self.signal_evaluator.evaluate(
                strategy_spec,
                context,
                as_of=decision_bar.bar_timestamp,
                market=asset.country or asset.exchange,
            )
            if signal.status != "triggered":
                continue
            entry_bar = bars[index + 1]
            theoretical_entry = float(entry_bar.open if entry_bar.open is not None else entry_bar.close)
            geometry = self.signal_evaluator.geometry(
                strategy_spec,
                entry_price=theoretical_entry,
                execution_history=[*history, decision_bar],
            )
            atr = geometry.atr
            stop = geometry.stop_price
            target = geometry.target_price
            liquidity = _liquidity_score(history)
            quality = sum(float(row.data_quality_score or 0.0) for row in history) / len(history)
            profile = self.execution_model.profile(market=asset.country, asset_type=asset.asset_type, liquidity_score=liquidity)
            entry = theoretical_entry * (1 + profile.one_way_bps / 10_000)
            sizing = self.position_sizer.size(
                capital=capital,
                entry=entry,
                stop=stop,
                atr=atr,
                liquidity_score=liquidity,
                confidence=65,
                edge_score=60,
                data_quality=quality,
                regime_alignment=65,
            )
            if sizing.units <= 0:
                continue
            exit_bar, raw_exit, exit_reason = _manage_trade(
                bars,
                index + 1,
                stop,
                target,
                maximum_holding_bars=strategy_spec.maximum_holding_bars,
            )
            exit_price = raw_exit * (1 - profile.one_way_bps / 10_000)
            gross_pnl = (raw_exit - theoretical_entry) * sizing.units
            net_pnl = (exit_price - entry) * sizing.units
            initial_risk = max(0.000001, (entry - stop) * sizing.units)
            benchmark_ticker, benchmark_excess = self._benchmark_excess(
                db,
                market=asset.country or asset.exchange or "UNKNOWN",
                timeframe=timeframe,
                entry_timestamp=entry_bar.bar_timestamp,
                exit_timestamp=exit_bar.bar_timestamp,
                asset_return=(exit_price / entry - 1) * 100,
            )
            trade = HyperbolicReplayTrade(
                run_id=run.id,
                asset_id=asset.id,
                ticker=asset.ticker,
                market=asset.country or asset.exchange or "UNKNOWN",
                setup_type=setup_type,
                strategy_fingerprint=strategy_spec.fingerprint,
                timeframe=timeframe,
                state="REPLAY_EVALUATED",
                evidence_type="REPLAY_EVIDENCE",
                decision_timestamp=decision_bar.bar_timestamp,
                entry_timestamp=entry_bar.bar_timestamp,
                exit_timestamp=exit_bar.bar_timestamp,
                entry_price=round(entry, 6),
                exit_price=round(exit_price, 6),
                stop_price=round(stop, 6),
                target_price=round(target, 6),
                position_size=sizing.units,
                gross_pnl=round(gross_pnl, 6),
                net_pnl=round(net_pnl, 6),
                r_multiple=round(net_pnl / initial_risk, 6),
                benchmark_excess=benchmark_excess,
                data_quality_score=round(quality, 2),
                decision_payload={
                    "feature_bar_timestamps": [row.bar_timestamp.isoformat() for row in history],
                    "context_bar_timestamps": {
                        key: [row.bar_timestamp.isoformat() for row in values]
                        for key, values in context.items()
                    },
                    "signal_bar_timestamp": decision_bar.bar_timestamp.isoformat(),
                    "setup_type": setup_type,
                    "strategy_fingerprint": strategy_spec.fingerprint,
                    "executable_strategy": strategy_spec.to_payload(),
                    "required_timeframes": list(strategy_spec.required_timeframes),
                    "regime": signal.regime,
                    "signal_evidence": signal.evidence,
                    "multi_timeframe_confirmation": {
                        "confirmed": signal.status == "triggered",
                        "trends": signal.higher_timeframe_trends,
                        "blockers": [],
                    },
                    "benchmark_ticker": benchmark_ticker,
                    "benchmark_status": "available" if benchmark_excess is not None else "missing",
                    "state_transitions": [
                        {"state": "REPLAY_CANDIDATE", "timestamp": decision_bar.bar_timestamp.isoformat()},
                        {"state": "REPLAY_OPEN", "timestamp": entry_bar.bar_timestamp.isoformat()},
                        {"state": "REPLAY_CLOSED", "timestamp": exit_bar.bar_timestamp.isoformat()},
                        {"state": "REPLAY_EVALUATED", "timestamp": exit_bar.bar_timestamp.isoformat()},
                    ],
                    "lookahead_policy": "closed_bars_only",
                },
                execution_payload={
                    "cost_profile": profile.to_dict(),
                    "position_sizing": sizing.to_dict(),
                    "theoretical_entry": theoretical_entry,
                    "trade_geometry": {
                        "stop_price": stop,
                        "target_price": target,
                        "trailing_stop": geometry.trailing_stop,
                        "risk_distance": geometry.risk_distance,
                        "atr": geometry.atr,
                    },
                },
                outcome_payload={"exit_reason": exit_reason, "evaluated_after_close": True},
            )
            db.add(trade)
            output.append(trade)
        db.flush()
        return output

    @staticmethod
    def _benchmark_excess(
        db: Session,
        *,
        market: str,
        timeframe: str,
        entry_timestamp: datetime,
        exit_timestamp: datetime,
        asset_return: float,
    ) -> tuple[str, float | None]:
        benchmark_ticker = BENCHMARK_BY_MARKET.get((market or "").upper(), "SPY")
        benchmark = db.scalar(select(Asset).where(Asset.ticker == benchmark_ticker))
        if benchmark is None:
            return benchmark_ticker, None
        entry_bar = db.scalar(
            select(ReplayMarketBar)
            .where(
                ReplayMarketBar.asset_id == benchmark.id,
                ReplayMarketBar.timeframe == timeframe,
                ReplayMarketBar.bar_timestamp <= entry_timestamp,
            )
            .order_by(ReplayMarketBar.bar_timestamp.desc())
            .limit(1)
        )
        exit_bar = db.scalar(
            select(ReplayMarketBar)
            .where(
                ReplayMarketBar.asset_id == benchmark.id,
                ReplayMarketBar.timeframe == timeframe,
                ReplayMarketBar.bar_timestamp <= exit_timestamp,
            )
            .order_by(ReplayMarketBar.bar_timestamp.desc())
            .limit(1)
        )
        if entry_bar is None or exit_bar is None or float(entry_bar.close or 0.0) <= 0:
            return benchmark_ticker, None
        benchmark_return = (float(exit_bar.close) / float(entry_bar.close) - 1) * 100
        return benchmark_ticker, round(asset_return - benchmark_return, 6)


def _choose_setup(available: set[str]) -> tuple[str, str] | None:
    eligible = _eligible_setups(available)
    return eligible[0] if eligible else None


def _eligible_setups(available: set[str]) -> list[tuple[str, str]]:
    eligible: list[tuple[str, str]] = []
    for setup in SETUP_PRIORITY:
        if set(SETUP_REQUIREMENTS[setup]).issubset(available):
            eligible.append((setup, SETUP_EXECUTION_TIMEFRAME[setup]))
    return eligible


def _breakout_signal(history: list[ReplayMarketBar], current: ReplayMarketBar) -> bool:
    prior = [float(row.close) for row in history[-10:]]
    return len(prior) >= 10 and float(current.close) > max(prior)


def _setup_signal(setup_type: str, history: list[ReplayMarketBar], current: ReplayMarketBar) -> bool:
    closes = [float(row.close) for row in history[-20:]]
    if len(closes) < 10:
        return False
    if setup_type == "mean_reversion":
        average = sum(closes) / len(closes)
        deviation = (sum((value - average) ** 2 for value in closes) / len(closes)) ** 0.5
        return float(current.close) < average - max(deviation, average * 0.01)
    if setup_type == "pullback":
        average = sum(closes[-10:]) / 10
        established_uptrend = closes[-1] > closes[0]
        return established_uptrend and float(current.close) <= average * 1.01 and float(current.close) >= average * 0.97
    return _breakout_signal(history, current)


def _context_at(
    bars_by_timeframe: dict[str, list[ReplayMarketBar]],
    timestamps_by_timeframe: dict[str, list[datetime]],
    replay_timestamp: datetime,
    history_size: int = 20,
) -> dict[str, list[ReplayMarketBar]]:
    output: dict[str, list[ReplayMarketBar]] = {}
    for timeframe, bars in bars_by_timeframe.items():
        stop = bisect_right(timestamps_by_timeframe[timeframe], replay_timestamp)
        output[timeframe] = bars[max(0, stop - max(2, history_size)) : stop]
    return output


def _regime(history: list[ReplayMarketBar]) -> str:
    closes = [float(row.close) for row in history[-20:]]
    if len(closes) < 5:
        return "insufficient_data"
    change = closes[-1] / closes[0] - 1 if closes[0] else 0.0
    if change > 0.03:
        return "trend_up"
    if change < -0.03:
        return "trend_down"
    return "range_bound"


def _multi_timeframe_confirmation(
    setup_type: str,
    context: dict[str, list[ReplayMarketBar]],
    execution_timeframe: str,
) -> dict:
    trends = {timeframe: _trend_score(rows) for timeframe, rows in context.items()}
    required = SETUP_REQUIREMENTS[setup_type]
    missing_context = [timeframe for timeframe in required if len(context.get(timeframe) or []) < 5]
    if missing_context:
        return {"confirmed": False, "trends": trends, "blockers": [f"INSUFFICIENT_CONTEXT_{value}" for value in missing_context]}
    higher_timeframes = [timeframe for timeframe in required if timeframe != execution_timeframe]
    if setup_type in {"intraday_breakout", "intraday_trend"}:
        aligned = all(trends.get(timeframe, 0.0) >= 0.0 for timeframe in higher_timeframes)
    elif setup_type == "pullback":
        aligned = trends.get("1d", 0.0) > 0.0
    elif setup_type == "mean_reversion":
        aligned = trends.get("15m", 0.0) > -0.03
    else:
        aligned = True
    return {
        "confirmed": aligned,
        "trends": trends,
        "blockers": [] if aligned else ["HIGHER_TIMEFRAME_CONTRADICTION"],
    }


def _trend_score(history: list[ReplayMarketBar]) -> float:
    closes = [float(row.close) for row in history[-20:]]
    if len(closes) < 2 or closes[0] == 0:
        return 0.0
    return round(closes[-1] / closes[0] - 1, 6)


def _atr(history: list[ReplayMarketBar]) -> float:
    ranges = [float(row.high or row.close) - float(row.low or row.close) for row in history[-14:]]
    return max(0.01, sum(ranges) / max(1, len(ranges)))


def _liquidity_score(history: list[ReplayMarketBar]) -> float:
    volumes = [float(row.volume or 0.0) for row in history[-20:]]
    average = sum(volumes) / max(1, len(volumes))
    return max(20.0, min(100.0, 20 + average / 20_000))


def _manage_trade(
    bars: list[ReplayMarketBar],
    entry_index: int,
    stop: float,
    target: float,
    maximum_holding_bars: int = 20,
) -> tuple[ReplayMarketBar, float, str]:
    last_index = min(len(bars) - 1, entry_index + max(1, maximum_holding_bars))
    for index in range(entry_index, last_index + 1):
        bar = bars[index]
        if float(bar.low or bar.close) <= stop:
            open_price = float(bar.open if bar.open is not None else bar.close)
            return bar, min(open_price, stop), "stop"
        if float(bar.high or bar.close) >= target:
            return bar, target, "target"
    bar = bars[last_index]
    return bar, float(bar.close), "time_exit"
