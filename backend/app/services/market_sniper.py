from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
from statistics import mean, median

import pandas as pd
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    ExecutionSimulation,
    ExitSignal,
    HistoricalPrediction,
    MarketRegimeSnapshot,
    NoTradeDecision,
    PortfolioRiskContext,
    PredictionOutcome,
    PriceHistory,
    RMultipleMetric,
    SetupLibrary,
    SignalReliabilityMatrix,
    SignalSnapshot,
    SniperScore,
    TradePlan,
    TradePlanOutcome,
)
from app.services.market_data import market_snapshot_for_asset
from app.services.technical_analysis_engine import TechnicalAnalysisEngine


settings = get_settings()

SNIPER_DISCLAIMER = "Informational trading scenario, not financial advice. No automatic trade execution is performed."
SETUP_TYPES = {
    "momentum_breakout",
    "pullback_to_trend",
    "trend_continuation",
    "reversal_from_support",
    "volatility_squeeze",
    "earnings_momentum",
    "post_earnings_drift",
    "gap_and_go",
    "failed_breakout",
    "mean_reversion",
    "sector_rotation_entry",
    "narrative_acceleration",
    "defensive_rotation",
    "avoid_no_edge",
}


@dataclass
class PriceContext:
    frame: pd.DataFrame
    latest_price: float | None
    latest_date: date | None
    row_count: int
    data_quality_score: float


class MarketRegimeService:
    """Classifies the market environment used to judge actionability."""

    benchmark_tickers = ["SPY", "VTI", "QQQ", "IWM"]
    sector_tickers = ["XLK", "XLF", "XLV", "XLE", "SMH", "XAR", "ICLN", "HACK"]

    def classify(self, db: Session, as_of: date | None = None, persist: bool = True) -> dict:
        as_of = as_of or latest_global_price_date(db) or datetime.utcnow().date()
        benchmark_blocks = {ticker: self.market_block(db, ticker, as_of) for ticker in self.benchmark_tickers}
        sector_blocks = {ticker: self.market_block(db, ticker, as_of) for ticker in self.sector_tickers}
        usable = [block for block in benchmark_blocks.values() if block["status"] == "ready"]
        risk_score = mean([block["risk_score"] for block in usable]) if usable else 50.0
        trend_score = mean([block["trend_score"] for block in usable]) if usable else 50.0
        volatility_score = mean([block["volatility_score"] for block in usable]) if usable else 50.0
        drawdown = mean([block["drawdown_pct"] for block in usable]) if usable else 0.0
        breadth = self.breadth_state(db, as_of)
        rotation = self.sector_rotation(sector_blocks)

        primary = "range_bound"
        if risk_score >= 62 and trend_score >= 58:
            primary = "risk_on"
        if trend_score >= 65:
            primary = "trend_up"
        if trend_score <= 38 or drawdown <= -12:
            primary = "trend_down"
        if risk_score <= 38 or drawdown <= -10:
            primary = "risk_off"
        if volatility_score >= 68:
            primary = "high_volatility"
        if rotation["score"] >= 67 and primary not in {"risk_off", "high_volatility"}:
            primary = "sector_rotation"

        secondary = "low_volatility" if volatility_score <= 38 else "high_volatility" if volatility_score >= 65 else "range_bound"
        if breadth["score"] >= 60 and primary in {"risk_on", "trend_up"}:
            secondary = "liquidity_expansion"
        elif breadth["score"] <= 38 or primary == "risk_off":
            secondary = "liquidity_contraction"

        confidence = clamp(45 + len(usable) * 8 + breadth["coverage"] * 0.12 + min(12, rotation["coverage"] * 2))
        payload = {
            "date": as_of.isoformat(),
            "regime_primary": primary,
            "regime_secondary": secondary,
            "volatility_state": secondary if "volatility" in secondary else ("high_volatility" if volatility_score >= 65 else "low_volatility" if volatility_score <= 38 else "normal"),
            "breadth_state": breadth["state"],
            "risk_appetite_score": round(risk_score, 2),
            "sector_rotation_score": rotation["score"],
            "confidence": round(confidence, 2),
            "data_sources": {
                "benchmarks": benchmark_blocks,
                "sectors": sector_blocks,
                "breadth": breadth,
                "rotation": rotation,
                "policy": "Regime is derived from stored public OHLCV only; missing proxies lower confidence.",
            },
        }
        if persist:
            db.add(
                MarketRegimeSnapshot(
                    date=as_of,
                    regime_primary=payload["regime_primary"],
                    regime_secondary=payload["regime_secondary"],
                    volatility_state=payload["volatility_state"],
                    breadth_state=payload["breadth_state"],
                    risk_appetite_score=payload["risk_appetite_score"],
                    sector_rotation_score=payload["sector_rotation_score"],
                    confidence=payload["confidence"],
                    data_sources=payload["data_sources"],
                )
            )
            db.flush()
        return payload

    def market_block(self, db: Session, ticker: str, as_of: date) -> dict:
        asset = db.scalar(select(Asset).where(Asset.ticker == ticker).limit(1))
        if not asset:
            return {"ticker": ticker, "status": "missing_asset"}
        frame = price_frame(
            db.scalars(
                select(PriceHistory)
                .where(PriceHistory.asset_id == asset.id, PriceHistory.date <= as_of)
                .order_by(PriceHistory.date)
            ).all()
        )
        if frame.empty or len(frame) < 60:
            return {"ticker": ticker, "status": "insufficient_ohlcv", "rows": len(frame)}
        close = frame["close"].astype(float)
        latest = float(close.iloc[-1])
        sma50 = float(close.tail(50).mean())
        sma200 = float(close.tail(min(200, len(close))).mean())
        ret_1m = pct(float(close.iloc[-22]), latest) if len(close) > 22 else 0.0
        ret_3m = pct(float(close.iloc[-64]), latest) if len(close) > 64 else ret_1m
        vol = float(close.pct_change().tail(30).std() * math.sqrt(252) * 100)
        high_126 = float(close.tail(min(126, len(close))).max())
        drawdown = (latest / high_126 - 1) * 100 if high_126 else 0.0
        trend_score = 50 + (12 if latest > sma50 else -12) + (12 if latest > sma200 else -12) + clamp(ret_3m, -18, 18)
        risk_score = 50 + clamp(ret_1m, -18, 18) + clamp(ret_3m / 2, -12, 12) + (8 if latest > sma50 else -8) + clamp(drawdown / 2, -14, 0)
        volatility_score = clamp(30 + vol * 1.2)
        return {
            "ticker": ticker,
            "status": "ready",
            "latest_date": str(frame["date"].iloc[-1]),
            "latest_price": round(latest, 4),
            "ret_1m": round(ret_1m, 3),
            "ret_3m": round(ret_3m, 3),
            "drawdown_pct": round(drawdown, 3),
            "trend_score": round(clamp(trend_score), 2),
            "risk_score": round(clamp(risk_score), 2),
            "volatility_score": round(volatility_score, 2),
        }

    def breadth_state(self, db: Session, as_of: date) -> dict:
        assets = db.scalars(select(Asset).where(Asset.is_active.is_(True), Asset.asset_type.in_(["Stock", "ETF"])).limit(220)).all()
        covered = 0
        above = 0
        for asset in assets:
            rows = db.scalars(
                select(PriceHistory)
                .where(PriceHistory.asset_id == asset.id, PriceHistory.date <= as_of)
                .order_by(desc(PriceHistory.date))
                .limit(80)
            ).all()
            if len(rows) < 50:
                continue
            frame = price_frame(list(reversed(rows)))
            last = float(frame["close"].iloc[-1])
            sma50 = float(frame["close"].astype(float).tail(50).mean())
            covered += 1
            if last >= sma50:
                above += 1
        ratio = above / covered if covered else 0.0
        state = "expanding" if ratio >= 0.58 else "contracting" if ratio <= 0.42 else "mixed"
        return {"state": state, "score": round(ratio * 100, 2), "coverage": covered, "above_sma50": above}

    def sector_rotation(self, sector_blocks: dict[str, dict]) -> dict:
        ready = [block for block in sector_blocks.values() if block.get("status") == "ready"]
        returns = [safe_float(block.get("ret_1m")) for block in ready]
        if len(returns) < 3:
            return {"score": 50.0, "coverage": len(ready), "leaders": [], "laggards": []}
        dispersion = max(returns) - min(returns)
        leaders = sorted(ready, key=lambda item: item.get("ret_1m", 0), reverse=True)[:3]
        laggards = sorted(ready, key=lambda item: item.get("ret_1m", 0))[:3]
        return {
            "score": round(clamp(40 + dispersion * 2.2), 2),
            "coverage": len(ready),
            "leaders": [{"ticker": item["ticker"], "ret_1m": item["ret_1m"]} for item in leaders],
            "laggards": [{"ticker": item["ticker"], "ret_1m": item["ret_1m"]} for item in laggards],
        }


