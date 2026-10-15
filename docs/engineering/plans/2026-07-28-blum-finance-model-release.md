# BLUM Finance 4B Model Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, evaluate and publish a real downloadable BLUM Finance 4B model from BLUM's curated reasoning evidence, with reproducible artifacts and an opt-in community contribution path.

**Architecture:** BLUM Engine exports a redacted, grouped and temporal reasoning dataset. A standalone `model_release` toolchain trains a Qwen3-4B LoRA, evaluates it against the immutable base revision, promotes only a passing candidate, packages Transformers/GGUF artifacts and publishes model-card evidence. Community data enters a separate quarantine repository and never updates active weights directly.

**Tech Stack:** Python 3.11+, SQLAlchemy, Pydantic 2, Hugging Face Transformers, Datasets, TRL, PEFT, Accelerate, Trackio, Inspect AI/LightEval, llama.cpp, Hugging Face Hub and Jobs.

## Global Constraints

- Primary model repository is exactly `Italianhype/Blum`.
- Base model is `Qwen/Qwen3-4B`.
- Model license target is Apache-2.0.
- BLUM Engine remains the source of truth.
- No user data upload occurs by default.
- No benchmark score is published unless it was executed and preserved with traces.
- No trading-alpha claim may be inferred from a language-model benchmark.
- Failed model candidates must not replace the primary model.
- The application Space remains separately deployable and operational.
- Do not stage or modify `blum_market_desk_agents_audit.zip`.

---

## File Structure

### Engine export boundary

- `backend/app/analyst/release_contracts.py`: immutable release schemas and validation.
- `backend/app/analyst/release_redaction.py`: secret, PII and unsafe-source filtering.
- `backend/app/analyst/release_dataset.py`: quality selection, deduplication, grouped temporal splitting and manifest creation.
- `backend/app/api/routers/analyst.py`: explicit POST release export and artifact download routes.
- `scripts/export_blum_model_release.py`: database-side CLI for reproducible export.
- `scripts/audit_blum_release_dataset.py`: offline integrity, leakage and redaction audit.

### Standalone model toolchain

- `model_release/pyproject.toml`: package and optional dependency groups.
- `model_release/blum_finance/schemas.py`: inference and contribution schemas.
- `model_release/blum_finance/inference.py`: Transformers inference facade.
- `model_release/blum_finance/contributions.py`: local opt-in contribution bundles.
- `model_release/training/train_sft.py`: LoRA SFT entry point.
- `model_release/training/config.yaml`: immutable initial training defaults.
- `model_release/evaluation/evaluate_candidate.py`: base/candidate evaluation.
- `model_release/evaluation/metrics.py`: deterministic metrics and bootstrap intervals.
- `model_release/evaluation/tasks/blum_finance_eval.py`: held-out domain task.
- `model_release/release/build_repository.py`: model repository assembly and gate.
- `model_release/release/convert_gguf.sh`: pinned GGUF conversion.
- `model_release/release/publish.py`: guarded Hub upload.
- `model_release/model_card/README.md.j2`: truthful, discoverable model card.
- `model_release/model_card/LICENSE`: model artifact license.
- `model_release/dataset_card/README.md.j2`: dataset provenance, schema and split card.
- `model_release/contribution_repo/README.md`: quarantine protocol and contribution terms.

### Tests and documentation

- `backend/tests/test_blum_model_release_dataset.py`
- `backend/tests/test_blum_model_release_api.py`
- `model_release/tests/test_schemas.py`
- `model_release/tests/test_contributions.py`
- `model_release/tests/test_metrics.py`
- `model_release/tests/test_release_gate.py`
- `README.md`
- `BLUM_FINANCE_MODEL_RELEASE_REPORT.md`

---

### Task 1: Define Immutable Release Contracts

**Files:**
- Create: `backend/app/analyst/release_contracts.py`
- Test: `backend/tests/test_blum_model_release_dataset.py`

**Interfaces:**
- Produces: `ReleaseExample`, `ReleaseManifest`, `DatasetSplit`, `validate_release_example(payload: dict) -> ReleaseExample`.
- Consumes: Pydantic 2 only.

