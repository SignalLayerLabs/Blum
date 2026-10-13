FROM node:20-bookworm-slim AS frontend
WORKDIR /workspace/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    NEXT_TELEMETRY_DISABLED=1 \
    TOKENIZERS_PARALLELISM=false \
    PAPER_FORWARD_LIFECYCLE_ENABLED=true \
    PAPER_FORWARD_MAX_HOLDING_DAYS=10 \
    BLUM_SEED_HISTORICAL_PRICES_ON_STARTUP=false \
    BLUM_SEED_SIGNALS_ON_STARTUP=false \
    BLUM_SEED_ACCURACY_ON_STARTUP=false \
    PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gcc \
    g++ \
    git \
    libpq-dev \
    postgresql \
    postgresql-contrib \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --no-deps \
    "git+https://github.com/AI4Finance-Foundation/FinRL-Trading.git@e65d6f0483ead7d2ef4a5fc940cdf960392a25c1"

COPY backend ./backend
COPY scripts ./scripts
ARG BLUM_SOURCE_REVISION=unavailable
RUN python -c 'import json,os; from pathlib import Path; Path("backend/app/data/build_revision.json").write_text(json.dumps({"source_revision":os.environ.get("BLUM_SOURCE_REVISION","unavailable")}))'
COPY --from=frontend /workspace/frontend/out ./backend/app/static

ENV BLUM_FINRLX_ENABLED=true \
    BLUM_FINRLX_RUNNER_COMMAND=/app/scripts/finrlx_runner.py \
    BLUM_FINRLX_ARTIFACT_ROOT=/data/trading_ml/finrlx \
    BLUM_FOREX_HISTORY_ENABLED=false \
    BLUM_FOREX_HISTORY_SOURCE_PATH=/app/backend/app/data/forex/Forex_sample_dataset.csv \
    BLUM_NAUTILUS_ENABLED=true \
    BLUM_NAUTILUS_MODE=shadow \
    BLUM_NAUTILUS_ASSET_CLASSES=equity,etf,forex \
    BLUM_NAUTILUS_CRYPTO_ENABLED=false \
    BLUM_NAUTILUS_CATALOG_PATH=/data/blum/nautilus/catalog

RUN chmod +x /app/scripts/start.sh /app/scripts/finrlx_runner.py

EXPOSE 7860
CMD ["/app/scripts/start.sh"]
