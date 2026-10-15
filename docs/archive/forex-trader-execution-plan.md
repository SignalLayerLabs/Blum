# Autonomous Forex Alpha Trader Execution Plan

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

1. Define immutable pair, market frame, agent output, proposal, risk and execution contracts.
2. Add additive persistence for cycles, decisions, positions, learning evidence, readiness and runtime control.
3. Implement versioned broker profiles and directional bid/ask execution with costs, margin, swap and gap-through stops.
4. Implement measurable context, price-action, macro, scalping and contrarian-risk agents.
5. Implement currency netting, position sizing and portfolio limits.
6. Implement the authoritative bounded core and minute position manager.
7. Implement append-only terminal-decision learning and evidence-gated readiness.
8. Add isolated scheduler, snapshot projection and POST-only controls.
9. Certify required scenarios, migration round trip, compile, regression suite and API smoke tests.
10. Commit and deploy only after all gates pass.

The architecture intentionally reuses stored replay bars, strategy validation,
paper equity and runtime infrastructure. It does not introduce a broker or a
real-money execution path.
