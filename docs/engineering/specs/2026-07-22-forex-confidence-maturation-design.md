# Forex Confidence Maturation and Paper Trading Segmentation

## Goal

Increase useful Forex confidence through better data freshness and validated
strategy evidence, never by inflating scores, and separate Forex from equity
opportunities on the snapshot-first Paper Trading page.

## Current Evidence

- Forex agents emit confidence on a normalized 0..1 contract.
- The latest production decisions are blocked by `NO_NET_EDGE` and
  `STRATEGY_NOT_READY`; most also contain `STALE_DATA`.
- Twelve pairs are eligible for scanning, but the refresh worker updates only
  one pair per minute while 1-minute evidence expires after three minutes.
- The strategy repository returns `unavailable` when no promoted or validated
  experimental Forex strategy matches `1h/15m/5m/1m`.
- Paper Trading receives all rows in one snapshot and currently renders the
  newest Forex decisions before older equity rows.

## Design

### Confidence Ladder

The Forex proposal will expose distinct 0..100 components:

- `setup_confidence`: price-action quality and timeframe agreement;
- `data_confidence`: frame quality and freshness;
- `strategy_confidence`: sample-aware historical reliability;
- `execution_confidence`: net edge after spread, slippage and commission;
- `decision_confidence`: weighted analytical confidence;
- `actionability_status`: executable or blocked, with explicit blockers.

The analytical score uses a weighted mean rather than a minimum so one veto
does not erase all useful analysis. Vetoes remain hard actionability gates. A
blocked setup can therefore have measurable analytical confidence while still
being forbidden from opening a paper position.

Strategy confidence is shrunk toward a conservative prior when sample size is
small. No strategy becomes paper eligible from confidence alone.

### Freshness Scheduler

The refresh service selects the stalest pairs first. Its per-minute batch is
at least `ceil(pair_count / freshness_window_minutes)`, bounded by the existing
configuration and pair count. With twelve pairs and a three-minute budget, at
least four pairs are refreshed each minute.

Provider timestamps remain authoritative. Delayed or stale evidence lowers
data confidence and blocks execution; it is never treated as a current fill.

### Strategy Evidence Bootstrap

Forex consumes only stored strategy validations from the existing Alpha
Strategy Factory registry. The factory/replay path must produce Forex variants
with the exact `1h/15m/5m/1m` stack and `FOREX`/`Forex` support metadata.

The existing gates remain authoritative:

- at least 50 robust samples for reduced-risk experimental paper evidence;
- at least 300 validated trades plus positive net expectancy, benchmark excess,
  stability and overfitting checks for certified promotion.

When no strategy passes, BLUM records training-only decisions and their
component scores. It does not open trades and does not fabricate readiness.

### Paper Trading Tabs

The page uses the existing unified snapshot and performs no additional fetch.
Two client-side tabs are rendered:

- `Azioni / ETF`: standard and equity intraday rows;
- `Forex`: Forex decisions and positions.

Each tab independently shows candidates, open positions and closed trades.
Aggregate evidence cards remain visible so total performance is not hidden.
The default tab is `Azioni / ETF` so Forex volume cannot obscure equities.

## Safety

- No confidence is increased without observed components.
- No stale quote can create an immediate fill.
- No strategy gate is lowered.
- No GET endpoint computes, trains or writes.
- No frontend mount triggers Forex cycles or replay.
- Raw component values and blockers remain auditable in frozen decisions.

## Verification

- Unit tests cover confidence components, sample-size shrinkage and hard vetoes.
- Scheduler tests prove oldest-first coverage and the minimum freshness batch.
- Registry tests prove Forex validation metadata is required.
- Frontend source/build tests prove tab filtering uses one snapshot request.
- Full backend suite and production snapshot are checked before completion.
