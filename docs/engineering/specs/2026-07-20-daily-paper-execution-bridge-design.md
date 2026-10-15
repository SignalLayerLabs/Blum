# Daily Paper Execution Bridge Design

## Objective

Route daily live-forward paper candidates through BLUM's existing realistic order lifecycle. A confirmed signal must create an order, not an immediate position. Only a later executable OHLCV observation may produce a fill and open exposure.

This closes the remaining parity gap between the documented execution architecture and `LiveForwardPaperTradingService`, without changing strategy selection, entry rules, risk rules, promotion gates, APIs, or the project version.

## Observed Gap

The daily paper-forward lifecycle currently performs this transition:

```text
confirmed trigger -> open at latest stored price
```

`PaperOrderLifecycleService` and `RealisticExecutionEngine` already model persisted orders, later-bar execution, spread, slippage, volume participation, partial fills, commissions, FX, borrow constraints, and unfilled orders. The intraday engine uses them, but the daily lifecycle bypasses them.

Consequences:

- theoretical signal price and executed price can be identical by construction;
- daily paper evidence can omit execution costs and fill uncertainty;
- an executable trigger can be counted as exposure before a later fill exists;
- daily and intraday evidence use different execution standards;
- copy-readiness can overstate the reproducibility of daily decisions.

## Chosen Design

### 1. Trigger Becomes Order Submission

When a frozen daily candidate passes classification, entry-window, trigger, and risk/reward checks, BLUM submits one idempotent `PaperExecutionOrder`.

The paper trade moves to `ORDER_SUBMITTED`. Capital, exposure, ledger entry fields, and open-position counts remain unchanged until a fill exists.

Order mapping:

- breakout or above-trigger entry -> buy stop order;
- pullback or bounded entry zone -> buy limit order;
- explicit market entry -> market order;
- unsupported or ambiguous entry geometry -> blocked, never silently converted to market.

The order preserves theoretical price, requested quantity, stop, target, decision timestamp, expiry, strategy identity, and frozen evidence.

### 2. Later-Bar Execution

On subsequent lifecycle runs, stored `PriceHistory` rows after order submission are converted into immutable `ExecutionMarketBar` values. OHLCV must come from the persisted row. Missing material OHLCV data blocks execution instead of receiving a favorable fill.

Spread and volatility estimates are conservative and explicitly marked as estimated when quote data is unavailable. Liquidity and maximum participation come from frozen scanner evidence and settings.

The existing execution engine determines:

- no fill;
- partial fill;
- full fill;
- rejection;
- expiry.

No bar at or before order submission is executable.

### 3. Fill Projection

Only a persisted fill may transition the paper trade to `PARTIALLY_FILLED` or `OPEN`.

At projection time BLUM updates:

- actual average entry price and filled quantity;
- spread, slippage, commission, FX, borrow, and gap costs;
- ledger trade and live position;
- game cash, exposure, and open-position count;
- entry risk/reward using the actual fill price;
- execution events and snapshots.

Projection is idempotent. Reprocessing the same order or fill cannot duplicate capital movements, positions, ledger rows, or events.

### 4. Failed Execution Becomes Evidence

Terminal orders that never fill do not become trades.

They produce explicit outcomes:

- `ORDER_NOT_FILLED` when price never executes within the order window;
- `SIGNAL_DECAY_BEFORE_ENTRY` when the thesis window expires;
- `EDGE_DESTROYED_BY_COSTS` when actual estimated execution makes net geometry unacceptable;
- `DATA_BLOCKED` when required execution evidence is missing.

These outcomes remain separate from closed-trade win/loss evidence and are available to learning and no-trade analysis.

## Boundaries

### Included

- daily live-forward paper lifecycle only;
- reuse of existing execution models and persistence;
- additive events and payload fields;
- backward-compatible status handling;
- migration-free implementation unless an unavoidable persisted field is discovered during implementation.

### Excluded

- broker integration or real-money execution;
- changes to candidate generation or strategy scores;
- synthetic fills;
- frontend redesign;
- promotion-threshold changes;
- short selling without borrow evidence;
- source-code self-modification.

## Failure and Compatibility Rules

- Existing open and closed paper trades remain unchanged.
- Existing submitted orders remain idempotent by duplicate key.
- Snapshot reads remain read-only and never process orders.
- Scheduler lifecycle runs may submit/process bounded orders, but GET endpoints may not.
- If execution data is unavailable, the system reports the blocker and keeps evidence truthful.
- Daily execution may reduce the number of opened trades; this is expected if previous openings were not realistically fillable.

## Verification

Tests must prove:

1. a confirmed daily trigger submits an order without opening a position;
2. the same lifecycle run cannot fill from the trigger observation itself;
3. a later crossing bar creates a persisted fill and opens the position;
4. the actual entry differs from the theoretical price when spread/slippage applies;
5. partial fills do not overstate quantity or exposure;
6. an unfilled expired order records `ORDER_NOT_FILLED`;
7. duplicate lifecycle runs do not duplicate orders, fills, positions, ledger rows, or capital changes;
8. missing OHLCV blocks execution;
9. existing closed-trade and snapshot behavior remains compatible;
10. all paper-forward and realistic-execution tests pass.

## Success Criteria

Daily paper-forward evidence is execution-realistic: every open position has a persisted later-bar fill, every cost is attributable, theoretical and executed prices remain separate, unfilled signals become learning evidence, and no dashboard or GET request performs execution work.
