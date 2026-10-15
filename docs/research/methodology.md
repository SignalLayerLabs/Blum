# BLUM Research Methodology

BLUM treats a market decision as an experiment. A profitable paper trade can
still be poor process, and a controlled loss can still be a valid decision.

## Evidence classes

Results remain separated by evaluation strength:

1. **Training replay** develops hypotheses from historical observations.
2. **Walk-forward validation** evaluates frozen decisions on later observations.
3. **Paper-forward** records decisions before future market data exists.
4. **Live-forward** is reserved for independently timestamped forward evidence
   where that source is available.

Metrics from one class are not relabeled as another. A replay result cannot
establish paper-forward alpha.

## Point-in-time rules

- a decision can use only evidence available at its timestamp;
- future outcomes are stored separately from the original thesis;
- training and validation windows require temporal separation where applicable;
- benchmark periods must match the decision holding period;
- missing data remains missing rather than being synthesized;
- a stored revision identifies model weights and memory used by each decision.

## Execution realism

Paper outcomes should separate theoretical and executable prices and account for
available spread, slippage, commissions, volume participation, partial fills,
gaps, latency and market hours. If required execution inputs are unavailable,
the result must disclose the simplification or remain ineligible for strong
evidence.

## Benchmarking

BLUM compares decisions with relevant alternatives such as SPY, QQQ, VTI,
sector ETFs, cash and simple strategy baselines. Benchmark methodology is
validated before benchmark-relative outcomes can enter learning.

Absolute return and benchmark excess answer different questions and are reported
separately. Capital-cycle resets and compounding must be aligned before comparing
performance.

## Statistical caution

Every edge claim requires enough independent observations across assets, periods
and regimes. BLUM reports sample size, concentration, drawdown, transaction-cost
sensitivity and forward coverage. High profit factor or win rate with a small or
concentrated sample is early evidence, not proof.

Candidate strategies should be rejected when they fail net-cost expectancy,
walk-forward robustness, regime stability, concentration, complexity or
multiple-testing controls. Promotion is reversible and versioned.

## Learning contract

Outcomes may update confidence, reliability memory, research priorities and
candidate rules only through auditable records. Insufficient samples freeze
weight changes. A learning event never edits source code and never bypasses risk
or portfolio controls.

## Claims BLUM does not make

- guaranteed returns;
- daily benchmark outperformance;
- production broker readiness;
- reliable alpha from replay alone;
- certainty from model-generated explanations;
- safety of using paper results with real capital.

BLUM is open-source research and paper-trading software, not financial advice.
