"""Apply source-attributed numerical policy to the native candidate structures."""

from dataclasses import asdict, replace

from app.core.config import get_settings
from .model import InformationOutcomeAdvisor
from .policy import InformationPolicy


class NativeInformationPolicy:
    def __init__(self, advisor=None):
        self.advisor = advisor or InformationOutcomeAdvisor()

    def _evaluate(self, db, context, baseline, fingerprint, risk_cap):
        advice = self.advisor.advise(
            db,
            context=context,
            strategy_fingerprint=fingerprint,
            baseline=baseline,
            as_of=context.decision_at,
        )
        policy = InformationPolicy().apply(
            baseline=baseline,
            context=context,
            advice=advice,
            risk_multiplier=min(
                risk_cap, get_settings().intraday_experimental_risk_multiplier
            ),
        )
        return policy, {
            k: v.isoformat() if hasattr(v, "isoformat") else v
            for k, v in asdict(advice).items()
        }

    def equity(self, db, *, decision, context):
        if context is None:
            return decision
        from app.services.intraday_contracts import (
            INTRADAY_TRADE_CANDIDATE,
            INTRADAY_BLOCKED,
        )

        baseline = {
            "rank": decision.edge_score / 100.0,
            "direction": "LONG",
            "setup_type": decision.setup_type,
            "regime": decision.regime,
            "features": {
                "confidence": decision.confidence,
                "session": decision.session,
                "timeframe": (decision.evidence.get("executable_strategy") or {}).get(
                    "execution_timeframe"
                ),
            },
            "blockers": (
                []
                if decision.status == INTRADAY_TRADE_CANDIDATE
                else [decision.reason_code]
            ),
        }
        prior_multiplier = float(decision.evidence.get("paper_risk_multiplier", 1.0))
        policy, advice = self._evaluate(
            db,
            context,
            baseline,
            decision.evidence.get("strategy_fingerprint") or "unsupported",
            prior_multiplier,
        )
        ratio = (
            policy["risk_multiplier"] / prior_multiplier
            if prior_multiplier > 0
            else 0.0
        )
        sizing = (
            replace(
                decision.sizing,
                quantity=decision.sizing.quantity * ratio,
                notional=decision.sizing.notional * ratio,
                risk_amount=decision.sizing.risk_amount * ratio,
                risk_percent=decision.sizing.risk_percent * ratio,
                reason=decision.sizing.reason
                + "; information policy risk cap applied.",
            )
            if decision.sizing
            else None
        )
        blockers = policy["blockers"]
        return replace(
            decision,
            status=(
                INTRADAY_BLOCKED
                if blockers and decision.status == INTRADAY_TRADE_CANDIDATE
                else decision.status
            ),
            reason_code=blockers[-1] if blockers else decision.reason_code,
            sizing=sizing,
            evidence={
                **decision.evidence,
                "information_context": context.to_payload(),
                "information_policy": policy,
                "information_advice": advice,
                "paper_risk_multiplier": policy["risk_multiplier"],
                "strategy_evidence_lane": decision.evidence.get("evidence_lane")
                or "certified_paper",
                "evidence_lane": (
                    decision.evidence.get("evidence_lane")
                    if decision.evidence.get("evidence_lane")
                    not in {None, "certified_paper"}
                    else "experimental_information_paper"
                ),
                "information_policy_evidence_lane": "experimental_information_paper",
                "certified_for_copy_readiness": False,
            },
        )

    def forex(self, db, *, evaluation, context):
        if context is None:
            return evaluation
        proposal = evaluation.proposal
        regime = evaluation.agent_outputs.get("context", {}).get("regime") or "unknown"
        baseline = {
            "rank": proposal.confidence,
            "direction": proposal.direction.value,
            "setup_type": proposal.setup_family,
            "regime": regime,
            "features": {
                "confidence": proposal.confidence,
                "direction": proposal.direction.value,
                "expected_net_pips": proposal.expected_net_pips,
                "expected_r": proposal.expected_r,
                "timeframe": proposal.execution_timeframe,
            },
            "blockers": list(evaluation.blockers),
        }
        policy, advice = self._evaluate(
            db, context, baseline, proposal.strategy_fingerprint or "unsupported", 1.0
        )
        return replace(
            evaluation,
            approved=evaluation.approved and not policy["blockers"],
            blockers=tuple(policy["blockers"]),
            proposal=replace(
                proposal,
                information_advice=advice,
                information_policy=policy,
                regime=regime,
                actionability_status=(
                    "BLOCKED" if policy["blockers"] else proposal.actionability_status
                ),
                evidence_lane="experimental_information_paper",
                certified_for_copy_readiness=False,
            ),
        )
