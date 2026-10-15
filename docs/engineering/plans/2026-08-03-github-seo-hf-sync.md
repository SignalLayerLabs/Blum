# GitHub SEO and Hugging Face Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish an accurate, professional BLUM repository landing surface and safely import Hugging Face Space commits into canonical GitHub history.

**Architecture:** GitHub remains canonical and Hugging Face remains the public deployment. A scheduled GitHub Action classifies commit ancestry and either does nothing, fast-forwards GitHub, or opens a protected synchronization pull request; the public README and focused documents expose the same boundary to contributors.

**Tech Stack:** Git, Git LFS, GitHub Actions, GitHub CLI, Python 3 standard library, Markdown, YAML, Docker, Hugging Face Spaces.

## Global Constraints

- Do not modify financial, learning, paper-trading, model or frontend behavior.
- Do not force-push GitHub `main`.
- Do not add Hugging Face credentials for public read synchronization.
- Preserve all existing project documentation and Git history.
- Keep GitHub as `origin` and Hugging Face as `hf`.
- Keep synchronization idempotent and observable.
- Do not claim alpha, guaranteed returns or production copy-trading readiness.

---

### Task 1: Deterministic synchronization classifier

**Files:**
- Create: `scripts/hf_sync_decision.py`
- Create: `backend/tests/test_hf_sync_decision.py`

**Interfaces:**
- Consumes: Git commit IDs and ancestry booleans computed by Git.
- Produces: `classify_sync(github_sha: str, hf_sha: str, github_is_ancestor: bool, hf_is_ancestor: bool) -> str` returning `noop_equal`, `noop_hf_behind`, `fast_forward` or `pull_request`.

- [ ] **Step 1: Write classifier tests**

```python
from scripts.hf_sync_decision import classify_sync


def test_equal_revisions_are_noop():
    assert classify_sync("a", "a", True, True) == "noop_equal"


def test_hf_behind_is_noop():
    assert classify_sync("b", "a", False, True) == "noop_hf_behind"


def test_hf_ahead_fast_forwards():
    assert classify_sync("a", "b", True, False) == "fast_forward"


def test_divergence_requires_pull_request():
    assert classify_sync("a", "b", False, False) == "pull_request"
```

- [ ] **Step 2: Run tests and confirm the missing module failure**

Run: `python3 -m unittest backend.tests.test_hf_sync_decision -v`

Expected: import failure for `scripts.hf_sync_decision`.

- [ ] **Step 3: Implement the pure classifier and CLI**

The CLI accepts `--github-sha`, `--hf-sha`, `--github-is-ancestor` and
`--hf-is-ancestor`, prints only the action string and rejects empty SHAs.

- [ ] **Step 4: Run classifier tests**

Run: `python3 -m unittest backend.tests.test_hf_sync_decision -v`

Expected: four passing tests.

- [ ] **Step 5: Commit the classifier**

```bash
git add scripts/hf_sync_decision.py backend/tests/test_hf_sync_decision.py
git commit -m "test: define HF sync ancestry decisions"
```

### Task 2: Safe scheduled Hugging Face synchronization

**Files:**
- Create: `.github/workflows/sync-huggingface.yml`
- Modify: `docs/DEPLOYMENT.md`

**Interfaces:**
- Consumes: public `https://huggingface.co/spaces/Italianhype/Blum`, `scripts/hf_sync_decision.py`, standard `GITHUB_TOKEN`.
- Produces: no-op, fast-forward of `main`, or `sync/hf-main` plus one pull request.

- [ ] **Step 1: Add workflow triggers and permissions**

Use `workflow_dispatch` and `schedule: cron: "17,47 * * * *"`, one concurrency
group, `contents: write` and `pull-requests: write`.

- [ ] **Step 2: Add full-history and LFS checkout**

Use `actions/checkout@v4` with `fetch-depth: 0` and `lfs: true`, configure the
`hf` remote and fetch only HF `main`.

- [ ] **Step 3: Classify ancestry**

Compute both merge-base checks, invoke `scripts/hf_sync_decision.py`, expose the
action and both SHAs as step outputs, and append them to `$GITHUB_STEP_SUMMARY`.

- [ ] **Step 4: Implement fast-forward with fallback**

Fetch and push LFS objects before advancing GitHub. Push the exact HF SHA to
`refs/heads/main` without force. If GitHub rejects the update, output
`pull_request` for the next step rather than overwriting branch protection.

- [ ] **Step 5: Implement divergence pull request**

Push the exact HF SHA to `sync/hf-main` using force-with-lease, reuse an open
`sync/hf-main` pull request when present, otherwise create one with evidence and
both revisions in its body.

