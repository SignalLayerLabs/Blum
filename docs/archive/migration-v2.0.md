# BLUM v2.0 Migration Guide

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Goal

Move BLUM from a monolithic application shape into three independent layers:

- `app.engine`: financial intelligence and truth.
- `app.runtime`: application delivery and observation.
- `app.analyst`: future model dataset and training boundary.

## Current State

v2.0 adds the contract layer without removing legacy APIs. Existing services remain available under `backend/app/services` while migrations proceed.

## New Endpoints

- `GET /api/engine/status`
- `GET /api/engine/contracts`
- `GET /api/runtime/status`
- `GET /api/runtime/contracts`
- `GET /api/analyst/status`
- `GET /api/architecture/contracts`

## Rules For New Code

1. Product pages call Runtime or Engine read contracts, not internal services.
2. Heavy intelligence runs in Engine workers, not Runtime render paths.
3. Dataset export goes through `BlumAnalystDatasetPipeline`.
4. Analyst model output must be validated by Engine before use.
5. Runtime may schedule work but must not own financial logic.

## Safe Migration Order

1. Add adapters under `app.engine` for existing services.
2. Move one module at a time behind an Engine interface.
3. Add tests that the moved module has no product UI imports.
4. Keep legacy route aliases until all clients migrate.
5. Retire direct imports from `routes.py` only after compatibility coverage exists.

## No-Break Guarantees

- Existing API routes remain.
- Existing database schema remains.
- Existing Learning Loop and Trading Game jobs remain enabled.
- No automatic fine-tuning is introduced.
- No real broker execution is introduced.

