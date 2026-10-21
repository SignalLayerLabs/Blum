"""Bounded, attributable information effects on the existing candidate policy."""

from math import isfinite


def _number(value, default=0.0):
    return (
        float(value)
        if isinstance(value, (float, int))
        and not isinstance(value, bool)
        and isfinite(value)
        else default
    )


class InformationPolicy:
    def apply(self, *, baseline, context, advice, risk_multiplier):
        output = {**baseline, "blockers": list(baseline.get("blockers") or [])}
        effects = []
        risk = min(1.0, max(0.0, _number(risk_multiplier)))
        rank = _number(baseline.get("rank"))
        coverage = min(
            1.0, max(0.0, _number(context.features.get("information_coverage")))
        )
        novelty = min(3.0, max(0.0, _number(context.features.get("event_novelty"))))
        if novelty and coverage:
            change = novelty * coverage * 0.05
            rank += change
            effects.append(
                {
                    "rule": "observed_event_novelty_v1",
                    "rank_delta": change,
                    "context_hash": context.hash,
                }
            )
        if context.calendar_state == "KNOWN_EVENT_WINDOW":
            output["blockers"] = list(
                dict.fromkeys([*output["blockers"], "NEWS_WINDOW_BLOCKED"])
            )
            risk = 0.0
            effects.append({"rule": "known_event_window", "risk_multiplier": risk})
        elif context.calendar_state == "UNKNOWN":
            risk *= 0.5
            effects.append(
                {
                    "rule": "unknown_calendar_reduced_research_risk",
                    "risk_multiplier": risk,
                }
            )
        if advice.status == "CALIBRATED" and advice.predicted_net_r is not None:
            change = max(-0.25, min(0.25, advice.predicted_net_r * 0.1))
            rank += change
            effects.append(
                {
                    "rule": "calibrated_net_outcome_rank",
                    "rank_delta": change,
                    "model_uid": advice.model_uid,
                }
            )
            if advice.predicted_net_r <= 0:
                output["blockers"] = list(
                    dict.fromkeys(
                        [*output["blockers"], "INFORMATION_MODEL_NON_POSITIVE_NET_EDGE"]
                    )
                )
                risk = 0.0
        if output["blockers"]:
            output["direction"] = "ABSTAIN"
            risk = 0.0
        output.update(
            rank=rank,
            risk_multiplier=risk,
            probability_positive_r=advice.probability_positive_r,
            predicted_net_r=advice.predicted_net_r,
            information_effects=effects,
            information_context_hash=context.hash,
            information_model_uid=advice.model_uid,
            information_model_authority=advice.decision_authority,
        )
        return output
