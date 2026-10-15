# BLUM Finance 4B Model Release Design

**Date:** 2026-07-28  
**Status:** Approved design  
**Primary model repository:** `Italianhype/Blum`  
**Application Space:** `Italianhype/Blum` under Hugging Face Spaces  
**Base model:** `Qwen/Qwen3-4B`  
**Model license target:** Apache-2.0  

## 1. Objective

Extract BLUM's financial reasoning capability into a real, downloadable Hugging Face
model named **BLUM Finance 4B - Financial Reasoning, Risk & Trading Intelligence**.

The release must:

- be usable independently from the BLUM web application;
- preserve BLUM Engine as the source of market truth;
- learn financial reasoning rather than memorizing price predictions;
- publish only measured and reproducible benchmark results;
- support explicit, privacy-preserving community contributions;
- remain honest about limitations and never imply guaranteed alpha;
- provide a simple Transformers path and a local GGUF path.

The release must not:

- upload the BLUM application as model weights;
- collect user prompts, decisions, account data or outcomes by default;
- accept community examples directly into active memory or model weights;
- claim that a download automatically improves a static model;
- claim official benchmark placement before a compatible evaluation is executed and
  published;
- make the model authoritative for prices, fills, returns or trading outcomes.

## 2. Current-State Findings

The current `Italianhype/Blum` model repository contains a dated application upload,
not a model. It has no model configuration, tokenizer, Safetensors weights, PEFT
adapter, GGUF artifact or structured evaluation result.

The running BLUM Engine currently reports:

- 4,435 knowledge records;
- 4,435 training examples;
- 4,435 export-ready examples;
- 3,813 training quality scores;
- 22,175 thesis outcomes;
- zero dataset exports;
- zero model training jobs.

This is sufficient for a controlled small LoRA experiment, but it is not proof that
the resulting model will outperform its base model.

The repository also lacks an explicit top-level software/model license. Licensing is
therefore a release blocker until the relevant artifacts are classified and licensed.

## 3. Product Identity

The existing model repository URL remains:

`https://huggingface.co/Italianhype/Blum`

Its public identity becomes:

- **Display name:** BLUM Finance 4B
- **Subtitle:** Financial Reasoning, Risk & Trading Intelligence
- **Pipeline:** text generation / conversational
- **Languages:** English and Italian
- **Primary uses:** financial thesis construction, contradictory evidence analysis,
  risk reasoning, invalidation logic, benchmark-aware interpretation, portfolio
  reasoning and confidence explanation
- **Non-use:** autonomous brokerage execution, guaranteed signals, unverified
  real-time prices or direct financial advice

The application remains separately deployed at:

`https://huggingface.co/spaces/Italianhype/Blum`

The model card links to the Space, while the Space identifies the model as a
reasoning assistant rather than the Engine's source of truth.

## 4. Release Architecture

### 4.1 Primary model repository

`Italianhype/Blum` contains the merged Transformers model:

- `config.json`;
- tokenizer files;
- generation configuration;
- sharded Safetensors weights and index;
- model card;
- model and artifact licenses;
- inference examples;
- reproducibility manifest;
- benchmark result files under `.eval_results/`;
- training and data lineage metadata;
- checksums and release manifest.

The dated application files are removed from the current model branch. Their Git
history is preserved.

### 4.2 Adapter artifact

The exact LoRA adapter is preserved as a versioned release artifact. If Hugging Face
loading behavior or repository size makes a subdirectory impractical, it is published
in a companion repository:

`Italianhype/Blum-Finance-4B-LoRA`

The primary model card links to the immutable adapter revision.

### 4.3 GGUF artifact

A quantized GGUF build is published for local CPU and Apple Silicon use. The preferred
initial quantization is Q4_K_M, with Q5_K_M added only if verification and storage
budgets permit.

If keeping GGUF files in the primary repository would make metadata or downloads
ambiguous, use:

`Italianhype/Blum-Finance-4B-GGUF`

Every GGUF artifact records the source model commit and conversion command.

### 4.4 Python package

A small `blum-finance` package provides:

- validated prompt and response schemas;
- local Transformers inference;
- optional GGUF invocation documentation;
- structured financial reasoning output;
- contribution bundle generation;
- local redaction and consent review;
- no telemetry by default.

The package does not contain market-data fetching or duplicate BLUM Engine logic.

## 5. Dataset Pipeline

### 5.1 Source boundary

The dataset originates only from persisted BLUM Engine evidence:

- point-in-time market context;
- asset and regime context;
- thesis and contradictory evidence;
- risk and invalidation reasoning;
- benchmark-relative outcomes;
- self-critique;
- confidence calibration;
- paper and replay outcomes where data provenance permits.

