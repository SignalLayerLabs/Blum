# Repository map

[Documentation](../README.md) · [Architecture](README.md)

BLUM keeps one canonical repository with distinct responsibilities. Paths used by imports, migrations, Docker, CI and trusted scripts remain stable. Documentation is organized by reader task.

```text
Blum/
├── .github/             GitHub presentation, review ownership, forms and workflows
├── backend/             Python engine, API, workers, persistence and tests
│   ├── app/             Runtime code and reviewed packaged data
│   ├── alembic/         Ordered, versioned schema migrations
│   └── tests/           Backend and operational contracts
├── frontend/            Next.js pages, components, view contracts and tests
├── cloudflare/          Public Worker, gateway policy and edge tests
├── model_release/       Separately packaged advisory-model tooling
├── scripts/             Stable operational and research entry points
├── docs/
│   ├── architecture/    Current system boundaries and this map
│   ├── guides/          Setup and development
│   ├── operations/      Deployment, recovery and gated model operations
│   ├── research/        Alpha Desk, ASCENT, methodology and data policy
│   ├── evidence/        Preserved machine-readable audit ledgers
│   ├── reports/         Historical subsystem implementation/audit reports
│   ├── archive/         Earlier releases, migrations and cumulative reference
│   ├── engineering/     Standards, dated plans and design records
│   └── assets/          Editable brand art and documented product captures
├── Dockerfile           Complete HF-compatible Docker runtime
├── requirements*.txt    Python runtime, development and optional training inputs
├── package.json         Root web/backend convenience commands
└── pytest.ini           Backend test discovery
```

## Find a component

| Area | Starting point |
| --- | --- |
| Financial contracts and product read models | [backend/app/engine](../../backend/app/engine) |
| Evidence, risk, execution, learning and validation | [backend/app/services](../../backend/app/services) |
| Bounded source experiments | [backend/app/services/ascent](../../backend/app/services/ascent) |
| Product/runtime API boundaries | [backend/app/api/routers](../../backend/app/api/routers) |
| Model/data export boundary | [backend/app/analyst](../../backend/app/analyst) |
| Runtime scheduling and delivery contracts | [backend/app/runtime](../../backend/app/runtime) |
| Browser routes and views | [frontend/app](../../frontend/app) and [frontend/components](../../frontend/components) |
| Public read-route policy | [backend/app/data/public_api_routes.json](../../backend/app/data/public_api_routes.json) |
| Deployment and recovery commands | [Script catalog](../../scripts/README.md) |

## Placement rules

Keep a file beside the component that owns it. Component-specific tests live with that component; shared operational contracts currently live in `backend/tests`. The existing broad `services` namespace is retained for compatibility; moving those modules requires a separate import/API migration, rather than a cosmetic directory change.

Current documentation uses lowercase, hyphenated filenames and relative links. Use `README.md` for folder entry points. Root community files remain discoverable by GitHub. The product presentation lives in [.github/README.md](../../.github/README.md), which GitHub gives precedence on the repository homepage; the root [README.md](../../README.md) is the focused Hugging Face Space card and runtime introduction. These documents serve different audiences rather than duplicating a long product page. Root Docker and dependency manifests remain where existing tools expect them.

Write reusable instructions in guides. Put a dated implementation report in `reports`, a version-specific retired document in `archive`, and planning records in `engineering/plans` or `engineering/specs`. Link historical records to the current policy so earlier readiness language cannot be mistaken for current evidence. Never rewrite an audit JSON merely to match a new presentation.

## What stays out of Git

Dependencies, build output, local environment files, model caches, temporary workspaces, database files and operational backup artifacts do not belong in source control. Use approved persistent storage for private research artifacts and recovery files. `.gitattributes` retains the active LFS patterns for large artifacts; generated build-cache and local virtual-environment entries have been removed.

The [historical archive](../archive/README.md) maps the former root documents to their new locations. Git history preserves earlier paths and file revisions.

GitHub README selection follows the [official repository README documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes).
