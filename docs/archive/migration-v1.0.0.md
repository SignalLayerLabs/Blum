# BLUM v1.0.0 Migration Notes

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

Apply Alembic revision:

```bash
cd backend
alembic upgrade head
```

New durable tables:

- `trading_game_readiness_snapshots`
- `alpha_readiness_snapshots`
- `alpha_gate_snapshots`
- `edge_map_snapshots`
- `paper_copy_strategies`
- `paper_copy_portfolios`
- `paper_copy_orders`
- `paper_copy_positions`
- `paper_copy_portfolio_snapshots`

The new endpoints can work with empty tables and return `INSUFFICIENT_EVIDENCE`, `WAITING_FOR_SOURCE_DATA` or candidate-only states. This is intentional: the UI should observe backend progress, not force training or recalculation during render.

