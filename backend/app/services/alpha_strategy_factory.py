from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
from itertools import product
import json
import random
from statistics import mean
from uuid import uuid4

from scipy.stats import ttest_1samp
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    HyperbolicReplayTrade,
    ReplayStrategyValidation,
    StrategyCandidateVariant,
    StrategyFactoryRun,
    StrategyPromotionEvent,
    StrategyValidationFold,
)
from app.services.strategy_factory_statistics import (
    backtest_overfitting_probability,
    benjamini_hochberg,
    build_purged_folds,
    deflated_sharpe_probability,
    evaluate_strategy_robustness,
)
from app.services.executable_strategy import ExecutableStrategySpec, canonical_strategy_spec


FAMILY_DEFINITIONS: dict[str, dict] = {
    "momentum": {"setup_type": "momentum_breakout", "entries": ["close_breakout", "relative_strength_reclaim"]},
    "trend_following": {"setup_type": "trend_continuation", "entries": ["ma_alignment", "weekly_trend_confirmed"]},
    "breakout": {"setup_type": "swing_breakout", "entries": ["close_breakout", "breakout_retest"]},
    "pullback": {"setup_type": "pullback", "entries": ["ma20_reversal", "ma50_reclaim"]},
    "mean_reversion": {"setup_type": "mean_reversion", "entries": ["rsi_reversion", "bollinger_reclaim"]},
    "volatility_expansion": {"setup_type": "volatility_squeeze", "entries": ["squeeze_release", "atr_expansion"]},
    "earnings_news_reaction": {"setup_type": "post_earnings_drift", "entries": ["gap_hold", "post_event_reclaim"]},
    "relative_strength": {"setup_type": "sector_rotation_entry", "entries": ["benchmark_breakout", "sector_leadership"]},
    "cross_sectional_ranking": {"setup_type": "cross_sectional_momentum", "entries": ["top_decile", "top_quintile"]},
    "intraday_scalping": {
        "setup_type": "intraday_breakout",
        "replay_setup_types": ["intraday_breakout", "intraday_trend"],
        "entries": ["one_minute_breakout", "five_minute_pullback"],
        "timeframe_stack": ["1d", "15m", "5m", "1m"],
        "holding_periods": [15, 45],
    },
}

