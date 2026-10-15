# Prospective Alpha Desk

BLUM 2.3 records what its decision engines actually call before observing the outcome. The objective is a reproducible, cost-aware track record across equities/ETFs and Forex. Bloomberg product superiority and market-leading alpha are ambitions, not established results.

## Registration

New paper candidates and final Forex decisions register in the same transaction as their authoritative source records. A unique source identity prevents duplicate registration. The manifest freezes the decision, model/strategy, confidence and price inputs. Its SHA256, source revision and protected-code fingerprint preserve lineage. Changes to a registered manifest are rejected or shown as integrity blockers. Completed historical decisions cannot be retrospectively registered.

The source engines retain order, risk and accounting authority. The registry is an audit record, not a second execution engine. It does not merge code or promote a model. Confidence is explicitly heuristic and is not advertised as a calibrated probability.

## Qualification

- Equity daily inputs may be at most 96 hours old at decision time. Forex inputs may be at most 180 seconds old.
- A named provider and source/availability timestamps are required; future input timestamps fail. Available quality scores below 70 fail.
- Registration delayed more than five minutes from the decision is unqualified. Current calls also need fresh quotes and an explicitly stored positive expected net edge.
- Side and entry/stop/target geometry must be valid. A closed call requires actual opening and closing timestamps and registration before closure.
- Net P/L must reconcile with gross P/L and recorded execution costs. Realistic fills already incorporate spread/slippage: their explicit commission and FX cash fees reconcile separately, with four-decimal P/L rounding tolerance. Forex swap credits are income; debits are costs. Unfilled orders never enter realized samples; filled positions closed by time expiry or invalidation remain realized outcomes. Account-currency totals remain separate.
- Paired percentage alpha additionally needs a positive notional whose gross holding return matches recorded gross P/L, plus a benchmark contract aligned to the actual entry and exit dates. Price endpoints require named providers and availability no later than their respective opening/closure. Missing days cannot substitute older closes. These are daily price benchmarks, not intraday total-return indices. Missing or inconsistent values remain missing. Native Forex calls lacking the required notional/benchmark contract cannot produce paired alpha.

These gates verify internal record consistency and declared source availability. They do not independently certify a provider's entire history, every model input, or all underlying database rows. A hash alone does not establish semantic validity. The prior data quarantines remain active.

## Evaluation

The service reads at most 2,000 recent registrations and reports truncation. Equity and Forex samples, exclusions and rankings are separate. Costs-qualified observations and paired benchmark observations have different counts. An absent P/L or benchmark displays as unavailable, not zero.

A deterministic bootstrap resamples complete closure-date groups, with 800 draws and seed 3407. The interval is a two-sided 95% empirical interval. A positive paired-sample label requires 100 paired observations, 30 closure dates, three assets and a lower bound above zero. These are conservative application gates, not a universal statistical certification standard. The interval does not correct selection bias, repeated monitoring or every overlapping holding period; it never authorizes promotion.

Irregular trade returns are not annualized into Sharpe ratios. Mean trade excursion is not represented as a portfolio equity-curve drawdown in this Desk. Legacy panels remain descriptive; positive historical grades without independently verified provenance are marked insufficient.

## Operation and limits

`GET /api/alpha/desk` and the existing Alpha snapshot read stored evidence. Page load cannot register calls, train weights or run orders. Public mutations remain blocked at Cloudflare and origin. Existing paid training stays disabled and all execution remains paper-only.

The maintained Space uses embedded PostgreSQL and periodic object-storage backups. Registrations inherit that recovery policy; they are not a guarantee of zero-loss restart durability. Failed logical restores stop startup. External PostgreSQL with a verified durability/recovery configuration is required for stricter guarantees.

The 2.3 registry starts empty. Legacy outcomes remain available, but cannot be counted as newly registered prospective calls. Qualification and independent forward performance must accumulate over real time.

## Research references

- [Bloomberg BQuant](https://professional.bloomberg.com/products/bloomberg-terminal/research/bquant/) describes Bloomberg's quantitative research platform; it supplies no public common test set establishing relative BLUM alpha.
- [Bailey and López de Prado: The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) explains selection bias and non-normality. BLUM does not label the Desk's bootstrap as DSR or as a multiple-testing correction.