class SetupClassifierService:
    """Maps technical evidence into a contextual setup class."""

    def classify(self, db: Session, asset: Asset, technical: dict, signal: SignalSnapshot | None, regime: dict) -> dict:
        if technical.get("status") != "ready":
            return self.setup("avoid_no_edge", 15, "not_valid", "No professional setup without enough OHLCV.", "No invalidation without price structure.", "none", 20, ["insufficient_price_history"])

        trend = technical.get("trend_direction")
        momentum = technical.get("momentum") or {}
        volume = technical.get("volume") or {}
        volatility = technical.get("volatility") or {}
        levels = technical.get("levels") or {}
        indicators = technical.get("technical_indicators") or {}
        breakout = as_score(technical.get("breakout_probability"))
        pullback = as_score(technical.get("pullback_quality"))
        trend_strength = safe_float(technical.get("trend_strength_score"))
        relative_volume = safe_float(volume.get("relative_volume"))
        rsi = safe_float(indicators.get("rsi"))
        price = safe_float(technical.get("last_price"))
        resistance = safe_float(levels.get("nearest_resistance"))
        support = safe_float(levels.get("nearest_support"))
        near_resistance = resistance > 0 and price > 0 and abs(pct(price, resistance)) <= 3.0
        near_support = support > 0 and price > 0 and abs(pct(price, support)) <= 4.0
        signal_class = (signal.classification if signal else "").lower()

        setup_type = "avoid_no_edge"
        quality = 35.0
        maturity = "developing"
        failure_modes = ["conflicting_signals", "data_quality_poor"]

        if "narrative" in signal_class and trend not in {"downtrend", "downtrend_attempt"}:
            setup_type = "narrative_acceleration"
            quality = 58 + min(18, relative_volume * 5) + (8 if regime.get("regime_primary") in {"risk_on", "trend_up", "sector_rotation"} else -8)
            failure_modes = ["sentiment_overcrowded", "narrative_without_price_confirmation"]
        if volatility.get("volatility_compression"):
            setup_type = "volatility_squeeze"
            quality = max(quality, 58 + breakout * 0.22)
            failure_modes = ["failed_confirmation", "volatility_expansion_without_direction"]
        if breakout >= 68 and near_resistance and trend in {"uptrend", "uptrend_attempt", "range_or_consolidation"}:
            setup_type = "momentum_breakout"
            quality = max(quality, 48 + breakout * 0.34 + min(16, relative_volume * 6))
            maturity = "confirmed_watch" if relative_volume >= 1.2 else "needs_volume"
            failure_modes = ["false_breakout", "weak_volume_confirmation", "entry_too_late"]
        if pullback >= 66 and trend in {"uptrend", "uptrend_attempt"} and near_support:
            setup_type = "pullback_to_trend"
            quality = max(quality, 50 + pullback * 0.35 + (8 if 38 <= rsi <= 62 else -5))
            maturity = "early" if rsi <= 62 else "late"
            failure_modes = ["trend_break", "catching_falling_knife", "support_failure"]
        if trend == "uptrend" and momentum.get("state") in {"improving", "extended_positive"} and relative_volume >= 1.0:
            setup_type = "trend_continuation" if setup_type == "avoid_no_edge" else setup_type
            quality = max(quality, 50 + trend_strength * 0.34 + min(10, relative_volume * 3))
            failure_modes = ["momentum_decay", "late_stage_extension"]
        if trend in {"downtrend", "downtrend_attempt"} and near_support and "bullish" in str(technical.get("divergences", {})):
            setup_type = "reversal_from_support"
            quality = max(quality, 46 + pullback * 0.25)
            maturity = "confirmation_required"
            failure_modes = ["falling_knife", "failed_reclaim", "market_regime_hostile"]
        if trend in {"downtrend", "downtrend_attempt"} and not near_support:
            setup_type = "avoid_no_edge"
            quality = min(quality, 38)
            failure_modes = ["trend_down", "no_clean_invalidation"]

        reliability = historical_reliability(db, setup_type, asset.sector or "Unknown", regime.get("regime_primary", "all"))
        required_confirmation = confirmation_for(setup_type, levels, volume)
        invalidation_logic = invalidation_for(setup_type, levels, technical)
        best_timeframe = best_timeframe_for(setup_type)
        if rsi >= 78 and setup_type in {"momentum_breakout", "trend_continuation"}:
            maturity = "late"
            quality -= 10
            failure_modes.append("overbought_signal_ignored")
        return self.setup(setup_type, quality, maturity, required_confirmation, invalidation_logic, best_timeframe, reliability, failure_modes)

    def setup(self, setup_type: str, quality: float, maturity: str, confirmation: str, invalidation: str, timeframe: str, reliability: float, failures: list[str]) -> dict:
        return {
            "setup_type": setup_type if setup_type in SETUP_TYPES else "avoid_no_edge",
            "setup_quality_score": round(clamp(quality), 2),
            "setup_maturity": maturity,
            "required_confirmation": confirmation,
            "invalidation_logic": invalidation,
            "best_timeframe": timeframe,
            "historical_reliability": round(clamp(reliability), 2),
            "regime_sensitivity": regime_sensitivity(setup_type),
            "common_failure_modes": sorted(set(failures)),
        }


class RiskEngine:
    def assess(self, asset: Asset, technical: dict, signal: SignalSnapshot | None, regime: dict, setup: dict) -> dict:
        if technical.get("status") != "ready":
            return {"total_risk_score": 92, "position_risk_class": "avoid", "avoid_reason": "insufficient verified OHLCV for risk model"}
        price = safe_float(technical.get("last_price"))
        indicators = technical.get("technical_indicators") or {}
        volatility = technical.get("volatility") or {}
        volume = technical.get("volume") or {}
        levels = technical.get("levels") or {}
        invalidation = safe_float(levels.get("invalidation_level"))
        atr_pct = safe_float(indicators.get("atr_percent") or volatility.get("atr_percent"))
        distance_to_invalidation = abs(pct(price, invalidation)) if price and invalidation else 12.0
        liquidity = liquidity_bucket(price, safe_float(volume.get("latest_volume")))
        regime_risk = 24 if regime.get("regime_primary") in {"risk_off", "high_volatility", "trend_down"} else 10 if regime.get("regime_primary") == "range_bound" else 4
        volatility_risk = clamp(atr_pct * 8 + safe_float(volatility.get("realized_volatility_30d")) * 0.65)
        liquidity_risk = {"high": 4, "medium": 12, "low": 24, "unknown": 18}.get(liquidity, 18)
        gap_risk = 14 if abs(safe_float((technical.get("gap_detection") or {}).get("latest_gap_pct"))) >= 2.0 else 4
        signal_risk = 18 if signal and str(signal.risk_level).lower() == "high" else 10 if signal else 14
        rr = technical.get("risk_reward_estimate") or {}
        rr_score = safe_float(rr.get("reward_to_risk"))
        risk_reward_penalty = 20 if rr_score and rr_score < 1.0 else 10 if not rr_score else 0
        total = clamp(distance_to_invalidation * 3.5 + volatility_risk * 0.35 + liquidity_risk + gap_risk + regime_risk + signal_risk + risk_reward_penalty)
        risk_class = "conservative" if total < 38 else "balanced" if total < 58 else "aggressive" if total < 76 else "avoid"
        max_risk = 0.25 if risk_class == "conservative" else 0.5 if risk_class == "balanced" else 0.75 if risk_class == "aggressive" else 0.0
        position_size = max(0.0, round(max_risk / max(0.25, distance_to_invalidation / 100), 3)) if max_risk else 0.0
        avoid_reason = ""
        if risk_class == "avoid":
            avoid_reason = f"Risk is too high: invalidation distance {distance_to_invalidation:.2f}%, ATR {atr_pct:.2f}% and regime {regime.get('regime_primary')}."
        return {
            "atr_risk": round(atr_pct, 3),
            "distance_to_invalidation_pct": round(distance_to_invalidation, 3),
            "volatility_risk": round(volatility_risk, 2),
            "liquidity_risk": liquidity_risk,
            "liquidity_bucket": liquidity,
            "gap_risk": gap_risk,
            "earnings_event_risk": "not_scheduled_in_demo_context",
            "correlation_risk": "portfolio_context_required",
            "market_regime_risk": regime_risk,
            "sector_risk": "tracked_through_regime_and_sector_reliability",
            "valuation_risk": "fundamental_snapshot_required",
            "sentiment_crowding_risk": "tracked_by_narrative_layer",
            "total_risk_score": round(total, 2),
            "position_risk_class": risk_class,
            "max_risk_per_trade_suggestion": f"{max_risk:.2f}% educational max-loss budget",
            "volatility_adjusted_position_size": position_size,
            "risk_reward_score": round(clamp((rr_score or 0) * 32), 2),
            "avoid_reason": avoid_reason,
        }


