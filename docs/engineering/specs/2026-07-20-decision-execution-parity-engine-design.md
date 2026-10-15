# Decision Execution Parity Engine Design

## Objective

Make every strategy researched by BLUM an executable, versioned contract that produces the same signal, entry, stop, target, and holding policy in historical replay and forward paper trading.

The release must improve the quality and speed of evidence generation without weakening certified promotion gates, fabricating positions, or mixing experimental evidence with copy-readiness evidence.

## Observed Failure

BLUM currently has strategy drift between research and execution:

- replay identifies a breakout from a fixed lookback while paper-forward uses one-bar direction changes;
- replay uses `max(ATR, 1%)` for risk while paper-forward uses `max(ATR, 0.15%)`;
- replay targets `2R` while paper-forward defaults to `1.8R`;
- strategy candidate metadata contains entry, stop, and target names that are not always executable;
- many generated variants have `evidence_binding=not_implemented`, so they cannot discover distinct edge;
- additional replay volume therefore validates a small set of static algorithms rather than exploring materially different executable policies.

This prevents BLUM from knowing whether a forward decision is the strategy that actually passed replay validation.

## Scope

### Included

1. A versioned executable strategy contract for the existing long-only setup families.
2. A pure point-in-time signal evaluator shared by replay and paper-forward.
3. Real parameter variants for intraday breakout and intraday trend.
4. Replay persistence of the exact strategy contract used by every trade.
5. Promotion persistence of the exact contract that generated the validated evidence.
6. Paper-forward evaluation and trade geometry generated from the promoted contract.
7. A promotion-frontier projection that explains each candidate's distance from experimental and certified gates.
8. Adaptive research focus metadata for near-promotion candidates while retaining broad exploration.

### Excluded

- real-money or broker execution;
- guaranteed profitability or forced paper trades;
- short selling;
- source-code self-modification;
- changes to certified minimum sample size or robustness gates;
- frontend redesign;
- project version changes.

## Architecture

### Executable Strategy Contract

Create `ExecutableStrategySpec`, an immutable domain object containing:

- schema version and strategy identity;
- setup type and required timeframe stack;
- entry rule and lookback;
- minimum relative volume;
- higher-timeframe trend threshold;
- ATR period and stop multiple;
- minimum stop percentage;
- target R multiple;
- trailing ATR multiple;
- maximum holding bars;
- allowed regime and market filters.

The contract validates supported rule combinations. Unsupported strategy metadata is rejected rather than counted as executable research.

### Shared Signal Evaluator

Create `StrategySignalEvaluator`, a side-effect-free service that accepts an executable strategy and point-in-time bars. It returns a structured evaluation:

- signal state: `triggered`, `waiting`, `blocked`;
- reason code;
- decision timestamp;
- theoretical entry;
- stop and target;
- regime and multi-timeframe confirmation;
- relative volume, ATR, and feature evidence.

It must never query the database and must never access bars after the evaluation timestamp.

### Replay Integration

The replay engine will call the shared evaluator for each executable candidate. Entry remains the first later executable bar. Realistic costs, sizing, benchmark comparison, and outcome management remain unchanged.

Each replay trade stores:

- strategy fingerprint;
- full frozen executable specification;
- signal evidence;
- theoretical and cost-adjusted execution geometry.

The factory groups evidence by strategy fingerprint, not only by setup label. Variants therefore represent genuinely different algorithms.

### Paper-Forward Integration

The promoted strategy registry exposes the frozen executable contract. Paper-forward calls the same evaluator on completed stored bars and uses its exact stop and target geometry.

The execution engine still requires a later bar, models costs, and may reject or partially fill an order. Experimental challengers remain reduced-risk and excluded from certified alpha or copy-readiness.

### Promotion Frontier

Create a read-only `StrategyPromotionFrontierService`. For each executable candidate it calculates:

- sample gap;
- net expectancy and benchmark-excess gap;
- stability gap;
- data-quality and cost-coverage gap;
- overfitting and multiple-testing blockers;
- experimental eligibility;
- certified eligibility;
- next evidence action.

This projection is persisted in factory summary metadata and can guide replay sampling. It does not change promotion criteria.

### Adaptive Research Focus

Replay allocation remains mixed:

- broad exploration preserves market and parameter coverage;
- near-frontier exploitation targets candidates with positive preliminary expectancy that mainly lack samples;
- failure replay targets candidates with unstable or cost-sensitive outcomes.

The selected research reason and strategy fingerprint are persisted with replay run metadata. No automatic source modification occurs.

## Data and Compatibility

An additive migration adds `strategy_fingerprint` to replay trades and changes replay identity from `(asset, setup, timeframe, decision timestamp)` to `(asset, strategy fingerprint, timeframe, decision timestamp)`. This is required because two executable variants may legitimately evaluate the same signal timestamp. Existing rows are backfilled with a deterministic legacy fingerprint before the new uniqueness rule is applied.

The full executable specification remains stored inside existing JSON payloads and validation metrics. No destructive data removal is allowed.

Existing replay rows without a strategy specification remain readable and are treated as legacy evidence. They cannot certify a new executable strategy unless the factory can map them unambiguously to the canonical legacy contract.

Existing API contracts remain valid. Additional fields are additive.

## Safety and Evidence Rules

- No look-ahead data in signals or feature construction.
- No paper order without a later executable bar.
- No strategy promotion from metadata-only variants.
- No certified promotion below 300 validated trades.
- No experimental challenger without positive net expectancy, positive benchmark excess, sufficient stability, cost coverage, and data quality.
- No forced trade when a trigger is absent.
- Replay, experimental paper, certified paper, and copy-readiness evidence remain separate.

## Verification

Required tests:

1. The same bars and strategy produce identical signal state, stop, and target in replay and paper-forward adapters.
2. Different executable parameters produce different fingerprints and decisions.
3. Unsupported strategy combinations are not counted as executable variants.
4. Replay persists the frozen strategy specification and uses no future feature bars.
5. The registry projects the exact promoted specification.
6. Paper-forward uses promoted stop and target rules rather than hard-coded defaults.
7. Promotion frontier reports the correct sample and evidence gaps.
8. Adaptive focus prioritizes a positive near-frontier candidate without eliminating exploration.
9. Existing tests and API behavior remain compatible.

## Success Criteria

- Replay and paper-forward strategy geometry are demonstrably identical.
- The factory evaluates real parameter variants rather than unsupported labels.
- Every promoted or experimental paper decision identifies the exact strategy fingerprint and parameters used.
- BLUM can explain why a candidate is not promoted and what evidence is required next.
- Paper positions still open only after real forward confirmation and executable future data.
