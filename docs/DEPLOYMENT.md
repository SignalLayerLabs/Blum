# BLUM release and operations

## Ownership

- Canonical source, CI, review and releases: GitHub `SignalLayerLabs/Blum`.
- Public product: `https://blum.signallayerlabs.workers.dev` on Cloudflare.
- Engine, scheduler and PostgreSQL: Hugging Face Docker Space `Italianhype/Blum`.
- Persistent evidence and recovery: existing `Italianhype/Blum-storage` bucket.

No workflow imports HF changes directly into GitHub `main`. Publication is one-way and fast-forward-only. Changes made directly on HF must be reviewed and ported into GitHub first.

## GitHub configuration

The production deployment job consumes:

| Name | Store | Purpose |
| --- | --- | --- |
| `HF_TOKEN` | Secret | Publish canonical source to the existing Space |
| `CLOUDFLARE_API_TOKEN` | Secret | Publish Worker and static assets |
| `CLOUDFLARE_ACCOUNT_ID` | Variable | Select the existing Cloudflare account |

Use deployment tokens with required access only. Never copy a short-lived Wrangler OAuth token into GitHub as a permanent credential. Repository or production-environment secrets can be used. Tokens are passed only to trusted deployment jobs, never PR builds.

`Verify BLUM` runs backend/migration contracts, exact source-data checks, web tests/build and gateway tests/types. `Deploy verified main` starts after successful main verification or a manual dispatch that passes the same preflight. It rejects stale or unverified revisions.

```bash
gh workflow run deploy.yml --repo SignalLayerLabs/Blum --ref main
gh run list --repo SignalLayerLabs/Blum --workflow deploy.yml
```

Deployment builds the web product, sets the HF source revision, transfers LFS and fast-forwards HF main. It waits for readiness and the baked backend revision, then publishes Cloudflare and checks all five pages, JSON snapshots and mutation denial.

## Cloudflare gateway

`cloudflare/wrangler.jsonc` serves `frontend/out` using an assets binding and the typed Worker. Keep `NEXT_PUBLIC_API_BASE` empty for same-origin requests. Public requests are GET/HEAD on the shared reviewed route list. Unvetted legacy GET handlers are private because some write even when persist=false. Persistence/rebuild queries are rejected. Client credentials/cookies are stripped; APIs stream with no-store. Redirects and non-JSON API responses fail explicitly. Asset detail APIs send Accept: application/json so they do not shadow HTML pages at the same path.

```bash
npm ci --prefix frontend --workspaces=false
npm --prefix frontend run build
npm ci --prefix cloudflare
npm --prefix cloudflare run types
npm --prefix cloudflare run typecheck
source_content_hash=$(PYTHONPATH=backend python -c 'from app.core.release import source_content_hash; print(source_content_hash())')
npm --prefix cloudflare run deploy -- --var "SOURCE_REVISION:$(git rev-parse HEAD)" --var "SOURCE_CONTENT_HASH:$source_content_hash"
```

Wrangler authentication is required for publication. A custom domain can be added later. This release does not alter unrelated DNS. Worker observability is enabled. Financial state is not stored in edge cache or a parallel Worker database.

## HF runtime and readiness

The image remains FastAPI + CPU ML + PostgreSQL with the static product. BLUM_SOURCE_REVISION is passed as a Docker build argument and baked into backend/app/data/build_revision.json. A runtime variable change cannot label an older baked image as the current release.

```bash
curl -fsS https://italianhype-blum.hf.space/startup/status
curl -fsS https://italianhype-blum.hf.space/api/runtime/release
curl -fsS https://blum.signallayerlabs.workers.dev/api/release
```

Require api_ready=true, ui_ready=true, no startup last_error, and the exact GitHub source revision. The release API also reports source_content_hash, computed from protected backend and script files. The verifier compares it with the verified checkout, so changing a revision variable cannot make an older code image pass. HTML with HTTP200 is not API readiness. `scripts/verify_deployment.py` enforces this contract.

The existing bucket stays attached. PostgreSQL remains on local disk; object storage holds physical recovery files and atomic logical backups. Embedded PostgreSQL supports one replica. Multiple replicas require an external database. Preserve recovery files and verify startup before declaring data recovery complete.

New physical backups publish base and streamed WAL together in `recovery.tar`, with an embedded size/SHA-256 manifest. Restore reads that single object once and checks each nested archive while extracting to local disk; it does not stage another full archive locally. This prevents independently cached base/WAL objects from different generations being combined. Incomplete, ambiguous or corrupted bundles fall back to the logical dump, with the existing incomplete-restore guard. Legacy two-file images remain readable, subject to PostgreSQL successfully starting. Additional tablespaces are rejected by this embedded backup path. Checksums establish consistency with the manifest, not independent authenticity or zero-loss recovery.

## Research configuration

Fresh installations default to ASCENT disabled. The maintained runtime can enable the existing bounded scheduler:

```text
BLUM_ASCENT_ENABLED=true
BLUM_ASCENT_SCHEDULER_ENABLED=true
BLUM_ASCENT_INTERVAL_MINUTES=360
BLUM_ASCENT_ARTIFACT_ROOT=/data/ascent
BLUM_ASCENT_ADMIN_KEY=<runtime secret>
```

The maintained origin enables BLUM_PUBLIC_OBSERVATORY_ENABLED=true. Unvetted API handlers and all mutations require the private X-BLUM-Admin-Key; the five product snapshots and their declared supporting reads stay public. Direct HF POST /api/ascent/run requires that key. Cloudflare blocks public mutations even if a caller sends a key. Viewing Evolution never starts research. Candidates remain research-only; deployment automation never promotes their source into application code.

Keep BLUM_FOREX_HISTORY_ENABLED=false, BLUM_HF_TRAINING_ENABLED=false, BLUM_HF_TRAINING_AUTO_LAUNCH=false, BLUM_HF_TRAINING_SCHEDULER_ENABLED=false and BLUM_HF_DATASET_SNAPSHOT_ENABLED=false until those sources pass a replacement audit. The accepted Forex snapshots produce only one causal example. All existing reasoning archive versions remain quarantined. See [data acceptance](DATA_QUALITY.md).

## Recovery and rollback

1. Inspect GitHub deployment logs and HF build/runtime logs. Preserve failed revisions and reports.
2. If HF diverged, stop publication and review its changes. Do not force-push it from CI or automatically import it into GitHub main.
3. Restore code with a reviewed GitHub revert and deploy the new verified revision. Preserve the database and recovery files.
4. For emergency UI rollback, use wrangler rollback to a recorded Worker version. Verify backend schema/API compatibility.
5. Additive migration 0044_ascent_evolution preserves existing data. Code rollback does not require dropping its tables or erasing evidence.

Report outages and missing evidence explicitly. Do not fill unavailable charts or APIs with fabricated results.

## Prospective call evidence

New decisions register within their original database transactions. The read-only `/api/alpha/desk` never backfills legacy records or starts financial execution. Migration 0045 is additive. Source fingerprints establish recorded code content, not semantic data validity or model outperformance. See [Alpha Desk](ALPHA_DESK.md).
