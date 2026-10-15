# BLUM v2.1 Migration Map

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## New Rule

New product endpoints must be added to bounded routers under:

`backend/app/api/routers/`

Do not add new product endpoints to:

`backend/app/api/routes.py`

## Product Route Flow

```text
frontend product page
-> app.api.routers.{brain,training,paper_trading,alpha}
-> BlumEngineFacade
-> Engine read model
-> stored evidence
```

## Runtime Route Flow

```text
runtime/dev request
-> app.api.routers.runtime
-> BlumRuntimeFacade or runtime service
-> snapshots / health / diagnostics
```

## Analyst Route Flow

```text
dataset/model request
-> app.api.routers.analyst
-> BlumAnalystDatasetPipeline
-> training manifest / curated dataset export
```

## Legacy Flow

```text
old endpoint
-> app.api.routers.legacy
-> app.api.routes
```

Legacy remains last in route order.

## Migrated in v2.1

- Trader Brain read model moved from `app.services.trader_brain` to `app.engine.brain.trader_brain`.
- Compatibility shim left at `app.services.trader_brain`.
- Product routers now call only `BlumEngineFacade`.
- Main app includes bounded routers before the legacy router.

## Next Migration Candidates

1. `trade_transparency.py` -> `engine/trading`
2. `trading_game_runtime.py` -> `engine/trading`
3. `alpha_operating_system.py` -> `engine/alpha`
4. `learning_loop.py` -> `engine/learning`
5. `dashboard_snapshots.py` -> `runtime/snapshots`
6. `performance.py` -> `runtime/performance`
