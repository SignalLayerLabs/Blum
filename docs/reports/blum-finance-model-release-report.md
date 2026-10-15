# BLUM Finance 4B Release Report

> Historical record. This document describes an earlier implementation or audit; its counts, configuration and readiness claims are not the current release status. Start with the [documentation index](../README.md) and [current data policy](../research/data-quality.md).

## Release Policy

BLUM Finance 4B is a financial reasoning model, not an execution engine and not
evidence of trading alpha. Promotion requires an immutable candidate to improve
over the exact base revision on the untouched temporal test split and pass
structured-output, evidence attribution, no-fabrication, risk, invalidation and
runtime smoke-test gates.

Community use never changes active weights directly. Contributions are disabled
by default, require explicit consent, enter quarantine and may only reach a later
challenger through a versioned training and evaluation cycle.

## Source Dataset

- BLUM Engine source revision: `973fa4a3579c8b883372e96ed6e7a6e1c99e534a`
- Dataset repository: `Italianhype/Blum-Finance-Reasoning`
- Dataset revision: `76ad77699d498fc930daf02e452fe3ec8b490f90`
- Records: `521`
- Train / validation / test: `416 / 52 / 53`
- Dataset content SHA-256:
  `4cd60a2a44eabc185f6eceba5e2619aeb11ec437b89fe3cacc5cff240e52deaf`
- Cross-split lineage leakage: `0`
- Redaction and schema audit: `passed`

The training derivative preserves point-in-time inputs and temporal split
membership. A deterministic evidence-bound sanitizer replaces numbers in target
answers that are absent from the corresponding input and caps unvalidated
confidence at 70. It made 3,095 target-only numeric/confidence replacements.
This improves grounding but is not a substitute for labeled market outcomes.

## Training

- Runtime: MLX on Apple Silicon
- Base model: `mlx-community/Qwen3-4B-4bit`
- Base revision: `4dcb3d101c2a062e5c1d4bb173588c54ea6c4d25`
- Method: QLoRA adapter training
- Adapter rank: `8`
- Adapted layers: `16`
- Learning rate: `1e-4`
- Batch size: `1`
- Maximum sequence length: `1024`
- Seed: `20260728`
- Assistant-only prompt masking: enabled
- Completed iterations: `20`
- Final validation loss: `0.020`
- Adapter revision:
  `ea297ba88ab008e97104b0c118103eef2f8f9ec1`

The adapter was fused into a standalone MLX repository. The release includes
the adapter separately for auditability and future governed continuation runs.

## Held-Out Evaluation

The untouched temporal test split contains 53 examples.

| Metric | Exact base | BLUM Finance 4B |
| --- | ---: | ---: |
| Aggregate task-contract score | 0.000000 | 0.962601 |
| Structured validity | 0.000000 | 1.000000 |
| Evidence attribution precision | 0.000000 | 0.857143 |
| Contradiction coverage | 0.000000 | 0.915094 |
| Invalidation completeness | 0.000000 | 1.000000 |
| Risk completeness | 0.000000 | 1.000000 |
| Numerical consistency | 0.000000 | 1.000000 |
| No-fabrication | 0.000000 | 0.928571 |
| Abstention accuracy | 0.000000 | 1.000000 |

The base score is zero because its readable prose did not satisfy the required
BLUM JSON decision contract. This comparison measures task-contract adherence,
not general intelligence.

The candidate aggregate 95% bootstrap lower bound is `0.955525`. Outcome
calibration is **not measured** because the test set has zero labeled mature
market outcomes. The displayed calibration error of zero therefore must not be
interpreted as calibrated confidence.

## Release Artifact

- Model repository: `Italianhype/Blum`
- Format: standalone fused MLX 4-bit model
- Model tensor SHA-256:
  `52270d4195b046ec5cfbacdf6c6435cd5f3f154a9cf20b4646dab45f87a196d1`
- Release files: `26`
- Release size: approximately `2.3 GB`
- Local release manifest: validated against 23 artifact hashes
- Deterministic fused-model smoke test: passed
- Remote revision: `bc6dcefc5b8674f443136986a5c0705d391df493`
- Remote model size: `2,263,022,417` bytes
- Remote model SHA-256: matched the local release manifest

The current artifact requires Apple Silicon and `mlx-lm`. A Transformers or
GGUF release has not been produced and is not implied by this release.

## Incremental Community Learning

The package exposes an opt-in contribution command. Accepted examples are
written to `Italianhype/Blum-Finance-Memory` only after schema, consent,
provenance and redaction checks. Inference requests are never treated as
training consent.

The safe lifecycle is:

1. collect explicitly contributed examples in quarantine;
2. validate provenance, evidence boundaries and outcome maturity;
3. build a new immutable training snapshot;
4. train a challenger adapter outside the inference request path;
5. compare it with the active model on untouched tests;
6. publish and promote a new version only if every gate passes.

This is incremental learning by governed versions. It is deliberately not
uncontrolled online weight mutation.

## Verification

- Full Python suite: `630 passed`
- BLUM Finance focused suite: `33 passed`
- Next.js production build: `61/61 pages generated`
- Legacy model-repository content archived as:
  `legacy-app-2026-07-08`
- Space deployment revision: updated after commit

## Known Limits

- No claim of market outperformance, profitable execution or copy-trading
  readiness is supported by this language-model release.
- Confidence is structurally bounded but not empirically calibrated against
  mature outcomes.
- The current test set is small and focused on the BLUM decision schema.
- Community examples do not become training data automatically.
- MLX limits this first model artifact to Apple Silicon environments.
