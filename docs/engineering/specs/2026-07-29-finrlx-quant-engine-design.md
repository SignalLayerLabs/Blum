# BLUM FinRL-X Quant Engine Design

## Goal

Add FinRL-X as an optional quantitative research and policy-challenger engine
without transferring market-data, risk, execution, or strategy-promotion
authority away from BLUM.

## Verified Upstream Boundary

The integration targets `AI4Finance-Foundation/FinRL-Trading` at pinned source
revision `e65d6f0483ead7d2ef4a5fc940cdf960392a25c1`. The upstream project is
Apache-2.0 licensed and exposes a weight-centric strategy contract. Its current
implementation is equity and Alpaca oriented; it is not a native BLUM Forex
broker, risk, or lifecycle implementation.

## Architecture

BLUM exports immutable, point-in-time training rows through its existing
Trading ML feature store. A bounded background worker may invoke a configured
FinRL-X-compatible runner outside the API process. The runner returns a signed
manifest and policy artifact. BLUM validates provenance, artifact hash, feature
schema, market family, action schema, and supported algorithm before registering
the result as a challenger.

At decision time, an optional adapter converts policy output into a normalized
`QuantPolicyProposal`. For equities this may represent target weights. For
Forex it represents a bounded directional score, never raw leverage or broker
orders. Existing BLUM deterministic blockers, cost checks, portfolio risk,
position sizing, and execution remain authoritative.

## Components

- `FinRLXArtifactManifest`: immutable provenance and compatibility contract.
- `FinRLXArtifactValidator`: rejects untrusted, incompatible, or modified
  artifacts before deserialization.
- `FinRLXQuantEngine`: optional subprocess boundary for training and a
  normalized inference interface.
- `QuantPolicyProposal`: common HOLD/LONG/SHORT or target-weight response with
  confidence, uncertainty, provenance, warnings, and paper-only status.
- Existing `TradingMLModelRegistry`: persists only validated challenger
  metadata and retains current promotion gates.
- Existing `TradingMLLearningWorker`: schedules bounded research work; no GET
  endpoint or frontend render starts training.

## Data Flow

1. Existing terminal trade evidence is projected point-in-time.
2. The background worker exports a bounded immutable dataset.
3. The optional runner trains one configured algorithm.
4. The runner writes an artifact and manifest atomically.
5. BLUM validates both and registers a `CHALLENGER`.
6. Challenger inference is stored as shadow evidence.
7. Existing purged walk-forward, cost, diversity, calibration, and forward
   evidence gates decide whether it can become `ACTIVE`.
8. An active policy can adjust confidence only within BLUM's existing bound;
   it cannot remove a blocker or create an order.

## Forex Contract

The Forex adapter consumes BLUM features and broker context: pair, timeframe,
session, spread, slippage, volatility, liquidity, expected costs, margin
context, and current currency exposure. Policy output is a signed score in
`[-1, 1]`. BLUM maps the sign to LONG/SHORT and magnitude to bounded advice.
Stops, targets, lots, leverage, margin, swap, and fills remain exclusively
owned by BLUM.

## Failure Behavior

- Missing optional runner: `UNAVAILABLE`; BLUM continues normally.
- Timeout: worker records `TIMEOUT`; no partial artifact is loaded.
- Hash or schema mismatch: `REJECTED`; artifact is never deserialized.
- Unsupported algorithm or market: `REJECTED`.
- Insufficient evidence: challenger remains shadow-only.
- Existing deterministic blocker: policy adjustment is zero.

## Performance

PyTorch, Stable-Baselines3, and FinRL-X are not imported during application
startup. Training runs only in a bounded subprocess/background worker.
Inference uses only previously validated local artifacts. Snapshot GETs remain
read-only.

## Safety

This release is paper/research only. It does not add broker integration, enable
real-money execution, claim alpha, or promote pretrained public checkpoints.
All proposed influence is auditable, reversible, sample-aware, and subordinate
to BLUM risk controls.