- [ ] **Step 6: Validate YAML and workflow policy**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/sync-huggingface.yml"); puts "yaml ok"'
rg -n 'force.*main|HF_TOKEN|huggingface.*token' .github/workflows/sync-huggingface.yml
```

Expected: YAML passes and forbidden patterns return no matches.

- [ ] **Step 7: Commit workflow**

```bash
git add .github/workflows/sync-huggingface.yml docs/DEPLOYMENT.md
git commit -m "ci: synchronize Hugging Face changes safely"
```

### Task 3: Professional root README and documentation map

**Files:**
- Move: `README.md` to `docs/PROJECT_REFERENCE.md`
- Create: `README.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/DEPLOYMENT.md`
- Create: `docs/RESEARCH_METHODOLOGY.md`

**Interfaces:**
- Consumes: existing architecture and release reports.
- Produces: concise public landing page and focused contributor documents.

- [ ] **Step 1: Preserve the cumulative README**

Move the existing file without changing its contents, then add an archive notice
that links back to the concise root README.

- [ ] **Step 2: Write the root landing page**

Keep the HF Space metadata frontmatter. Add BLUM identity, accurate search terms,
badges, live links, four product surfaces, architecture, evidence policy, quick
start, documentation index, contribution and disclaimer sections. Keep it below
450 lines.

- [ ] **Step 3: Write focused architecture documentation**

Document Engine, Runtime, Analyst, event/snapshot flow and the source-of-truth
boundary. Link detailed historical reports instead of duplicating them.

- [ ] **Step 4: Write deployment and synchronization documentation**

Document local, Docker, GitHub and HF remotes, sync decisions, manual dispatch,
failure recovery and the absence of an HF credential in the inbound workflow.

- [ ] **Step 5: Write research methodology**

Document point-in-time evidence, look-ahead protection, transaction costs,
benchmark separation, sample-size warnings and paper-only claims.

- [ ] **Step 6: Validate public documentation**

Run:

```bash
test "$(wc -l < README.md)" -le 450
rg -n 'guaranteed|guaranteed alpha|daily profit' README.md docs/ARCHITECTURE.md docs/RESEARCH_METHODOLOGY.md
git diff --check
```

Expected: line budget passes, no prohibited claim is introduced and whitespace
validation passes.

- [ ] **Step 7: Commit documentation redesign**

```bash
git add README.md docs/PROJECT_REFERENCE.md docs/ARCHITECTURE.md docs/DEPLOYMENT.md docs/RESEARCH_METHODOLOGY.md
git commit -m "docs: redesign BLUM public repository"
```

### Task 4: Community health, citation and ownership

**Files:**
- Create: `SUPPORT.md`
- Create: `CITATION.cff`
- Create: `.github/CODEOWNERS`
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Modify: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Modify: `.github/ISSUE_TEMPLATE/feature_request.yml`

**Interfaces:**
- Consumes: GitHub Discussions, issue tracker and security policy.
- Produces: explicit community routing, citation metadata and code ownership.

- [ ] **Step 1: Add support routing**

Route reproducible defects to Issues, usage and research questions to
Discussions, and vulnerabilities to private reporting.

- [ ] **Step 2: Add citation metadata**

Create valid CFF 1.2.0 metadata for BLUM Financial Lab, repository URL, project
URL, Apache-2.0 license and finance/AI keywords. Do not invent a DOI.

- [ ] **Step 3: Add ownership and issue routing**

Set `@BlumFinancialLab` as default owner and explicit owner for Engine, Runtime,
model-release, workflow and documentation paths. Disable blank issues and add
Discussion and security contact links.

- [ ] **Step 4: Validate YAML and links**

Run:

```bash
ruby -e 'require "yaml"; Dir[".github/**/*.yml", "CITATION.cff"].flatten.each { |f| YAML.load_file(f); puts f }'
git diff --check
```

Expected: all YAML parses and no whitespace errors exist.

- [ ] **Step 5: Commit community metadata**

```bash
git add SUPPORT.md CITATION.cff .github
git commit -m "docs: complete GitHub community metadata"
```

### Task 5: Publication, metadata and end-to-end verification

**Files:**
- Modify: GitHub repository metadata through `gh repo edit`.
- Modify: GitHub Actions workflow permissions through the GitHub API.

**Interfaces:**
- Consumes: committed repository and authenticated GitHub CLI.
- Produces: searchable topics, enabled workflow permissions and deployed docs.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python3 -m unittest backend.tests.test_hf_sync_decision -v
/Users/renatovinai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test frontend/tests/*.test.mjs
git diff --check
```

Expected: all classifier and frontend tests pass.

- [ ] **Step 2: Push GitHub and configure metadata**

Push `main`; set accurate repository description, Space homepage and up to 20
topics covering financial intelligence, quantitative finance, paper trading,
backtesting, AI agents, equities, Forex, FastAPI, Next.js and Hugging Face.

- [ ] **Step 3: Configure Actions permissions**

Set default workflow permission to write and allow workflow pull-request
creation. Do not add repository secrets.

- [ ] **Step 4: Dispatch synchronization workflow**

Run `gh workflow run sync-huggingface.yml`, wait for completion and verify the
expected `noop_hf_behind` or `noop_equal` result.

- [ ] **Step 5: Deploy documentation to Hugging Face**

Push `main` to `hf`, wait for runtime stage `RUNNING`, and verify `/`,
`/api/brain/snapshot`, `/api/training/snapshot`, `/api/paper-trading/snapshot`
and `/api/alpha/snapshot` return HTTP 200.

- [ ] **Step 6: Verify revision and repository health**

Confirm local, GitHub and HF main SHAs match after deployment; verify GitHub
detects Apache-2.0, community files, topics, homepage and the new README.

- [ ] **Step 7: Record final status**

Report commits, files, tests, workflow run URL, deployment revision, sync policy
and remaining operational limitations without claiming performance changes.
