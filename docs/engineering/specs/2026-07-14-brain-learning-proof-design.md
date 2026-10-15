# Brain Learning Proof Design

## Objective

Make the Brain page answer, from stored evidence, whether BLUM is learning, how quickly it is learning, whether paper decisions are profitable, whether performance is improving versus a benchmark, and what still blocks copy readiness.

The page must not imply that every trade can or should be profitable. Robustness is measured through positive net expectancy, bounded drawdown, benchmark-relative results, calibration, reproducibility and sufficient forward samples.

## Product Contract

The Brain page continues to make one read-only request to `GET /api/brain/snapshot`. The response gains three bounded evidence sections:

- `learning_proof`: productive cycles, predictions, evaluated outcomes, memory updates, outcome conversion rate and a timestamped learning-throughput series.
- `trading_proof`: closed/open trades, wins, losses, realized and unrealized P/L, expectancy R, maximum drawdown, BLUM and benchmark equity series and evidence source.
- `copy_readiness`: strategy readiness, real-capital eligibility, maturity, forward sample and observation progress, blockers and the next milestone.

Unknown values remain `null`. Historical, walk-forward and paper-forward evidence remain separately labeled. No GET runs training, recalculation or trade lifecycle work.

## User Interface

The first screen retains the existing terminal layout and adds a compact evidence area:

1. `Brain Improvement`: Brain Score, Decision Quality and Learning Velocity over time.
2. `P/L vs Benchmark`: cumulative BLUM and benchmark curves with realized P/L, win/loss count, expectancy and drawdown.
3. `Learning Throughput`: predictions, outcomes and memory updates per learning cycle.
4. `Copy Trading Gate`: current readiness, progress toward forward sample and observation thresholds, capital eligibility and blockers.

Charts use lightweight responsive SVG and do not add a charting dependency. Empty and insufficient-evidence states explain what data is missing instead of drawing synthetic lines.

## Data Sources

- Brain evolution: `BlumTradingPowerScore` and `LearningProgressSnapshot`.
- Learning throughput: bounded recent `LearningRun` rows.
- Trading performance: stored terminal `LiveForwardPaperTrade` rows and stored benchmark-relative fields; historical replay remains separately identified when used.
- Copy readiness: latest append-only `StrategyReadinessHistory` through `CopyReadinessSummaryService`.

## Safety

- No broker integration or real-money execution.
- No claim that every investment will be profitable.
- No copy-ready status from replay evidence alone.
- Missing benchmark or P/L data is displayed as unavailable, never zero.
- The snapshot reports sample size and evidence class next to performance.

## Verification

- Backend tests prove bounded, read-only aggregation and null-preserving behavior.
- Frontend validation proves one Brain request, responsive chart rendering and honest empty states.
- Full backend suite and production frontend build must pass before deployment.

