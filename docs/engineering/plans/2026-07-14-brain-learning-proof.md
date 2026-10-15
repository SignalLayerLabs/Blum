# Brain Learning Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show measurable learning, paper P/L, benchmark progress and copy-readiness evidence on the Brain page from one read-only snapshot.

**Architecture:** Extend the existing Trader Brain read model with three bounded projections backed by persisted rows. Render those projections through reusable dependency-free SVG chart components while preserving the single-request Brain surface.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, Next.js, React, TypeScript, CSS, SVG.

## Global Constraints

- No heavy computation or writes in `GET /api/brain/snapshot`.
- No broker integration or real-money execution.
- Preserve evidence-class separation and null values.
- Do not promise that every trade will be profitable.
- Do not change the project version.

---

### Task 1: Brain evidence projections

**Files:**
- Modify: `backend/app/engine/brain/trader_brain.py`
- Test: `backend/tests/test_trader_brain.py`

**Interfaces:**
- Consumes: persisted `LearningRun`, `LearningProgressSnapshot`, `BlumTradingPowerScore`, `LiveForwardPaperTrade` and copy-readiness rows.
- Produces: `learning_proof`, `trading_proof`, `copy_readiness` dictionaries in `TraderBrainService.brain()`.

- [ ] Add a failing test that persists learning cycles, paper outcomes and readiness history and asserts bounded timestamped series, P/L metrics, benchmark data and readiness progress.
- [ ] Run `../.venv/bin/python -m pytest tests/test_trader_brain.py -q` and confirm the new assertions fail because the fields are absent.
- [ ] Implement pure projection helpers and wire them into `brain()` without writes or recalculation.
- [ ] Run the focused test and confirm it passes.

### Task 2: Brain proof charts

**Files:**
- Create: `frontend/components/BrainEvidenceCharts.tsx`
- Modify: `frontend/app/brain/page.tsx`
- Modify: `frontend/app/globals.css`

**Interfaces:**
- Consumes: the three dictionaries added in Task 1.
- Produces: responsive Brain Improvement, P/L vs Benchmark, Learning Throughput and Copy Trading Gate panels.

- [ ] Add frontend source validation assertions for one API request, no fabricated fallback series, and the four analytical panels.
- [ ] Run the validation and confirm it fails before the components exist.
- [ ] Implement bounded SVG charts, legends, metrics, empty states and copy-readiness progress.
- [ ] Run TypeScript/build validation and confirm it passes.

### Task 3: Regression, documentation and deployment

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: completed backend and frontend implementation.
- Produces: verified and deployed Brain Learning Proof surface.

- [ ] Document evidence semantics and the distinction between profitable expectancy and an impossible all-winning target.
- [ ] Run the full backend suite with `PAPER_FORWARD_LIFECYCLE_ENABLED=false ../.venv/bin/python -m pytest -q`.
- [ ] Run the clean frontend build.
- [ ] Review the diff for duplicated logic, unbounded queries, GET side effects and unsupported claims.
- [ ] Commit, push to Hugging Face, wait for `RUNNING`, and verify `/api/brain/snapshot` plus `/brain`.
