# BLUM v1.0.0 Release Notes

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

Release identity: `v1.0.0 | alpha-operating-system`

## What Changed

- BLUM now exposes a compact Alpha Operating System layer around the existing runtime.
- Trading Game evidence has a readiness state before the UI tries to load heavy evidence.
- Command Center can show the level of BLUM's brain through capability, benchmark, learning and copy-readiness summaries.
- Alpha Readiness measures whether stored evidence is mature enough to discuss possible edge.
- Alpha Gates block unsupported claims when samples, benchmarks or live paper evidence are missing.
- Paper Copy Trading is now modeled as a paper-only operating layer with durable schema support.

## What Did Not Change

- No broker integration was added.
- No real trades are executed.
- Existing Trading Game, Learning Loop, Sniper, Decision, Portfolio, Alpha Recovery and Meta-Cognition logic remain backward compatible.
- GET endpoints remain read-only and do not run heavy recalculation.

## Validation Standard

Performance and alpha claims are still evidence-bound. BLUM must say insufficient evidence when samples, benchmark comparisons or live paper validation are not mature.