class EntryExitEngine:
    def plan(self, asset: Asset, technical: dict, setup: dict, risk: dict, regime: dict) -> dict:
        price = safe_float(technical.get("last_price"))
        levels = technical.get("levels") or {}
        indicators = technical.get("technical_indicators") or {}
        volatility = technical.get("volatility") or {}
        setup_type = setup["setup_type"]
        support = safe_float(levels.get("nearest_support"))
        resistance = safe_float(levels.get("nearest_resistance"))
        atr = price * safe_float(indicators.get("atr_percent") or volatility.get("atr_percent")) / 100 if price else 0.0
        atr = atr or (price * 0.025 if price else 0.0)

        if setup_type == "momentum_breakout":
            anchor = resistance or price
            entry_zone = zone(anchor * 0.995, anchor * 1.012)
            trigger = f"Close above {round(anchor, 4)} with relative volume > 1.5x and no broad-market risk-off deterioration."
            invalidation = max(0.01, min(support or anchor - atr * 1.5, anchor - atr * 1.2))
            target_1 = anchor + atr * 2.0
            target_2 = anchor + atr * 3.5
            stop_logic = "Close back below breakout level or ATR-adjusted stop invalidates the breakout thesis."
        elif setup_type == "pullback_to_trend":
            anchor = support or (price - atr)
            entry_zone = zone(anchor, anchor + atr * 0.8)
            trigger = "Bullish reversal from support/MA area with stabilizing volume and no fresh lower low."
            invalidation = max(0.01, anchor - atr * 1.2)
            target_1 = resistance or price + atr * 2.0
            target_2 = (resistance or price) + atr * 3.2
            stop_logic = "Close below support or MA50 area invalidates the pullback thesis."
        elif setup_type == "reversal_from_support":
            anchor = support or price
            entry_zone = zone(anchor, anchor + atr)
            trigger = "Reclaim support plus positive divergence confirmation; avoid catching an unconfirmed falling knife."
            invalidation = max(0.01, anchor - atr * 1.4)
            target_1 = price + atr * 2.0
            target_2 = resistance or price + atr * 3.0
            stop_logic = "Failure to hold reclaimed support invalidates the reversal."
        else:
            entry_zone = zone(price * 0.99 if price else None, price * 1.01 if price else None)
            trigger = setup.get("required_confirmation", "Wait for independent confirmation before treating this as active.")
            invalidation = support or (price - atr * 1.5 if price else None)
            target_1 = resistance or (price + atr * 2 if price else None)
            target_2 = (target_1 + atr * 1.8) if target_1 else None
            stop_logic = setup.get("invalidation_logic", "No clean setup without explicit invalidation.")

        rr = risk_reward(price, invalidation, target_1)
        no_trade = []
        if risk.get("avoid_reason"):
            no_trade.append(risk["avoid_reason"])
        no_trade.extend(default_no_trade_conditions(setup_type))
        return {
            "entry_zone": entry_zone,
            "entry_trigger": trigger,
            "confirmation_condition": setup.get("required_confirmation", trigger),
            "invalidation_level": round_float(invalidation),
            "stop_logic": stop_logic,
            "target_1": round_float(target_1),
            "target_2": round_float(target_2),
            "trailing_exit_logic": "Trail with 2.0x ATR after target 1 or when price closes below EMA21 after an extended move.",
            "partial_exit_logic": "Educational scenario: partial risk reduction can be modeled near target 1; not an order instruction.",
            "no_trade_conditions": no_trade,
            "timeframe": setup.get("best_timeframe", "short/medium"),
            "expected_holding_period": holding_period_for(setup_type),
            "risk_reward_estimate": rr,
            "confidence": round(clamp((setup.get("setup_quality_score", 0) * 0.42) + (setup.get("historical_reliability", 50) * 0.28) + (100 - risk.get("total_risk_score", 50)) * 0.3), 2),
            "historical_setup_reliability": setup.get("historical_reliability", 50),
            "disclaimer": SNIPER_DISCLAIMER,
        }


class NoTradeFilter:
    def evaluate(self, technical: dict, setup: dict, risk: dict, plan: dict, regime: dict) -> list[dict]:
        reasons = []
        rr = safe_float((plan.get("risk_reward_estimate") or {}).get("reward_to_risk"))
        indicators = technical.get("technical_indicators") or {}
        volume = technical.get("volume") or {}
        rsi = safe_float(indicators.get("rsi"))
        if setup["setup_type"] == "avoid_no_edge":
            reasons.append(self.reason("No clean edge: setup classifier returned avoid_no_edge.", "high", setup_type=setup["setup_type"]))
        if rr and rr < 1.15:
            reasons.append(self.reason(f"Risk/reward is weak at {rr:.2f}R.", "high", reward_to_risk=rr))
        if safe_float(risk.get("distance_to_invalidation_pct")) > 9:
            reasons.append(self.reason(f"Invalidation is too wide at {risk.get('distance_to_invalidation_pct')}%.", "high", risk=risk))
        if rsi >= 78:
            reasons.append(self.reason(f"RSI is extremely extended at {rsi:.1f} without enough consolidation.", "medium", rsi=rsi))
        if safe_float(volume.get("relative_volume")) < 0.65:
            reasons.append(self.reason("Relative volume is low; confirmation quality is weak.", "medium", relative_volume=volume.get("relative_volume")))
        if regime.get("regime_primary") in {"risk_off", "high_volatility", "trend_down"} and setup["setup_type"] in {"momentum_breakout", "trend_continuation"}:
            reasons.append(self.reason(f"Market regime is hostile for breakout risk: {regime.get('regime_primary')}.", "high", regime=regime))
        if setup.get("historical_reliability", 50) < 42:
            reasons.append(self.reason("Similar setup reliability is weak in stored BLUM history.", "medium", reliability=setup.get("historical_reliability")))
        if risk.get("position_risk_class") == "avoid":
            reasons.append(self.reason(risk.get("avoid_reason") or "Risk engine rejects this setup.", "high", risk=risk))
        return dedupe_reasons(reasons)

    def reason(self, reason: str, severity: str, **conditions: object) -> dict:
        return {"reason": reason, "severity": severity, "conditions": conditions}


class ExitEngine:
    def evaluate(self, asset: Asset, technical: dict, plan: dict, setup: dict, risk: dict) -> list[dict]:
        if technical.get("status") != "ready":
            return []
        price = safe_float(technical.get("last_price"))
        indicators = technical.get("technical_indicators") or {}
        momentum = technical.get("momentum") or {}
        volume = technical.get("volume") or {}
        invalidation = safe_float(plan.get("invalidation_level"))
        target_1 = safe_float(plan.get("target_1"))
        signals = []
        if invalidation and price and price <= invalidation:
            signals.append(self.signal("stop_invalidation_exit", "exit_or_reduce", 88, "Price is at or below technical invalidation.", {"price": price, "invalidation": invalidation}))
        if target_1 and price and price >= target_1:
            signals.append(self.signal("partial_profit_at_target_1", "reduce_or_review", 72, "Target 1 zone reached; reassess risk/reward.", {"price": price, "target_1": target_1}))
        if momentum.get("state") in {"weakening", "oversold"} and safe_float(indicators.get("macd_hist")) < 0:
            signals.append(self.signal("momentum_decay_exit", "reduce_or_watch", 64, "Momentum has weakened and MACD histogram is negative.", {"momentum": momentum}))
        if safe_float(volume.get("relative_volume")) >= 2.5 and safe_float(indicators.get("rsi")) >= 76:
            signals.append(self.signal("volume_climax_exit", "reduce_or_review", 68, "High volume plus stretched RSI can mark exhaustion risk.", {"volume": volume, "rsi": indicators.get("rsi")}))
        return signals

    def signal(self, exit_type: str, action: str, confidence: float, reason: str, evidence: dict) -> dict:
        return {"exit_type": exit_type, "action": action, "confidence": confidence, "reason": reason, "evidence": evidence}


