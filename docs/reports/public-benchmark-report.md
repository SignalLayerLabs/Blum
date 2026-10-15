# BLUM Finance Public Benchmark Report

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Objective

Publish BLUM Finance through reproducible public evaluations without treating
language-model benchmark scores as trading performance.

## Benchmark Targets

### Hugging Face Open LLM Leaderboard

The official suite evaluates:

- IFEval;
- BBH;
- MATH Level 5;
- GPQA;
- MuSR;
- MMLU-PRO.

The submitted artifact is the immutable portable Transformers repository
`Italianhype/Blum-Finance-4B`, revision
`ad6f5cec7f729370d2976d8c78983521cb37ca83`, BF16 precision, original weights
and the model's chat template.

The automated submission endpoint rejected the model because its validator
classified Qwen3 as requiring `trust_remote_code=True`. This is not true with
the validated local runtime (`transformers==4.57.6`): `AutoConfig`,
`AutoTokenizer` and `AutoModelForCausalLM` load without remote code. The
leaderboard result therefore remains unavailable rather than failed.

### Financial Evaluation

Financial evaluation remains separate:

- BLUM temporal reasoning test for evidence attribution and fabrication;
- FinBen/FinQA-compatible evaluation for financial language and numerical
  reasoning;
- paper-forward and benchmark-relative outcomes for actual trading evidence.

Only the last category can provide evidence about trading decisions. Static LLM
benchmarks cannot establish alpha.

### MMLU Finance and Business

A reproducible community evaluation uses the canonical `cais/mmlu` test splits
for:

- business ethics;
- econometrics;
- high-school macroeconomics;
- high-school microeconomics;
- management;
- marketing;
- professional accounting.

The protocol is five-shot multiple-choice scoring over answer-token logits,
with a deterministic cap of 100 test rows per subject. It records per-subject
accuracy, micro/macro accuracy, sample counts, Wilson 95% confidence intervals
and all predictions. It is explicitly not an official leaderboard score.

Dataset revision: `c30699e8356da336a370243923dbaf21066bb9fe`.

## Community Evaluation Result

| Subject | Correct | Samples | Accuracy |
|---|---:|---:|---:|
| Business ethics | 77 | 100 | 77% |
| Econometrics | 65 | 100 | 65% |
| High-school macroeconomics | 70 | 100 | 70% |
| High-school microeconomics | 87 | 100 | 87% |
| Management | 87 | 100 | 87% |
| Marketing | 92 | 100 | 92% |
| Professional accounting | 46 | 100 | 46% |

- Total: `524/700`
- Micro accuracy: `74.86%`
- Macro accuracy: `74.86%`
- Wilson 95% confidence interval: `71.51–77.93%`

The result is an author-run, stratified subset evaluation. It is not the full
MMLU suite, an official leaderboard score, or evidence of trading alpha.
Professional accounting is the clearest measured weakness and is disclosed
rather than averaged away.

### Independent Professional Evaluations

Submission packages are prepared for:

- Vals AI `CorpFin v2` and `Finance Agent v2`;
- Scale Labs `Professional Reasoning Benchmark - Finance`.

Both organizations run or control their own benchmark process. No Vals or Scale
score is claimed before they independently evaluate the immutable revision.

## Portable Conversion

- Source MLX model: `Italianhype/Blum`
- Base: `Qwen/Qwen3-4B`
- Base revision: `1cfa9a7208912126459214e8b04321603b3df60c`
- Adapter rank: `8`
- MLX scale: `20`
- Equivalent PEFT alpha: `160`
- Adapted layers: `20–35`
- Fused modules: `112`
- Missing modules: `0`

MLX stores A as input-by-rank and B as rank-by-output. The portable conversion
transposes both tensors and preserves the update `20 × Bᵀ × Aᵀ`. The converted
PEFT adapter and merged Transformers model produced identical deterministic
smoke output.

## Portable Validation

The portable five-example smoke evaluation on source evidence returned:

- aggregate task-contract score: `97.32%`;
- structured validity: `100%`;
- evidence attribution precision: `85.71%`;
- no-fabrication: `92.86%`;
- sample size: `5`.

This is a conversion smoke test with a very small sample, not a benchmark result
or robust performance estimate.

## Safety Finding

The portable smoke test returned valid structured JSON and respected the
confidence cap, but incorrectly identified NVDA as Applied Materials under
sparse evidence. This failure is disclosed in the model card. The model must not
be treated as a market-data source.

## Status

- Portable Transformers model: published
- Hub repository: `Italianhype/Blum-Finance-4B`
- Immutable revision: `ad6f5cec7f729370d2976d8c78983521cb37ca83`
- Release tag: `benchmark-submission-v1`
- AutoModel/AutoTokenizer load: passed
- `trust_remote_code`: not required
- Conversion tests: passed
- Remote artifact parity: passed (`10` shards, `8,044,981,536` weight bytes)
- Open LLM Leaderboard: submission attempted; external Qwen3 validator rejected
- FinOS Open Financial LLM Leaderboard: submission attempted; same validator rejection
- MMLU finance/business community evaluation: completed (`700` samples)
- MMLU finance/business accuracy: `74.86%` (CI95 `71.51–77.93%`)
- Community evaluation Hub revision: `c2138bd9288d9891da3b0f6b6e00b50784554d13`
- Community evaluation tag: `community-eval-mmlu-finance-v1.1`
- Vals AI submission package: prepared; independent evaluation required
- Scale PRBench Finance submission package: prepared; independent evaluation required
- Official public leaderboard scores: unavailable
- Trading alpha claim: not supported