The export excludes secrets, database identifiers, account information, broker
information, raw private prompts and unlicensed verbatim source material.

### 5.2 Quality gate

An example is eligible only when it has:

- a valid schema version;
- evidence provenance;
- sufficient data quality;
- explicit contradiction handling;
- calibrated confidence language;
- an outcome state or an explicit insufficient-evidence label;
- no unsupported numerical claims;
- no direct financial-advice language;
- no duplicate or near-duplicate reasoning trace.

Examples with unclear outcomes may be retained for no-fabrication and abstention tasks
but cannot be labeled as successful market reasoning.

### 5.3 Split strategy

Random row splitting is prohibited.

Splits are grouped and temporal:

- training uses older eligible records;
- validation uses a later time window;
- final test uses the newest untouched time window;
- records from the same thesis lineage remain in one split;
- near-duplicate ticker/context examples remain in one split;
- benchmark evaluation cases are excluded from training;
- public benchmark contamination is checked before reporting results.

The split manifest records record counts, date ranges, ticker counts, regime coverage,
hashes and exclusion reasons.

### 5.4 Dataset repository

The releasable, redacted dataset is published separately:

`Italianhype/Blum-Finance-Reasoning`

The collaborative contribution queue is separate:

`Italianhype/Blum-Finance-Memory`

The reasoning dataset uses a data-appropriate open license only after confirming that
all included content can be redistributed. Model and code licensing does not
automatically license training data.

## 6. Training Design

### 6.1 Base model

Use `Qwen/Qwen3-4B`, selected because it is a practical 4B conversational model with
an Apache-2.0 license and current Transformers/TRL support.

### 6.2 Initial method

Run supervised fine-tuning with LoRA:

- assistant/completion-only loss;
- packed examples where schema boundaries remain intact;
- deterministic seed;
- bf16 where supported;
- gradient accumulation sized to available GPU memory;
- early stopping based on held-out financial reasoning quality;
- Trackio training metrics;
- immutable training manifest;
- adapter checkpoint retention.

DPO is excluded from the first release unless the preference dataset passes an
independent validity check and contains enough non-synthetic preference pairs.

### 6.3 Model gate

The merged model is promoted only if it:

- improves the target financial reasoning aggregate over the exact base revision;
- does not regress materially on no-fabrication and abstention tests;
- does not regress materially on contradictory-evidence handling;
- preserves risk and invalidation completeness;
- produces valid structured outputs at an acceptable rate;
- passes smoke inference in Transformers;
- passes GGUF inference parity within documented tolerance.

If the gate fails, publish the dataset and evaluation report but do not replace the
primary model repository with failed weights.

## 7. Evaluation and Benchmarking

### 7.1 Benchmark classes

Evaluate the base model and BLUM model with the same prompts, decoding settings and
hardware assumptions:

1. public financial QA/reasoning benchmarks whose licenses permit evaluation;
2. financial sentiment classification;
3. BLUM held-out thesis reasoning;
4. contradictory evidence handling;
5. invalidation and risk completeness;
6. confidence calibration and abstention;
7. numerical consistency;
8. structured-output validity;
9. Italian and English financial explanation quality.

FinQA is included only if its license, task adapter and contamination checks pass.

### 7.2 Statistical reporting

Every result includes:

- dataset revision and split;
- sample size;
- metric definition;
- bootstrap confidence interval where meaningful;
- base-model comparison;
- decoding configuration;
- evaluation code revision;
- failed-example count;
- contamination and limitations notes.

No benchmark result is invented, estimated from training loss or copied from the base
model's card.

### 7.3 Hugging Face publication

Verified results are published:

- in the model card;
- in machine-readable `.eval_results/*.yaml`;
- with linked evaluation traces where publishable;
- to compatible Hugging Face benchmark datasets/leaderboards.

Leaderboard inclusion is described as pending until Hugging Face accepts and
aggregates the result. The release does not use the word "official" for author-only
results.

Text-model benchmarks are not presented as evidence of trading alpha. Trading alpha
requires BLUM Engine's historical, walk-forward and paper-forward evidence.

## 8. Community Memory Protocol

### 8.1 Consent

Community learning is opt-in. Installation and inference never upload data.

The contributor must run an explicit command:

`blum contribute`

Before upload, the tool shows:

- fields to be shared;
- redactions performed;
- target repository;
- contribution license;
- model and schema versions;
- a final confirmation step.

### 8.2 Contribution envelope

Each contribution contains:

