"""Bounded experiment worker. Frozen packs, exact episode accounting, stored reads."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import threading
import math
import time

from sqlalchemy import select, update, or_, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.services.executable_strategy import normalize_market

from app.models import (
    Asset,
    ReplayDataCoverage,
    ReplayMarketBar,
    TradingCurriculumState,
    TradingCurriculumEpisode,
    TradingCurriculumSource,
)
from app.services import trading_curriculum as kernel

_LOCK = threading.Lock()
LIMITATIONS = [
    "Experimental long-only research; no automatic promotion or real-money routing.",
    "Development windows are reused for monitoring. Reserved confirmation remains unopened.",
    "Universe selection, corporate actions and survivorship require further audit; hold is price-only, excluding dividends.",
    "OHLC execution assumes stop-first within ambiguous bars; exit trigger fills do not validate broker depth.",
    "Forex uses a declared 100,000-unit OTC capacity scenario, not observed traded volume. Cash is per-lane quote currency, not EUR portfolio P/L.",
    "Training blocks and expert counterfactuals are dependent; learned-outcome counts are not independent forward evidence.",
    "Wilson win-rate intervals assume independent Bernoulli outcomes; serial dependence can make these descriptive intervals overconfident.",
    "Bar opening fills use a modeled opening price and whole-bar participation capacity; they are not timestamp-certified broker fills.",
    "Source packs are immutable. Exhausted packs require a new audited corpus version; repeated episodes never inflate learning.",
]


class TradingCurriculumWorker:
    def snapshot(self, db: Session) -> dict:
        states = db.execute(
            select(
                TradingCurriculumState.updated_at,
                TradingCurriculumState.payload["public"].label("summary"),
            ).order_by(TradingCurriculumState.lane)
        ).all()
        lanes = []
        for row in states:
            lanes.append(row.summary)
        return dict(
            version=kernel.VERSION,
            status="EXPERIMENTAL",
            updated_at=max((r.updated_at for r in states), default=None),
            lanes=lanes,
            limitations=LIMITATIONS,
        )

    def run_once(
        self,
        db: Session,
        *,
        now: datetime | None = None,
        max_lanes: int = 2,
        max_seconds: float = 20,
    ) -> dict:
        if not _LOCK.acquire(blocking=False):
            return dict(status="deferred", reason="curriculum_already_running")
        try:
            now = now or datetime.utcnow()
            started = time.monotonic()
            self._discover(db, now)
            states = db.scalars(
                select(TradingCurriculumState)
                .order_by(
                    TradingCurriculumState.updated_at, TradingCurriculumState.lane
                )
                .limit(8)
            ).all()
            training = {
                r.lane
                for r in sorted(
                    (
                        r
                        for r in states
                        if r.payload["training_status"] != "PACK_EXHAUSTED"
                    ),
                    key=lambda r: (r.payload["training_episodes"], r.lane),
                )[: max(1, min(8, max_lanes))]
            }
            processed = []
            for row in states:
                if time.monotonic() - started >= max_seconds:
                    break
                old_revision = row.revision
                payload = deepcopy(row.payload)
                with db.no_autoflush:
                    if row.lane in training:
                        self._train(db, payload, now)
                    self._forward(db, payload, now)
                    payload["public"] = self._public(payload)
                    changed = db.execute(
                        update(TradingCurriculumState)
                        .where(
                            TradingCurriculumState.lane == row.lane,
                            TradingCurriculumState.revision == old_revision,
                        )
                        .values(
                            payload=payload, revision=old_revision + 1, updated_at=now
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if changed.rowcount != 1:
                        db.rollback()
                        return dict(status="deferred", reason="checkpoint_changed")
                db.commit()
                processed.append(row.lane)
            db.expire_all()
            return dict(
                status="ok", lanes=processed, elapsed_seconds=time.monotonic() - started
            )
        finally:
            _LOCK.release()

    def _public(self, payload: dict) -> dict:
        result = {
            key: deepcopy(payload.get(key))
            for key in (
                "lane",
                "market",
                "timeframe",
                "ticker",
                "checkpoint",
                "training_episodes",
                "learned_outcomes",
                "training_status",
                "source_hash",
                "source_rows",
                "benchmark",
            )
        }
        result["forward"] = {
            k: deepcopy(v)
            for k, v in payload["forward"].items()
            if k not in ("proposal", "observed")
        }
        return result

    def _discover(self, db: Session, now: datetime):
        existing = set(db.scalars(select(TradingCurriculumState.lane)).all())
        coverage = []
        for timeframe in ("1d", "5m"):
            for forex in (True, False):
                market_filter = (
                    or_(
                        func.upper(ReplayDataCoverage.market) == "FOREX",
                        Asset.ticker.endswith("=X"),
                    )
                    if forex
                    else func.upper(ReplayDataCoverage.market).in_(
                        ("USA", "US", "UNITED STATES", "NASDAQ", "NYSE")
                    )
                )
                coverage.extend(
                    db.scalars(
                        select(ReplayDataCoverage)
                        .join(Asset, Asset.id == ReplayDataCoverage.asset_id)
                        .where(
                            ReplayDataCoverage.timeframe == timeframe,
                            Asset.is_active.is_(True),
                            ReplayDataCoverage.rows_available >= 600,
                            ReplayDataCoverage.data_quality_score >= 80,
                            market_filter,
                        )
                        .order_by(
                            ReplayDataCoverage.available_end.desc(),
                            ReplayDataCoverage.asset_id,
                        )
                        .limit(12)
                    ).all()
                )
        counts = {}
        for lane in existing:
            group = tuple(lane.split(":")[:2])
            counts[group] = counts.get(group, 0) + 1
        for row in coverage:
            asset = db.get(Asset, row.asset_id)
            if not asset or not asset.is_active:
                continue
            market = (
                "FOREX"
                if row.market.upper() == "FOREX" or "=X" in asset.ticker
                else "USA" if normalize_market(row.market) == "USA" else None
            )
            if market is None:
                continue
            lane = f"{market}:{row.timeframe}:{asset.ticker}"
            group = (market, row.timeframe)
            if lane in existing:
                continue
            if counts.get(group, 0) >= 2:
                continue
            pack = self._bars(db, asset.id, row.timeframe, market, now, limit=5000)
            if len(pack) < 600 or any(not kernel.valid_bar(b) for b in pack):
                continue
            windows = kernel.training_windows(len(pack), seed=17)
            payload = dict(
                lane=lane,
                market=market,
                timeframe=row.timeframe,
                ticker=asset.ticker,
                asset_id=asset.id,
                quote_currency=asset.currency,
                source_hash=kernel.digest(pack),
                source_rows=len(pack),
                source_provider=row.provider,
                catalogue_hash=kernel.digest(
                    [s.to_payload() for s in kernel.catalogue(row.timeframe, market)]
                ),
                windows=windows,
                model={},
                training_episodes=0,
                learned_outcomes=0,
                training_status="TRAINING",
                checkpoint=kernel.digest({}),
                forward=dict(
                    status="WAITING_SIGNAL",
                    closed_count=0,
                    cash_quote_units=kernel.CAPITAL,
                ),
            )
            payload["public"] = self._public(payload)
            try:
                with db.begin_nested():
                    if db.get(TradingCurriculumSource, payload["source_hash"]) is None:
                        db.add(
                            TradingCurriculumSource(
                                uid=payload["source_hash"],
                                payload={"bars": pack},
                                created_at=now,
                            )
                        )
                    db.add(
                        TradingCurriculumState(
                            lane=lane,
                            revision=0,
                            payload=payload,
                            updated_at=datetime(1970, 1, 1),
                        )
                    )
                    db.flush()
            except IntegrityError:
                if db.get(TradingCurriculumState, lane) is None:
                    raise
            existing.add(lane)
            counts[group] = counts.get(group, 0) + 1
        db.commit()

    def _bars(
        self,
        db: Session,
        asset_id: int,
        timeframe: str,
        market: str,
        now: datetime,
        *,
        limit: int,
        after: datetime | None = None,
    ) -> list[dict]:
        query = select(ReplayMarketBar).where(
            ReplayMarketBar.asset_id == asset_id,
            ReplayMarketBar.timeframe == timeframe,
            ReplayMarketBar.bar_timestamp <= now,
            ReplayMarketBar.acquired_at <= now,
        )
        if after:
            query = query.where(
                ReplayMarketBar.bar_timestamp
                > (after - timedelta(days=1) if timeframe == "1d" else after)
            )
        if after:
            rows = db.scalars(
                query.order_by(ReplayMarketBar.bar_timestamp).limit(
                    limit + 3 if timeframe == "1d" else limit
                )
            ).all()
        else:
            rows = list(
                reversed(
                    db.scalars(
                        query.order_by(ReplayMarketBar.bar_timestamp.desc()).limit(
                            limit
                        )
                    ).all()
                )
            )
        pack = []
        for row in rows:
            available = kernel.available_at(row.bar_timestamp, timeframe, market)
            bar = dict(
                start=kernel.session_start(
                    row.bar_timestamp, timeframe, market
                ).isoformat(),
                available=available.isoformat(),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=float(row.volume or 0),
                provider=row.provider,
            )
            invalid_fields = [
                key
                for key in ("open", "high", "low", "close", "volume")
                if isinstance(bar[key], (int, float)) and not math.isfinite(bar[key])
            ]
            if invalid_fields:
                for key in invalid_fields:
                    bar[key] = None
                bar["invalid_reason"] = "NON_FINITE_MARKET_DATA"
                bar["invalid_fields"] = invalid_fields
            if row.data_quality_score < 80 and not bar.get("invalid_reason"):
                bar["invalid_reason"] = "LOW_SOURCE_QUALITY"
            if available <= now and (after is None or bar["start"] > after.isoformat()):
                pack.append(bar)
        return pack[:limit] if after else pack

    def _train(self, db: Session, payload: dict, now: datetime):
        cursor = payload["training_episodes"]
        if cursor >= len(payload["windows"]):
            payload["training_status"] = "PACK_EXHAUSTED"
            return
        start, end = payload["windows"][cursor]
        uid = kernel.digest(
            [
                kernel.VERSION,
                payload["lane"],
                payload["source_hash"],
                payload["catalogue_hash"],
                kernel.COST_VERSION,
                start,
                end,
            ]
        )
        if db.get(TradingCurriculumEpisode, uid):
            raise RuntimeError(
                "curriculum checkpoint/episode inconsistency; refusing duplicate learning"
            )
        pack = db.get(TradingCurriculumSource, payload["source_hash"]).payload["bars"]
        model = kernel.Selector(payload["model"])
        outcomes = []
        for spec in kernel.catalogue(payload["timeframe"], payload["market"]):
            report = kernel.simulate(
                pack,
                market=payload["market"],
                timeframe=payload["timeframe"],
                start=start,
                end=end,
                expert=spec,
            )
            for trade in report["trades"]:
                if trade["status"] == "CLOSED":
                    model.learn(spec.fingerprint, trade["context"], trade["net_r"])
                    outcomes.append(trade)
        payload["model"] = model.payload()
        payload["training_episodes"] += 1
        payload["learned_outcomes"] += len(outcomes)
        payload["checkpoint"] = kernel.digest(
            dict(
                model=payload["model"],
                source=payload["source_hash"],
                catalogue=payload["catalogue_hash"],
                costs=kernel.COST_VERSION,
            )
        )
        previous = payload.get("benchmark", {}).get("policy", {}).get("net_return")
        payload["benchmark"] = self._benchmark(payload, pack)
        current = payload["benchmark"]["policy"]["net_return"]
        payload["benchmark"]["previous_net_return"] = previous
        payload["benchmark"]["return_change_from_previous"] = (
            current - previous if current is not None and previous is not None else None
        )
        db.add(
            TradingCurriculumEpisode(
                uid=uid,
                lane=payload["lane"],
                phase="train",
                payload=dict(
                    start=start,
                    end=end,
                    source_hash=payload["source_hash"],
                    checkpoint=payload["checkpoint"],
                    outcomes=outcomes,
                    benchmark=payload["benchmark"],
                ),
                created_at=now,
            )
        )

    def _benchmark(self, payload: dict, pack: list[dict]) -> dict:
        split = kernel.partition(len(pack))
        start, end = split["development_start"], split["development_end"]
        kwargs = dict(
            market=payload["market"],
            timeframe=payload["timeframe"],
            start=start,
            end=end,
        )
        policy = kernel.simulate(
            pack, model=kernel.Selector(payload["model"]), **kwargs
        )
        baseline = kernel.simulate(
            pack,
            expert=kernel.catalogue(payload["timeframe"], payload["market"])[0],
            **kwargs,
        )
        # Price-only same-asset reference, same delayed entry open and final close interval.
        entry_i = next(
            i
            for i in range(start + 1, end)
            if pack[i]["start"] > pack[start]["available"]
        )
        hold = pack[end - 1]["close"] / pack[entry_i]["open"] - 1
        for report in (policy, baseline):
            report.pop("trades", None)
        return dict(
            window_hash=kernel.digest(pack[start:end]),
            start=pack[start]["available"],
            end=pack[end - 1]["available"],
            confirmation_opened=False,
            policy=policy,
            fixed_expert=baseline,
            cash_return=0.0,
            buy_hold_price_return=hold,
            note="Repeated development monitoring, not final confirmation; hold excludes costs/dividends and remains fully invested.",
        )

    def _forward(self, db: Session, payload: dict, now: datetime):
        forward = payload["forward"]
        pending = forward.get("proposal")
        if pending:
            future = forward.setdefault("observed", [])
            after = datetime.fromisoformat(
                future[-1]["start"] if future else pending["decision_at"]
            )
            fresh = (
                self._bars(
                    db,
                    payload["asset_id"],
                    payload["timeframe"],
                    payload["market"],
                    now,
                    limit=kernel.HOLD - len(future),
                    after=after,
                )
                if len(future) < kernel.HOLD
                else []
            )
            future.extend(fresh)
            outcome = kernel.resolve(
                pending,
                future,
                market=payload["market"],
                complete=False,
                cash=forward["cash_quote_units"],
            )
            if outcome is None:
                forward["status"] = "PENDING"
                return
            uid = kernel.digest(
                [
                    payload["lane"],
                    pending["input_hash"],
                    pending["decision_at"],
                    "forward",
                ]
            )
            row = db.get(TradingCurriculumEpisode, uid)
            if row is None:
                raise RuntimeError("missing frozen forward episode")
            row.payload = dict(
                proposal=pending,
                outcome=outcome,
                observations=future,
                observed_hash=kernel.digest(future),
                resolved_at=(
                    now.isoformat()
                    if outcome["status"] not in ("OPEN", "BLOCKED")
                    else None
                ),
            )
            if outcome["status"] in ("OPEN", "BLOCKED"):
                forward.update(
                    status=outcome["status"],
                    last_outcome=outcome,
                    updated_at=now.isoformat(),
                )
                return
            if outcome["status"] == "CLOSED":
                forward["cash_quote_units"] += outcome["pnl"]
                forward["closed_count"] += 1
                live = kernel.Selector(payload.get("live_updates", {}))
                live.learn(pending["expert"], pending["context"], outcome["net_r"])
                payload["live_updates"] = live.payload()
                forward["learned_outcomes"] = sum(
                    v["n"] for v in live.payload().values()
                )
            forward.update(
                status=outcome["status"],
                last_outcome=outcome,
                last_feature=pending["feature_latest"],
                updated_at=now.isoformat(),
            )
            forward.pop("proposal", None)
            forward.pop("observed", None)
            return
        history = self._bars(
            db,
            payload["asset_id"],
            payload["timeframe"],
            payload["market"],
            now,
            limit=kernel.WARMUP + 2,
        )
        freshness = (
            timedelta(days=4) if payload["timeframe"] == "1d" else timedelta(minutes=20)
        )
        if (
            not history
            or now - datetime.fromisoformat(history[-1]["available"]) > freshness
        ):
            forward.update(status="STALE_CONTEXT", updated_at=now.isoformat())
            return
        if any(not kernel.valid_bar(b) for b in history):
            forward.update(
                status="BLOCKED",
                reason="INVALID_CONTEXT_BAR",
                updated_at=now.isoformat(),
            )
            return
        if forward.get("last_feature") == history[-1]["available"]:
            return
        proposal = kernel.propose(
            history,
            market=payload["market"],
            timeframe=payload["timeframe"],
            model=kernel.Selector(
                kernel.merge_models(payload["model"], payload.get("live_updates", {}))
            ),
            decision_at=now,
        )
        if proposal is None:
            forward.update(status="WAITING_SIGNAL", updated_at=now.isoformat())
            return
        proposal["checkpoint"] = kernel.digest(
            [payload["checkpoint"], payload.get("live_updates", {})]
        )
        proposal["cash_budget"] = forward["cash_quote_units"]
        forward.update(
            status="PENDING",
            proposal=proposal,
            decision_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        uid = kernel.digest(
            [
                payload["lane"],
                proposal["input_hash"],
                proposal["decision_at"],
                "forward",
            ]
        )
        db.add(
            TradingCurriculumEpisode(
                uid=uid,
                lane=payload["lane"],
                phase="forward",
                payload=dict(proposal=proposal, outcome=None),
                created_at=now,
            )
        )
