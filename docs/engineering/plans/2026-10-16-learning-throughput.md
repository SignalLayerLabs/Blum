# Learning throughput and evidence

User priority: the engine must learn faster and produce measurable added value. This continues the operating-workspace goal; useful code and data must be delivered, not a claim that package count or model size proves intelligence.

Verified production at main63a0c11: the latest worker used80.4 seconds, considered zero new rows and reported BUDGET_EXHAUSTED for both markets. Optional FinRLX initialization runs before core learning. OnlineShadowTrainer reconstructs its estimator/preprocessing on every call, ignores sample weights and repeatedly receives the latest500 rows. Accepted packaged prices contain75,381 usable rows; old reasoning and the conflicting Forex archive remain quarantined.

## Contracts

Persistent SQLite checkpoints separate equity and Forex. A transaction stores the estimator, integrity checksum, contract version, processed source fingerprints and cumulative measurements together. Repeated identities cannot update weights twice; changed evidence is an explicit error. Future outcomes are rejected. Fixed hashed coordinates with log-compressed numeric inputs support missing values/new categories without learning future preprocessing statistics. Classification and robust net-R regression update with declared sample weights. The model stays shadow-only.

Historical test-before-update measurements use the model before a decision group is learned and exclude groups whose decisions precede already-consumed outcomes. Report coverage, overlap exclusions, Brier score and net-R error against a historical constant baseline. These are research measurements, not decision-time production predictions or proof of forward trading alpha.

Read bounded immutable feature-store partitions in commit order with a resumable cursor. Commit model/identity changes before advancing the reader cursor; replay after interruption is idempotent. Core market learning precedes optional external work. Unchanged data performs zero optimizer updates. Stable challenger dataset identity remains the hash of its actual bounded training window, separate from cumulative online lineage.

New sources require pinned revisions/hashes, provider attribution, permission/use scope, OHLC/date/duplicate checks, causal feature reconstruction and purged chronological evaluation. Twelve Data daily bars are a candidate for local research; their vendor rights and adjustment semantics need review. Papers With Backtest Forex is subscription-gated and is excluded from this release. Do not re-enable paid jobs or quarantine-rejected sources.

## Implementation and verification

- [x] Persistent per-market exactly-once online trainer, weight handling, causal measurements, restart/duplicate/corruption/concurrency tests.
- [x] Worker consumes unseen partitions, gives both core learning lanes first access to its budget and exposes real optimizer/sample progress; 10,000-row online capacity is separate from the 500-row challenger window.
- [x] Pinned local source adapter and quality audit; separate feature/label times and training/validation/final holdout. Vendor rights and negative validation keep the new data out of runtime ingestion.
- [x] Real-data baseline comparison and repeated-run workload measurements. Corrected v2: 100,000 examples / 7.83 seconds locally, repeated 500 rows / zero optimizer updates; neither classifier beats the 2024 baseline. No before/after latency ratio or alpha claim.
- [ ] Full tests, independent review, PR and concrete release approval, then deployed progress/continuity verification.

Ruling: use the existing scikit-learn/Polars/SQLite runtime for the observed state and scheduling defects. A new dependency requires measured benefit on a declared holdout. No paid hardware, new credentials, weaker risk/promotion gates or market-outperformance guarantee are implied.

Local final verification: `python -m pytest -q --disable-warnings --tb=short` — 955 passed, 25,125 warnings, 113.64 seconds. Packaged historical audit and HF Space metadata checks passed. Independent review findings on rejected-page ordering, checkpoint/cursor recovery, committed-progress reporting and future eligibility were reproduced with failing tests and resolved. Separate-process retention was verified. CI, final merge approval and deployed verification remain release steps.
