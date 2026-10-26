# Blum v3 research and paper trading

Approved scope: a complete application rewrite, separate equity/ETF and Forex evaluation, research and paper trading on real observations before broker integration. Preserve v2 as read-only migration evidence and a reversible deployment option. No profitability or universal benchmark-superiority claim follows from shipping software.

## Architecture

New Python 3.12 package `blum_v3`, FastAPI `/api/v3`, PostgreSQL transactional journal and durable jobs, immutable local/object artifact interfaces, and a new TypeScript/Next.js static application in `web_v3`. Domain modules never import legacy application services. One accepted journal owns financial events and projections; each paper account has serialized writes. Execution adapters and model outputs cannot overwrite financial truth. A pinned optional native matching adapter requires explicit compatibility checks; unavailable adapters fail explicitly.

Every source, transform, experiment, decision, order and fill has versioned identity and availability clocks. Money, percentages, basis points and R multiples are distinct. Decimal money and explicit currency conversion are mandatory. Repeated commands have idempotent effects; changed payloads under one key are rejected. Corrections are appended, not silently edited. Readers cannot initiate financial computation.

## Data and research

Accept attributed real OHLCV and bid/ask files; optional public history retrieval remains research-only and preserves provider terms. Reject incoherent OHLC, negative/unknown volume confusion, conflicting duplicate keys, invalid sessions, naive timestamps and future information. Source and first-seen clocks remain distinct. Historical availability assumptions are disclosed. Old quarantined Forex/reasoning data is not training evidence.

Three explicit tiers: BAR_RESEARCH, MODELED_PAPER and QUOTE_QUALIFIED_PAPER. The second uses actual observations with declared cost/fill scenarios. The third needs prospective clocks, actual quotes, financing, eligible conversions and reconciliation; it is unavailable when any required evidence is absent. No fabricated market fallback or silent zero cost. Dividends/total return require explicit actions; otherwise report price returns.

Hypotheses, inputs, splits, cost/risk/benchmark settings, model/version and trial family are frozen before scoring. Fit preprocessing on training folds only; chronological splits purge overlapping outcome horizons and enforce embargo. Record all alternatives and failures. Holdouts cannot be repeatedly tuned against. Begin with simple momentum/trend and regularized/nonlinear challengers. Verify statistical units independently; do not invent PBO/DSR when their input experiment is missing. NLP/RL assistance is optional and never owns account authority.

## Execution and accounting

The same frozen decision, order and ledger contracts drive replay and prospective paper. Decisions cannot fill on an already-observed close. Model partial fills, stop/limit expiry, gaps, adverse spread/slippage, capacity, commission, conversion and financing. Intrabar ambiguity uses a disclosed conservative scenario. Preserve zero-volume orders as unfilled. Distinguish OTC FX capacity assumptions from reported equity volume.

Reserve accepted orders, release/settle through their lifecycle and include pending orders in risk. Journal postings balance by currency; cash, open positions, fees and eligible conversions determine NAV. Marked NAV and modeled liquidation value are separate. Unknown risk remains unknown. Initial paper defaults: gross exposure <=1x NAV, instrument <=20%, daily loss stop 2%, drawdown stop 10%; equity long/cash, Forex long/short. Configuration is frozen per account/experiment and is not real-money advice. Missing/stale market state or reconciliation blocks new risk while reducing actions remain possible when safely executable.

Keep sleeve currencies and result series separate. Currency conversion needs an eligible observed rate and reference; never sum unlike currencies. Portfolio drawdown includes open positions. Classification scores, closed R outcomes and portfolio returns cannot share an ambiguous label.

## Product and evaluation

Research, Paper Portfolio, Performance and Operations workspaces expose hypothesis-to-run-to-paper workflows, source freshness, exclusions and meaningful errors. Authenticated mutations create durable resumable jobs; read-only projections never start training/trading. Model chat is optional. Use compact charts and tables, accessible forms and responsive layouts.

Freeze primary benchmark and secondary comparisons before a run. Equity references include declared passive allocation and cash; relevant SPY/QQQ comparisons need actual aligned observations. Forex benchmarks are account strategies (cash/no-position and a frozen simple rule), not currency price ratios. Report net returns, open NAV drawdown, exposure, turnover, capacity, costs, benchmark excess, uncertainty, concentration, exclusions and trial counts. Stress costs at 1x/2x and additional latency. Prospective evidence is distinct from historical replay. Strong performance qualification requires complete paths, adjusted uncertainty, risk compliance and predeclared statistical power; floors of 60 sessions/100 outcomes alone do not prove an edge.

## Durability and delivery

Production requires external PostgreSQL, tested backups/restores, durable job ownership and writer leases. SQLite is local development only. Version schema changes and retain immutable source/experiment artifacts. Preserve v2 evidence in a separate read-only namespace; new paper accounts have a new epoch. No silent import of legacy champions/track records. Cutover disables the old writer before enabling its replacement. Rollback retains v3 events and never enables competing writers.

No broker orders, paid provider purchases or production cutover are part of this PR. Deployment assets must make v3 runnable independently. Missing provider/database access is an explicit operational limitation. Keep code/docs English and product copy focused on Blum behavior. Preserve mandatory third-party license notices.

Completion requires domain/accounting invariants, causal/split checks, deterministic replay, crash/retry recovery, held-out baseline/stress reports, real-data equity/FX research-to-paper paths, API authorization, side-effect-free reads, frontend build/browser checks and reversible archive/cutover receipts. Market fixtures in tests are mathematical contract cases, never published performance evidence.
