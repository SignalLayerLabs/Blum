from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from math import floor, gcd, lcm, isfinite

from app.services.forex_broker import ForexBrokerProfile
from app.services.forex_contracts import ForexTradeProposal, pair_config
from app.core.config import get_settings


@dataclass(frozen=True)
class ForexPortfolioState:
    equity: float
    daily_realized_pnl: float = 0.0
    open_positions: tuple[dict, ...] = ()
    used_margin: float = 0.0
    drawdown_percent: float = 0.0
    pair_correlations: dict[str, float] | None = None
    pending_orders: tuple[dict, ...] = ()


@dataclass(frozen=True)
class ForexRiskDecision:
    decision: str
    quantity_lots: float
    risk_amount: float
    risk_percent: float
    margin_required: float
    exposure_by_currency: dict[str, float]
    blockers: tuple[str, ...]
    explanation: str


class BlumForexPortfolioRiskEngine:
    risk_per_trade_percent = 0.5
    daily_loss_limit_percent = 2.0
    max_open_positions = 4
    max_currency_exposure_multiple = 3.0

    def __init__(self) -> None:
        settings = get_settings()
        self.risk_per_trade_percent = min(
            0.5, max(0.05, float(settings.forex_risk_per_trade_percent))
        )
        self.daily_loss_limit_percent = min(
            2.0, max(0.25, float(settings.forex_daily_loss_limit_percent))
        )
        self.max_open_positions = min(4, max(1, int(settings.forex_max_open_positions)))

    def evaluate(
        self,
        proposal: ForexTradeProposal,
        state: ForexPortfolioState,
        broker: ForexBrokerProfile,
        *,
        quotes=None,
        now=None,
        execution_context=None,
    ) -> ForexRiskDecision:
        committed = state.open_positions + state.pending_orders
        exposures = self.currency_exposure(committed)
        if (
            state.equity <= 0
            or state.daily_realized_pnl
            <= -state.equity * self.daily_loss_limit_percent / 100
        ):
            return self._reject("REJECT_DAILY_LOSS", exposures)
        if len(committed) >= self.max_open_positions:
            return self._reject("REJECT_MAX_POSITIONS", exposures)
        if any(item.get("pair") == proposal.pair for item in committed):
            return self._reject("REJECT_CURRENCY_EXPOSURE", exposures)
        config = pair_config(proposal.pair)
        stop_pips = abs(proposal.entry - proposal.stop) / config.pip_size
        evidence_multiplier = max(0.25, min(1.0, proposal.confidence))
        cost_multiplier = max(
            0.25,
            min(
                1.0,
                proposal.expected_net_pips / max(proposal.expected_gross_pips, 1e-9),
            ),
        )
        drawdown_multiplier = max(0.25, 1.0 - max(0.0, state.drawdown_percent) / 10.0)
        correlation = abs(
            float((state.pair_correlations or {}).get(proposal.pair, 0.0))
        )
        correlation_multiplier = 0.5 if correlation >= 0.8 else 1.0
        sizing_multiplier = min(
            evidence_multiplier,
            cost_multiplier,
            drawdown_multiplier,
            correlation_multiplier,
        )
        information_multiplier = proposal.information_policy.get("risk_multiplier", 1.0)
        if (
            isinstance(information_multiplier, bool)
            or not isinstance(information_multiplier, (float, int))
            or not isfinite(information_multiplier)
        ):
            return self._reject("REJECT_INFORMATION_RISK", exposures)
        effective_risk_percent = (
            self.risk_per_trade_percent
            * sizing_multiplier
            * max(0.0, min(1.0, information_multiplier))
        )
        risk_amount = state.equity * effective_risk_percent / 100
        lot_step = common_lot_step(config.lot_step, broker.lot_step)
        from app.services.forex_cash_accounting import convert_cash

        from app.services.forex_contracts import ForexOrderRequest, ForexDirection
        from app.services.forex_execution import BlumForexExecutionSimulator

        request = ForexOrderRequest.from_proposal(proposal, quantity_lots=1.0)
        request = replace(request, **(execution_context or {}))
        quoted = (quotes or {}).get(proposal.pair)
        sign = 1 if proposal.direction == ForexDirection.LONG else -1
        if quoted is not None:
            side_price = quoted.ask if sign == 1 else quoted.bid
        else:
            half_spread = (
                broker.spread_pips.get(proposal.pair, 0.0)
                * broker.session_spread_multiplier.get(request.session, 1.25)
                * config.pip_size
                / 2
            )
            side_price = proposal.entry + sign * half_spread
        expected_fill = (
            side_price
            + sign
            * BlumForexExecutionSimulator._slippage_pips(request, broker)
            * config.pip_size
        )
        quote_risk = max(0.0, (expected_fill - proposal.stop) * sign) * 100_000
        if config.quote_currency == broker.account_currency:
            per_lot_risk = quote_risk
        elif quotes and now is not None:
            converted = convert_cash(
                -quote_risk,
                config.quote_currency,
                broker.account_currency,
                quotes,
                now=now,
            )
            if converted is None:
                return self._reject("REJECT_ACCOUNT_CONVERSION", exposures)
            per_lot_risk = abs(converted["amount"])
        else:
            return self._reject("REJECT_ACCOUNT_CONVERSION", exposures)
        if config.base_currency == broker.account_currency:
            per_lot_notional = 100_000
        elif config.quote_currency == broker.account_currency:
            per_lot_notional = proposal.entry * 100_000
        else:
            converted = convert_cash(
                -100_000, config.base_currency, broker.account_currency, quotes, now=now
            )
            if converted is None:
                return self._reject("REJECT_ACCOUNT_CONVERSION", exposures)
            per_lot_notional = abs(converted["amount"])
        lots = risk_amount / max(
            per_lot_risk + broker.commission_per_lot_round_trip, 1e-9
        )
        lots = max(0.0, floor(lots / lot_step + 1e-12) * lot_step)

        def allocated_risk(quantity):
            return per_lot_risk * quantity + 2 * max(
                broker.minimum_commission,
                broker.commission_per_lot_round_trip * quantity / 2,
            )

        if allocated_risk(lots) > risk_amount + 1e-9:
            fixed_fee_lots = max(
                0.0, risk_amount - 2 * broker.minimum_commission
            ) / max(per_lot_risk, 1e-9)
            lots = min(lots, floor(fixed_fee_lots / lot_step + 1e-12) * lot_step)
        if lots < max(config.minimum_lot, broker.minimum_lot):
            return self._reject("REJECT_MARGIN", exposures)
        margin = per_lot_notional * lots * broker.margin_requirement
        notional = per_lot_notional * lots
        if (
            margin + state.used_margin > state.equity
            or notional > state.equity * broker.maximum_internal_leverage
        ):
            return self._reject("REJECT_MARGIN", exposures)
        projected = self._apply(
            exposures, proposal.pair, proposal.direction.value, per_lot_notional * lots
        )
        strongest = max((abs(value) for value in projected.values()), default=0.0)
        existing_notional = sum(
            abs(float(item.get("notional") or 0)) for item in committed
        )
        correlation_limited = correlation >= 0.8
        if correlation_limited or (
            existing_notional
            and strongest
            > max(
                state.equity * self.max_currency_exposure_multiple,
                existing_notional * 0.8,
            )
        ):
            reduced_lots = floor(lots * 0.5 / lot_step + 1e-12) * lot_step
            if reduced_lots < max(config.minimum_lot, broker.minimum_lot):
                return self._reject(
                    (
                        "REJECT_CORRELATION"
                        if correlation_limited
                        else "REJECT_CURRENCY_EXPOSURE"
                    ),
                    exposures,
                )
            return ForexRiskDecision(
                "APPROVE_REDUCED_SIZE",
                reduced_lots,
                allocated_risk(reduced_lots),
                allocated_risk(reduced_lots) / state.equity * 100,
                per_lot_notional * reduced_lots * broker.margin_requirement,
                self._apply(
                    exposures,
                    proposal.pair,
                    proposal.direction.value,
                    per_lot_notional * reduced_lots,
                ),
                ("CORRELATION_LIMIT",),
                "Pair correlation or clustered currency exposure reduced the evidence-adjusted position size",
            )
        return ForexRiskDecision(
            "APPROVE_FULL_SIZE",
            lots,
            allocated_risk(lots),
            allocated_risk(lots) / state.equity * 100,
            margin,
            projected,
            (),
            "Stop-based size adjusted for evidence, execution cost and drawdown",
        )

    def currency_exposure(self, positions: tuple[dict, ...]) -> dict[str, float]:
        result: dict[str, float] = {}
        for item in positions:
            try:
                result = self._apply(
                    result,
                    str(item["pair"]),
                    str(item["direction"]),
                    float(item.get("notional") or 0),
                )
            except (KeyError, ValueError):
                continue
        return result

    def _apply(
        self, exposure: dict[str, float], pair: str, direction: str, notional: float
    ) -> dict[str, float]:
        result = dict(exposure)
        config = pair_config(pair)
        sign = 1 if direction == "LONG" else -1
        result[config.base_currency] = (
            result.get(config.base_currency, 0.0) + sign * notional
        )
        result[config.quote_currency] = (
            result.get(config.quote_currency, 0.0) - sign * notional
        )
        return result

    def _reject(self, decision: str, exposure: dict[str, float]) -> ForexRiskDecision:
        blocker = {
            "REJECT_ACCOUNT_CONVERSION": "ACCOUNT_CONVERSION_UNAVAILABLE",
            "REJECT_DAILY_LOSS": "DAILY_LOSS_LIMIT",
            "REJECT_MAX_POSITIONS": "MAX_POSITIONS",
            "REJECT_MARGIN": "MARGIN_LIMIT",
            "REJECT_CURRENCY_EXPOSURE": "CURRENCY_EXPOSURE_LIMIT",
            "REJECT_CORRELATION": "CORRELATION_LIMIT",
        }[decision]
        return ForexRiskDecision(
            decision, 0.0, 0.0, 0.0, 0.0, exposure, (blocker,), blocker
        )


def common_lot_step(pair_step: float, broker_step: float) -> float:
    pair, broker = Fraction(str(pair_step)), Fraction(str(broker_step))
    return float(
        Fraction(
            lcm(pair.numerator, broker.numerator),
            gcd(pair.denominator, broker.denominator),
        )
    )
