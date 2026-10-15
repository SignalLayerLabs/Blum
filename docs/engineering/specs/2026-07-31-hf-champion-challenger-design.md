# BLUM Hugging Face Champion–Challenger Design

**Date:** 2026-07-31
**Status:** Approved
**Owner:** Italianhype / BLUM

## Objective

Connect the BLUM Space learning memory to a controlled Hugging Face model-improvement pipeline without training inside the production Space and without allowing user requests or unverified model output to mutate model weights.

The authoritative model remains `Italianhype/Blum-Finance-4B`. Every proposed update is trained and evaluated as a challenger. Initial promotion is manual and reversible. `Italianhype/Blum` remains a verified MLX 4-bit conversion of a promoted BF16 champion, never an independently trained model.

## Non-goals

- Online or per-request self-training.
- Automatic production promotion in the first releases.
- Training from raw user conversations, unlicensed text, pending outcomes, contaminated records, or the fixed evaluation set.
- Running GPU fine-tuning inside the Docker Space.
- Treating trading return alone as proof of model quality.

## Architecture

```text
BLUM Space / PostgreSQL
  ├─ reasoning records
  ├─ matured thesis outcomes
  ├─ quality scores
  └─ provenance and contamination flags
            │
            ▼
Dataset Snapshot Builder
  ├─ quality and maturity gates
  ├─ lineage deduplication
  ├─ deterministic grouped temporal split
  ├─ SHA-256 manifest
  └─ immutable Hub revision
            │
            ▼
Italianhype/Blum-Finance-Reasoning
            │
            ▼
Hugging Face GPU Job
  ├─ Qwen3-4B / current champion
  ├─ PEFT LoRA SFT
  └─ merged challenger revision
            │
            ▼
Italianhype/Blum-Finance-4B-Challenger
            │
            ▼
Evaluation Job
  ├─ BLUM contract validity
  ├─ no-fabrication checks
  ├─ LONG/SHORT accounting regressions
  ├─ temporal leakage checks
  ├─ confidence calibration
  └─ champion comparison
            │
      eligible / rejected
            │
            ▼
Manual Promotion + Rollback Registry
            │
            ▼
Italianhype/Blum-Finance-4B
            │
            ▼
Verified MLX conversion → Italianhype/Blum
```

## Components

### Dataset snapshot builder

The builder queries only export-ready BLUM training examples and joins their knowledge records and matured outcomes. It rejects records when:

- no realized outcome exists;
- quality is below the configured threshold;
- a contamination, unverifiable-source, leakage, or quarantine flag is present;
- the messages or expected output are empty;
- the same thesis lineage is duplicated;
- a lineage would cross train, validation, and test.

The split is derived from a stable hash of the thesis lineage, not a row number. The snapshot contains `train.jsonl`, `validation.jsonl`, `test.jsonl`, and `manifest.json`. The manifest records code revision, parent model revision, quality policy, row counts, hashes, timestamps, and rejection reasons.

### Training supervisor

The Space supervisor evaluates readiness but remains disabled unless `BLUM_HF_TRAINING_ENABLED=true`. A training cycle is eligible only when all configured gates pass, initially:

- at least 250 approved examples;
- at least 80% of selected examples have matured outcomes;
- at least 30 days since the previous launched cycle;
- no active training/evaluation job;
- no critical quality-gate failure;
- a write-capable `HF_TOKEN` is available.

The supervisor creates a `BlumModelTrainingJob` row before launching external work. Remote identifiers, URLs, dataset revisions, candidate revisions, and evaluation metrics are stored in the existing JSON fields so the first release needs no new database schema.

### Hugging Face Jobs launcher

The launcher calls `huggingface_hub.run_uv_job` through an injected client. Secrets are passed as encrypted Job secrets, never logged or persisted in the database. The Space records only whether a token is configured.

The training job uses a pinned dataset revision and publishes to a unique challenger branch. It never writes directly to the champion repository.

### Evaluation and promotion

Evaluation results are written to the challenger revision and copied into the BLUM job record. A candidate can become `eligible` only when every hard gate passes. Promotion remains a separate authenticated, manual operation. Before promotion, the current champion commit is tagged for rollback. Promotion never deletes the prior champion.

### Runtime safety

- Scheduler concurrency is one supervisor instance.
- Job launch is idempotent by dataset hash.
- Network/API failures mark a job `launch_failed` or `degraded`; they do not affect Space inference.
- The production Space continues to use the current champion during all training and evaluation activity.
- A kill switch disables launch without disabling dataset collection.

## Alembic runtime fix

Alembic's default version table stores a 32-character revision identifier. The failed identifier `0025_trading_game_runtime_snapshots` exceeds that limit. The canonical revision is `0025_tg_runtime_snap`, and migration `0026_alpha_operating_system` must reference that short identifier. A test scans every migration revision and fails when an identifier exceeds 32 characters.

## API surface

- `GET /analyst/hf-training/status`
- `POST /analyst/hf-training/snapshot`
- `POST /analyst/hf-training/launch`
- `POST /analyst/hf-training/sync`
- `POST /analyst/hf-training/promote/{job_id}`
- `POST /analyst/hf-training/rollback/{job_id}`

Write endpoints are disabled when the feature flag is off. Promotion and rollback additionally require the configured admin key.

## Testing

- Pure policy tests for readiness and rejection reasons.
- Deterministic split and no-lineage-leakage tests.
- Manifest and hash reproducibility tests.
- Fake-client tests for job launch, sync, idempotency, and failure handling.
- Promotion-gate and rollback tests.
- Alembic revision-length regression test.
- Existing backend suite remains green.

## Rollout

1. Deploy the short Alembic revision and restore Space runtime.
2. Deploy pipeline code with training disabled.
3. Generate and inspect the first dataset snapshot.
4. Configure HF secrets and enable launch only.
5. Run one challenger cycle.
6. Review evaluation artifacts manually.
7. Promote only after explicit approval.
8. Convert the promoted BF16 model to MLX and verify parity.
