from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import (
    alpha_router,
    analyst_router,
    brain_router,
    copy_readiness_router,
    legacy_router,
    paper_trading_router,
    runtime_router,
    training_router,
    forex_trader_router,
)
from app.core.config import get_settings
from app.api.routers.ascent import router as ascent_router
from app.core.database import SessionLocal
from app.services.bootstrap import bootstrap_database
from app.services.performance import performance_recorder
from app.services.realtime import start_realtime_services, stop_realtime_services


settings = get_settings()

app = FastAPI(
    title="Blum AI Financial Intelligence API",
    version=settings.app_version,
    description=(
        "Open-source AI financial intelligence backend for equities, ETFs, "
        "semantic news analysis, filing intelligence, Market Brain orchestration, "
        "signal scoring, explainability and validation."
    ),
)

origins = ["*"] if settings.cors_origins == "*" else [item.strip() for item in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def include_legacy_router_without_duplicate_operations(
    application: FastAPI,
    source_router: APIRouter,
) -> None:
    """Keep legacy API coverage without shadowing modular route handlers."""

    existing = {
        (route.path, frozenset(route.methods or set()))
        for route in application.routes
        if hasattr(route, "methods")
    }
    filtered = APIRouter()
    for route in source_router.routes:
        key = (route.path, frozenset(route.methods or set()))
        if key in existing:
            continue
        filtered.routes.append(route)
        existing.add(key)
    application.include_router(filtered)


app.include_router(brain_router)
app.include_router(copy_readiness_router)
app.include_router(training_router)
app.include_router(paper_trading_router)
app.include_router(alpha_router)
app.include_router(runtime_router)
app.include_router(analyst_router)
app.include_router(ascent_router)
include_legacy_router_without_duplicate_operations(app, legacy_router)
app.include_router(forex_trader_router)


@app.middleware("http")
async def performance_timing_middleware(request: Request, call_next):
    started_at = datetime.utcnow()
    started = time.perf_counter()
    status_code = 500
    response = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        duration_ms = (time.perf_counter() - started) * 1000
        budget = endpoint_budget_ms(request.method, request.url.path)
        if duration_ms > budget:
            response.headers["X-BLUM-SLOW-ENDPOINT"] = "true"
            response.headers["X-BLUM-PERFORMANCE-BUDGET-MS"] = str(int(budget))
            performance_recorder.record_dashboard_widget(
                "performance.slow_endpoint_budget",
                duration_ms,
                {"method": request.method, "path": request.url.path, "budget_ms": budget},
            )
        if is_heavy_recalculation_call(request.method, request.url.path) and "/learning" in request.headers.get("referer", ""):
            response.headers["X-BLUM-HEAVY-RECALCULATION-DURING-PAGE-LOAD"] = "true"
            performance_recorder.record_dashboard_widget(
                "performance.heavy_recalculation_triggered_during_page_load",
                duration_ms,
                {"method": request.method, "path": request.url.path, "referer": request.headers.get("referer", "")[:180]},
            )
        if request.method.upper() == "GET" and "persist=true" in request.url.query.lower():
            response.headers["X-BLUM-GET-SIDE-EFFECT-RISK"] = "true"
            performance_recorder.record_dashboard_widget(
                "performance.GET_ENDPOINT_SIDE_EFFECT_DETECTED",
                duration_ms,
                {"method": request.method, "path": request.url.path, "query": request.url.query[:180]},
            )
        return response
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        client = request.client.host if request.client else ""
        performance_recorder.record_api_request(
            method=request.method,
            path=request.url.path,
            query_string=request.url.query,
            status_code=status_code,
            duration_ms=duration_ms,
            started_at=started_at,
            client=client,
        )


def endpoint_budget_ms(method: str, path: str) -> float:
    if method.upper() != "GET":
        return 3000.0
    if path == "/api/learning-intelligence/summary":
        return 300.0
    if path in {"/dashboard/overview", "/api/trading-game/status", "/api/trading-game/cycles/current", "/api/learning-intelligence/trading-power"}:
        return 1000.0
    if path.startswith("/api/trading-game/ledger") or path.startswith("/learning/"):
        return 1500.0
    if path.startswith("/model/") or path.startswith("/api/decision-intelligence") or path.startswith("/api/business-quality") or path.startswith("/api/portfolio-intelligence"):
        return 3000.0
    return 1500.0


def is_heavy_recalculation_call(method: str, path: str) -> bool:
    if method.upper() != "POST":
        return False
    heavy_fragments = (
        "/recalculate",
        "/universe-snapshots/recalculate",
        "/portfolio-intelligence/recalculate",
        "/business-quality/recalculate",
        "/decision-intelligence/superiority/recalculate",
        "/learning-intelligence/self-improvement/generate",
        "/api/meta-cognition/recalculate",
        "/api/meta-cognition/factor-importance/recalculate",
        "/api/meta-cognition/evaluate",
        "/api/meta-cognition/capital-preservation/evaluate",
        "/api/meta-cognition/learning-focus/generate",
        "/api/meta-cognition/noise/detect",
        "/snapshots/produce",
    )
    return any(fragment in path for fragment in heavy_fragments)

STATIC_DIR = Path(__file__).parent / "static"
if (STATIC_DIR / "_next").exists():
    app.mount("/_next", StaticFiles(directory=STATIC_DIR / "_next"), name="next-static")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def startup() -> None:
    performance_recorder.mark_startup_begin()
    with performance_recorder.startup_phase("bootstrap_database"):
        with SessionLocal() as db:
            bootstrap_database(db)
    with performance_recorder.startup_phase("start_realtime_services"):
        start_realtime_services()
    performance_recorder.mark_startup_complete()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_realtime_services()


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    if not STATIC_DIR.exists():
        return {"message": "Frontend build not found. Run the Next.js build or use the API docs at /docs."}
    target = STATIC_DIR / full_path
    if target.is_file():
        return FileResponse(target)
    html_file = target / "index.html"
    if html_file.is_file():
        return FileResponse(html_file)
    return FileResponse(STATIC_DIR / "index.html")
