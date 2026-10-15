# Forex Hierarchical Reinforcement Design

## Objective

Make completed Forex paper trades influence later decisions faster without
turning small samples into artificial confidence. BLUM must become more
selective by transferring robust lessons from broad contexts to sparse
specialized contexts.

## Current Constraint

The current contextual bandit stores one state for the exact combination of
strategy, session, regime, setup and direction. A policy adjustment requires
30 outcomes in that exact cell. Forward evidence is therefore persisted and
scored, but most cells remain unable to influence later decisions.

## Chosen Architecture

Extend the existing `ForexReinforcementPolicyService`; do not add empty agents.
Every eligible terminal outcome updates four independently audited scopes:

1. `STRATEGY`: strategy-wide reward memory.
2. `SETUP`: setup and direction within the strategy.
3. `REGIME_SETUP`: regime, setup and direction.
4. `FULL_CONTEXT`: session, regime, setup and direction.

`ForexPolicyState` remains the materialized policy state. `ForexPolicyUpdate`
records one immutable update per evidence and scope. Existing updates migrate
to `FULL_CONTEXT`, preserving history.

## Statistical Gates

- Positive confidence adjustments require at least 30 samples and a 95%
  confidence interval whose lower bound is above zero.
- Negative safety adjustments may activate after 12 samples only when the 95%
  confidence interval upper bound is below zero.
- Adjustments remain capped at plus or minus 8 percentage points.
- Sparse child contexts back off to eligible parent contexts.
- A specialized context can dominate only when it has stronger eligible
  evidence; no child context bypasses cost, liquidity, regime or risk gates.

## Decision Integration

The Decision Agent resolves all matching policy scopes into one bounded
`hierarchical_policy_adjustment`. The result records:

- contributing policy states;
- scope and sample size;
- Q-value and confidence adjustment;
- effective adjustment;
- dominant observed failure causes.

The Risk Agent vetoes an otherwise attractive proposal when statistically
eligible policy evidence identifies negative contextual expectancy. Positive
memory can improve confidence but cannot independently make an ineligible setup
actionable.

## Failure Attribution

Each policy state stores aggregate terminal-cause counts derived from observed
evidence, such as `STOP_HIT`, `TIME_STOP` and execution-cost failures. This
attribution explains why a setup is penalized without applying a second,
unmeasured reward.

## Backfill and Runtime

The existing bounded `replay_pending` job backfills missing policy scopes in
small batches. It remains idempotent and resumable. GET endpoints never trigger
backfill or policy updates.

## Safety

- Paper trading only; no broker execution.
- No future data enters an episode reward.
- No positive policy promotion from insufficient samples.
- Every update is reversible through persisted scope-specific audit rows.
- Loss penalties are evidence-bound and capped.
- Existing financial execution, spread, slippage and risk logic remains intact.

## Verification

Tests must prove:

- each outcome updates all four scopes once;
- rerunning an outcome is idempotent;
- broad negative evidence penalizes a sparse child context;
- positive evidence cannot boost confidence below 30 samples;
- reliable specialized evidence overrides broader evidence only when eligible;
- a negative eligible context creates a Risk Agent veto;
- pending historical evidence backfills incrementally;
- existing Forex lifecycle and full backend suites remain green.