- [ ] **Step 1: Write failing schema tests**

```python
def test_release_example_requires_provenance_and_evidence():
    with pytest.raises(ValidationError):
        ReleaseExample.model_validate({"schema_version": "blum-finance-v1"})


def test_release_manifest_records_immutable_source_revision():
    manifest = ReleaseManifest.model_validate(valid_manifest())
    assert len(manifest.source_revision) == 40
    assert manifest.base_model == "Qwen/Qwen3-4B"
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python3 -m pytest backend/tests/test_blum_model_release_dataset.py -q`  
Expected: FAIL because `release_contracts` does not exist.

- [ ] **Step 3: Implement strict contracts**

Implement:

```python
class DatasetSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class ReleaseExample(BaseModel):
    schema_version: Literal["blum-finance-reasoning-v1"]
    example_id: str
    source_record_id: int
    source_revision: str
    created_at: datetime
    ticker: str
    thesis_lineage_id: str
    split: DatasetSplit
    task_type: str
    messages: list[Message]
    evidence: EvidenceBundle
    outcome: OutcomeBundle
    quality: QualityBundle
    content_hash: str


class ReleaseManifest(BaseModel):
    schema_version: Literal["blum-finance-manifest-v1"]
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    base_model: Literal["Qwen/Qwen3-4B"]
    generated_at: datetime
    split_counts: dict[DatasetSplit, int]
    split_date_ranges: dict[DatasetSplit, DateRange]
    exclusion_counts: dict[str, int]
    dataset_sha256: str
```

- [ ] **Step 4: Run schema tests**

Run: `python3 -m pytest backend/tests/test_blum_model_release_dataset.py -q`  
Expected: PASS for contract tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analyst/release_contracts.py backend/tests/test_blum_model_release_dataset.py
git commit -m "feat: define BLUM Finance release contracts"
```

---

### Task 2: Build Redaction, Deduplication and Temporal Splitting

**Files:**
- Create: `backend/app/analyst/release_redaction.py`
- Create: `backend/app/analyst/release_dataset.py`
- Modify: `backend/tests/test_blum_model_release_dataset.py`

**Interfaces:**
- Consumes: `ReleaseExample`, SQLAlchemy `Session`, `BlumTrainingExample`, `TrainingExampleQualityScore`.
- Produces: `sanitize_payload(payload: dict) -> RedactionResult`, `build_release_dataset(db: Session, *, source_revision: str, output_dir: Path, min_score: float = 70.0) -> ReleaseManifest`.

- [ ] **Step 1: Add failing redaction and split tests**

```python
def test_redaction_removes_tokens_email_and_broker_identifiers():
    result = sanitize_payload({
        "text": "mail me at trader@example.com",
        "api_key": "hf_secret",
        "broker_account_id": "ABC-123",
    })
    assert "trader@example.com" not in json.dumps(result.payload)
    assert "hf_secret" not in json.dumps(result.payload)
    assert result.blocked_fields == ["api_key", "broker_account_id"]


def test_thesis_lineage_never_crosses_dataset_splits(db):
    manifest = build_release_dataset(db, source_revision=REVISION, output_dir=tmp_path)
    rows = read_all_release_rows(tmp_path)
    lineage_splits = group_splits(rows, key="thesis_lineage_id")
    assert all(len(splits) == 1 for splits in lineage_splits.values())
```

- [ ] **Step 2: Verify tests fail**

Run: `python3 -m pytest backend/tests/test_blum_model_release_dataset.py -q`  
Expected: FAIL for missing redaction and builder.

- [ ] **Step 3: Implement redaction**

Use deny-listed keys, email/token/account regexes, normalized whitespace and a
redistribution policy:

```python
BLOCKED_KEYS = {
    "api_key", "authorization", "broker_account_id", "account_id",
    "access_token", "refresh_token", "raw_article", "full_report",
}

def sanitize_payload(payload: dict) -> RedactionResult:
    cleaned = walk_and_redact(payload)
    return RedactionResult(
        payload=cleaned,
        blocked_fields=sorted(find_blocked_fields(payload)),
        pii_matches=sorted(find_pii(payload)),
        publishable=not contains_unlicensed_verbatim_source(cleaned),
    )
