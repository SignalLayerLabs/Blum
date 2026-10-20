# Curriculum source recovery

PR14 reached production at `c09579f`, but its first operational check found four Forex lanes with 30 attempted blocks each and zero learned outcomes. No USA lane had been created. Deployment success did not establish useful learning.

## Reproduced failure

The two captured Yahoo daily responses each contained 2,608 London-midnight labels followed by a quote timestamp equal to `meta.regularMarketTime` (`2026-10-19T10:21:50Z`). The importer stored every distinct timestamp as another candle. Repeated polling could therefore accumulate quote observations under a daily or five-minute label. Yahoo's maintained adapter documents this separate live-row behavior in its [source](https://github.com/ranaroussi/yfinance/blob/main/yfinance/utils.py).

The deployed daily development partitions contained 970 observations in approximately eight days. The five-minute partitions contained 986 observations within approximately 27–29 hours, where fewer than 350 distinct five-minute openings fit. These corpora cannot represent the declared intervals. Exact per-episode attribution still requires the new stored diagnostics; the summary alone does not prove every rejected training context.

Discovery also depended on a request-range coverage table. Its local-history fast paths did not always populate that table. More importantly, discovery rejected an entire multi-year pack if even one candle failed validation. The live USA PriceHistory report showed 73 active histories through 16 October; reading those prices directly avoids catalogue omissions and mixed daily timestamp labels.

## Recovery contract

- Yahoo quote observations outside the declared opening grid are quarantined at acquisition. An on-grid candle must also be closed before the request cutoff; it is never rounded, resampled or manufactured from a quote.
- A validated closed refetch may replace a legacy partial at equal or better source quality once. Existing frozen curriculum packs and monetary journals are untouched.
- A legacy record (including PriceHistory, whose rows are replaced on refresh) captured before its declared availability remains invalid until that refetch. Simply waiting does not finalize previously captured OHLC.
- Source policy `declared-open-grid-v2` filters non-candle labels before the bounded source query. USA daily lanes prefer stored PriceHistory; other lanes use ReplayMarketBar. Actual missing intervals and invalid canonical candles remain in the evidence and block affected contexts or execution paths.
- Readiness counts only the decisions actually sampled by the existing training blocks. An unusable source cannot crowd out another eligible asset. Candidate preferences are fixed before observing performance, and existing lanes retain priority.
- Replacing the source policy archives the previous payload, model, benchmark, checkpoint, cash state and source references. The source and episode tables retain their original rows. Counters restart for the new corpus and are never added to the old counters. A pending prospective decision retains its original source until terminal. Replacement uses revision compare-and-swap.
- The stored public report distinguishes attempted blocks, productive blocks, learned dependent outcomes, missing or invalid contexts, no trigger, and execution statuses. An exhausted corpus with no outcomes is labeled explicitly.

This repairs data readiness and observability. It does not relax promotion, force trades or establish alpha. Quote-currency research cash remains separate from portfolio accounting. Stored PriceHistory has no independent publication-vintage audit; corporate actions, source revisions and survivorship remain research limitations.

## Reproduction

The committed [recovery receipt](../evidence/curriculum-source-recovery.json) runs the production worker against a fresh, temporary database using the packaged QQQ/SPY history and the two hashed raw Forex responses. No production state is read or written. Raw external data stays outside Git.

```sh
PYTHONPATH=backend python scripts/verify_curriculum_source_recovery.py \
  --forex 'EURUSD=X=/path/to/eurusd-yahoo.json' \
  --forex 'GBPUSD=X=/path/to/gbpusd-yahoo.json' \
  --output /tmp/curriculum-source-recovery.json
```

The recorded run completed 60 distinct blocks across four lanes and learned 1,109 dependent expert outcomes: EURUSD 70, GBPUSD 62, QQQ 475 and SPY 502. Forty-five blocks produced at least one closed outcome. A new database session then added zero historical updates and retained the same source hashes, checkpoints and counters. Invalid Forex candles remained in the packs.

These are correlated expert outcomes, not 1,109 independent trades. Development returns were approximately −0.39% EURUSD, −0.97% GBPUSD, +0.34% QQQ and −0.34% SPY, with only 1–7 selected-policy closed trades. Confirmation remains unopened. This is evidence of working outcome ingestion and checkpoint retention; it does not support a high win-rate or superior-return claim. Source cleanup changes the corpus, so these returns must not be compared with the contaminated production partitions.

## Release acceptance

After deploying this correction, verify the exact backend and gateway revision, inspect source-policy replacement and its preserved history, and observe new learned outcomes on eligible USA and Forex lanes. Check a subsequent cycle for retention and duplicate rejection. A stale source, invalid context, absent trigger or unfilled order remains an explicit waiting/blocking result. Do not report qualified trading or live profitability from research counts.
