# BLUM Hugging Face Champion–Challenger Implementation Plan

> **For Codex:** Execute this plan task-by-task with test-driven development and verification before completion.

**Goal:** Connect BLUM's validated Space memory to Hugging Face Jobs for controlled challenger training, evaluation, manual promotion, and rollback.

**Architecture:** The Space builds immutable, lineage-safe dataset snapshots and launches isolated GPU Jobs. Challengers are evaluated against the current champion; production promotion is manual and reversible.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, Pydantic Settings, Alembic, `huggingface_hub`, TRL, PEFT, Transformers, Hugging Face Jobs.

---

## Task 1: Lock the Alembic revision invariant

**Files:**
- Verify: `backend/alembic/versions/0025_tg_runtime_snap.py`
- Verify: `backend/alembic/versions/0026_alpha_operating_system.py`
- Create: `backend/tests/test_alembic_revision_ids.py`

1. Write a test that imports every migration and asserts `len(revision) <= 32`.
2. Run the test and confirm the long live identifier would fail.
3. Verify the canonical `0025_tg_runtime_snap` and downstream reference pass.

## Task 2: Add configuration and pure training policy

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/analyst/hf_training.py`
- Create: `backend/tests/test_hf_training_policy.py`

1. Write failing tests for readiness thresholds, cooldown, active-job exclusion, token absence, and feature kill switch.
2. Add typed settings for repositories, hardware, thresholds, timeout, admin key, and feature flags.
3. Implement pure policy evaluation and make tests pass.

## Task 3: Build immutable dataset snapshots

**Files:**
- Modify: `backend/app/analyst/hf_training.py`
- Create: `backend/tests/test_hf_dataset_snapshot.py`

1. Write failing tests for contamination rejection, matured outcomes, deterministic lineage split, no cross-split lineage, and stable hashes.
2. Implement row normalization, grouped split, JSONL generation, and manifest generation.
3. Add a Hub publisher behind an injected client.
4. Verify repeat runs with identical rows produce the same content hash and do not relaunch training.

## Task 4: Add HF Jobs launcher and status sync

**Files:**
- Create: `backend/app/analyst/hf_job_scripts.py`
- Modify: `backend/app/analyst/hf_training.py`
- Create: `backend/tests/test_hf_job_launcher.py`

1. Write fake-client tests for encrypted secret passing, pinned revisions, unique candidate branches, persisted remote IDs, and launch failures.
2. Generate the UV training and evaluation scripts with pinned repositories/revisions.
3. Implement launch and status synchronization using `huggingface_hub.run_uv_job` and `inspect_job`.
4. Store remote metadata in existing `training_config` and `metrics` JSON fields.

## Task 5: Add manual promotion and rollback gates

**Files:**
- Modify: `backend/app/analyst/hf_training.py`
- Create: `backend/tests/test_hf_model_promotion.py`

1. Write failing tests for ineligible candidates, missing admin key, champion backup tag, promotion, and rollback.
2. Implement hard evaluation gates and manual operations through an injected Hub client.
3. Ensure no automatic path can write to the champion repository.

## Task 6: Expose API and scheduler integration

**Files:**
- Modify: `backend/app/api/routers/analyst.py`
- Modify: `backend/app/services/realtime.py`
- Modify: `backend/app/analyst/dataset_pipeline.py`
- Create: `backend/tests/test_hf_training_api.py`

1. Add status, snapshot, launch, sync, promotion, and rollback endpoints.
2. Add a low-frequency supervisor scheduler guarded by the feature flag.
3. Update Analyst status and training manifest to expose real pipeline state.
4. Test that page reads never trigger training and disabled mode is read-only.

## Task 7: Add operational scripts and documentation

**Files:**
- Create: `scripts/train_blum_challenger.py`
- Create: `scripts/evaluate_blum_challenger.py`
- Create: `HF_TRAINING.md`
- Modify: `README.md` if present

1. Add standalone, versioned scripts matching the inline Job payloads.
2. Document required Space secrets and variables.
3. Document first-run, manual review, promotion, rollback, and MLX conversion sequence.

## Task 8: Verify and package

1. Run targeted tests.
2. Run backend test suite where available.
3. Compile all modified Python modules.
4. Inspect `git diff --check` and secrets scan.
5. Produce a patch, implementation archive, and verification report.