class ExecutionSimulatorService:
    """Tests whether historical trade plans were executable using stored future OHLCV."""

    def simulate_from_predictions(self, db: Session, ticker: str | None = None, limit: int = 120, persist: bool = True) -> dict:
        query = (
            select(HistoricalPrediction, PredictionOutcome)
            .join(PredictionOutcome, PredictionOutcome.prediction_id == HistoricalPrediction.id)
            .order_by(desc(HistoricalPrediction.created_at))
            .limit(limit)
        )
        if ticker:
            query = (
                select(HistoricalPrediction, PredictionOutcome)
                .join(PredictionOutcome, PredictionOutcome.prediction_id == HistoricalPrediction.id)
                .where(HistoricalPrediction.ticker == ticker.upper())
                .order_by(desc(HistoricalPrediction.created_at))
                .limit(limit)
            )
        rows = db.execute(query).all()
        simulations = []
        for prediction, outcome in rows:
            technical = ((prediction.point_in_time_context or {}).get("technical") or {})
            setup_type = infer_setup_type_from_prediction(prediction, technical)
            r_value = r_multiple_from_outcome(outcome)
            sim = {
                "ticker": prediction.ticker,
                "prediction_id": prediction.id,
                "setup_type": setup_type,
                "timeframe": outcome.timeframe,
                "entry_model": "entry_at_close_or_trigger_proxy",
                "exit_model": "invalidation_target_time_stop_proxy",
                "realized_r_multiple": r_value,
                "max_adverse_excursion": outcome.max_adverse_excursion,
                "max_favorable_excursion": outcome.max_favorable_excursion,
                "time_in_trade": outcome.horizon_days,
                "stop_hit": bool(outcome.invalidation_hit),
                "target_hit": bool(outcome.target_hit),
                "trailing_exit_hit": bool(outcome.target_hit and outcome.max_favorable_excursion and outcome.max_favorable_excursion > 6),
                "missed_entry": bool(outcome.missed_opportunity),
                "false_breakout": bool(outcome.false_positive),
                "failed_confirmation": bool(outcome.outcome_label == "wrong" and not outcome.target_hit),
                "opportunity_cost": outcome.realized_return if outcome.missed_opportunity else 0,
                "policy": "Historical execution simulation uses stored prediction/outcome rows and never uses future data before prediction persistence.",
            }
            simulations.append(sim)
            if persist:
                db.add(
                    ExecutionSimulation(
                        prediction_id=prediction.id,
                        ticker=prediction.ticker,
                        setup_type=setup_type,
                        simulation_mode="historical_learning_loop",
                        entry_model=sim["entry_model"],
                        exit_model=sim["exit_model"],
                        realized_r_multiple=r_value,
                        max_adverse_excursion=outcome.max_adverse_excursion,
                        max_favorable_excursion=outcome.max_favorable_excursion,
                        time_in_trade=outcome.horizon_days,
                        stop_hit=sim["stop_hit"],
                        target_hit=sim["target_hit"],
                        trailing_exit_hit=sim["trailing_exit_hit"],
                        missed_entry=sim["missed_entry"],
                        false_breakout=sim["false_breakout"],
                        failed_confirmation=sim["failed_confirmation"],
                        opportunity_cost=sim["opportunity_cost"],
                        simulation_payload=sim,
                    )
                )
        if persist and simulations:
            update_r_metrics(db, simulations)
            update_signal_reliability_matrix(db, rows, simulations)
            db.flush()
        return {
            "status": "ok" if simulations else "insufficient_history",
            "simulations": simulations[:80],
            "summary": r_summary(simulations),
            "guardrails": [
                "No look-ahead data is used before historical prediction save.",
                "R-multiple learning values expectancy over raw win rate.",
                "Small samples are marked as unreliable.",
            ],
        }


class PortfolioRiskContextService:
    def snapshot(self, db: Session, candidates: list[dict], persist: bool = False) -> dict:
        sector_counts: dict[str, int] = defaultdict(int)
        theme_counts: dict[str, int] = defaultdict(int)
        actionability_counts: dict[str, int] = defaultdict(int)
        for item in candidates:
            sector_counts[item.get("asset", {}).get("sector") or item.get("sector") or "Unknown"] += 1
            actionability_counts[item.get("actionability", "unknown")] += 1
            for theme in ((item.get("narrative") or {}).get("themes") or []):
                theme_counts[str(theme)] += 1
        payload = {
            "context_name": "default_research_book",
            "sector_concentration": dict(sorted(sector_counts.items(), key=lambda kv: kv[1], reverse=True)),
            "factor_concentration": {"actionability": dict(actionability_counts)},
            "correlation": {"policy": "Pairwise correlation requires portfolio holdings and longer synchronized histories."},
            "beta": {"policy": "Beta is evaluated at asset level when benchmark history is available."},
            "volatility_contribution": {"policy": "Volatility contribution is informational without real portfolio weights."},
            "overlapping_etf_exposure": {"policy": "ETF overlap is tracked as future portfolio metadata."},
            "max_simultaneous_setups": 8,
            "risk_per_theme": dict(sorted(theme_counts.items(), key=lambda kv: kv[1], reverse=True)),
            "risk_per_regime": {"current": candidates[0].get("market_regime") if candidates else "unknown"},
        }
        if persist:
            db.add(PortfolioRiskContext(**payload))
            db.flush()
        return payload


