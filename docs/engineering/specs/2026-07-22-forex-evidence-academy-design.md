# Forex Evidence Academy

## Goal

Give BLUM broad, structured Forex knowledge while preserving the distinction
between educational knowledge and evidence of executable edge. The sprint must
increase the rate and quality of Forex experiments, not inflate confidence or
risk.

## Current State

BLUM already scans twelve liquid currency pairs, evaluates `1h/15m/5m/1m`
frames, models spread/slippage/commission, applies portfolio risk controls and
stores Forex learning outcomes. Current decisions remain mostly
`STRATEGY_NOT_READY` because the validated strategy sample is too small. The
existing data layer also lacks a durable Forex-specific knowledge catalog and
a compiler that turns validated replay outcomes into contextual memory.

## Source Policy

Sources are classified before use:

- **authoritative context**: ECB/FRED macro and rate series and CFTC COT
  positioning data;
- **market replay evidence**: timestamped OHLC data with explicit provenance,
  gaps and timezone metadata;
- **evaluation corpora**: manually annotated Forex news/sentiment datasets;
- **untrusted reference**: community material without sufficient provenance.

External material can improve feature extraction, research coverage and model
evaluation. It cannot directly promote a strategy or increase executable
confidence. Only point-in-time replay, purged walk-forward and paper-forward
outcomes count as edge evidence.

The first curated catalog includes:

- ECB Data Portal SDMX exchange-rate and macro series;
- FRED/ALFRED macro series, with vintage-aware usage where available;
- CFTC Commitments of Traders positioning history;
- `elthariel/histdata_fx_1m` as a replay backfill candidate, subject to schema,
  license, timezone and gap validation;
- Zenodo DOI `10.5281/zenodo.7976208` as a human-annotated Forex sentiment
  evaluation corpus;
- `Tropstan/Forex_Factory_Calendar` as a calendar backfill candidate, never an
  authoritative event source without cross-validation.

## Architecture

### Forex Knowledge Catalog

`ForexKnowledgeCatalogService` publishes versioned source manifests and a
structured curriculum covering:

- market sessions and liquidity transitions;
- pair conventions, pip economics and currency exposure;
- trend, pullback, breakout, mean-reversion and volatility setups;
- rate differentials, carry, risk appetite and cross-asset context;
- macro-event risk and surprise interpretation;
- execution costs, latency, gaps, partial fills and no-trade rules;
- common failure modes and invalidation logic.

Catalog records are auditable and store provenance, license, role, freshness,
validation state and allowed uses. The service does not download large datasets
during startup or GET requests.

### Forex Curriculum Planner

`ForexCurriculumPlanner` creates bounded research assignments by pair, session,
regime and setup. It prioritizes sample gaps, failures and under-covered cells
while preserving broad exploration. Every adaptive replay slice reserves a
Forex experiment when Forex is enabled.

The planner reports expected information gain and never changes risk limits or
strategy readiness directly.

### Contextual Memory Compiler

`ForexMemoryCompiler` aggregates stored replay and paper evidence into
contextual memory cells keyed by strategy, pair family, session, regime and
setup. A cell records sample size, expectancy, benchmark excess, win rate,
cost failure rate, confidence interval and evidence grade.

Memory is only actionable when the sample threshold and out-of-sample evidence
requirements are met. Otherwise it remains `LEARNING_ONLY`.

### Decision Integration

Forex decisions receive a `knowledge_context` and `curriculum_context` for
explainability. Validated contextual memory may influence strategy confidence;
the general knowledge catalog may not. Hard vetoes for stale data, event risk,
costs and strategy readiness remain authoritative.

Experimental strategies with sufficient replay evidence may enter the existing
reduced-risk paper path. Certified confidence still requires the existing
forward sample and alpha gates.

### Snapshot and Scheduling

Knowledge catalog refresh, curriculum generation and memory compilation run in
bounded background jobs. Snapshots expose progress without triggering work.
No GET route downloads data, trains, recalculates or writes.

## Data Model

Add cross-database-safe tables:

- `forex_knowledge_sources`: source manifest, validation and permitted use;
- `forex_curriculum_assignments`: bounded research objective and status;
- `forex_contextual_memory`: compiled evidence by context;
- `forex_knowledge_ingestion_runs`: incremental cursor and validation results.

Historical evidence remains immutable. Compiled memory is versioned and
rebuildable from source outcomes.

## Safety

- No source-code self-modification.
- No confidence boost from text ingestion alone.
- No future data before a replay decision.
- No automatic bulk download during API reads or startup.
- No leverage or risk-limit increase.
- No strategy promotion without minimum sample, cost, benchmark and
  out-of-sample checks.
- Dataset license and provenance failures block ingestion.
- All external-source failures degrade safely and preserve existing trading.

## Verification

Tests must prove:

- catalog entries retain provenance and usage restrictions;
- knowledge-only sources cannot increase executable confidence;
- replay evidence compiles into contextual memory;
- insufficient samples remain learning-only;
- validated memory can influence strategy confidence conservatively;
- Forex curriculum is present in bounded replay cycles;
- all external fetches are background/manual and incremental;
- GET endpoints remain read-only;
- existing Forex execution, risk and paper lifecycle tests continue to pass.

## Expected Outcome

BLUM gains a durable Forex research curriculum and a clear path from external
knowledge to experiments, from experiments to validated memory, and from
validated memory to conservative paper actionability. More activity is earned
through better coverage and faster evidence production, not lower standards.
