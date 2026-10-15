# Engineering Standards

Blum must be developed as a serious open-source technical case study. Every shipped increment should be designed for correctness, efficiency, transparency and maintainability.

## Non-Negotiable Rules

- Do not ship placeholders as working functionality.
- Do not fabricate data.
- Do not generate synthetic market prices, synthetic news, synthetic sentiment, synthetic backtest results or synthetic AI evidence.
- If a data source fails, report the failure clearly instead of filling the gap with fake values.
- If a feature cannot be fully implemented in the current increment, mark it as unavailable, document the limitation and do not present it as complete.
- Keep code, comments, UI copy and documentation in English.
- Treat every score as research triage, not financial advice or a trading recommendation.

## Efficiency Standard

Every implementation should aim for the best practical efficiency available within the current architecture.

Required practices:

- Prefer batch operations over per-row network or database calls.
- Use incremental updates where possible.
- Avoid recomputing indicators, embeddings or model outputs when persisted results are fresh.
- Keep provider calls bounded, retry-aware and observable.
- Keep AI models lazy-loaded and task-specific.
- Cache expensive model or vector operations only when the cache is evidence-preserving and invalidation is clear.
- Avoid blocking frontend rendering on long-running ingestion or model tasks.
- Keep API responses structured, compact and explicit.

## Data Integrity Standard

Every stored data row must preserve its source.

Required practices:

- Persist provider names for OHLCV data.
- Persist model names for sentiment, embeddings and AI explanations.
- Persist timestamps for ingestion, scoring and insight generation.
- Distinguish missing data from zero values.
- Distinguish provider failure from no matching data.
- Never silently downgrade from real data to synthetic data.

## AI Standard

AI modules must be specialized and evidence-bound.

Required practices:

- Use FinBERT or equivalent financial NLP for financial sentiment when available.
- Keep VADER as a baseline or fallback, not the primary engine when FinBERT is available.
- Use sentence-transformers for semantic retrieval and clustering.
- Use the LLM only for structured explanation from retrieved evidence.
- The LLM must not invent facts, prices, events, forward returns, recommendations or catalysts.
- Store model metadata with each AI output.

## Signal Standard

Signals must be explainable and auditable.

Required practices:

- Store factor inputs and normalized score components.
- Version score logic when weights or formulas change.
- Separate signal score, confidence, risk and classification.
- Explain why an asset surfaced.
- Explain what confirms the signal.
- Explain what contradicts the signal.
- Explain what to monitor next.
- Report missing evidence as part of the decision.

## UI Standard

The frontend must behave like a financial intelligence platform, not a decorative landing page.

Required practices:

- Prioritize dense but readable information.
- Show what to watch and why.
- Make loading, empty and error states explicit.
- Use charts and tables to support decisions, not decoration.
- Keep dark professional styling, clear hierarchy and responsive layouts.
- Avoid consumer-style visual filler.

## Verification Standard

Every meaningful increment should include verification.

Minimum checks:

- Python syntax or unit checks for backend changes.
- Type/build checks for frontend changes when dependencies are available.
- API smoke checks for changed endpoints when runtime is available.
- Documentation update when behavior, architecture or limitations change.
- Clear statement of what was and was not verified.

