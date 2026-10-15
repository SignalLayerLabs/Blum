# BLUM backend

The Python runtime owns financial evidence, deterministic decision/risk contracts, paper execution, learning records and API delivery. PostgreSQL remains the financial evidence store.

| Path | Responsibility |
| --- | --- |
| [app/engine](app/engine) | Financial facade, cooperative-agent contracts and product read models |
| [app/services](app/services) | Evidence, risk, paper execution, learning and validation services |
| [app/services/ascent](app/services/ascent) | Bounded candidate language, datasets, evaluator and evolution checkpoints |
| [app/services/trading_ml](app/services/trading_ml) | Trading ML features, validation and champion/challenger boundaries |
| [app/services/deterministic_execution](app/services/deterministic_execution) | Optional deterministic execution-kernel integration |
| [app/api/routers](app/api/routers) | Bounded product, runtime, analyst and compatibility APIs |
| [app/runtime](app/runtime) | Delivery/scheduling contracts and runtime facade |
| [app/analyst](app/analyst) | Reviewed datasets and advisory-model operations |
| [app/providers](app/providers) | Market-data provider contracts |
| [app/data](app/data) | Reviewed packaged data and public read-route policy |
| [alembic](alembic) | Ordered SQL migration history |
| [tests](tests) | Backend, migration and operational tests |

Start with the [development guide](../docs/guides/development.md). Use the [architecture guide](../docs/architecture/README.md) before changing ownership, and the [data policy](../docs/research/data-quality.md) before importing evidence. New product endpoints use routers and facades rather than extending `app/api/routes.py`.

Product reads consume stored evidence; they do not start learning or execution. Advisory models and generated research candidates cannot bypass risk or promote themselves into production.