```

- [ ] **Step 4: Implement dataset selection and split**

Query only scored examples with `final_training_value_score >= min_score`, order by
source creation time, deduplicate by canonical content hash, group by thesis lineage,
then allocate chronological groups 80/10/10 without splitting a group. Write:

- `train.jsonl`
- `validation.jsonl`
- `test.jsonl`
- `manifest.json`
- `excluded.jsonl`

- [ ] **Step 5: Run focused tests**

Run: `python3 -m pytest backend/tests/test_blum_model_release_dataset.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/analyst/release_redaction.py backend/app/analyst/release_dataset.py backend/tests/test_blum_model_release_dataset.py
git commit -m "feat: build leakage-safe BLUM Finance dataset"
```

---

### Task 3: Add Explicit Release Export Boundary

**Files:**
- Modify: `backend/app/analyst/dataset_pipeline.py`
- Modify: `backend/app/api/routers/analyst.py`
- Create: `scripts/export_blum_model_release.py`
- Create: `backend/tests/test_blum_model_release_api.py`

**Interfaces:**
- Consumes: `build_release_dataset`.
- Produces: `BlumAnalystDatasetPipeline.export_release(...) -> dict`, `POST /api/analyst/release-export`, `GET /api/analyst/release-exports/{export_id}/manifest`, `GET /api/analyst/release-exports/{export_id}/artifact`.

- [ ] **Step 1: Write failing API tests**

```python
def test_release_export_is_post_only(client):
    assert client.get("/api/analyst/release-export").status_code == 405


def test_manifest_get_does_not_generate_or_write(client, db_write_spy):
    response = client.get("/api/analyst/release-exports/1/manifest")
    assert response.status_code in {200, 404}
    assert db_write_spy.count == 0


def test_artifact_download_rejects_internal_export(client, seeded_internal_export):
    response = client.get(
        f"/api/analyst/release-exports/{seeded_internal_export.id}/artifact"
    )
    assert response.status_code == 403
```

- [ ] **Step 2: Verify failure**

Run: `python3 -m pytest backend/tests/test_blum_model_release_api.py -q`  
Expected: FAIL because routes do not exist.

- [ ] **Step 3: Implement export and manifest endpoints**

The POST creates a sanitized tar archive and persists a `BlumDatasetExport` with
hashes and `release_safe=true`. The GET routes read only the persisted manifest or
archive. They must not rebuild data, and the artifact route rejects exports without
the release-safe marker.

- [ ] **Step 4: Add CLI**

The CLI accepts:

```text
--output-dir
--min-score
--source-revision
--limit
```

It exits non-zero when no publishable rows exist or any split is empty.

Add `scripts/audit_blum_release_dataset.py`. It validates every JSONL row against the
release schema, recomputes hashes, scans for blocked fields/PII, verifies temporal
ordering and proves that no thesis lineage appears in more than one split.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest backend/tests/test_blum_model_release_api.py backend/tests/test_blum_model_release_dataset.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/analyst/dataset_pipeline.py backend/app/api/routers/analyst.py scripts/export_blum_model_release.py scripts/audit_blum_release_dataset.py backend/tests/test_blum_model_release_api.py
git commit -m "feat: expose guarded BLUM Finance release export"
```

---

### Task 4: Implement Standalone Inference and Opt-In Contributions

**Files:**
- Create: `model_release/pyproject.toml`
- Create: `model_release/blum_finance/__init__.py`
- Create: `model_release/blum_finance/schemas.py`
- Create: `model_release/blum_finance/inference.py`
- Create: `model_release/blum_finance/contributions.py`
- Create: `model_release/tests/test_schemas.py`
- Create: `model_release/tests/test_contributions.py`

**Interfaces:**
- Produces: `FinancialReasoningRequest`, `FinancialReasoningResponse`, `BlumFinancePipeline`, `build_contribution_bundle`, CLI `blum-contribute`.
- Consumes: local model path or Hub model ID, no BLUM database.

- [ ] **Step 1: Write failing tests**

