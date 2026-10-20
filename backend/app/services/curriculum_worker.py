"""Bounded experiment worker. Frozen packs, exact episode accounting, stored reads."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import threading
import math
import time

from sqlalchemy import select, update, or_, func, extract, case
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import (
    Asset,
    PriceHistory,
    ReplayMarketBar,
    TradingCurriculumState,
    TradingCurriculumEpisode,
    TradingCurriculumSource,
)
from app.services import trading_curriculum as kernel
from app.services import curriculum_valuation as valuation
from app.services.forex_contracts import pair_config

SOURCE_POLICY = "declared-open-grid-v2"


class CheckpointChanged(RuntimeError):
    pass


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
            discovery = self._discover(db, now, deadline=started + max_seconds)
            states = db.scalars(
                select(TradingCurriculumState)
                .order_by(
                    case(
                        (
                            TradingCurriculumState.payload[
                                "training_status"
                            ].as_string()
                            == "DATA_BLOCKED",
                            1,
                        ),
                        else_=0,
                    ),
                    TradingCurriculumState.updated_at,
                    TradingCurriculumState.lane,
                )
                .limit(8)
            ).all()
            training = {
                r.lane
                for r in sorted(
                    (
                        r
                        for r in states
                        if r.payload["training_status"]
                        not in (
                            "PACK_EXHAUSTED",
                            "PACK_EXHAUSTED_NO_OUTCOMES",
                            "DATA_BLOCKED",
                        )
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
                    self._refresh_valuation(db, payload)
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
                status="ok",
                lanes=processed,
                discovery=discovery,
                elapsed_seconds=time.monotonic() - started,
            )
        except CheckpointChanged:
            db.rollback()
            return dict(status="deferred", reason="checkpoint_changed")
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
                "source_kind",
                "source_policy",
                "source_audit",
                "source_readiness",
                "training_diagnostics",
                "productive_episodes",
            )
        }
        result["source_history"] = [
            {
                k: old.get(k)
                for k in (
                    "source_hash",
                    "checkpoint",
                    "training_episodes",
                    "learned_outcomes",
                    "training_status",
                    "archived_at",
                    "reason",
                )
            }
            for old in payload.get("source_history", [])
        ]
        result["forward"] = {
            k: deepcopy(v)
            for k, v in payload["forward"].items()
            if k not in ("proposal", "observed")
        }
        return result

    def _discover(self, db: Session, now: datetime, *, deadline: float = float("inf")):
        """Find actual stored prices; request-range coverage is not a data catalogue."""
        states = {r.lane: r for r in db.scalars(select(TradingCurriculumState)).all()}
        diagnostics = []
        for timeframe in ("1d", "5m"):
            for market in ("FOREX", "USA"):
                eligible = (
                    or_(
                        func.upper(Asset.country) == "FOREX",
                        Asset.ticker.endswith("=X"),
                    )
                    if market == "FOREX"
                    else func.upper(Asset.country).in_(
                        ("USA", "US", "UNITED STATES", "NASDAQ", "NYSE")
                    )
                )
                # Fixed, ex-ante preferences, independent of returns. The fallback
                # remains bounded and never needs network acquisition on this worker.
                retained = [
                    r.payload["ticker"]
                    for r in states.values()
                    if r.payload["market"] == market
                    and r.payload["timeframe"] == timeframe
                ]
                candidates = db.scalars(
                    select(Asset)
                    .where(Asset.is_active.is_(True), eligible)
                    .order_by(
                        case((Asset.ticker.in_(retained), -1), else_=1),
                        case(
                            (
                                Asset.ticker.in_(
                                    ("SPY", "QQQ", "EURUSD=X", "GBPUSD=X")
                                ),
                                0,
                            ),
                            else_=1,
                        ),
                        Asset.ticker,
                    )
                    .limit(12)
                ).all()
                ready = 0
                for asset in candidates:
                    if time.monotonic() >= deadline or ready >= 2:
                        break
                    lane = f"{market}:{timeframe}:{asset.ticker}"
                    old = states.get(lane)
                    if old and old.payload.get("source_policy") == SOURCE_POLICY:
                        ready += 1
                        continue
                    # A frozen pending decision keeps its original observations
                    # and clock until terminal; changing its source would be hindsight.
                    if old and old.payload["forward"].get("proposal"):
                        ready += 1
                        diagnostics.append(
                            dict(lane=lane, status="LEGACY_PENDING_SOURCE_RETAINED")
                        )
                        continue
                    kind = "replay"
                    if market == "USA" and timeframe == "1d":
                        count = (
                            db.scalar(
                                select(func.count(PriceHistory.id)).where(
                                    PriceHistory.asset_id == asset.id,
                                    PriceHistory.date <= now.date(),
                                )
                            )
                            or 0
                        )
                        if count >= 600:
                            kind = "price_history"
                    pack = self._bars(
                        db,
                        asset.id,
                        timeframe,
                        market,
                        now,
                        limit=5000,
                        canonical=True,
                        source_kind=kind,
                    )
                    if len(pack) < 600:
                        diagnostics.append(
                            dict(
                                lane=lane,
                                status="INSUFFICIENT_CLOSED_GRID_BARS",
                                rows=len(pack),
                            )
                        )
                        if old:
                            replacement = deepcopy(old.payload)
                            replacement["training_status"] = "DATA_BLOCKED"
                            replacement["source_readiness"] = dict(
                                reason="INSUFFICIENT_CLOSED_GRID_BARS", rows=len(pack)
                            )
                            replacement["public"] = self._public(replacement)
                            self._replace_state(db, old, replacement, now)
                        continue
                    audit = self._audit(pack, market, timeframe)
                    if not audit["usable_training_decisions"]:
                        diagnostics.append(
                            dict(
                                lane=lane,
                                status="NO_CONTIGUOUS_TRAINING_CONTEXT",
                                audit=audit,
                            )
                        )
                        if old:
                            replacement = deepcopy(old.payload)
                            replacement["training_status"] = "DATA_BLOCKED"
                            replacement["source_readiness"] = dict(
                                reason="NO_CONTIGUOUS_TRAINING_CONTEXT", audit=audit
                            )
                            replacement["public"] = self._public(replacement)
                            self._replace_state(db, old, replacement, now)
                        continue
                    payload = dict(
                        lane=lane,
                        market=market,
                        timeframe=timeframe,
                        ticker=asset.ticker,
                        asset_id=asset.id,
                        quote_currency=asset.currency,
                        source_hash=kernel.digest(pack),
                        source_rows=len(pack),
                        source_kind=kind,
                        source_policy=SOURCE_POLICY,
                        source_audit=audit,
                        catalogue_hash=kernel.digest(
                            [
                                x.to_payload()
                                for x in kernel.catalogue(timeframe, market)
                            ]
                        ),
                        windows=kernel.training_windows(len(pack), seed=17),
                        model={},
                        training_episodes=0,
                        learned_outcomes=0,
                        productive_episodes=0,
                        training_diagnostics={},
                        training_status=(
                            "TRAINING"
                            if audit["usable_training_decisions"]
                            else "DATA_BLOCKED"
                        ),
                        checkpoint=kernel.digest({}),
                        forward=dict(
                            status="WAITING_SIGNAL",
                            closed_count=0,
                            cash_quote_units=kernel.CAPITAL,
                        ),
                    )
                    if old:
                        archived = deepcopy(old.payload)
                        history = archived.pop("source_history", [])
                        archived.pop("public", None)
                        archived.update(
                            archived_at=now.isoformat(),
                            reason="SOURCE_CLOCK_POLICY_REPLACED",
                        )
                        payload["source_history"] = history + [archived]
                    payload["public"] = self._public(payload)
                    try:
                        with db.begin_nested():
                            if (
                                db.get(TradingCurriculumSource, payload["source_hash"])
                                is None
                            ):
                                db.add(
                                    TradingCurriculumSource(
                                        uid=payload["source_hash"],
                                        payload={"bars": pack},
                                        created_at=now,
                                    )
                                )
                            if old:
                                self._replace_state(
                                    db, old, payload, datetime(1970, 1, 1)
                                )
                            else:
                                row = TradingCurriculumState(
                                    lane=lane,
                                    revision=0,
                                    payload=payload,
                                    updated_at=datetime(1970, 1, 1),
                                )
                                db.add(row)
                                states[lane] = row
                            db.flush()
                    except IntegrityError:
                        if db.get(TradingCurriculumState, lane) is None:
                            raise
                    diagnostics.append(
                        dict(
                            lane=lane,
                            status=payload["training_status"],
                            rows=len(pack),
                            source_kind=kind,
                            audit=audit,
                        )
                    )
                    ready += 1
        db.commit()
        return diagnostics

    @staticmethod
    def _replace_state(db, row, payload, now):
        with db.no_autoflush:
            changed = db.execute(
                update(TradingCurriculumState)
                .where(
                    TradingCurriculumState.lane == row.lane,
                    TradingCurriculumState.revision == row.revision,
                )
                .values(payload=payload, revision=row.revision + 1, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise CheckpointChanged()
        db.expire(row)

    @staticmethod
    def _audit(pack, market, timeframe):
        gaps = [
            i
            for i in range(1, len(pack))
            if not kernel.consecutive(
                datetime.fromisoformat(pack[i - 1]["start"]),
                datetime.fromisoformat(pack[i]["start"]),
                timeframe,
                market,
            )
        ]
        invalid = {i for i, b in enumerate(pack) if not kernel.valid_bar(b)}
        gap_set = set(gaps)
        attempts = (
            i
            for start, end in kernel.training_windows(len(pack), seed=17)
            for i in range(start, end - 2)
        )
        usable = sum(
            not invalid.intersection(range(i - kernel.WARMUP + 1, i + 1))
            and not gap_set.intersection(range(i - kernel.WARMUP + 2, i + 1))
            for i in attempts
        )
        return dict(
            policy=SOURCE_POLICY,
            invalid_rows=len(invalid),
            missing_interval_boundaries=len(gaps),
            usable_training_decisions=usable,
            start=pack[0]["start"],
            end=pack[-1]["available"],
        )

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
        canonical: bool = False,
        source_kind: str = "replay",
    ) -> list[dict]:
        if source_kind == "price_history":
            query = select(PriceHistory).where(
                PriceHistory.asset_id == asset_id, PriceHistory.date <= now.date()
            )
            if after:
                query = query.where(PriceHistory.date >= after.date())
            clock = PriceHistory.date
        else:
            query = select(ReplayMarketBar).where(
                ReplayMarketBar.asset_id == asset_id,
                ReplayMarketBar.timeframe == timeframe,
                ReplayMarketBar.bar_timestamp <= now,
                ReplayMarketBar.acquired_at <= now,
            )
            clock = ReplayMarketBar.bar_timestamp
            if after:
                query = query.where(
                    clock > (after - timedelta(days=1) if timeframe == "1d" else after)
                )
            if canonical:
                # Filter before LIMIT: quote polling can bury years of daily bars.
                query = query.where(extract("second", clock) == 0)
                if timeframe == "1d":
                    query = (
                        query.where(
                            extract("minute", clock) == 0,
                            extract("hour", clock).in_((0, 23)),
                        )
                        if market == "FOREX"
                        else query.where(
                            or_(
                                (extract("hour", clock) == 0)
                                & (extract("minute", clock) == 0),
                                (extract("hour", clock).in_((13, 14)))
                                & (extract("minute", clock) == 30),
                            )
                        )
                    )
                else:
                    query = query.where(extract("minute", clock) % 5 == 0)
        # A small daily lookahead allows normalized NY opening labels after `after`.
        rows = db.scalars(
            query.order_by(clock if after else clock.desc()).limit(
                limit + (3 if after and timeframe == "1d" else 0)
            )
        ).all()
        if not after:
            rows = list(reversed(rows))
        pack = []
        for row in rows:
            timestamp = (
                datetime.combine(row.date, datetime.min.time())
                if source_kind == "price_history"
                else row.bar_timestamp
            )
            if canonical:
                from app.services.market_bar_clock import canonical_open

                if not canonical_open(timestamp, timeframe, market):
                    continue
            available = kernel.available_at(timestamp, timeframe, market)
            bar = dict(
                start=kernel.session_start(timestamp, timeframe, market).isoformat(),
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
            if (
                source_kind != "price_history"
                and row.data_quality_score < 80
                and not bar.get("invalid_reason")
            ):
                bar["invalid_reason"] = "LOW_SOURCE_QUALITY"
            if canonical:
                bar["source_policy"] = SOURCE_POLICY
                captured_at = (
                    row.created_at
                    if source_kind == "price_history"
                    else row.acquired_at
                )
                if captured_at < available and not bar.get("invalid_reason"):
                    # Aging a captured partial OHLC does not create the final
                    # candle. A closed refetch must confirm it first.
                    bar["invalid_reason"] = "CAPTURED_BEFORE_BAR_FINALIZATION"
            if available <= now and (after is None or bar["start"] > after.isoformat()):
                pack.append(bar)
        return pack[:limit] if after else pack

    def _train(self, db: Session, payload: dict, now: datetime):
        cursor = payload["training_episodes"]
        if cursor >= len(payload["windows"]):
            payload["training_status"] = (
                "PACK_EXHAUSTED"
                if payload["learned_outcomes"]
                else "PACK_EXHAUSTED_NO_OUTCOMES"
            )
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
        diagnostics = payload.setdefault("training_diagnostics", {})
        for spec in kernel.catalogue(payload["timeframe"], payload["market"]):
            report = kernel.simulate(
                pack,
                market=payload["market"],
                timeframe=payload["timeframe"],
                start=start,
                end=end,
                expert=spec,
            )
            for reason, count in report["decision_diagnostics"].items():
                diagnostics[reason] = diagnostics.get(reason, 0) + count
            for trade in report["trades"]:
                reason = "EXECUTION_" + trade["status"]
                diagnostics[reason] = diagnostics.get(reason, 0) + 1
                if trade["status"] == "CLOSED":
                    model.learn(spec.fingerprint, trade["context"], trade["net_r"])
                    outcomes.append(trade)
        payload["productive_episodes"] = payload.get("productive_episodes", 0) + bool(
            outcomes
        )
        payload["training_status"] = "TRAINING" if outcomes else "TRAINING_NO_OUTCOMES"
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

    def _refresh_valuation(self, db: Session, payload: dict):
        # A report-version migration must not count as another learning episode.
        old = payload.get("benchmark")
        if not old or old.get("evaluation_version") == valuation.VERSION:
            return
        source = db.get(TradingCurriculumSource, payload["source_hash"])
        refreshed = self._benchmark(payload, source.payload["bars"])
        for key in ("previous_net_return", "return_change_from_previous"):
            if key in old:
                refreshed[key] = old[key]
        payload["benchmark"] = refreshed

    @staticmethod
    def _quote_currency(payload: dict) -> str | None:
        if payload["market"] == "FOREX":
            try:
                return pair_config(payload["ticker"]).quote_currency
            except KeyError:
                return None
        return payload.get("quote_currency", "USD")

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
        hold = (
            pack[end - 1]["close"] / pack[entry_i]["open"] - 1
            if kernel.valid_bar(pack[end - 1]) and kernel.valid_bar(pack[entry_i])
            else None
        )
        as_of = datetime.fromisoformat(pack[end - 1]["available"])
        values = {
            "policy": valuation.value_frozen_trades(
                pack, policy["trades"], as_of=as_of, **kwargs
            ),
            "fixed_expert": valuation.value_frozen_trades(
                pack, baseline["trades"], as_of=as_of, **kwargs
            ),
            "modeled_hold": valuation.modeled_hold(pack, as_of=as_of, **kwargs),
        }
        selected, held = values["policy"], values["modeled_hold"]
        eligible = all(
            v["status"] == "COMPLETE" and v["net_liquidation_return"] is not None
            for v in (selected, held)
        )
        values.update(
            quote_currency=self._quote_currency(payload),
            evaluation_hash=kernel.digest(
                [
                    valuation.VERSION,
                    payload["checkpoint"],
                    kernel.digest(pack[start:end]),
                    kernel.COST_VERSION,
                ]
            ),
            comparison=dict(
                eligible=eligible,
                net_liquidation_excess_return=(
                    (
                        selected["net_liquidation_return"]
                        - held["net_liquidation_return"]
                    )
                    if eligible
                    else None
                ),
            ),
        )
        for report in (policy, baseline):
            report.pop("trades", None)
        return dict(
            window_hash=kernel.digest(pack[start:end]),
            start=pack[start]["available"],
            end=pack[end - 1]["available"],
            confirmation_opened=False,
            evaluation_version=valuation.VERSION,
            valuation=values,
            policy=policy,
            fixed_expert=baseline,
            cash_return=0.0,
            buy_hold_price_return=hold,
            note="Repeated development monitoring, not final confirmation; hold excludes costs/dividends and remains fully invested.",
        )

    def _forward(self, db: Session, payload: dict, now: datetime):
        forward = payload["forward"]
        pending = forward.get("proposal")
        if not pending and payload.get("source_readiness"):
            forward.update(
                status="WAITING_CONTEXT",
                reason=payload["source_readiness"]["reason"],
                updated_at=now.isoformat(),
            )
            return
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
                    canonical=payload.get("source_policy") == SOURCE_POLICY,
                    source_kind=payload.get("source_kind", "replay"),
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
            forward["valuation"] = valuation.value_frozen_trades(
                future,
                [outcome],
                market=payload["market"],
                timeframe=payload["timeframe"],
                start=0,
                end=len(future),
                as_of=now,
                capital=pending["cash_budget"],
            )
            forward["valuation"]["quote_currency"] = self._quote_currency(payload)
            forward["valuation"]["scope"] = "current_episode_only"
            row.payload = dict(
                valuation=forward["valuation"],
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
            canonical=payload.get("source_policy") == SOURCE_POLICY,
            source_kind=payload.get("source_kind", "replay"),
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
        decision_diagnostics = {}
        proposal = kernel.propose(
            history,
            market=payload["market"],
            timeframe=payload["timeframe"],
            model=kernel.Selector(
                kernel.merge_models(payload["model"], payload.get("live_updates", {}))
            ),
            decision_at=now,
            diagnostics=decision_diagnostics,
        )
        if proposal is None:
            forward.update(
                status=(
                    "WAITING_CONTEXT"
                    if "MISSING_CONTEXT_INTERVAL" in decision_diagnostics
                    or "INSUFFICIENT_CLOSED_CONTEXT" in decision_diagnostics
                    else "WAITING_SIGNAL"
                ),
                reason=next(iter(decision_diagnostics), "NO_EXPERT_TRIGGER"),
                updated_at=now.isoformat(),
            )
            return
        proposal["checkpoint"] = kernel.digest(
            [payload["checkpoint"], payload.get("live_updates", {})]
        )
        forward.pop("valuation", None)
        proposal["cash_budget"] = forward["cash_quote_units"]
        forward.update(
            status="PENDING",
            proposal=proposal,
            reason=None,
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
