# Forex Trader Current State

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Scope

Audit performed against the repository at Alembic head
`0035_decision_execution_parity`. The target is an autonomous, paper-only Forex
trader. Existing financial behavior remains authoritative outside Forex.

## Component Classification

| Component | Classification | Decision |
| --- | --- | --- |
| `BlumIntradayPaperEngine` | REUSE | Keep as the generic intraday worker. Forex routing moves to the dedicated authoritative core. |
| `StrictIntradayDataGateway` | COMPLETE | Reuse provider/storage conventions; Forex core enforces its own strict 1H/15m/5m/1m contract. |
| `RealisticExecutionEngine` | REUSE | Keep for non-Forex assets. Forex requires directional bid/ask, margin and swap semantics. |
| `PaperExecutionOrder` / `PaperExecutionFill` | REUSE | Preserve generic execution history. Forex cycle/order details use dedicated append-only evidence. |
| `LiveForwardPaperGame` | REUSE | Source of paper equity; no real-money path is introduced. |
| `ReplayMarketBar` | REUSE | Point-in-time Forex candles and quotes remain the stored market evidence. |
| `PromotedStrategyRegistry` | REUSE | Source of eligible and experimental strategy contracts. |
| `AlphaStrategyFactory` | COMPLETE | Continue producing Forex hypotheses; it does not approve orders. |
| `BlumAdaptiveTrainingController` / replay | COMPLETE | Continue historical Forex training with physically separate evidence. |
| `ForexDeskAgent` | CONSOLIDATE | Market-universe discovery only. It must not transform analysis into a Forex order. |
| Generic live-forward candidate scanner | CONSOLIDATE | Non-Forex use remains unchanged; Forex decisions route through `BlumForexTraderCore`. |
| Generic intraday lifecycle | CONSOLIDATE | Existing positions remain supported; new Forex positions are managed by the Forex position manager. |
| Dashboard snapshot infrastructure | REUSE | Add a `forex_trader_summary` projection. GET remains read-only. |
| APScheduler/runtime worker coordinator | REUSE | Add one isolated, non-overlapping Forex job. |

## Missing Before This Sprint

- No single authoritative Forex decision-to-order orchestrator.
- No typed debate between context, price action, macro, scalping and risk agents.
- No dedicated pair metadata for all 12 required major/cross pairs.
- No strict Forex 1H/15m/5m/1m freshness contract.
- No directional bid/ask execution contract with swap and margin evidence.
- No dynamic currency exposure netting.
- No persistent Forex cycle, decision, position, learning and readiness state.
- No independent Forex scheduler heartbeat/control state.
- No snapshot-only Forex API or precise inactivity reason.

## Ownership Boundary

`BlumForexTraderCore` is the only component allowed to convert a Forex proposal
into a new paper order. Specialist agents publish typed evidence only. The risk
engine may approve, reduce or reject. The execution simulator may fill or reject
but cannot generate a signal. The scheduler invokes a bounded core cycle and
never contains financial decision logic.
