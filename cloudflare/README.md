# BLUM public gateway

Cloudflare serves the exported web product and proxies the reviewed read-only JSON APIs to the existing HF runtime. It does not own a financial database, run models or execute research.

| Path | Responsibility |
| --- | --- |
| [src](src) | Worker and upstream/gateway policy |
| [tests](tests) | Read policy, mutation denial and upstream behavior contracts |
| [wrangler.jsonc](wrangler.jsonc) | Worker configuration and frontend assets binding |

Build `frontend/out` first. From the repository root:

```bash
npm ci --prefix cloudflare
npm --prefix cloudflare test
npm --prefix cloudflare run types
npm --prefix cloudflare run typecheck
npm --prefix cloudflare run preview
```

The shared [public route policy](../backend/app/data/public_api_routes.json) defines the allowed API reads. Credential/cookie forwarding, unreviewed API routes and public mutations are rejected. Financial JSON is streamed with caching disabled and bounded upstream waits.

The configured origin is the public HF runtime. Previewing the gateway can read that origin; check `BACKEND_ORIGIN` deliberately. For publication, follow [deployment and rollback](../docs/operations/deployment.md), including source revision and protected-content verification. Keep generated Wrangler types and `.wrangler` state untracked.
