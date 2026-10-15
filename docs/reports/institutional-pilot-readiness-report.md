# Institutional Pilot Readiness Report

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Scope

This release adds an evidence gate and accelerates bounded research. It does not add broker connectivity, real-money execution, guaranteed returns or relaxed promotion criteria.

## Decision Contract

The gate returns one of `NOT_ELIGIBLE`, `EVIDENCE_BUILDING`, `ELIGIBLE_FOR_SHADOW_PILOT`, `ELIGIBLE_FOR_LIMITED_PILOT` or `SUSPENDED`. Every result includes blockers, warnings, observed metrics, required thresholds, a bounded capital envelope and kill-switch state.

Limited-pilot eligibility requires all existing strict thresholds: 500 global forward trades, 150 exact-strategy forward trades, 270 observation days, maximum 10% evidence drawdown, maximum 20% replay/forward decay, 10 tickers, 3 regimes, controlled ticker/market concentration, valid benchmark methodology and execution-quality evidence.

## Research Acceleration

The strategy promotion frontier selects experiments across four lanes: 50% closest-to-promotion candidates, 25% failure replay, 12.5% coverage gaps and 12.5% broad exploration. Selection history is checkpointed, bounded and exposed as telemetry. A candidate that yields no evidence for three slices is rotated, with periodic retry to avoid permanent exclusion.

## Safety

- Read paths remain read-only and do not run learning or lifecycle work.
- A numeric zero remains observed evidence and cannot trigger a more favorable fallback.
- Missing methodology, costs, slippage, data quality or provenance blocks eligibility.
- The gate is reversible data policy; it never self-modifies source code.
- The kill switch fails closed on stale, invalid, degraded or risk-breaching states.

## Current Interpretation

Deployment of the gate does not make BLUM pilot-ready. Production eligibility depends on future stored forward evidence. Until all gates pass, the correct state remains `NOT_ELIGIBLE`, `EVIDENCE_BUILDING` or `SUSPENDED`.
