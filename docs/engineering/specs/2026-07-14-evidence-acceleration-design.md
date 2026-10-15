# Evidence Acceleration Design

## Objective

Accelerate genuine Brain and paper-forward evidence without lowering statistical thresholds, fabricating outcomes, or mixing historical replay with forward evidence.

## Observed Failure Modes

- `BlumTradingPowerScore` history is empty because persistence is only invoked by a manual POST endpoint.
- The scheduled paper-forward worker advances lifecycle state but does not scan and persist new candidates in the same bounded cycle.
- Existing open paper-forward trades have no `expires_at`, so trades that hit neither stop nor target can remain open indefinitely.
- The Brain correctly requires five score observations and thirty closed paper-forward trades; these thresholds must remain unchanged.

## Design

### Evidence-aware Brain score persistence

Add a background-only projector that persists at most one `BlumTradingPowerScore` for each new productive learning state. It fingerprints the latest productive `LearningRun` and the underlying trade sample, stores the fingerprint in the score warnings metadata, and skips unchanged evidence. The professional learning worker invokes the projector after completing learning and trading work. GET endpoints remain read-only.

### Coordinated paper-forward cycle

The scheduled paper-forward worker executes one candidate scan followed by one lifecycle pass. Both phases remain bounded and idempotent. Candidate duplicate keys prevent duplicate decisions, while lifecycle processing is limited by existing worker budgets.

### Deterministic time stop

When a position opens, assign `expires_at` from the frozen plan's expected holding period. If the plan does not provide a valid value, use a configurable ten-day default. Lifecycle processing backfills missing expirations for already-open trades from `opened_at`, falling back to `decision_timestamp`, then applies the normal time-exit rule using later stored market data.

### Evidence integrity

- Keep Brain minimum at 5 snapshots.
- Keep paper-forward minimum at 30 closed trades.
- Never create synthetic trades or prices.
- Never classify historical replay as paper-forward evidence.
- Persist score snapshots only when source evidence changes.
- Keep all execution in scheduler workers; frontend and GET routes remain read-only.

## Verification

- Unit tests prove unchanged evidence does not create duplicate score snapshots.
- Unit tests prove a new productive learning state creates a score snapshot.
- Unit tests prove scheduled paper-forward execution scans before lifecycle.
- Unit tests prove new and legacy open trades receive deterministic expirations.
- Existing backend suite must pass.
- Production verification requires `RUNNING` on `cpu-basic`, HTTP 200 for product snapshots, and observable growth in Brain score sample history after a productive cycle.
