# Kronos assessment — 20 October 2026

**Decision: retain as an experimental pretrained price-path challenger. Do not enable trading authority or claim an alpha improvement.** A local CPU feasibility probe succeeded, but the small diagnostic sample does not establish predictive superiority. The approved information → native paper execution → outcome learning architecture remains necessary.

## What it contributes

[Kronos](https://github.com/shiyu-coder/Kronos) forecasts OHLCV/amount sequences using a financial tokenizer and autoregressive model. Mini has 4.1M parameters and a 2048-bar context; small/base have 24.7M/102.3M parameters and 512-bar contexts. Large weights are not public. The repository and the [mini model card](https://huggingface.co/NeoQuasar/Kronos-mini) declare MIT licensing. Preserve notices if redistributing code.

The [paper](https://arxiv.org/html/2508.02739v1) reports pretraining through June 2024 and later forecasting tests including Forex without volume. Its portfolio simulation concerns Chinese equities with a 0.15% per-trade cost. That experiment is not a BLUM USA/Forex execution result; the paper's cutoff is not independent verification of every later mini checkpoint's training provenance.

## Actual local probe

Pinned source: `67b630e67f6a18c9e9be918d9b4337c960db1e9a`. Mini weights: `f4e68697d9d5aed55cef5c96aabc3376bcad9f81`. Tokenizer: `26966d0035065a0cae0ebad7af8ece35bc1fb51c`. Weight hashes and the protocol frozen before inference are in [the probe manifest](2026-10-20-kronos-probe.json).

CPU, two threads, PyTorch 2.13.0, 64 daily context bars, five forecast bars, four separate seeded calls per origin. Only complete positive, finite and geometrically valid input OHLC windows were accepted. Dates after 9 September 2025 were considered, with at least ten bars between origins and a maximum of eight per asset. Local dependencies and approximately 32 MB of safe tensor weights stayed outside the application environment. Existing raw cached prices were used; dataset-derived macro/technical features were excluded.

| Diagnostic | AAPL | EUR/USD |
| --- | ---: | ---: |
| Usable origins | 8 | 2 |
| Mean path MAE, basis points of origin close | 371.81 | 26.56 |
| Unchanged-price MAE, same units | 363.48 | 26.81 |
| Correct terminal price directions | 3/8 | 0/2 |
| Valid OHLC generated paths | 26/32 | 4/8 |
| Median five-bar path inference | 15.5 ms | 15.4 ms |

Model plus tokenizer loading took 0.14 s; total measured process peak RSS was approximately 362 MiB. These are measurements on the local Mac, not Hugging Face hardware guarantees. Timing excludes imports and input parsing. Ten generated paths violated OHLC geometry; do not repair them silently or treat them as executable market bars. No validity-conditioned performance claim is made.

This is an exploratory current-vintage forecasting diagnostic, not a point-in-time backtest, trading win rate or financial trial. Original data availability, corporate-action vintages and source session labels are not certified. There are no modeled fills, fees or portfolio accounting in this probe. Yahoo requests returned HTTP 429 and an alternate CSV endpoint returned HTML; neither response was accepted as price data or bypassed. The sample is too small for significance or promotion.

## Integration requirements

- Run optional inference in a bounded worker, with pinned code, safe tensor artifacts, explicit CPU/RAM limits and cache keys containing model, input and schema hashes. An unavailable challenger must not delay management of open positions.
- The [upstream predictor](https://github.com/shiyu-coder/Kronos/blob/67b630e67f6a18c9e9be918d9b4337c960db1e9a/model/kronos.py) averages paths when `sample_count` exceeds one. Retain separate seeded paths for distribution features. Path frequency is not calibrated trade profitability.
- Preserve missing FX volume/amount as missingness alongside the model's zero sentinel. Validate generated prices, horizons and exchange calendars; forecasts never enter observed-bar tables or become realized training labels.
- Compare mini and, if resource budgets allow, small against the unchanged-price baseline, current numerical model and established strategies on frozen chronological windows. Calibrate any trade advice on genuine matured outcomes, with net costs and market evaluations separate. Additional tuning needs a development split; it cannot consume the final holdout repeatedly.
- Only the existing native ledger can create fills and outcomes. Prospective qualification still requires the predeclared complete-account trial and evidence thresholds in the approved specification.

The upstream requirements file pins versions that differ from BLUM. It was not installed into the application. `einops==0.8.1` was extracted into an isolated probe directory after wheel SHA-256 verification; no new production dependency or remote execution service was enabled.
