# Blum v3 production cutover

The user authorizes deployment to the existing workers.dev domain. Use the existing Cloudflare Worker, HF Docker Space, PostgreSQL and backup bucket; do not introduce paid infrastructure. PR17 is already merged, but the production workflow still builds and serves v2.

Switch the production build to web_v3 and the HF process to blum_v3 API plus one supervised worker. Retain the existing database recovery/backup path and all legacy tables; v3 uses its own prefixed tables. Stop legacy writers through container replacement. Reuse the existing private operator key when no explicit v3 key is configured; fail closed without either. Never bake, log or expose a key.

Forward only caller-provided Bearer authorization and bounded JSON/idempotency commands on /api/v3 through the Worker. Reject anonymous commands, cross-origin writes, redirects and HTML API fallbacks. Public release/health endpoints expose readiness, exact baked revision and a protected runtime content hash. Require both API and worker health before routing the new frontend. Preserve legacy gateway behavior as an explicit rollback channel.

Use GitHub Actions' existing production credentials. Require successful v2 and v3 verification for the exact current main revision. Publish backend first, then assets/gateway, then verify public HTML and API boundaries. Preserve a rollback recipe. No broker execution or historic performance promotion.