class MarketSniperEngine:
    def __init__(self) -> None:
        self.regime_service = MarketRegimeService()
        self.classifier = SetupClassifierService()
        self.risk = RiskEngine()
        self.plans = EntryExitEngine()
        self.no_trade = NoTradeFilter()
        self.exits = ExitEngine()
        self.simulator = ExecutionSimulatorService()
        self.portfolio = PortfolioRiskContextService()

    def status(self, db: Session) -> dict:
        latest = db.scalar(select(SniperScore).order_by(desc(SniperScore.created_at)).limit(1))
        counts = {
            "sniper_scores": int(db.scalar(select(func.count(SniperScore.id))) or 0),
            "trade_plans": int(db.scalar(select(func.count(TradePlan.id))) or 0),
            "execution_simulations": int(db.scalar(select(func.count(ExecutionSimulation.id))) or 0),
            "r_multiple_metrics": int(db.scalar(select(func.count(RMultipleMetric.id))) or 0),
            "no_trade_decisions": int(db.scalar(select(func.count(NoTradeDecision.id))) or 0),
            "exit_signals": int(db.scalar(select(func.count(ExitSignal.id))) or 0),
        }
        return {
            "status": "active",
            "engine": "BLUM Market Sniper Engine",
            "version": "market-sniper-v1",
            "latest_score": serialize_sniper_score(latest) if latest else None,
            "counts": counts,
            "guardrails": guardrails(),
            "disclaimer": SNIPER_DISCLAIMER,
        }

    def candidates(self, db: Session, limit: int = 40, persist: bool = False) -> dict:
        assets = self.candidate_assets(db, limit=limit)
        results = [self.evaluate_asset(db, asset, persist=persist) for asset in assets]
        results = sorted(results, key=lambda item: item.get("sniper_score", 0), reverse=True)
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "market_regime": self.regime_service.classify(db, persist=False),
            "summary": self.summary(results),
            "candidates": results,
            "sections": {
                "active_setups": [item for item in results if item.get("actionability") == "active_setup"],
                "wait_for_trigger": [item for item in results if item.get("actionability") in {"wait_for_trigger", "actionable_if_confirmed"}],
                "avoid_list": [item for item in results if item.get("actionability") == "avoid"],
                "best_risk_reward": sorted(results, key=lambda item: safe_float((item.get("trade_plan") or {}).get("risk_reward_estimate", {}).get("reward_to_risk")), reverse=True)[:10],
            },
            "portfolio_context": self.portfolio.snapshot(db, results),
            "disclaimer": SNIPER_DISCLAIMER,
        }

    def candidate(self, db: Session, ticker: str, persist: bool = False) -> dict:
        asset = db.scalar(select(Asset).where(Asset.ticker == ticker.upper()).limit(1))
        if not asset:
            raise ValueError(f"Unknown ticker: {ticker}")
        return self.evaluate_asset(db, asset, persist=persist)

    def evaluate(self, db: Session, tickers: list[str] | None = None, limit: int = 40) -> dict:
        assets = []
        if tickers:
            assets = db.scalars(select(Asset).where(Asset.ticker.in_([ticker.upper() for ticker in tickers]))).all()
        else:
            assets = self.candidate_assets(db, limit=limit)
        results = [self.evaluate_asset(db, asset, persist=True) for asset in assets]
        self.simulator.simulate_from_predictions(db, limit=min(200, max(40, limit * 4)), persist=True)
        db.commit()
        return {"status": "ok", "evaluated": len(results), "candidates": sorted(results, key=lambda item: item.get("sniper_score", 0), reverse=True), "disclaimer": SNIPER_DISCLAIMER}

    def simulate(self, db: Session, ticker: str | None = None, limit: int = 120) -> dict:
        result = self.simulator.simulate_from_predictions(db, ticker=ticker, limit=limit, persist=True)
        db.commit()
        return result

    def evaluate_asset(self, db: Session, asset: Asset, persist: bool = False) -> dict:
        price_context = self.price_context(db, asset)
        signal = latest_signal(db, asset.id)
        regime = self.regime_service.classify(db, as_of=price_context.latest_date, persist=persist)
        technical = TechnicalAnalysisEngine().analyze(price_context.frame, timeframe="1Y")
        setup = self.classifier.classify(db, asset, technical, signal, regime)
        risk = self.risk.assess(asset, technical, signal, regime, setup)
        plan = self.plans.plan(asset, technical, setup, risk, regime)
        no_trade = self.no_trade.evaluate(technical, setup, risk, plan, regime)
        actionability = actionability_from(setup, risk, plan, no_trade, regime)
        score_components = sniper_components(setup, risk, plan, technical, signal, regime, price_context)
        score = final_sniper_score(score_components, actionability)
        exit_signals = self.exits.evaluate(asset, technical, plan, setup, risk)
        explanation = explanation_for(asset, setup, actionability, score, no_trade, plan, regime)
        persisted_score = None
        persisted_plan = None
        if persist:
            self.upsert_setup(db, setup)
            persisted_score = SniperScore(
                asset_id=asset.id,
                ticker=asset.ticker,
                setup_type=setup["setup_type"],
                sniper_score=score,
                actionability=actionability,
                components=score_components,
                explanation=explanation,
                confidence=plan["confidence"],
                data_quality_score=price_context.data_quality_score,
            )
            db.add(persisted_score)
            db.flush()
            persisted_plan = TradePlan(
                asset_id=asset.id,
                sniper_score_id=persisted_score.id,
                ticker=asset.ticker,
                setup_type=setup["setup_type"],
                actionability=actionability,
                timeframe=plan["timeframe"],
                entry_zone=plan["entry_zone"],
                entry_trigger=plan["entry_trigger"],
                confirmation_condition=plan["confirmation_condition"],
                invalidation_level=plan["invalidation_level"],
                stop_logic=plan["stop_logic"],
                target_1=plan["target_1"],
                target_2=plan["target_2"],
                trailing_exit_logic=plan["trailing_exit_logic"],
                partial_exit_logic=plan["partial_exit_logic"],
                no_trade_conditions=plan["no_trade_conditions"],
                expected_holding_period=plan["expected_holding_period"],
                risk_reward_estimate=plan["risk_reward_estimate"],
                confidence=plan["confidence"],
                historical_setup_reliability=plan["historical_setup_reliability"],
                disclaimer=SNIPER_DISCLAIMER,
            )
            db.add(persisted_plan)
            db.flush()
            for reason in no_trade:
                db.add(NoTradeDecision(asset_id=asset.id, trade_plan_id=persisted_plan.id, ticker=asset.ticker, setup_type=setup["setup_type"], reason=reason["reason"], severity=reason["severity"], conditions=reason["conditions"]))
            for item in exit_signals:
                db.add(ExitSignal(asset_id=asset.id, trade_plan_id=persisted_plan.id, ticker=asset.ticker, exit_type=item["exit_type"], action=item["action"], confidence=item["confidence"], reason=item["reason"], evidence=item["evidence"]))
            db.flush()
        return {
            "ticker": asset.ticker,
            "asset": serialize_asset(asset),
            "market_snapshot": market_snapshot_for_asset(db, asset),
            "market_regime": regime,
            "setup": setup,
            "risk": risk,
            "trade_plan": plan,
            "no_trade_reasons": no_trade,
            "exit_signals": exit_signals,
            "sniper_score": score,
            "actionability": actionability,
            "score_components": score_components,
            "explanation": explanation,
            "price_context": {"latest_price": price_context.latest_price, "latest_date": price_context.latest_date.isoformat() if price_context.latest_date else None, "rows": price_context.row_count, "data_quality_score": price_context.data_quality_score},
            "persisted_ids": {"sniper_score_id": persisted_score.id if persisted_score else None, "trade_plan_id": persisted_plan.id if persisted_plan else None},
            "disclaimer": SNIPER_DISCLAIMER,
        }

    def candidate_assets(self, db: Session, limit: int = 40) -> list[Asset]:
        rows = db.execute(
            select(SignalSnapshot, Asset)
            .join(Asset, Asset.id == SignalSnapshot.asset_id)
            .where(Asset.is_active.is_(True))
            .order_by(desc(SignalSnapshot.created_at), desc(SignalSnapshot.confidence_score), desc(SignalSnapshot.blum_score))
            .limit(limit * 3)
        ).all()
        seen = set()
        assets = []
        for _, asset in rows:
            if asset.ticker in seen:
                continue
            seen.add(asset.ticker)
            assets.append(asset)
            if len(assets) >= limit:
                break
        if assets:
            return assets
        return db.scalars(select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_type, Asset.ticker).limit(limit)).all()

    def price_context(self, db: Session, asset: Asset, as_of: date | None = None) -> PriceContext:
        query = select(PriceHistory).where(PriceHistory.asset_id == asset.id).order_by(PriceHistory.date)
        if as_of:
            query = select(PriceHistory).where(PriceHistory.asset_id == asset.id, PriceHistory.date <= as_of).order_by(PriceHistory.date)
        rows = db.scalars(query).all()
        frame = price_frame(rows)
        latest_price = float(frame["close"].iloc[-1]) if not frame.empty else None
        latest_date = as_date(frame["date"].iloc[-1]) if not frame.empty else None
        quality = clamp(min(60, len(frame) / 4) + (25 if len(frame) >= 252 else 0) + (15 if latest_price else 0))
        return PriceContext(frame=frame, latest_price=latest_price, latest_date=latest_date, row_count=len(frame), data_quality_score=round(quality, 2))

    def upsert_setup(self, db: Session, setup: dict) -> None:
        row = db.scalar(select(SetupLibrary).where(SetupLibrary.setup_type == setup["setup_type"]).limit(1))
        if row is None:
            row = SetupLibrary(setup_type=setup["setup_type"])
            db.add(row)
        row.setup_quality_score = setup["setup_quality_score"]
        row.setup_maturity = setup["setup_maturity"]
        row.required_confirmation = setup["required_confirmation"]
        row.invalidation_logic = setup["invalidation_logic"]
        row.best_timeframe = setup["best_timeframe"]
        row.historical_reliability = setup["historical_reliability"]
        row.regime_sensitivity = setup["regime_sensitivity"]
        row.common_failure_modes = {"items": setup["common_failure_modes"]}
        row.updated_at = datetime.utcnow()

    def setups(self, db: Session) -> list[dict]:
        rows = db.scalars(select(SetupLibrary).order_by(desc(SetupLibrary.historical_reliability), desc(SetupLibrary.setup_quality_score))).all()
        if not rows:
            return [default_setup_library_item(setup_type) for setup_type in sorted(SETUP_TYPES)]
        return [serialize_setup(row) for row in rows]

    def regimes(self, db: Session, limit: int = 80) -> list[dict]:
        rows = db.scalars(select(MarketRegimeSnapshot).order_by(desc(MarketRegimeSnapshot.created_at)).limit(limit)).all()
        if not rows:
            return [self.regime_service.classify(db, persist=False)]
        return [serialize_regime(row) for row in rows]

    def metrics(self, db: Session) -> dict:
        r_rows = db.scalars(select(RMultipleMetric).order_by(desc(RMultipleMetric.expectancy_r)).limit(120)).all()
        matrix = db.scalars(select(SignalReliabilityMatrix).order_by(desc(SignalReliabilityMatrix.reliability_score)).limit(120)).all()
        simulations = db.scalars(select(ExecutionSimulation).order_by(desc(ExecutionSimulation.created_at)).limit(500)).all()
        no_trades = db.scalars(select(NoTradeDecision).order_by(desc(NoTradeDecision.created_at)).limit(120)).all()
        return {
            "r_multiple": [serialize_r_metric(row) for row in r_rows],
            "signal_reliability_matrix": [serialize_matrix(row) for row in matrix],
            "execution_summary": r_summary([serialize_simulation(row) for row in simulations]),
            "no_trade_reasons": summarize_no_trades(no_trades),
            "guardrails": guardrails(),
        }

    def lessons(self, db: Session, limit: int = 40) -> list[dict]:
        rows = db.scalars(select(SignalReliabilityMatrix).order_by(desc(SignalReliabilityMatrix.updated_at)).limit(limit)).all()
        lessons = []
        for row in rows:
            if row.sample_count < 5:
                continue
            if row.expectancy_r is not None and row.expectancy_r < 0:
                lessons.append({"severity": "Warning", "lesson": f"{row.signal_name} has negative expectancy in {row.setup_type}/{row.market_regime}. Prefer wait or avoid until conditions improve.", "sample_count": row.sample_count})
            elif row.reliability_score >= 62:
                lessons.append({"severity": "Info", "lesson": f"{row.signal_name} is relatively reliable inside {row.setup_type}/{row.market_regime}, but still requires current confirmation.", "sample_count": row.sample_count})
        if not lessons:
            lessons.append({"severity": "Info", "lesson": "Sniper memory needs more point-in-time simulations before making strong reliability adjustments.", "sample_count": 0})
        return lessons[:limit]

    def summary(self, results: list[dict]) -> dict:
        actions = defaultdict(int)
        setups = defaultdict(int)
        for item in results:
            actions[item.get("actionability", "unknown")] += 1
            setups[(item.get("setup") or {}).get("setup_type", "unknown")] += 1
        scores = [safe_float(item.get("sniper_score")) for item in results]
        return {
            "candidate_count": len(results),
            "average_sniper_score": round(mean(scores), 2) if scores else 0,
            "top_sniper_score": round(max(scores), 2) if scores else 0,
            "actionability": dict(actions),
            "setup_distribution": dict(setups),
        }