REPLAY_IMPLEMENTATIONS: dict[str, dict] = {
    "swing_breakout": {"entry_rule": "close_breakout", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
    "pullback": {"entry_rule": "pullback_signal", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
    "mean_reversion": {"entry_rule": "mean_reversion_signal", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
    "intraday_breakout": {"entry_rule": "close_breakout", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
    "intraday_trend": {"entry_rule": "five_minute_breakout", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
}

REPLAY_REGIME_FILTERS = ("all", "trend_up_only", "range_bound_only", "trend_down_only")
REPLAY_MARKET_FILTERS = ("all", "usa_only", "europe_only", "forex_only")


class StrategyFamilyRegistry:
    def names(self) -> tuple[str, ...]:
        return tuple(FAMILY_DEFINITIONS)

    def variants(self, family: str, *, max_variants: int, seed: int) -> list[dict]:
        definition = FAMILY_DEFINITIONS.get(family)
        if definition is None:
            raise KeyError(f"unknown strategy family: {family}")
        if family == "intraday_scalping":
            return self._intraday_variants(max_variants=max_variants, seed=seed)
        timeframe_stack = list(definition.get("timeframe_stack") or ["1d"])
        holding_periods = list(definition.get("holding_periods") or [10, 20])
        combinations = [
            (definition["setup_type"], *combination, "all")
            for combination in product(
                definition["entries"],
                ["atr_1_5", "structure"],
                ["two_r", "trailing_atr"],
                holding_periods,
                ["all", "aligned_only"],
            )
        ]
        random.Random(int(seed)).shuffle(combinations)
        variants: list[dict] = []
        canonical_setups = []
        for setup_type in definition.get("replay_setup_types") or [definition["setup_type"]]:
            canonical = REPLAY_IMPLEMENTATIONS.get(setup_type)
            if canonical:
                canonical_setups.append(
                    (
                        setup_type,
                        canonical["entry_rule"],
                        canonical["stop_rule"],
                        canonical["target_rule"],
                        canonical["holding_period"],
                    )
                )
        canonical_combinations = [
            (*canonical, regime_filter, market_filter)
            for market_filter in REPLAY_MARKET_FILTERS
            for regime_filter in REPLAY_REGIME_FILTERS
            for canonical in canonical_setups
        ]
        combinations = canonical_combinations + combinations
        seen: set[tuple] = set()
        for setup_type, entry, stop, target, holding, regime_filter, market_filter in combinations:
            combination = (setup_type, entry, stop, target, holding, regime_filter, market_filter)
            if combination in seen:
                continue
            seen.add(combination)
            canonical = REPLAY_IMPLEMENTATIONS.get(setup_type)
            specification = {
                    "family": family,
                    "setup_type": setup_type,
                    "market": "global",
                    "asset_class": "stocks,etfs",
                    "benchmark_ticker": "SPY",
                    "timeframe_stack": timeframe_stack,
                    "entry_rule": entry,
                    "stop_rule": stop,
                    "target_rule": target,
                    "holding_period": holding,
                    "regime_filter": regime_filter,
                    "complexity": 5,
                    "execution_model": "realistic_execution_v1",
                    "evidence_binding": "hyperbolic_replay_v1" if canonical and combination[1:5] == (
                        canonical["entry_rule"],
                        canonical["stop_rule"],
                        canonical["target_rule"],
                        canonical["holding_period"],
                    ) else "not_implemented",
                }
            if market_filter != "all":
                specification["market_filter"] = market_filter
            if specification["evidence_binding"] == "hyperbolic_replay_v1":
                spec = ExecutableStrategySpec.from_payload(
                    {
                        **canonical_strategy_spec(setup_type).to_payload(),
                        "regime_filter": regime_filter,
                        "market_filter": market_filter,
                    }
                )
                specification.update(
                    timeframe_stack=list(spec.required_timeframes),
                    strategy_fingerprint=spec.fingerprint,
                    executable_strategy=spec.to_payload(),
                )
            variants.append(specification)
            if len(variants) >= max(1, int(max_variants)):
                break
        return variants

    @staticmethod
    def _intraday_variants(*, max_variants: int, seed: int) -> list[dict]:
        combinations = list(
            product(
                ("intraday_breakout", "intraday_trend"),
                REPLAY_REGIME_FILTERS,
                REPLAY_MARKET_FILTERS,
            )
        )
        canonical = [
            ("intraday_breakout", "all", "all"),
            ("intraday_breakout", "all", "forex_only"),
            ("intraday_trend", "all", "all"),
            ("intraday_trend", "all", "forex_only"),
        ]
        remainder = [combination for combination in combinations if combination not in canonical]
        random.Random(int(seed)).shuffle(remainder)
        combinations = canonical + remainder
        variants: list[dict] = []
        for setup_type, regime_filter, market_filter in combinations:
            setup_index = ("intraday_breakout", "intraday_trend").index(setup_type)
            regime_index = REPLAY_REGIME_FILTERS.index(regime_filter)
            market_index = REPLAY_MARKET_FILTERS.index(market_filter)
            is_forex = market_filter == "forex_only"
            canonical = canonical_strategy_spec(setup_type)
            spec = ExecutableStrategySpec.from_payload(
                {
                    **canonical.to_payload(),
                    "required_timeframes": ["1h", "15m", "5m", "1m"] if is_forex else list(canonical.required_timeframes),
                    "lookback": (5, 10, 20)[(regime_index + market_index) % 3],
                    "minimum_relative_volume": 0.0 if is_forex else (0.0, 1.2)[(setup_index + regime_index) % 2],
                    "stop_atr_multiple": (1.0, 1.5)[(regime_index + market_index) % 2],
                    "minimum_stop_percent": 0.0005 if is_forex else canonical.minimum_stop_percent,
                    "target_r_multiple": (1.5, 2.0, 2.5)[(setup_index + regime_index + market_index) % 3],
                    "maximum_holding_bars": (15, 30)[(setup_index + market_index) % 2],
                    "higher_timeframe_min_trend": -1.0 if regime_filter == "trend_down_only" else 0.0,
                    "regime_filter": regime_filter,
                    "market_filter": market_filter,
                }
            )
            variants.append(
                {
                    "family": "intraday_scalping",
                    "setup_type": setup_type,
                    "market": "global",
                    "asset_class": "stocks,etfs,forex",
                    "benchmark_ticker": "UUP" if is_forex else "SPY",
                    "timeframe_stack": list(spec.required_timeframes),
                    "entry_rule": spec.entry_rule,
                    "stop_rule": f"atr_{spec.stop_atr_multiple:g}",
                    "target_rule": f"{spec.target_r_multiple:g}_r",
                    "holding_period": spec.maximum_holding_bars,
                    "regime_filter": regime_filter,
                    "market_filter": market_filter,
                    "complexity": 5,
                    "execution_model": "realistic_execution_v1",
                    "evidence_binding": "hyperbolic_replay_v1",
                    "strategy_fingerprint": spec.fingerprint,
                    "executable_strategy": spec.to_payload(),
                }
            )
            if len(variants) >= max(1, int(max_variants)):
                break
        return variants


class ChampionChallengerRegistry:
    def promote(
        self,
        db: Session,
        candidate: StrategyCandidateVariant,
        validation: ReplayStrategyValidation,
    ) -> dict:
        if validation.verdict != "PROMOTED_TO_PAPER" or int(validation.sample_size or 0) < 300:
            return {"status": "not_promoted", "reason": "certification gates are not satisfied"}
        registry_key = self.registry_key(candidate)
        if candidate.is_champion:
            return {
                "status": "already_champion",
                "candidate_id": candidate.id,
                "previous_candidate_id": None,
                "registry_key": registry_key,
                "reversible": True,
            }
        champions = db.scalars(
            select(StrategyCandidateVariant).where(
                StrategyCandidateVariant.family == candidate.family,
                StrategyCandidateVariant.market == candidate.market,
                StrategyCandidateVariant.asset_class == candidate.asset_class,
                StrategyCandidateVariant.is_champion.is_(True),
            )
        ).all()
        previous = next((row for row in champions if list(row.timeframe_stack or []) == list(candidate.timeframe_stack or [])), None)
        if previous is not None:
            previous.is_champion = False
            previous.lifecycle_state = "CHALLENGER_REPLACED"
        candidate.is_champion = True
        candidate.lifecycle_state = "PROMOTED"
        candidate.final_verdict = "PROMOTED_TO_PAPER"
        event = StrategyPromotionEvent(
            candidate_id=candidate.id,
            validation_id=validation.id,
            previous_candidate_id=previous.id if previous else None,
            registry_key=registry_key,
            event_type="PROMOTED",
            reason=validation.explanation,
            evidence_json={
                "sample_size": validation.sample_size,
                "metrics": validation.metrics_json,
                "previous_candidate_id": previous.id if previous else None,
            },
            reversible=True,
        )
        db.add(event)
        db.flush()
        return {
            "status": "promoted",
            "candidate_id": candidate.id,
            "previous_candidate_id": previous.id if previous else None,
            "registry_key": registry_key,
            "reversible": True,
            "event_id": event.id,
        }

    @staticmethod
    def registry_key(candidate: StrategyCandidateVariant) -> str:
        stack = "-".join(candidate.timeframe_stack or ["1d"])
        return f"{candidate.family}:{candidate.market}:{candidate.asset_class}:{stack}"


class AlphaStrategyFactory:
    def __init__(self, registry: StrategyFamilyRegistry | None = None, champions: ChampionChallengerRegistry | None = None):
        self.registry = registry or StrategyFamilyRegistry()
        self.champions = champions or ChampionChallengerRegistry()

    def run_once(
        self,
        db: Session,
        *,
        families: list[str] | None = None,
        max_variants_per_family: int = 24,
        seed: int = 7,
        trigger: str = "scheduled",
    ) -> dict:
        selected = families or list(self.registry.names())
        selected_families = [str(family) for family in selected]
        now = datetime.utcnow()
        run = StrategyFactoryRun(
            run_uid=f"factory-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            hypothesis_family=factory_hypothesis_key(selected_families),
            generation_seed=int(seed),
            status="RUNNING",
            budgets_json={
                "max_variants_per_family": max_variants_per_family,
                "trigger": trigger,
                "selected_families": selected_families,
            },
        )
        db.add(run)
        db.flush()
        specifications = [
            specification
            for family in selected
            for specification in self.registry.variants(family, max_variants=max_variants_per_family, seed=seed)
        ]
        new_candidates: list[StrategyCandidateVariant] = []
        evaluation_candidates: list[StrategyCandidateVariant] = []
        for specification in specifications:
            fingerprint = str(specification.get("strategy_fingerprint") or strategy_fingerprint(specification))
            existing = db.scalar(select(StrategyCandidateVariant).where(StrategyCandidateVariant.fingerprint == fingerprint))
            if existing is not None:
                if self._has_new_evidence(db, existing):
                    existing.lifecycle_state = "REVALIDATING"
                    evaluation_candidates.append(existing)
                continue
            candidate = StrategyCandidateVariant(
                factory_run_id=run.id,
                fingerprint=fingerprint,
                family=specification["family"],
                setup_type=specification["setup_type"],
                market=specification["market"],
                asset_class=specification["asset_class"],
                timeframe_stack=specification["timeframe_stack"],
                specification_json=specification,
                complexity=specification["complexity"],
                benchmark_ticker=specification["benchmark_ticker"],
                lifecycle_state="VALIDATING",
            )
            db.add(candidate)
            db.flush()
            new_candidates.append(candidate)
            evaluation_candidates.append(candidate)

        replay_cache: dict[tuple[str, tuple[str, ...]], list[HyperbolicReplayTrade]] = {}
        evidence_by_candidate = [
            (candidate, self._candidate_evidence(db, candidate, replay_cache=replay_cache))
            for candidate in evaluation_candidates
        ]
        corrections = benjamini_hochberg(
            [
                1.0 if evidence.get("raw_p_value") is None else float(evidence["raw_p_value"])
                for _, evidence in evidence_by_candidate
            ],
            false_discovery_rate=0.05,
        )
        rejection_counts: Counter[str] = Counter()
        promoted_count = 0
        for index, (candidate, evidence) in enumerate(evidence_by_candidate):
            correction = corrections[index]
            evidence["adjusted_p_value"] = correction.adjusted_p_value
            evidence["multiple_testing_significant"] = correction.significant
            evidence["family_size"] = len(evidence_by_candidate)
            result = evaluate_strategy_robustness(evidence, seed=seed)
            persisted_metrics = {
                key: value
                for key, value in result.metrics.items()
                if key not in {"timestamps", "returns_r", "benchmark_excess_returns"}
            }
            validation = ReplayStrategyValidation(
                experiment_id=None,
                setup_type=candidate.setup_type,
                evidence_type="PURGED_WALK_FORWARD_EVIDENCE",
                sample_size=result.sample_size,
                markets_json=list(evidence.get("markets") or []),
                windows_json=list(evidence.get("windows") or []),
                metrics_json=persisted_metrics,
                overfitting_score=round(result.overfitting_probability * 100.0, 4),
                verdict=result.verdict,
                explanation=result.reason,
            )
            db.add(validation)
            db.flush()
            candidate.validation_id = validation.id
            candidate.final_verdict = result.verdict
            candidate.lifecycle_state = (
                "CERTIFIED"
                if result.verdict == "PROMOTED_TO_PAPER"
                else "AWAITING_EVIDENCE"
                if result.verdict == "NEEDS_MORE_EVIDENCE"
                else "REJECTED"
            )
            self._persist_folds(db, candidate, evidence)
            if result.verdict == "PROMOTED_TO_PAPER":
                promotion = self.champions.promote(db, candidate, validation)
                promoted_count += int(promotion.get("status") == "promoted")
            else:
                rejection_counts[result.verdict] += 1

        run.variants_examined = len(specifications)
        run.promoted_count = promoted_count
        run.rejection_counts_json = dict(rejection_counts)
        run.status = "COMPLETED"
        run.completed_at = datetime.utcnow()
        run.summary_json = {
            "new_candidates": len(new_candidates),
            "revalidated_candidates": len(evaluation_candidates) - len(new_candidates),
            "duplicate_candidates": len(specifications) - len(new_candidates),
            "rejection_counts": dict(rejection_counts),
            "promoted_count": promoted_count,
            "policy": "Only purged, cost-adjusted, multiple-testing-corrected evidence can promote.",
        }
        db.commit()
        return {
            "status": run.status,
            "run_id": run.id,
            "run_uid": run.run_uid,
            "variants_examined": len(specifications),
            "new_candidates": len(new_candidates),
            "revalidated_candidates": len(evaluation_candidates) - len(new_candidates),
            "rejection_counts": dict(rejection_counts),
            "promoted_to_paper": promoted_count,
        }

    @staticmethod
    def _candidate_replay_rows(
        db: Session,
        candidate: StrategyCandidateVariant,
        *,
        replay_cache: dict[tuple[str, tuple[str, ...]], list[HyperbolicReplayTrade]] | None = None,
    ) -> list[HyperbolicReplayTrade]:
        specification = dict(candidate.specification_json or {})
        if specification.get("evidence_binding") != "hyperbolic_replay_v1":
            return []
        expected_timeframes = tuple(candidate.timeframe_stack or [])
        exact_fingerprint = str(specification.get("strategy_fingerprint") or "")
        cache_key = (exact_fingerprint or candidate.setup_type, expected_timeframes)
        rows = replay_cache.get(cache_key) if replay_cache is not None else None
        if rows is None:
            stored_rows = db.scalars(
                select(HyperbolicReplayTrade)
                .where(
                    HyperbolicReplayTrade.setup_type == candidate.setup_type,
                    HyperbolicReplayTrade.state == "REPLAY_EVALUATED",
                    *(
                        (HyperbolicReplayTrade.strategy_fingerprint == exact_fingerprint,)
                        if exact_fingerprint
                        else ()
                    ),
                )
                .order_by(HyperbolicReplayTrade.decision_timestamp)
                .limit(5_000)
            ).all()
            rows = [
                row
                for row in stored_rows
                if tuple((row.decision_payload or {}).get("required_timeframes") or []) == expected_timeframes
            ]
            if replay_cache is not None:
                replay_cache[cache_key] = rows
        market_filter = str(specification.get("market_filter") or "all")
        if market_filter != "all":
            expected_market = market_filter.removesuffix("_only")
            rows = [row for row in rows if replay_market_bucket(row.market) == expected_market]
        regime_filter = str(specification.get("regime_filter") or "all")
        if regime_filter == "all":
            return list(rows)
        expected_regime = regime_filter.removesuffix("_only")
        return [
            row
            for row in rows
            if str((row.decision_payload or {}).get("regime") or "unknown") == expected_regime
        ]

    @staticmethod
    def _candidate_evidence(
        db: Session,
        candidate: StrategyCandidateVariant,
        *,
        replay_cache: dict[tuple[str, tuple[str, ...]], list[HyperbolicReplayTrade]] | None = None,
    ) -> dict:
        specification = dict(candidate.specification_json or {})
        binding = specification.get("evidence_binding")
        rows = AlphaStrategyFactory._candidate_replay_rows(db, candidate, replay_cache=replay_cache)
        returns = [float(row.r_multiple or 0.0) for row in rows]
        excess = [float(row.benchmark_excess) for row in rows if row.benchmark_excess is not None]
        windows = split_windows(returns, 3)
        tickers = sorted({row.ticker for row in rows if row.ticker})
        markets = sorted({row.market for row in rows if row.market})
        asset_classes = sorted(
            {
                str(value)
                for value in db.scalars(select(Asset.asset_type).where(Asset.ticker.in_(tickers))).all()
                if value
            }
        ) if tickers else []
        regimes = sorted({str((row.decision_payload or {}).get("regime") or "unknown") for row in rows})
        pnl_by_asset: dict[str, float] = defaultdict(float)
        for row in rows:
            pnl_by_asset[row.ticker] += max(0.0, float(row.net_pnl or 0.0))
        positive_total = sum(pnl_by_asset.values())
        contributions = {ticker: value / positive_total for ticker, value in pnl_by_asset.items()} if positive_total > 0 else {}
        raw_p = 1.0
        if len(returns) >= 2:
            test = ttest_1samp(returns, popmean=0.0, alternative="greater")
            raw_p = float(test.pvalue) if test.pvalue == test.pvalue else 1.0
        rank_pairs = [(index + 1, index + 1 if row["expectancy_r"] > 0 else len(windows)) for index, row in enumerate(windows)]
        costs_complete = bool(rows) and all(bool((row.execution_payload or {}).get("cost_profile")) for row in rows)
        quality = mean([float(row.data_quality_score or 0.0) for row in rows]) if rows else 0.0
        stability_by_window = [100.0 if row["expectancy_r"] > 0 else 0.0 for row in windows]
        stability_by_market = group_stability(rows, key=lambda row: replay_market_bucket(row.market))
        stability_by_regime = group_stability(
            rows,
            key=lambda row: str((row.decision_payload or {}).get("regime") or "unknown"),
        )
        stability_dimensions = [
            mean(values)
            for values in (stability_by_window, stability_by_market, stability_by_regime)
            if values
        ]
        return {
            "sample_size": len(rows),
            "returns_r": returns,
            "benchmark_excess_returns": excess,
            "markets": markets,
            "tickers": tickers,
            "regimes": regimes,
            "regime_filter": specification.get("regime_filter") or "all",
            "market_filter": specification.get("market_filter") or "all",
            "timestamps": [row.decision_timestamp for row in rows if row.decision_timestamp is not None],
            "windows": windows,
            "max_drawdown": max_drawdown(returns),
            "raw_p_value": raw_p,
            "overfitting_probability": backtest_overfitting_probability(rank_pairs, variants=max(2, len(windows))),
            "deflated_sharpe_probability": deflated_sharpe_probability(returns, trials=max(1, len(windows))),
            "stability_by_window": stability_by_window,
            "stability_by_market": stability_by_market,
            "stability_by_regime": stability_by_regime,
            "experimental_stability_score": min(stability_dimensions, default=0.0),
            "asset_pnl_contributions": contributions,
            "cost_coverage": 1.0 if costs_complete else 0.0,
            "data_quality_score": quality,
            "complexity": candidate.complexity,
            "timeframe_stack": list(candidate.timeframe_stack or []),
            "supported_asset_classes": asset_classes or ["Stock", "ETF"],
            "entry_rules": {"trigger": (candidate.specification_json or {}).get("entry_rule")},
            "stop_rules": {"method": (candidate.specification_json or {}).get("stop_rule")},
            "target_rules": {"method": (candidate.specification_json or {}).get("target_rule")},
            "certification_version": "alpha_strategy_factory_v1",
            "evidence_binding": binding,
            "evidence_binding_status": "EXECUTED_IMPLEMENTATION" if binding == "hyperbolic_replay_v1" else "IMPLEMENTATION_NOT_AVAILABLE",
            "strategy_fingerprint": specification.get("strategy_fingerprint"),
            "executable_strategy": specification.get("executable_strategy"),
        }

    @staticmethod
    def _has_new_evidence(db: Session, candidate: StrategyCandidateVariant) -> bool:
        if candidate.is_champion:
            return False
        validation = db.get(ReplayStrategyValidation, candidate.validation_id) if candidate.validation_id else None
        if validation is not None and (candidate.specification_json or {}).get("evidence_binding") != "hyperbolic_replay_v1":
            return False
        current_sample = len(AlphaStrategyFactory._candidate_replay_rows(db, candidate))
        return validation is None or current_sample != int(validation.sample_size or 0)

    @staticmethod
    def _persist_folds(db: Session, candidate: StrategyCandidateVariant, evidence: dict) -> None:
        existing = int(
            db.scalar(select(func.count(StrategyValidationFold.id)).where(StrategyValidationFold.candidate_id == candidate.id))
            or 0
        )
        if existing:
            return
        rows = evidence.get("timestamps") or []
        if not rows:
            trades = AlphaStrategyFactory._candidate_replay_rows(db, candidate)
            rows = [trade.decision_timestamp for trade in trades]
        rows = sorted({timestamp for timestamp in rows if timestamp is not None})
        if len(rows) < 12:
            return
        for fold in build_purged_folds(rows, n_splits=3, purge_bars=5, embargo_bars=3):
            db.add(
                StrategyValidationFold(
                    candidate_id=candidate.id,
                    fold_number=fold.fold_number,
                    train_start=fold.train_start,
                    train_end=fold.train_end,
                    validation_start=fold.validation_start,
                    validation_end=fold.validation_end,
                    purge_bars=fold.purge_bars,
                    embargo_bars=fold.embargo_bars,
                    train_count=len(fold.train_indices),
                    validation_count=len(fold.validation_indices),
                    metrics_json={"embargo_end_index": fold.embargo_end_index},
                    coverage_json={"timeframe_stack": list(candidate.timeframe_stack or [])},
                    warnings_json=[],
                )
            )


def factory_hypothesis_key(families: list[str]) -> str:
    if len(families) == 1 and len(families[0]) <= 80:
        return families[0]
    serialized = ",".join(families)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]
    return f"multi_family:{len(families)}:{digest}"


def strategy_fingerprint(specification: dict) -> str:
    canonical = json.dumps(specification, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def split_windows(values: list[float], count: int) -> list[dict]:
    if not values:
        return []
    size = max(1, len(values) // max(1, count))
    output = []
    for start in range(0, len(values), size):
        subset = values[start : start + size]
        if subset:
            output.append({"id": f"w{len(output) + 1}", "sample_size": len(subset), "expectancy_r": round(mean(subset), 8)})
    return output[:count]


def group_stability(rows: list[HyperbolicReplayTrade], *, key) -> list[float]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(key(row))].append(float(row.r_multiple or 0.0))
    return [100.0 if mean(values) > 0 else 0.0 for values in groups.values()]


def replay_market_bucket(value: str | None) -> str:
    market = str(value or "").strip().upper()
    if market in {"USA", "US", "UNITED STATES", "NASDAQ", "NYSE"}:
        return "usa"
    if market in {"EUROPE", "FRANCE", "GERMANY", "ITALY", "SPAIN", "NETHERLANDS", "UNITED KINGDOM", "UK"}:
        return "europe"
    return market.lower()


def max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return round(drawdown, 8)


def strategy_factory_snapshot(db: Session) -> dict:
    verdict_rows = db.execute(
        select(StrategyCandidateVariant.final_verdict, func.count(StrategyCandidateVariant.id)).group_by(StrategyCandidateVariant.final_verdict)
    ).all()
    verdicts = {str(verdict or "PENDING"): int(count) for verdict, count in verdict_rows}
    latest = db.scalar(select(StrategyFactoryRun).order_by(desc(StrategyFactoryRun.started_at), desc(StrategyFactoryRun.id)).limit(1))
    promotions = int(db.scalar(select(func.count(StrategyCandidateVariant.id)).where(StrategyCandidateVariant.is_champion.is_(True))) or 0)
    examined = int(db.scalar(select(func.count(StrategyCandidateVariant.id))) or 0)
    rejected = {key: value for key, value in verdicts.items() if key.startswith("REJECTED") or key == "NEEDS_MORE_EVIDENCE"}
    primary_blocker = max(rejected.items(), key=lambda item: item[1])[0] if rejected else None
    return {
        "status": "READY" if latest else "NO_FACTORY_RUNS",
        "examined_variants": examined,
        "rejection_counts": rejected,
        "promoted_to_paper": promotions,
        "champions": promotions,
        "challengers": max(0, int(verdicts.get("PROMOTED_TO_PAPER", 0)) - promotions),
        "primary_blocker": primary_blocker,
        "latest_run_at": latest.completed_at.isoformat() if latest and latest.completed_at else None,
        "latest_run_status": latest.status if latest else None,
        "policy": "Promotion requires purged walk-forward, realistic costs, robustness, concentration, and multiple-testing gates.",
    }
