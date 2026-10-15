# BLUM v2.1 Deprecation Report

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Removed Files

No files were deleted in this sprint.

Reason: the existing legacy API surface still has active dependencies and should not be removed until route-level usage is measured.

## Deprecated / Legacy Areas

### `backend/app/api/routes.py`

Status: legacy compatibility router.

Reason: it mixes product, runtime, diagnostic, model, market and recalculation endpoints in one file. New product traffic is now routed through bounded routers before this legacy router.

Action:

- keep for backward compatibility;
- do not add new product endpoints here;
- migrate endpoint groups into bounded routers over time.

### `backend/app/services/trader_brain.py`

Status: compatibility shim.

Reason: the implementation moved to `backend/app/engine/brain/trader_brain.py`, but tests and legacy code may still import the old path.

Action:

- keep shim until old imports are removed;
- new code should import from `app.engine.brain.trader_brain` or call `BlumEngineFacade`.

## Hidden Product Surface

Primary navigation remains limited to:

- Brain
- Training
- Paper Trading
- Alpha

Developer diagnostics remain reachable but are not product navigation items.

## Still-Needed Legacy Code

The following areas remain in `backend/app/services` because moving them all at once would create avoidable regression risk:

- Learning Loop
- Trading Game
- Alpha Recovery
- Market Sniper
- Meta Cognition
- Decision Intelligence
- Capital Allocation
- Runtime snapshots/performance

## Risk Notes

- Removing old routes before telemetry is available could break existing frontend aliases, user bookmarks or automation scripts.
- Moving all services physically in one sprint would be a high-risk big-bang refactor.
- The safe strategy is incremental migration with route-order tests and compatibility shims.
