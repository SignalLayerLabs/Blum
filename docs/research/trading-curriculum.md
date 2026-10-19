# Outcome-driven trading curriculum

The incremental memory was working, but its example counts did not demonstrate executable skill. This increment connects frozen historical episodes, actual expert selection, a cash-constrained simulator, checkpoint comparison and prospective research paper observation. It does not establish a profitable policy or authorize real-money execution.

## Implemented path

The bounded `trading_curriculum` worker runs every minute when learning and the curriculum are enabled. Each slice can train two lanes and update prospective observations across up to eight lanes: two assets per market/timeframe, USA and Forex, daily and five-minute. It uses existing replay coverage, at least 600 acceptable bars and quality 80, without downloading datasets in request handlers. Source packs hold at most 5,000 bars and remain immutable in a separate table. Exhausted training packs stop generating training examples; completed prospective observations can continue adapting the live selector.

Every pack freezes 60% chronological training, 20% development and 20% reserved confirmation, with a 14-bar boundary purge. Random 96-bar training blocks are shuffled without replacement; 60 preceding bars are warmup only. The worker learns completed counterfactual expert outcomes exactly once. Correlated experts and overlapping market regimes do not become independent statistical evidence.

Eight seeded contracts cover four mechanisms at 10/30-bar lookbacks: close-channel breakout, trend continuation, deviation reversion and pullback. They are explicitly versioned **BLUM single-frame adaptations**, not reproductions of published strategies. All use trailing ATR geometry, 1.5 ATR stop distance, 2R target, maximum 12-bar holding and long-only exposure. The contextual ridge selector predicts bounded net-R from trailing returns, volatility and range. It selects an expert **before** evaluating that expert's trigger: different learned choices can change activity, including waiting. No new dependency is required beyond installed NumPy and the shared evaluator/execution engine.

Mechanism references: [AQR's time-series momentum research](https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Original-Paper-Data), [QuantConnect's Donchian definition](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/donchian-channel), [Schwab's technical screening explanation](https://www.schwab.com/learn/story/how-to-pick-stocks-using-fundamental-and-technical-analysis), and [John Bollinger's own rules](https://www.bollingerbands.com/bollinger-band-rules). BLUM's close-channel rule differs from a high/low Donchian channel; its deviation rule differs from standard20-period/two-deviation Bollinger bands. These references establish mechanisms, not universal profitability.

## Causality, cash and execution

The shared clock releases US daily OHLC only after 16:00 New York plus one minute, including DST; daily opens use 09:30 New York. Non-US daily bars without a certified provider clock use a conservative 26-hour delay from their opening label. Intraday availability follows interval close plus one minute. The next executable bar must start strictly after the frozen decision. Missing/future/invalid bars are not silently repaired.

Each independent historical episode starts with 10,000 quote units, one position at a time, maximum 0.5% initial risk and no leverage. A predeclared 10 bp entry collar cancels adverse opening gaps; partial entry remainder is cancelled. Spread/slippage assumptions for opening fills are frozen from prior context, while participation capacity uses observed bar volume. Stops and targets are frozen before outcomes; stop-first handling is conservative when an OHLC bar reaches both. Gap stops fill at the adverse open. Commission is debited once; spread/slippage already embedded in fill prices are not debited again.

This remains an aggregate OHLC execution model: opening timestamps are modeled, not certified broker fills; full-bar participation is not observable opening depth. Insufficient exit capacity blocks the account, withholds its net-return claim and prevents reuse of tied capital. Exit-depth assumptions, missing FX carry/funding, dividends, corporate actions and survivorship require further validation. Forex uses an explicitly declared 100,000-unit OTC capacity scenario when reported volume is unavailable. It does not pretend OTC capacity is observed volume, and it does not merge quote-unit balances into the EUR portfolio.

Prospective observations freeze wall-clock time, input/checkpoint hashes, geometry and model before future fill bars. Observed bars are retained once, protecting an entry from later data revisions. An open or blocked position remains reserved; later slices resolve it. Completed outcomes update separate live sufficient statistics, preserving the historical checkpoint and historical development benchmark. This journal never writes into native or qualified paper P/L.

## Continuous comparison and actual result

Every training checkpoint is scored on the same development interval against cash and the unchanged seeded breakout expert. A separate same-asset price-only hold reference excludes dividends and costs and has different exposure. Reported measures include closed trades, Wilson win-rate interval, net return after modeled costs, closed-trade drawdown, profit factor and net-R expectancy. Wilson intervals assume independent Bernoulli observations; serial dependence can make them overconfident. Development is reused for monitoring; it is not an unbiased final test. Confirmation remains unopened.

The [reproducible receipt](../evidence/curriculum-evaluation.json) includes four packaged equity/ETF series and two fresh Yahoo Chart Forex series, with hashes and provider timezone treatment. Raw external prices remain outside Git. The run completed in approximately 21 seconds. These are **historical development returns**, not annualized or prospective results:

| Series | Seeded policy | Final learned policy | Final closed trades |
|---|---:|---:|---:|
| DIA |2.82%|1.09%|30|
| IWM |0.69%|1.89%|10|
| QQQ |2.90%|0.34%|7|
| SPY |3.57%|−0.34%|2|
| EURUSD |0.87%|−0.65%|3|
| GBPUSD |0.46%|−0.46%|16|

The learned policy improves **one of six** final comparisons and underperforms five. There is no broad alpha improvement and no high-win-rate claim. Consequently it remains an isolated experimental curriculum; existing promotion and trading gates are unchanged. The small final trade samples further limit conclusions. The engineering improvement is the closed, auditable learning/measurement loop and correction of execution/clock defects, not a proven profitable replacement.

## Dependency research decision

Unconstrained RL is deferred: [Stable-Baselines3's evaluation guidance](https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html) describes evaluation/seeding requirements; another RL package would not repair a leaking or disconnected execution contract. [Vowpal Wabbit contextual-bandit tooling](https://vowpalwabbit.org/docs/vowpal_wabbit/python/latest/tutorials/python_Contextual_bandits_and_Vowpal_Wabbit.html) is a future option when genuinely randomized logging and propensities exist. Counterfactual full-information expert replay needs no invented propensity values. Existing gradient-boosting/Optuna dependencies remain available for a separately validated challenger. Multiple-testing safeguards remain necessary; see the original [deflated-Sharpe work](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

## Operate and reproduce

- Public stored read: `GET /api/training/curriculum`; reading never starts training. The Research workspace displays the comparisons, identity, sample counts and separate prospective status.
- Protected bounded write: `POST /api/training/curriculum/run`, under the existing admin guard.
- Configuration: `TRADING_CURRICULUM_ENABLED` (default true), `TRADING_CURRICULUM_MINUTES` (default 1). Resource pressure defers the scheduled slice.
- Persistence: migration 0047 creates immutable sources, revision-guarded lane checkpoints and separate train/forward episode records. Normal source content is not rewritten on each checkpoint; public reads project compact summaries.
- Local experiment: `PYTHONPATH=backend python scripts/evaluate_trading_curriculum.py --output /tmp/curriculum.json`. Add `--forex 'EURUSD=X=/path/to/yahoo-chart-response.json'` for a locally retained provider response. The script uses `exchangeTimezoneName` for daily labels/availability and rejects unclosed bars. The public receipt records source hashes; prices are not redistributed.