```python
def test_contribution_is_disabled_until_explicit_confirmation(tmp_path):
    with pytest.raises(ConsentRequired):
        build_contribution_bundle(example(), output=tmp_path / "bundle.json")


def test_bundle_never_contains_secrets(tmp_path):
    bundle = build_contribution_bundle(
        example(api_key="secret"),
        output=tmp_path / "bundle.json",
        consent=True,
    )
    assert "secret" not in bundle.path.read_text()
```

- [ ] **Step 2: Verify tests fail**

Run: `python3 -m pytest model_release/tests/test_schemas.py model_release/tests/test_contributions.py -q`  
Expected: FAIL because package does not exist.

- [ ] **Step 3: Implement schemas and inference facade**

`BlumFinancePipeline.generate()` must:

- render the model chat template;
- request JSON output;
- validate with `FinancialReasoningResponse`;
- return an explicit `insufficient_evidence` status on invalid or unsupported facts;
- never fetch market data.

- [ ] **Step 4: Implement contribution bundles**

Bundles are written locally only. Upload requires a separate `--push` flag and a
logged-in Hub token. Print the exact target and record count before confirmation.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest model_release/tests -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add model_release/pyproject.toml model_release/blum_finance model_release/tests
git commit -m "feat: add standalone BLUM Finance client"
```

---

### Task 5: Implement Reproducible LoRA Training

**Files:**
- Create: `model_release/training/train_sft.py`
- Create: `model_release/training/config.yaml`
- Create: `model_release/training/requirements.txt`
- Create: `model_release/tests/test_training_config.py`

**Interfaces:**
- Consumes: dataset directory containing `manifest.json`, `train.jsonl`, `validation.jsonl`.
- Produces: LoRA adapter, trainer state, Trackio run, `training_manifest.json`.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_training_config_pins_base_and_assistant_only_loss():
    config = load_training_config(CONFIG_PATH)
    assert config.base_model == "Qwen/Qwen3-4B"
    assert config.assistant_only_loss is True
    assert config.seed == 20260728


def test_training_refuses_mismatched_dataset_hash(tmp_path):
    with pytest.raises(DatasetIntegrityError):
        verify_dataset_manifest(tmp_path, expected_sha256="wrong")
```

- [ ] **Step 2: Verify tests fail**

Run: `python3 -m pytest model_release/tests/test_training_config.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement training entry point**

Use `SFTTrainer` and `LoraConfig` with:

```yaml
base_model: Qwen/Qwen3-4B
seed: 20260728
learning_rate: 0.0001
num_train_epochs: 3
max_length: 4096
packing: true
assistant_only_loss: true
lora_r: 32
lora_alpha: 64
lora_dropout: 0.05
target_modules: [q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj]
metric_for_best_model: eval_loss
load_best_model_at_end: true
```

The script verifies dataset hashes before allocating the model and pushes no artifact
unless `--push-adapter` is explicitly supplied.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest model_release/tests/test_training_config.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add model_release/training model_release/tests/test_training_config.py
git commit -m "feat: add reproducible BLUM Finance LoRA training"
```

---

### Task 6: Build Candidate Evaluation and Promotion Gate

**Files:**
- Create: `model_release/evaluation/metrics.py`
- Create: `model_release/evaluation/evaluate_candidate.py`
- Create: `model_release/evaluation/tasks/blum_finance_eval.py`
- Create: `model_release/release/build_repository.py`
- Create: `model_release/tests/test_metrics.py`
- Create: `model_release/tests/test_release_gate.py`

**Interfaces:**
- Consumes: immutable base revision, candidate adapter, held-out test data.
- Produces: `evaluation_summary.json`, trace JSONL, `.eval_results/*.yaml`, `PromotionDecision`.

- [ ] **Step 1: Write failing metric and gate tests**

```python
def test_bootstrap_interval_is_deterministic():
    first = bootstrap_ci([1, 0, 1, 1], seed=7)
    second = bootstrap_ci([1, 0, 1, 1], seed=7)
    assert first == second


def test_candidate_with_hallucination_regression_is_rejected():
    decision = promotion_gate(
        base=metrics(no_fabrication=0.93, aggregate=0.61),
        candidate=metrics(no_fabrication=0.84, aggregate=0.70),
    )
    assert decision.promoted is False
    assert "no_fabrication_regression" in decision.reasons
```

