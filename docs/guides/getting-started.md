# Run BLUM

[Documentation](../README.md) · [Development](development.md) · [Operations](../operations/deployment.md)

## Explore without installing

Open the [public observatory](https://blum.signallayerlabs.workers.dev). Its five workspaces expose stored research snapshots and paper evidence. Public page loads do not start research or execution. An unavailable panel is reported explicitly; it is not filled with synthetic results.

## Start the complete Docker runtime

Install Git, Git LFS and Docker. Run from a new checkout:

```bash
git clone https://github.com/SignalLayerLabs/Blum.git
cd Blum
git lfs pull
docker build -t blum --build-arg BLUM_SOURCE_REVISION=$(git rev-parse HEAD) .
docker run --rm -p 7860:7860 blum
```

Visit [localhost:7860](http://localhost:7860). The multi-stage image builds the Next.js static product and installs the Python/CPU ML runtime. No paid GPU job is needed. The first build may be substantial; startup and research readiness are separate stages.

```bash
curl -fsS http://localhost:7860/startup/status
curl -fsS http://localhost:7860/health
curl -fsS http://localhost:7860/api/runtime/release
```

Use the startup response to distinguish restore, API readiness and UI readiness. A successful HTML response alone does not prove the financial runtime is ready. A new installation may show missing evidence until actual data is collected; bundled history is not a prospective track record.

## Retain research data

The command above creates a disposable container. Without `DATABASE_URL`, the entrypoint starts embedded PostgreSQL on the container's local disk. A `/data` volume preserves periodic recovery files and artifacts, rather than every committed database transaction:

```bash
docker volume create blum-data
docker run --rm -p 7860:7860 -v blum-data:/data blum
```

Recovery can lose writes after the most recent usable checkpoint. Do not run multiple containers against the same embedded recovery volume. For durable operation or multiple replicas, configure an external PostgreSQL database and verify its backup/recovery policy. Put its SQLAlchemy `postgresql+psycopg2://` URL in a private `.env` file, then pass it explicitly:

```bash
docker run --rm -p 7860:7860 --env-file .env -v blum-data:/data blum
```

The external database must be reachable from the container; `127.0.0.1` inside Docker refers to that container. Never commit the environment file. [Deployment and recovery details](../operations/deployment.md).

## Configure research deliberately

Fresh installations leave ASCENT disabled by default. Paid HF training, automatic training launch and automatic dataset publication should stay disabled while the source quarantine applies. Optional model loading and provider access depend on the configured environment. The deterministic engine owns risk and paper execution; a model is advisory.

Use the [ASCENT guide](../research/ascent.md) for its bounded scheduler and trusted CLI. Use the [data policy](../research/data-quality.md) before importing history or preparing training exports. No setup step establishes alpha or enables broker execution.

## Troubleshoot the right layer

| Symptom | Check |
| --- | --- |
| Build cannot find large historical files | Install Git LFS and run `git lfs pull` |
| Startup remains in restore | Inspect container logs and `/startup/status`; preserve recovery files |
| Database connection fails | Verify `DATABASE_URL`, container networking and PostgreSQL access |
| UI loads but evidence is absent | Check API readiness, source availability and the relevant evidence gates |
| Model unavailable on local hardware | Inspect model state and configured loading policy; do not substitute fabricated evidence |

For reproducible defects, follow the [support guide](../../SUPPORT.md) with the revision and non-sensitive logs.
