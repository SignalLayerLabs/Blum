# BLUM Real Learning Acceleration Engine Report

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Status

DONE.

This sprint turns BLUM learning acceleration from advisory metadata into a bounded operational loop. It still does not fabricate evidence, does not promote model versions outside existing thresholds, and does not run heavy work from GET endpoints or page render.

## What changed

- `BlumLearningAccelerationAgent` now selects real acceleration targets from stored BLUM evidence:
  - active/proposed `LearningFocusPriority` rows;
  - repeated scanner blockers;
  - weak `StrategyMemory` / `SignalPerformance` rows;
  - `MissedWinner` rows;
  - walk-forward benchmark blockers.
- Manual `POST /api/training/accelerate` executes bounded `LearningLoopService.run_batch(...)` work when targets exist.
- Automatic scanner execution schedules acceleration metadata only by default, so paper-forward scanning does not silently launch heavy learning.
- `BlumExperimentManagerAgent` now persists structured experiments in `blum_learning_experiments`.
- Training Ground snapshot now includes:
  - `learning_acceleration`;
  - `learning_experiments`;
  - `training_continuity`.
- Explicit benchmark blocker support remains visible through `WALK_FORWARD_BENCHMARK_MISSING`.

## Database

Migration added:

- `backend/alembic/versions/0029_learning_acceleration_engine.py`

New table:

- `blum_learning_experiments`

The table stores hypotheses, target market/asset class/setup, training and validation windows, sample size, benchmark, status, result summary, conclusion, next action, and source payload.

## Runtime behavior

### Backend scanner

The scanner calls:

- `BlumLearningAccelerationAgent.accelerate(..., execute=False)`

This records bounded priorities and experiment proposals but does not run historical replay during scan.

### Manual acceleration endpoint

The endpoint calls:

- `BlumLearningAccelerationAgent.accelerate(..., execute=True)`

This may execute bounded learning batches through `LearningLoopService.run_batch(...)`, limited by:

- `blum_learning_acceleration_max_batches_per_run`
- `blum_learning_acceleration_max_assets_per_run`
- `blum_learning_acceleration_max_runtime_seconds`
- existing Learning Loop daily budget guards

## Evidence of learning use

The new tests prove:

- acceleration invokes `LearningLoopService.run_batch(...)` with trigger `learning_acceleration`;
- bounded batch counts are respected;
- a `LearningEvent` with type `blum_learning_acceleration_completed` is persisted;
- experiments are persisted as rows, not returned as ephemeral JSON only;
- completed learning runs can mark experiments as `COMPLETED`;
- Training product routers stay behind `BlumEngineFacade`.

## Verification

Commands run:

```bash
python3 -m compileall backend/app
PYTHONPATH=backend ./hf-blum-mvp/.upload-venv/bin/python -m pytest backend/tests/test_accelerated_global_trader_brain.py -q --tb=short
PYTHONPATH=backend ./hf-blum-mvp/.upload-venv/bin/python -m pytest backend/tests/test_clean_core_release.py::test_product_routers_depend_on_engine_facade_not_low_level_services backend/tests/test_clean_core_release.py::test_product_routes_are_served_by_bounded_routers_before_legacy_router -q --tb=short
PYTHONPATH=backend ./hf-blum-mvp/.upload-venv/bin/python -m pytest -q --tb=short
```

Results:

- `compileall`: passed
- accelerated trader brain tests: `26 passed`
- clean core route boundary tests: `2 passed`
- full backend suite: `194 passed`

Warnings observed:

- existing `datetime.utcnow()` deprecation warnings;
- existing Pydantic class config deprecation warnings.

## Local HTTP smoke checks

Local backend was not running on `localhost:8000`.

Smoke results:

- `GET /api/training/snapshot`: `BACKEND_NOT_RUNNING`
- `GET /api/alpha/snapshot`: `BACKEND_NOT_RUNNING`
- `POST /api/training/accelerate`: `BACKEND_NOT_RUNNING`

## Remote deployment

Hugging Face Space:

- `Italianhype/Blum`

Commits deployed:

- `7ccbfff869629855cc655cf04a5d56834d7b955a` - initial learning acceleration upload
- `fa3b3785194b4410bb77ccacdb227fd25e32bce4` - Alembic revision-id fix

Runtime verification:

- runtime stage: `RUNNING`
- runtime sha: `fa3b3785194b4410bb77ccacdb227fd25e32bce4`

Remote smoke checks after deploy:

- `GET /api/brain/snapshot`: `200`
- `GET /api/training/snapshot`: `200`
- `GET /api/alpha/snapshot`: `200`
- `POST /api/training/accelerate`: `200`

Observed remote acceleration result:

```json
{
  "status": "THROTTLED",
  "batches_requested": 3,
  "batches_completed": 2,
  "experiments_created": 3,
  "experiments_completed": 3,
  "memory_updates": 0,
  "next_action": "Wait for budget guard reset, then continue bounded acceleration."
}
```

Post-run Training snapshot evidence:

- `learning_acceleration.status`: `THROTTLED`
- `learning_acceleration.batches_requested`: `3`
- `learning_acceleration.batches_completed`: `2`
- `learning_experiments.count`: `3`
- `learning_experiments.completed_count`: `3`

Deployment issue fixed:

- The first remote deploy failed during Alembic upgrade because the revision id `0029_learning_acceleration_engine` exceeded the Space database's `alembic_version.version_num` length.
- Fixed by shortening the revision id to `0029_learning_accel`.

## Known limitations

- Manual acceleration only executes when stored evidence targets exist; it does not invent training samples.
- Model version promotion remains governed by existing evidence thresholds.
- Walk-forward benchmark gaps are surfaced as blockers; this sprint does not backfill missing benchmark rows.
- Real improvement still depends on the quality and breadth of stored historical market data.
