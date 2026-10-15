# BLUM web product

Next.js supplies the public research workspaces. The maintained navigation is Brain, Training Ground, Paper Trading, Alpha and Evolution. Older routes remain for compatibility and diagnostics; their presence does not make them additional public product promises.

| Path | Responsibility |
| --- | --- |
| [app](app) | Page routes, layout and shared styling |
| [components](components) | Research views and interface components |
| [lib](lib) | API client, types and view-level contracts |
| [tests](tests) | Node test-runner contracts for views and public behavior |
| [next.config.mjs](next.config.mjs) | Static export configuration |

From the repository root:

```bash
npm ci --prefix frontend --workspaces=false
NEXT_PUBLIC_API_BASE=http://127.0.0.1:7860 npm --prefix frontend run dev
npm --prefix frontend test
npm --prefix frontend run build
```

Run the backend separately for development. The complete [development guide](../docs/guides/development.md) covers TypeScript and gateway checks. The production export is `frontend/out`, consumed by Docker and the Cloudflare assets binding. Leave `NEXT_PUBLIC_API_BASE` empty for same-origin production requests. Never embed credentials in public variables.

Page rendering reads stored snapshots and must not launch training, recalculation or execution. Missing, stale and insufficient evidence are meaningful states that the UI must preserve.