def latest_signal(db: Session, asset_id: int) -> SignalSnapshot | None:
    return db.scalar(select(SignalSnapshot).where(SignalSnapshot.asset_id == asset_id).order_by(desc(SignalSnapshot.created_at)).limit(1))


def latest_global_price_date(db: Session) -> date | None:
    value = db.scalar(select(func.max(PriceHistory.date)))
    return as_date(value)


def price_frame(rows: list[PriceHistory]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "date": row.date,
                "open": row.open if row.open is not None else row.close,
                "high": row.high if row.high is not None else row.close,
                "low": row.low if row.low is not None else row.close,
                "close": row.close,
                "volume": row.volume or 0,
            }
            for row in rows
        ]
    ).sort_values("date")


def historical_reliability(db: Session, setup_type: str, sector: str, regime: str) -> float:
    rows = db.scalars(
        select(RMultipleMetric)
        .where(RMultipleMetric.setup_type == setup_type)
        .order_by(desc(RMultipleMetric.sample_count), desc(RMultipleMetric.expectancy_r))
        .limit(20)
    ).all()
    if rows:
        samples = sum(row.sample_count for row in rows)
        weighted = sum((row.expectancy_r or 0) * row.sample_count for row in rows) / max(1, samples)
        hit = mean([row.hit_rate for row in rows if row.hit_rate is not None] or [0.5])
        return clamp(42 + weighted * 18 + hit * 30 + min(10, math.log1p(samples) * 2))
    perf = db.scalars(select(SignalSnapshot).where(SignalSnapshot.classification.ilike("%breakout%")).limit(1)).all()
    return 52.0 if perf else 45.0


def update_r_metrics(db: Session, simulations: list[dict]) -> None:
    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for sim in simulations:
        key = (sim["setup_type"], sim.get("timeframe", "all"), sim.get("market_regime", "all"), sim.get("sector", "all"))
        grouped[key].append(sim)
    for key, items in grouped.items():
        setup_type, timeframe, regime, sector = key
        row = db.scalar(
            select(RMultipleMetric)
            .where(RMultipleMetric.setup_type == setup_type, RMultipleMetric.timeframe == timeframe, RMultipleMetric.market_regime == regime, RMultipleMetric.sector == sector)
            .limit(1)
        )
        if row is None:
            row = RMultipleMetric(setup_type=setup_type, timeframe=timeframe, market_regime=regime, sector=sector)
            db.add(row)
        r_values = [safe_float(item.get("realized_r_multiple")) for item in items if item.get("realized_r_multiple") is not None]
        positives = [value for value in r_values if value > 0]
        negatives = [abs(value) for value in r_values if value < 0]
        row.sample_count = len(r_values)
        row.hit_rate = round(len(positives) / len(r_values), 4) if r_values else None
        row.average_r = round(mean(r_values), 4) if r_values else None
        row.median_r = round(median(r_values), 4) if r_values else None
        row.max_drawdown_r = round(min(r_values), 4) if r_values else None
        row.profit_factor = round(sum(positives) / max(0.01, sum(negatives)), 4) if r_values else None
        row.payoff_ratio = round((mean(positives) if positives else 0) / max(0.01, mean(negatives) if negatives else 0.01), 4) if r_values else None
        row.expectancy_r = row.average_r
        row.evidence = {"last_values": r_values[-80:], "sample_policy": "R values are recalculated from historical execution simulations."}
        row.updated_at = datetime.utcnow()


def update_signal_reliability_matrix(db: Session, rows: list[tuple[HistoricalPrediction, PredictionOutcome]], simulations: list[dict]) -> None:
    from app.services.information.outbox import claim_once
    from app.services.information.contracts import digest
    by_prediction = {item["prediction_id"]: item for item in simulations if item.get("prediction_id")}
    row_cache: dict[tuple[str, str, str, str, str, str, str, str], SignalReliabilityMatrix] = {}
    for prediction, outcome in rows:
        sim = by_prediction.get(prediction.id)
        if not sim:
            continue
        if prediction.id is None or outcome.id is None or outcome.realized_return is None or outcome.outcome_label == "inconclusive":
            continue
        signal_scores = ((prediction.prediction_payload or {}).get("prediction") or {}).get("signal_scores", {})
        setup_type = sim["setup_type"]
        r_value = safe_float(sim.get("realized_r_multiple"))
        if not claim_once(db, consumer_version="legacy-sniper-reliability-v2:"+digest([setup_type, outcome.timeframe])[:12],
            source_uid=f"prediction_outcome:{outcome.id}", decision_uid=f"historical_prediction:{prediction.id}",
            payload={"setup_type": setup_type, "timeframe": outcome.timeframe, "r_value": r_value,
                     "realized_return": outcome.realized_return, "signal_scores": signal_scores}):
            continue
        for signal_name, signal_score in signal_scores.items():
            key = {
                "signal_name": signal_name,
                "setup_type": setup_type,
                "timeframe": outcome.timeframe,
                "sector": prediction.sector or "Unknown",
                "market_regime": prediction.market_regime or "Unknown",
                "volatility_state": prediction.volatility_regime or "Unknown",
                "asset_class": prediction.asset_type or "Unknown",
                "liquidity_bucket": "unknown",
            }
            cache_key = (
                key["signal_name"],
                key["setup_type"],
                key["timeframe"],
                key["sector"],
                key["market_regime"],
                key["volatility_state"],
                key["asset_class"],
                key["liquidity_bucket"],
            )
            row = row_cache.get(cache_key)
            if row is None:
                row = db.scalar(
                    select(SignalReliabilityMatrix).where(
                        SignalReliabilityMatrix.signal_name == key["signal_name"],
                        SignalReliabilityMatrix.setup_type == key["setup_type"],
                        SignalReliabilityMatrix.timeframe == key["timeframe"],
                        SignalReliabilityMatrix.sector == key["sector"],
                        SignalReliabilityMatrix.market_regime == key["market_regime"],
                        SignalReliabilityMatrix.volatility_state == key["volatility_state"],
                        SignalReliabilityMatrix.asset_class == key["asset_class"],
                        SignalReliabilityMatrix.liquidity_bucket == key["liquidity_bucket"],
                    ).limit(1)
                )
            if row is None:
                row = SignalReliabilityMatrix(**key)
                db.add(row)
            row_cache[cache_key] = row
            values = (row.evidence or {}).get("r_values", [])
            values = (values + [r_value])[-240:]
            row.sample_count = len(values)
            row.correct_count = sum(1 for value in values if value > 0)
            row.false_positive_count = sum(1 for value in values if value <= -1)
            row.average_r = round(mean(values), 4) if values else None
            row.expectancy_r = row.average_r
            row.reliability_score = round(clamp(38 + (row.average_r or 0) * 18 + (row.correct_count / max(1, row.sample_count)) * 36 - (row.false_positive_count / max(1, row.sample_count)) * 18 + min(8, safe_float(signal_score) / 12)), 2)
            row.evidence = {"r_values": values, "last_signal_score": signal_score, "policy": "Contextual signal reliability is setup/regime-specific."}
            row.updated_at = datetime.utcnow()