- [ ] **Step 2: Verify failure**

Run: `python3 -m pytest model_release/tests/test_metrics.py model_release/tests/test_release_gate.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement evaluation metrics**

Measure:

- structured output validity;
- evidence attribution precision;
- contradiction coverage;
- invalidation completeness;
- abstention correctness;
- numerical consistency;
- confidence calibration error;
- financial QA exact match where licensed;
- sentiment macro-F1 where licensed.

- [ ] **Step 4: Implement promotion gate**

Promotion requires:

- target aggregate improvement greater than zero;
- lower confidence bound not materially below base;
- no-fabrication regression no worse than 2 percentage points;
- structured validity at least 95%;
- risk/invalidation completeness no worse than base;
- all required traces and revisions present.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest model_release/tests/test_metrics.py model_release/tests/test_release_gate.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add model_release/evaluation model_release/release/build_repository.py model_release/tests/test_metrics.py model_release/tests/test_release_gate.py
git commit -m "feat: gate BLUM Finance promotion on evidence"
```

---

### Task 7: Add Model Card, GGUF and Guarded Publication

**Files:**
- Create: `model_release/model_card/README.md.j2`
- Create: `model_release/model_card/LICENSE`
- Create: `model_release/dataset_card/README.md.j2`
- Create: `model_release/contribution_repo/README.md`
- Create: `model_release/release/convert_gguf.sh`
- Create: `model_release/release/publish.py`
- Create: `model_release/tests/test_model_card.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: promoted merged model, evaluation summary and trace URLs.
- Produces: staged primary model repository, adapter repository and GGUF repository.

- [ ] **Step 1: Write failing card and publication tests**

```python
def test_model_card_requires_real_evaluation_values():
    with pytest.raises(MissingEvaluationEvidence):
        render_model_card(manifest(validated=False))


def test_publish_refuses_unpromoted_candidate():
    with pytest.raises(CandidateNotPromoted):
        publish_release(candidate_manifest(promoted=False))
```

- [ ] **Step 2: Verify tests fail**

Run: `python3 -m pytest model_release/tests/test_model_card.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement model card**

Include title, base model, dataset lineage, quick start, structured example, measured
base/candidate comparison, failure cases, contribution protocol, limitations,
financial disclaimer, Space link and citation. The dataset card documents source
revisions, exclusions, split methodology and redistribution limits. The contribution
repository card marks every upload as quarantined and non-training by default.

- [ ] **Step 4: Implement conversion and upload guards**

`convert_gguf.sh` pins the llama.cpp commit in the release manifest. `publish.py`
requires:

