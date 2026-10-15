# Repository presentation and information architecture

> Editorial implementation plan · 2026-10-15

**Goal:** Make BLUM easy to understand, explore and contribute to through a product-led README and an orderly repository.

**Scope:** Documentation, public presentation, navigation and repository housekeeping. Runtime entry points, imports, migrations, datasets, deployment contracts and dependency versions retain their existing paths and contents.

**Architecture:** Keep the existing backend, frontend, Cloudflare, model-release and operational-script boundaries. Organize documentation by reader task; preserve implementation reports and historical design records with explicit context.

**Stack:** GitHub Markdown, accessible SVG, an actual product screenshot, existing Python/Node verification commands.

## Global constraints

- GitHub remains canonical; preserve the root Hugging Face Docker card and root deployment manifests.
- Distinguish shipped capability, historical documentation and future plans. No unverified performance, adoption or competitor claims.
- Keep equities/ETFs and Forex evaluation separate; state that qualified prospective alpha is not established.
- Preserve every tracked evidence ledger and report. No deletion of runtime data or private operations.
- Use npm and Python commands that match the repository. Documentation-only work uses link, inventory and existing contract checks rather than new behavior-mirroring tests.
- Work in the existing task-owned clone on a focused branch. No additional checkout or production restart is needed for this editorial task.

## Task 1 — Organize the repository

Move current architecture, research and operations guides to named subdirectories. Move root subsystem reports into docs/reports; place version-specific records and the old roadmap under docs/archive. Move engineering plans/specs into docs/engineering. Update relative links from their original locations. Add an index for each audience and component. Remove obsolete LFS entries for ignored build and virtual-environment files; retain all active data patterns.

**Validation:** Compare the old/new tracked inventory and report/evidence content, scan relative Markdown links, inspect all changed non-documentation paths and preserve the protected runtime hash.

## Task 2 — Rebuild the public presentation

Write an entirely new README with a clear product promise, useful public links, a branded SVG header, an authentic dated product view, task-oriented benefits, separate research status and a concise Docker start. Put extended setup in guides. Refresh contribution commands, citation metadata and the roadmap; retain the old roadmap as historical documentation.

**Validation:** Preserve the HF card contract, verify every local link and image, render the README visually, verify public product routes and inspect the copy against the implementation.

## Task 3 — Verify and publish the change for review

Run the affected existing contracts, web/gateway tests and web build; request one independent whole-branch review, fix material findings, commit and open a pull request. Preserve the production runtime during the repository presentation change.

**Validation:** Git diff whitespace check, complete Markdown navigation check, unchanged runtime fingerprint, CI results and rendered GitHub presentation.

## Review focus

Check misleading marketing, stale historical claims presented as current, broken relative links after moves, lost reports, image readability, incorrect setup instructions and accidental changes to runtime/deployment paths. Check that no private logs, credentials, operational artifacts or database snapshots enter the repository.

## Verification record

Initial implementation checks: all 604 original tracked files retained at their original or mapped paths; 76 moves; root files reduced from 45 to 19; nine evidence ledgers unchanged. Local navigation check: 105 Markdown files, 312 relative links and two Markdown anchors, with no missing target. HF metadata, SVG XML and whitespace checks passed. Focused existing backend contracts: 34 passed; frontend: 17 passed; gateway: 12 passed. Frontend static export and gateway types/typecheck passed. Reviewed historical-source policy check passed. Protected runtime fingerprint remained `09ea98a83bd08e9de3a3ac784e592784f7d7069f1cdb14491f9addec19a17854`.

An independent whole-branch review and GitHub CI follow publication of the review branch. Production maintenance is outside this editorial change.

## Visual QA decision

GitHub rendered the required HF frontmatter as a large metadata table above the product hero. The marketing presentation now lives in `.github/README.md`, GitHub's documented first-choice homepage README. The root README retains the HF metadata and a focused runtime introduction. Both use relative links from their own locations, and neither requires a deployment/source-mirror change. This replaces the initial single-file presentation approach to preserve both platform contracts without duplicate long-form copy.

## Independent review and fixes

The first reviewer could not start because of its usage limit; a fresh independent reviewer completed the whole-branch review. It found a migration command resolving the wrong scripts directory (Important) and an obsolete migration-readiness checkpoint (labeled Minor). Both concern whether a maintainer can perform or correctly verify setup, so both were treated as actionable documentation correctness issues.

The original root Alembic command was executed and failed because root `alembic/` does not exist. The guide now uses the backend working directory, matching the Docker entrypoint. The operations guide checks current/head for the evaluated release rather than stopping at migration 0025, and documents the existing private-origin authorization checks. No runtime or authentication configuration changed. Financial-performance certification and live operational state were outside the editorial review; the branch makes no new performance or deployment claim.