def r_multiple_from_outcome(outcome: PredictionOutcome) -> float | None:
    if outcome.realized_return is None:
        return None
    risk_pct = abs(outcome.max_adverse_excursion or outcome.drawdown or 0)
    if risk_pct < 0.5:
        risk_pct = max(1.0, abs(outcome.realized_return) / 2)
    return round(float(outcome.realized_return) / risk_pct, 4)


def infer_setup_type_from_prediction(prediction: HistoricalPrediction, technical: dict) -> str:
    payload = prediction.prediction_payload or {}
    score = safe_float(((payload.get("prediction") or {}).get("aggregate_score")))
    trend = technical.get("trend_direction")
    breakout = as_score(technical.get("breakout_probability"))
    pullback = as_score(technical.get("pullback_quality"))
    volatility = technical.get("volatility") or {}
    if volatility.get("volatility_compression"):
        return "volatility_squeeze"
    if breakout >= 65 and score >= 58:
        return "momentum_breakout"
    if pullback >= 65 and trend in {"uptrend", "uptrend_attempt"}:
        return "pullback_to_trend"
    if trend in {"uptrend", "uptrend_attempt"}:
        return "trend_continuation"
    if trend in {"downtrend", "downtrend_attempt"}:
        return "mean_reversion" if "bullish" in str(technical.get("divergences", {})) else "avoid_no_edge"
    return "avoid_no_edge"


def sniper_components(setup: dict, risk: dict, plan: dict, technical: dict, signal: SignalSnapshot | None, regime: dict, price: PriceContext) -> dict:
    rr = safe_float((plan.get("risk_reward_estimate") or {}).get("reward_to_risk"))
    volume = technical.get("volume") or {}
    breakdown = signal.score_breakdown if signal else {}
    return {
        "technical_setup_quality": setup.get("setup_quality_score", 0),
        "entry_clarity": 82 if plan.get("entry_zone") and plan.get("invalidation_level") else 30,
        "invalidation_clarity": 88 if plan.get("invalidation_level") else 20,
        "risk_reward": clamp(rr * 34) if rr else 20,
        "regime_alignment": regime_alignment_score(setup["setup_type"], regime),
        "volume_confirmation": clamp(40 + safe_float(volume.get("relative_volume")) * 24),
        "relative_strength": safe_float(breakdown.get("momentum_score") or breakdown.get("trend_score") or 50),
        "sentiment_narrative_confirmation": safe_float(breakdown.get("sentiment_score") or breakdown.get("semantic_trend_score") or 50),
        "fundamental_support": safe_float(breakdown.get("fundamental_score") or 50),
        "historical_reliability": setup.get("historical_reliability", 50),
        "execution_feasibility": clamp(100 - risk.get("liquidity_risk", 18) - safe_float(risk.get("distance_to_invalidation_pct")) * 2),
        "downside_risk": clamp(100 - risk.get("total_risk_score", 50)),
        "data_quality": price.data_quality_score,
    }


def final_sniper_score(components: dict, actionability: str) -> float:
    weights = {
        "technical_setup_quality": 0.14,
        "entry_clarity": 0.10,
        "invalidation_clarity": 0.10,
        "risk_reward": 0.12,
        "regime_alignment": 0.10,
        "volume_confirmation": 0.07,
        "relative_strength": 0.08,
        "sentiment_narrative_confirmation": 0.07,
        "fundamental_support": 0.06,
        "historical_reliability": 0.08,
        "execution_feasibility": 0.05,
        "downside_risk": 0.08,
        "data_quality": 0.05,
    }
    score = sum(safe_float(components.get(key)) * weight for key, weight in weights.items())
    if actionability == "avoid":
        score = min(score, 42)
    if actionability == "wait_for_trigger":
        score = min(score, 72)
    if actionability == "active_setup":
        score += 4
    return round(clamp(score), 2)


def actionability_from(setup: dict, risk: dict, plan: dict, no_trade: list[dict], regime: dict) -> str:
    if any(item["severity"] == "high" for item in no_trade):
        return "avoid"
    if risk.get("position_risk_class") == "avoid" or setup["setup_type"] == "avoid_no_edge":
        return "avoid"
    rr = safe_float((plan.get("risk_reward_estimate") or {}).get("reward_to_risk"))
    if rr < 1.15:
        return "watch"
    if setup.get("setup_maturity") in {"needs_volume", "confirmation_required", "developing", "early"}:
        return "wait_for_trigger"
    if setup.get("setup_quality_score", 0) >= 70 and plan.get("confidence", 0) >= 62 and regime.get("regime_primary") not in {"risk_off", "high_volatility", "trend_down"}:
        return "active_setup"
    if setup.get("setup_quality_score", 0) >= 58:
        return "actionable_if_confirmed"
    return "watch"


def confirmation_for(setup_type: str, levels: dict, volume: dict) -> str:
    resistance = levels.get("nearest_resistance")
    support = levels.get("nearest_support")
    if setup_type == "momentum_breakout":
        return f"Close above {resistance or 'nearest resistance'} with relative volume > 1.5x and broad market not risk-off."
    if setup_type == "pullback_to_trend":
        return f"Hold {support or 'support/MA zone'} and print a reversal candle with volume stabilization."
    if setup_type == "volatility_squeeze":
        return "Directional close out of compression range with volume expansion; avoid guessing direction early."
    if setup_type == "reversal_from_support":
        return f"Reclaim support near {support or 'support'} plus momentum divergence confirmation."
    if setup_type == "avoid_no_edge":
        return "No confirmation available. Wait for a cleaner setup."
    return "Require price, volume and regime confirmation before considering the setup active."


def invalidation_for(setup_type: str, levels: dict, technical: dict) -> str:
    support = levels.get("nearest_support")
    resistance = levels.get("nearest_resistance")
    if setup_type == "momentum_breakout":
        return f"Close back below breakout level or below ATR-adjusted support near {support or 'support'}."
    if setup_type == "pullback_to_trend":
        return f"Close below support/MA area near {support or 'nearest support'}."
    if setup_type == "reversal_from_support":
        return f"Failure to hold reclaimed support near {support or 'support'}."
    if setup_type == "failed_breakout":
        return f"Reclaim of resistance near {resistance or 'resistance'} invalidates bearish failure view."
    return "Invalidation must be explicit before actionability can be upgraded."


def best_timeframe_for(setup_type: str) -> str:
    return {
        "momentum_breakout": "short",
        "gap_and_go": "short",
        "earnings_momentum": "short",
        "post_earnings_drift": "short/medium",
        "pullback_to_trend": "short/medium",
        "trend_continuation": "medium",
        "sector_rotation_entry": "medium",
        "narrative_acceleration": "medium",
        "defensive_rotation": "medium",
        "reversal_from_support": "short",
        "mean_reversion": "short",
        "volatility_squeeze": "short/medium",
    }.get(setup_type, "none")


def regime_sensitivity(setup_type: str) -> dict:
    favorable = {
        "momentum_breakout": ["risk_on", "trend_up", "sector_rotation"],
        "pullback_to_trend": ["risk_on", "trend_up", "range_bound"],
        "trend_continuation": ["risk_on", "trend_up"],
        "reversal_from_support": ["recovery", "range_bound"],
        "defensive_rotation": ["risk_off", "high_volatility"],
        "mean_reversion": ["range_bound", "low_volatility"],
    }.get(setup_type, ["risk_on", "range_bound"])
    unfavorable = ["risk_off", "high_volatility", "trend_down"] if setup_type not in {"defensive_rotation", "mean_reversion"} else ["risk_on_euphoria"]
    return {"favorable": favorable, "unfavorable": unfavorable}


def regime_alignment_score(setup_type: str, regime: dict) -> float:
    primary = regime.get("regime_primary")
    sensitivity = regime_sensitivity(setup_type)
    if primary in sensitivity["favorable"]:
        return 76
    if primary in sensitivity["unfavorable"]:
        return 32
    return 54


