# Forex Evidence Academy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an evidence-bound Forex knowledge, curriculum and contextual-memory pipeline that accelerates validated learning without inflating confidence or risk.

**Architecture:** Add focused persistence models and one `ForexEvidenceAcademyService` facade over three cohesive components: source catalog, curriculum planner and contextual memory compiler. Adaptive replay consumes curriculum priorities; the Forex decision evaluator receives read-only contextual memory, while general knowledge remains explanatory only.

**Tech Stack:** Python 3, SQLAlchemy, Alembic, pytest, FastAPI service conventions, existing replay and Forex agent contracts.

## Global Constraints

- No confidence boost from text ingestion alone.
- No future data before a replay decision.
- No heavy work on GET routes or frontend mount.
- No leverage, risk-limit or certified promotion threshold increase.
- External ingestion is incremental, provenance-aware and failure-isolated.
- Existing Forex paper execution and strategy promotion logic remains backward compatible.

---

### Task 1: Persist the Forex academy state

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0037_forex_evidence_academy.py`
- Modify: `backend/tests/test_migration_chain.py`
- Test: `backend/tests/test_forex_evidence_academy.py`

**Interfaces:**
- Produces: `ForexKnowledgeSource`, `ForexCurriculumAssignment`, `ForexContextualMemory`, `ForexKnowledgeIngestionRun`.

- [ ] Add failing model and migration-chain tests for the four tables, unique keys, JSON fields and indexes.
- [ ] Run `python3 -m pytest backend/tests/test_forex_evidence_academy.py backend/tests/test_migration_chain.py -q` and confirm failure.
- [ ] Add SQLAlchemy models and cross-database-safe Alembic migration `0037_forex_evidence_academy`.
- [ ] Re-run the focused tests and confirm pass.

### Task 2: Build the curated source catalog and curriculum

**Files:**
- Create: `backend/app/services/forex_evidence_academy.py`
- Test: `backend/tests/test_forex_evidence_academy.py`

**Interfaces:**
- Produces: `ForexKnowledgeCatalogService.refresh(db, validate=False) -> dict`.
- Produces: `ForexCurriculumPlanner.generate(db, limit=12) -> list[ForexCurriculumAssignment]`.
- Produces: `ForexEvidenceAcademyService.run_background_slice(db, max_assignments=12) -> dict`.

- [ ] Add failing tests proving source provenance, license and usage policy are persisted.
- [ ] Add a failing test proving knowledge sources are never marked as edge evidence.
- [ ] Add failing curriculum tests for broad exploration, sample-gap priority and bounded output.
- [ ] Implement the catalog and planner with no network access by default.
- [ ] Run focused tests and confirm pass.

### Task 3: Compile contextual Forex memory

**Files:**
- Modify: `backend/app/services/forex_evidence_academy.py`
- Test: `backend/tests/test_forex_evidence_academy.py`

**Interfaces:**
- Produces: `ForexMemoryCompiler.compile(db, limit=1000) -> dict`.
- Produces: `ForexMemoryCompiler.context_for(db, *, strategy_id, pair, session, regime, setup_family) -> dict`.

- [ ] Add failing tests for grouped sample size, expectancy, benchmark excess, confidence intervals and cost-failure rates.
- [ ] Add a failing test proving fewer than 30 outcomes remain `LEARNING_ONLY`.
- [ ] Add a failing test proving validated positive memory is `CONTEXT_ELIGIBLE`.
- [ ] Implement incremental aggregation from immutable `ForexLearningEvidence` rows.
- [ ] Run focused tests and confirm pass.

### Task 4: Apply only validated memory to decisions

**Files:**
- Modify: `backend/app/services/forex_contracts.py`
- Modify: `backend/app/services/forex_agents.py`
- Modify: `backend/app/services/forex_trader.py`
- Test: `backend/tests/test_forex_trader_core.py`
- Test: `backend/tests/test_forex_evidence_academy.py`

**Interfaces:**
- Extends: `ForexStrategyEvidence.contextual_memory: dict`.
- Extends: `ForexTradeProposal.knowledge_context: dict`.

- [ ] Add failing tests proving catalog-only knowledge does not alter confidence.
- [ ] Add a failing test proving eligible contextual memory makes a bounded confidence adjustment.
- [ ] Add a failing test proving memory cannot bypass strategy-readiness or data vetoes.
- [ ] Load contextual memory in the strategy repository and expose its adjustment in confidence components.
- [ ] Persist knowledge/curriculum context in frozen Forex decisions.
- [ ] Run focused Forex tests and confirm pass.

### Task 5: Feed the curriculum into adaptive replay

**Files:**
- Modify: `backend/app/services/adaptive_replay_training.py`
- Modify: `backend/app/services/realtime.py`
- Test: `backend/tests/test_adaptive_replay_training.py`
- Test: `backend/tests/test_forex_evidence_academy.py`

**Interfaces:**
- Consumes: active `ForexCurriculumAssignment` rows.
- Produces: replay `strategy_specs` and `research_selection` metadata with `forex_curriculum_assignment_id`.

- [ ] Add a failing test proving an active Forex assignment enters the next bounded replay request.
- [ ] Add a failing test proving broad replay coverage remains present.
- [ ] Implement curriculum projection into replay specifications and completion counters.
- [ ] Add the bounded academy slice to the existing background scheduler, never to GET routes.
- [ ] Run scheduler and adaptive replay tests and confirm pass.

### Task 6: Documentation, verification and deployment

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents: source policy, curriculum, contextual memory and confidence boundary.

- [ ] Document the Forex Evidence Academy and its safety boundary.
- [ ] Run `python3 -m pytest backend/tests/test_forex_evidence_academy.py backend/tests/test_forex_trader_core.py backend/tests/test_adaptive_replay_training.py backend/tests/test_migration_chain.py -q`.
- [ ] Run `python3 -m pytest -q`.
- [ ] Run `git diff --check` and inspect the final diff.
- [ ] Commit, push `main` to the Hugging Face Space and verify startup plus the read-only Paper Trading snapshot.
