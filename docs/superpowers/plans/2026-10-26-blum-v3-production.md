# Blum v3 production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the verified v3 workspace and authenticated API at the existing production domain.
**Architecture:** Existing HF PostgreSQL recovery is retained; a supervised API/worker replaces legacy writers. Cloudflare serves web_v3 and forwards user Bearer commands; Actions gates and verifies exact runtime content.
**Tech Stack:** Python 3.12, PostgreSQL15, Node24, Cloudflare Workers, HF Docker, GitHub Actions.
**Spec:** docs/superpowers/specs/2026-10-26-blum-v3-production-design.md

## Global Constraints
- Existing domain, Space, database and bucket; no new paid services.
- Preserve legacy tables/backups; no financial history imported as prospective.
- Never publish credentials; reuse operator key, fail closed without it.
- Backend first, then gateway; exact baked revision and content verification.

## Review Focus
- An authenticated command must retain identity/body without forwarding cookies.
- Missing key, stale backend or dead worker must never report a ready deployment.
- Origin redirects and HTML fallbacks must fail explicitly.
- Both CI workflows must pass for current main before deployment.
- Existing legacy data and backups must survive process replacement.

### Task 1: Production runtime and release identity
Files: blum_v3/release.py, blum_v3/runtime.py, blum_v3/api.py, scripts/start.sh, Dockerfile, tests_v3/test_release.py.
Produces public release/readiness with baked revision and protected content, supervised processes and isolated v3 tables in restored PostgreSQL.
- [ ] Write failing release/readiness/key tests; watch RED.
- [ ] Implement runtime supervision/release identity and production start branch.
- [ ] Run v3 suite and shell syntax; commit.

### Task 2: Authenticated production gateway
Files: cloudflare/src/v3.ts, cloudflare/src/index.ts, cloudflare/wrangler.jsonc, cloudflare/tests/v3.test.mjs.
Consumes Task1 release/readiness; produces authenticated same-origin v3 command transport with explicit legacy rollback channel.
- [ ] Write failing auth/body/idempotency/release/redirect tests; watch RED.
- [ ] Implement v3 gateway and web_v3 assets binding.
- [ ] Run full gateway suite; typecheck/build in CI; commit.

### Task 3: Verified cutover workflow and public verification
Files: .github/workflows/deploy.yml, scripts/check_release_revision.py, scripts/verify_v3_deployment.py, docs/operations/deployment.md, tests_v3/test_release.py.
Consumes Tasks1/2; produces backend-first deployment gated on both workflow suites and exact content.
- [ ] Test stale/missing CI gates and protected content mismatches; watch RED.
- [ ] Update workflow builds, readiness verifier and rollback/operator instructions.
- [ ] Run complete appropriate suites; fresh whole-change review; fix material findings with RED/GREEN.
- [ ] Publish PR, verify CI, merge authorized cutover, monitor Actions and public release verification.
