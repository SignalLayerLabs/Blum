# Develop BLUM

[Documentation](../README.md) · [Repository map](../architecture/repository-map.md) · [Contributing](../../CONTRIBUTING.md)

Run the following commands from the repository root unless a working directory is stated. CI uses Python 3.12 and Node.js 24. The Docker frontend build currently uses Node.js 20; these are existing environment contracts, not an instruction to upgrade dependencies during a documentation change.

## Python engine and API

Configure a PostgreSQL database and a private `DATABASE_URL` before running migrations or starting the API. The local default is `postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/blum`; the `blum` database and role must already exist when running outside Docker. Protect non-disposable credentials in your environment.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt
(cd backend && PYTHONPATH=. alembic -c alembic.ini upgrade head)
PYTHONPATH=backend uvicorn app.main:app --host 127.0.0.1 --port 7860
```

FastAPI serves API documentation at [localhost:7860/docs](http://localhost:7860/docs). Running Uvicorn directly does not build the web UI or start embedded PostgreSQL; the Docker entrypoint performs those complete-runtime steps.

```bash
PYTHONPATH=backend python -m pytest -q --tb=short
PYTHONPATH=backend python scripts/audit_historical_sources.py --check
python scripts/check_space_metadata.py
```

The default pytest configuration discovers `backend/tests`. Run the separately packaged model tooling tests explicitly when changing that component:

```bash
PYTHONPATH=model_release python -m pytest -q model_release/tests
```

Its optional test/release/inference dependencies are declared in [model_release/pyproject.toml](../../model_release/pyproject.toml); install the extras needed for the affected tests.

## Web product

```bash
npm ci --prefix frontend --workspaces=false
NEXT_PUBLIC_API_BASE=http://127.0.0.1:7860 npm --prefix frontend run dev
```

Open [localhost:3000](http://localhost:3000). The API base is explicit because the development server runs on a different port. For production, keep `NEXT_PUBLIC_API_BASE` empty to use the same-origin gateway. Public environment values are embedded in browser assets; never place secrets there.

```bash
npm --prefix frontend test
cd frontend
npx tsc --noEmit
cd ..
npm --prefix frontend run build
```

The static export is generated under `frontend/out`; generated assets and dependencies stay untracked.

## Cloudflare gateway

Build the frontend first, then:

```bash
npm ci --prefix cloudflare
npm --prefix cloudflare test
npm --prefix cloudflare run types
npm --prefix cloudflare run typecheck
npm --prefix cloudflare run preview
```

The default upstream in Wrangler configuration is the public HF origin. Review `BACKEND_ORIGIN` before using a different HTTPS origin. A local gateway preview serves the static product and existing reviewed read routes; it is not a second financial engine. Publication requires the existing deployment credentials and the [verified release procedure](../operations/deployment.md).

## Change the right boundary

- Financial evidence, risk and accounting belong to the engine/services boundary.
- Product endpoints use bounded routers and facades; new work does not extend the legacy router.
- Product page reads stay read-only and consume stored snapshots.
- Data changes require provenance, license review, point-in-time rules and acceptance-policy review.
- Keep exact source revision, protected-content hash and runtime readiness distinct.

[Verify BLUM](../../.github/workflows/ci.yml) runs the backend contracts, data audit, frontend checks and gateway checks. A passing PR does not itself publish a deployment. Main verification can trigger the existing production workflow; coordinate a fresh recovery checkpoint before any runtime restart.