def default_no_trade_conditions(setup_type: str) -> list[str]:
    common = ["Avoid if data freshness is stale or if price moves too far from the entry zone before confirmation."]
    if setup_type == "momentum_breakout":
        common.extend(["Avoid breakout without relative volume expansion.", "Avoid if RSI is extremely extended and no consolidation occurred."])
    if setup_type == "pullback_to_trend":
        common.extend(["Avoid if support/MA area fails on closing basis.", "Avoid if pullback becomes a lower-low trend break."])
    if setup_type == "reversal_from_support":
        common.extend(["Avoid unconfirmed falling knives.", "Require reclaim of support before upgrading actionability."])
    return common


def holding_period_for(setup_type: str) -> str:
    return {
        "momentum_breakout": "5-20 trading days",
        "gap_and_go": "1-10 trading days",
        "pullback_to_trend": "10-45 trading days",
        "trend_continuation": "20-63 trading days",
        "sector_rotation_entry": "20-63 trading days",
        "narrative_acceleration": "20-63 trading days",
        "reversal_from_support": "5-20 trading days",
        "mean_reversion": "3-15 trading days",
    }.get(setup_type, "research watch only")


def r_summary(simulations: list[dict]) -> dict:
    values = [safe_float(item.get("realized_r_multiple")) for item in simulations if item.get("realized_r_multiple") is not None]
    if not values:
        return {"sample_count": 0, "expectancy_r": None, "hit_rate": None, "profit_factor": None}
    positives = [value for value in values if value > 0]
    negatives = [abs(value) for value in values if value < 0]
    return {
        "sample_count": len(values),
        "expectancy_r": round(mean(values), 4),
        "average_r": round(mean(values), 4),
        "median_r": round(median(values), 4),
        "hit_rate": round(len(positives) / len(values), 4),
        "profit_factor": round(sum(positives) / max(0.01, sum(negatives)), 4),
        "max_drawdown_r": round(min(values), 4),
    }


def summarize_no_trades(rows: list[NoTradeDecision]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.setdefault(row.reason, {"reason": row.reason, "count": 0, "severity": row.severity})
        item["count"] += 1
    return sorted(grouped.values(), key=lambda item: item["count"], reverse=True)[:20]


def explanation_for(asset: Asset, setup: dict, actionability: str, score: float, no_trade: list[dict], plan: dict, regime: dict) -> str:
    if actionability == "avoid":
        reason = no_trade[0]["reason"] if no_trade else "No clean edge or risk/reward is not acceptable."
        return f"{asset.ticker} is not actionable now. Sniper Score {score:.1f}/100. Reason: {reason}"
    if actionability == "wait_for_trigger":
        return f"{asset.ticker} is interesting but not active. It is a {setup['setup_type']} setup that needs confirmation: {plan['confirmation_condition']}"
    if actionability == "active_setup":
        return f"{asset.ticker} is an active conditional setup only while confirmation, invalidation and regime alignment remain valid."
    return f"{asset.ticker} is a {setup['setup_type']} research setup. Actionability is {actionability}; BLUM should stay selective."


def guardrails() -> list[str]:
    return [
        "No guaranteed profit and no direct financial advice.",
        "No active setup without confirmation and explicit invalidation.",
        "No target without risk/reward and no entry plan without a no-trade checklist.",
        "R-multiple expectancy is preferred over raw win rate.",
        "Insufficient samples lower reliability; perfect-looking small samples are distrusted.",
        "No automatic trading and no source-code self-modification.",
    ]


def serialize_asset(asset: Asset) -> dict:
    return {"ticker": asset.ticker, "name": asset.name, "asset_type": asset.asset_type, "sector": asset.sector, "industry": asset.industry, "country": asset.country, "exchange": asset.exchange, "currency": asset.currency}


def serialize_sniper_score(row: SniperScore | None) -> dict | None:
    if row is None:
        return None
    return {"ticker": row.ticker, "setup_type": row.setup_type, "sniper_score": row.sniper_score, "actionability": row.actionability, "confidence": row.confidence, "created_at": iso(row.created_at), "explanation": row.explanation}


def serialize_setup(row: SetupLibrary) -> dict:
    return {
        "setup_type": row.setup_type,
        "setup_quality_score": row.setup_quality_score,
        "setup_maturity": row.setup_maturity,
        "required_confirmation": row.required_confirmation,
        "invalidation_logic": row.invalidation_logic,
        "best_timeframe": row.best_timeframe,
        "historical_reliability": row.historical_reliability,
        "regime_sensitivity": row.regime_sensitivity,
        "common_failure_modes": row.common_failure_modes,
        "updated_at": iso(row.updated_at),
    }


def default_setup_library_item(setup_type: str) -> dict:
    return {"setup_type": setup_type, "setup_quality_score": 0, "setup_maturity": "template", "required_confirmation": confirmation_for(setup_type, {}, {}), "invalidation_logic": invalidation_for(setup_type, {}, {}), "best_timeframe": best_timeframe_for(setup_type), "historical_reliability": 50, "regime_sensitivity": regime_sensitivity(setup_type), "common_failure_modes": []}


def serialize_regime(row: MarketRegimeSnapshot) -> dict:
    return {
        "date": iso(row.date),
        "regime_primary": row.regime_primary,
        "regime_secondary": row.regime_secondary,
        "volatility_state": row.volatility_state,
        "breadth_state": row.breadth_state,
        "risk_appetite_score": row.risk_appetite_score,
        "sector_rotation_score": row.sector_rotation_score,
        "confidence": row.confidence,
        "data_sources": row.data_sources,
        "created_at": iso(row.created_at),
    }


def serialize_r_metric(row: RMultipleMetric) -> dict:
    return {"setup_type": row.setup_type, "timeframe": row.timeframe, "market_regime": row.market_regime, "sector": row.sector, "sample_count": row.sample_count, "hit_rate": row.hit_rate, "average_r": row.average_r, "median_r": row.median_r, "max_drawdown_r": row.max_drawdown_r, "profit_factor": row.profit_factor, "payoff_ratio": row.payoff_ratio, "expectancy_r": row.expectancy_r, "updated_at": iso(row.updated_at)}


def serialize_matrix(row: SignalReliabilityMatrix) -> dict:
    return {"signal_name": row.signal_name, "setup_type": row.setup_type, "timeframe": row.timeframe, "sector": row.sector, "market_regime": row.market_regime, "volatility_state": row.volatility_state, "asset_class": row.asset_class, "liquidity_bucket": row.liquidity_bucket, "sample_count": row.sample_count, "correct_count": row.correct_count, "false_positive_count": row.false_positive_count, "average_r": row.average_r, "expectancy_r": row.expectancy_r, "reliability_score": row.reliability_score, "updated_at": iso(row.updated_at)}


def serialize_simulation(row: ExecutionSimulation) -> dict:
    return {"ticker": row.ticker, "setup_type": row.setup_type, "realized_r_multiple": row.realized_r_multiple, "max_adverse_excursion": row.max_adverse_excursion, "max_favorable_excursion": row.max_favorable_excursion, "stop_hit": row.stop_hit, "target_hit": row.target_hit, "missed_entry": row.missed_entry, "false_breakout": row.false_breakout}


def risk_reward(price: float, invalidation: float | None, target: float | None) -> dict:
    if not price or not invalidation or not target:
        return {"reward_to_risk": None, "label": "not_available"}
    risk = abs(price - invalidation)
    reward = abs(target - price)
    ratio = reward / risk if risk > 0 else None
    label = "poor"
    if ratio and ratio >= 2.0:
        label = "strong"
    elif ratio and ratio >= 1.35:
        label = "acceptable"
    elif ratio and ratio >= 1.0:
        label = "thin"
    return {"risk_per_share": round(risk, 4), "reward_to_target_1": round(reward, 4), "reward_to_risk": round(ratio, 3) if ratio else None, "label": label}


def zone(low: float | None, high: float | None) -> dict:
    return {"low": round_float(low), "high": round_float(high)}


def liquidity_bucket(price: float, volume: float) -> str:
    turnover = price * volume if price and volume else 0
    if turnover >= 500_000_000:
        return "high"
    if turnover >= 50_000_000:
        return "medium"
    if turnover > 0:
        return "low"
    return "unknown"


def as_score(value: object) -> float:
    if isinstance(value, dict):
        return safe_float(value.get("score"))
    return safe_float(value)


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    except (TypeError, ValueError):
        pass
    return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, safe_float(value)))


def pct(old: float, new: float) -> float:
    return (new / old - 1) * 100 if old else 0.0


def round_float(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(safe_float(value), digits)


def as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def iso(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def dedupe_reasons(reasons: list[dict]) -> list[dict]:
    output = []
    seen = set()
    for item in reasons:
        key = item["reason"]
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output