- `promotion.promoted == true`;
- all artifact hashes;
- successful Transformers smoke test;
- successful GGUF smoke test;
- authenticated Hub user `Italianhype`;
- explicit `--confirm-repository Italianhype/Blum`.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest model_release/tests/test_model_card.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add model_release/model_card model_release/dataset_card model_release/contribution_repo model_release/release .gitignore model_release/tests/test_model_card.py
git commit -m "feat: package guarded BLUM Finance release"
```

---

### Task 8: Export and Publish the Versioned Dataset

**Files:**
- Generated outside Git: `.artifacts/blum-finance-dataset/*`
- Modify: `BLUM_FINANCE_MODEL_RELEASE_REPORT.md`

**Interfaces:**
- Consumes: deployed BLUM Engine release exporter and Hub authentication.
- Produces: immutable dataset revision in `Italianhype/Blum-Finance-Reasoning`.

- [ ] **Step 1: Deploy the export code to the Space**

Push the application commits to `spaces/Italianhype/Blum`, wait for `RUNNING`, then
verify `/api/analyst/status`.

- [ ] **Step 2: Generate the production release export**

Run the explicit POST/CLI path with minimum score 70 and source commit hash. Download
the resulting redacted artifact and verify its SHA-256 against `manifest.json`.

- [ ] **Step 3: Audit dataset**

Run:

```bash
python3 -m pytest backend/tests/test_blum_model_release_dataset.py -q
python3 scripts/audit_blum_release_dataset.py .artifacts/blum-finance-dataset
```

Expected: no secrets, no cross-split lineage, no empty split and no invalid schema.

- [ ] **Step 4: Publish dataset**

Create or update `Italianhype/Blum-Finance-Reasoning`, upload immutable JSONL and
manifest plus its dataset card, record the returned commit in the release report.

- [ ] **Step 5: Commit report checkpoint**

```bash
git add BLUM_FINANCE_MODEL_RELEASE_REPORT.md
git commit -m "docs: record BLUM Finance dataset release"
```

---

### Task 9: Train, Evaluate and Promote on Hugging Face Jobs

**Files:**
- Modify: `BLUM_FINANCE_MODEL_RELEASE_REPORT.md`
- Generated outside Git: `.artifacts/blum-finance-eval/*`

**Interfaces:**
- Consumes: immutable dataset revision and Task 5/6 scripts.
- Produces: adapter revision, evaluation evidence and promotion decision.

- [ ] **Step 1: Launch LoRA training job**

Use a Hugging Face GPU Job with `HF_TOKEN` secret, Trackio enabled, immutable dataset
revision and output repository `Italianhype/Blum-Finance-4B-LoRA`.

- [ ] **Step 2: Monitor training**

Wait for terminal completion. Persist job ID, hardware, duration, final eval loss,
adapter revision and Trackio URL. A failed job is diagnosed and fixed before retry;
metrics are never inferred.

- [ ] **Step 3: Run base and candidate evaluations**

Evaluate the exact base revision and candidate adapter with identical decoding and
test revision. Save traces and confidence intervals.

- [ ] **Step 4: Apply promotion gate**

If rejected, stop publication and document reasons. If promoted, merge the adapter,
run Transformers smoke inference and continue.

- [ ] **Step 5: Commit evidence checkpoint**

```bash
git add BLUM_FINANCE_MODEL_RELEASE_REPORT.md
git commit -m "docs: record BLUM Finance training evidence"
```

---

### Task 10: Publish Model, GGUF, Benchmarks and Documentation

**Files:**
- Modify: `README.md`
- Modify: `BLUM_FINANCE_MODEL_RELEASE_REPORT.md`

**Interfaces:**
- Consumes: promoted model and verified artifacts.
- Produces: public `Italianhype/Blum`, adapter, GGUF, benchmark results and collection.

- [ ] **Step 1: Publish merged Transformers model**

Run guarded publication and verify:

```python
AutoTokenizer.from_pretrained("Italianhype/Blum")
AutoModelForCausalLM.from_pretrained("Italianhype/Blum")
```

- [ ] **Step 2: Publish and verify GGUF**

Upload Q4_K_M, run a deterministic prompt through llama.cpp and compare required
structured fields against Transformers output.

- [ ] **Step 3: Publish evaluation results**

Upload `.eval_results/*.yaml` only for executed compatible benchmarks. Link traces and
mark author-provided results accurately.

- [ ] **Step 4: Create Hub collection**

Create a BLUM Finance collection linking model, adapter, GGUF, dataset, contribution
queue and Space.

- [ ] **Step 5: Create the contribution quarantine repository**

Create `Italianhype/Blum-Finance-Memory` as a dataset repository. Publish only the
schema, card and an empty validated data file. Confirm that installing or invoking
the model generates no network request. A contribution appears only after
`blum contribute --push` and remains quarantined.

- [ ] **Step 6: Update project documentation**

Document:

- model quick start;
- architecture boundary;
- dataset provenance;
- contribution consent;
- benchmark interpretation;
- known limitations;
- immutable Hub revisions.

- [ ] **Step 7: Run full verification**

Run:

```bash
python3 -m pytest -q
python3 -m pytest model_release/tests -q
npm --prefix frontend run build
```

Expected: all tests pass and frontend build succeeds.

- [ ] **Step 8: Commit final release**

```bash
git add README.md BLUM_FINANCE_MODEL_RELEASE_REPORT.md
git commit -m "docs: publish BLUM Finance model release"
```