- schema version;
- model repository and immutable revision;
- prompt category and structured context;
- model output;
- user correction or preference;
- optional outcome recorded after the required horizon;
- evidence references that can legally be shared;
- anonymization report;
- content hash;
- contributor-selected license;
- timestamp and evaluation mode.

It must not contain:

- API keys or tokens;
- broker/account identifiers;
- personal positions unless explicitly transformed and anonymized;
- raw proprietary market feeds;
- copyrighted full articles or reports;
- unreviewed private conversations.

### 8.3 Quarantine and promotion

Contributions enter a quarantine split. They are:

1. schema validated;
2. scanned for secrets and PII;
3. checked for redistribution rights;
4. deduplicated;
5. scored for evidence and reasoning quality;
6. checked for poisoning and prompt injection;
7. evaluated against known outcomes where applicable;
8. reviewed or rejected;
9. promoted only into a future versioned dataset release.

No contribution directly updates production memory, active weights or trading rules.
Model updates occur in explicit versions and must pass the same out-of-sample gate as
the initial release.

## 9. Model Card and Discoverability

The model card leads with a factual capability summary and runnable examples.

Search-oriented tags include:

- finance;
- financial-reasoning;
- investment-research;
- risk-management;
- portfolio-analysis;
- market-regime;
- financial-sentiment;
- explainable-ai;
- text-generation;
- conversational;
- Italian;
- English.

The card includes:

- thirty-second quick start;
- Transformers example;
- structured-output example;
- local GGUF example;
- intended uses and prohibited uses;
- training-data lineage;
- benchmark table with base deltas;
- calibration and failure examples;
- community contribution instructions;
- Space demo link;
- citation;
- changelog;
- financial disclaimer.

Marketing language may emphasize accessibility and transparent financial reasoning.
It may not claim superior returns, guaranteed signals, autonomous profitability or
benchmark leadership unsupported by published evidence.

## 10. Integration with BLUM Engine

BLUM Analyst remains non-authoritative.

The Engine may use the model to propose:

- a balanced thesis;
- bull and bear arguments;
- contradiction summaries;
- risk and invalidation explanations;
- missing evidence;
- confidence rationale.

The Engine validates:

- market facts;
- timestamps;
- calculations;
- price levels;
- benchmark outcomes;
- portfolio and risk constraints;
- actionability.

Model output that cannot be validated is labeled insufficient evidence and cannot
raise actionability by itself.

## 11. Testing

Required automated tests include:

- export schema and deterministic split tests;
- no cross-split thesis lineage leakage;
- redaction of secrets and PII;
- copyrighted-source exclusion;
- contribution disabled by default;
- explicit-consent enforcement;
- content-hash deduplication;
- quarantine enforcement;
- model-card metadata validation;
- Transformers smoke inference;
- structured-output validation;
- base-versus-fine-tuned evaluation parity;
- no-fabrication regression gate;
- GGUF conversion and smoke inference;
- immutable model/data revision references.

## 12. Release Sequence

1. Add licensing and artifact-boundary documentation.
2. Export a redacted dataset candidate from BLUM Engine.
3. Audit and create temporal grouped splits.
4. Publish the versioned reasoning dataset.
5. Implement reproducible LoRA training.
6. Run training on Hugging Face Jobs with Trackio.
7. Evaluate base and candidate on identical held-out suites.
8. Reject or promote the candidate using the model gate.
9. Merge and publish Transformers weights if promoted.
10. Convert and verify GGUF.
11. Replace the stale model-repository card with the BLUM Finance card.
12. Publish verified evaluation results.
13. Add the opt-in contribution package and quarantine dataset.
14. Link the model, dataset, GGUF, adapter and Space in a Hugging Face collection.

## 13. Success Criteria

The release is complete only when:

- `Italianhype/Blum` loads with `AutoModelForCausalLM.from_pretrained`;
- the model repository contains real weights and tokenizer artifacts;
- an independent user can run a documented prompt;
- training and dataset revisions are immutable and documented;
- benchmark numbers are reproducible and linked to traces;
- the candidate's comparison against the base is visible;
- GGUF runs locally;
- community contribution is opt-in and privacy-preserving;
- unvalidated contributions cannot alter model or Engine state;
- limitations and non-alpha status are explicit;
- the Space continues to run independently.

## 14. Known Constraints

- 4,435 examples are enough for an initial adapter experiment, not proof of a durable
  financial model.
- The current quality scorer is partly heuristic and must not be the sole training
  gate.
- Public benchmark licenses and contamination status require per-dataset verification.
- Community contributions can improve future releases only after curation and
  validation; downloads alone do not update weights.
- Financial reasoning benchmark gains do not prove trading profitability.
- Legal review may still be required before assigning an open license to the exported
  dataset.
