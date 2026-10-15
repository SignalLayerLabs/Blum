# BLUM Hugging Face Champion–Challenger Operations

> Gated operator reference. The maintained deployment keeps paid training, automatic launch and automatic dataset publication disabled. Existing reasoning archives are quarantined for new training/promotion. The steps below describe the optional tooling, not current source eligibility or authorization to launch jobs. Start with [data acceptance](../research/data-quality.md) and [deployment](deployment.md).

BLUM uses the Space as a controlled orchestrator. The Space prepares validated dataset snapshots and records state; GPU fine-tuning, evaluation, promotion, and rollback run in separate Hugging Face Jobs.

## Safety model

- Requests to the Space never update model weights.
- Only export-ready examples with acceptable quality, valid provenance, and matured outcomes enter a snapshot.
- Thesis lineages are deduplicated and assigned to one deterministic split.
- The training job writes only to `Italianhype/Blum-Finance-4B-Challenger`.
- The champion remains unchanged until a manual authenticated promotion.
- Every promotion creates a rollback tag on the previous champion.
- The MLX model is converted only from a promoted BF16 champion.

## Dependencies

Runtime dependencies come from the root [requirements.txt](../../requirements.txt); optional training dependencies are separated in [requirements-hf-training.txt](../../requirements-hf-training.txt) and the [model package](../../model_release/pyproject.toml). Do not edit the runtime dependency set merely to follow an older training guide.

GPU job scripts declare their own PEP 723 environment. Any future launch must verify its installed API versions, immutable source revisions, hardware cost and source eligibility before enabling paid execution. Leave `BLUM_HF_TRAINING_IMAGE` empty unless a deliberately selected custom image contains the required `uv` executable.

## Required Space secrets

Configure these as Hugging Face Space secrets, not normal variables:

```text
HF_TOKEN=<fine-grained write token with Jobs and repository access>
BLUM_HF_TRAINING_ADMIN_KEY=<long random administrative key>
```

The token needs access to:

- `Italianhype/Blum-Finance-Reasoning`;
- `Italianhype/Blum-Finance-4B-Challenger`;
- `Italianhype/Blum-Finance-4B` for explicit promotion and rollback;
- Hugging Face Jobs under the `Italianhype` account.

The Space stores only remote Job identifiers and repository revisions. It never persists `HF_TOKEN`.

## Recommended first deployment

Deploy the code with external work disabled:

```text
BLUM_HF_TRAINING_ENABLED=false
BLUM_HF_TRAINING_AUTO_LAUNCH=false
BLUM_HF_TRAINING_SCHEDULER_ENABLED=false
```

Confirm the Space starts and the Alembic revision is `0025_tg_runtime_snap`, not the overlong `0025_trading_game_runtime_snapshots`.

Inspect readiness:

```bash
curl https://<space-host>/api/analyst/hf-training/status
```

Generate a local dry-run manifest without writing to the Hub:

```bash
curl -X POST 'https://<space-host>/api/analyst/hf-training/snapshot?publish=false'
```

After reviewing counts and rejection reasons, enable controlled external operations:

```text
BLUM_HF_TRAINING_ENABLED=true
BLUM_HF_TRAINING_AUTO_LAUNCH=false
BLUM_HF_TRAINING_SCHEDULER_ENABLED=true
BLUM_HF_TRAINING_SUPERVISOR_MINUTES=360
```

The scheduler synchronizes active remote Jobs. With `AUTO_LAUNCH=false`, it does not start a new paid GPU Job by itself.

## Manual cycle

Publish the immutable snapshot:

```bash
curl -X POST 'https://<space-host>/api/analyst/hf-training/snapshot?publish=true'
```

Launch the challenger:

```bash
curl -X POST 'https://<space-host>/api/analyst/hf-training/launch'
```

Synchronize training and evaluation state:

```bash
curl -X POST 'https://<space-host>/api/analyst/hf-training/sync'
```

When a job becomes `eligible`, promote it explicitly:

```bash
curl -X POST \
  -H 'X-BLUM-Admin-Key: <admin-key>' \
  'https://<space-host>/api/analyst/hf-training/promote/<job-id>'
```

Rollback to the saved champion tag:

```bash
curl -X POST \
  -H 'X-BLUM-Admin-Key: <admin-key>' \
  'https://<space-host>/api/analyst/hf-training/rollback/<job-id>?backup_tag=champion-backup-...'
```

## Initial gates

Defaults:

```text
BLUM_HF_TRAINING_MINIMUM_EXAMPLES=250
BLUM_HF_TRAINING_MINIMUM_MATURED_RATIO=0.80
BLUM_HF_TRAINING_MINIMUM_DAYS_BETWEEN_RUNS=30
BLUM_HF_TRAINING_MINIMUM_QUALITY=70
BLUM_HF_EVAL_MAX_EXAMPLES=53
BLUM_HF_TRAINING_HARDWARE=a10g-large
BLUM_HF_TRAINING_TIMEOUT=8h
```

A candidate cannot be promoted when it regresses aggregate contract score or no-fabrication performance, falls below structured-validity or directional-accounting gates, contains temporal leakage, or introduces a critical regression.

## Automatic launch

Enable only after several manually reviewed successful cycles:

```text
BLUM_HF_TRAINING_AUTO_LAUNCH=true
```

This enables automatic challenger launch after all readiness gates pass. It still does not enable automatic production promotion.

## Model lineage

The authoritative release order is:

```text
Italianhype/Blum-Finance-4B-Challenger@candidate-...
  → manual promotion
Italianhype/Blum-Finance-4B@main
  → verified MLX conversion
Italianhype/Blum
```

Record the BF16 champion commit in the MLX model card and conversion manifest so the two public model repositories cannot silently diverge.
