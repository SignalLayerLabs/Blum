from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    BlumTradingPowerScore,
    DashboardSnapshot,
    LearningBenchmarkComparison,
    LearningRun,
    LearningStrengthWeaknessMap,
    TradingCapitalCycle,
    TradingGame,
    TradingGameTrade,
    TradingIntelligenceMetric,
    TradeLearningEvidence,
)
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.learning_summary import LearningSummaryService, build_truth_panel, safe_progress, summarize_benchmarks


def test_safe_progress_handles_partial_data():
    assert safe_progress(None, 10000) is None
    assert safe_progress(50, 100) == 0.5
    assert safe_progress(200, 100) == 1


def test_summarize_benchmarks_returns_partial_status():
    payload = summarize_benchmarks([])
    assert payload["status"] == "initializing"
    assert payload["major_benchmarks"]["SPY"]["result_label"] == "insufficient_sample"


def test_truth_panel_is_honest_when_power_missing():
    rows = build_truth_panel(None, summarize_benchmarks([]), ["No benchmark summary."], [])
    assert rows[0].startswith("Not enough precomputed evidence")
    assert any("No benchmark summary" in row for row in rows)


def test_learning_summary_returns_partial_payload_without_precomputed_rows():
    engine = create_engine("sqlite:///:memory:", future=True)
    for model in [
        BlumTradingPowerScore,
        DashboardSnapshot,
        LearningBenchmarkComparison,
        LearningRun,
        LearningStrengthWeaknessMap,
        TradingCapitalCycle,
        TradingGame,
        TradingGameTrade,
        TradingIntelligenceMetric,
        TradeLearningEvidence,
    ]:
        model.__table__.create(bind=engine)

    with Session(engine) as db:
        payload = LearningSummaryService().summary(db)

    assert payload["status"] == "initializing"
    assert "trading_power_score" in payload["missing_sections"]
    assert "trading_intelligence_metrics" in payload["missing_sections"]
    assert payload["backend_training_status"]["frontend_policy"] == "read_only_snapshot_observer"
    assert "snapshots" in payload
    assert payload["truth_panel"][0].startswith("Not enough precomputed evidence")


def test_dashboard_snapshot_round_trip_and_stale_flag():
    engine = create_engine("sqlite:///:memory:", future=True)
    DashboardSnapshot.__table__.create(bind=engine)
    service = DashboardSnapshotService()
    with Session(engine) as db:
        written = service.write(db, "learning_summary", {"status": "ready"}, ttl_seconds=1)
        assert written["status"] == "ready"
        latest = service.latest(db, "learning_summary")
        assert latest["payload"]["status"] == "ready"
        row = db.get(DashboardSnapshot, 1)
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        stale = service.latest(db, "learning_summary")
        assert stale["status"] == "stale"




def test_deep_diagnostics_uses_human_readable_renderer_not_raw_json_dump():
    page = Path(__file__).resolve().parents[2] / "frontend" / "components" / "DiagnosticPanelRenderer.tsx"
    text = page.read_text()

    assert "compactPreview" not in text
    assert "JSON.stringify(compactPreview" not in text
    assert "DiagnosticPanelRenderer" in text
    assert "Show raw JSON" in text


def test_diagnostic_panel_renderer_hides_raw_json_by_default():
    renderer = Path(__file__).resolve().parents[2] / "frontend" / "components" / "DiagnosticPanelRenderer.tsx"
    text = renderer.read_text()

    assert "export function DiagnosticPanelRenderer" in text
    assert "function ReliabilityByRegimeRenderer" in text
    assert "function EnsembleStatusRenderer" in text
    assert "export function SampleSizeWarning" in text
    assert "export function WeightDistributionTable" in text
    assert "Show raw JSON" in text
    assert "Hide raw JSON" in text
    assert "open && <pre" in text


def test_diagnostic_renderer_exposes_evidence_warnings_and_tables():
    renderer = Path(__file__).resolve().parents[2] / "frontend" / "components" / "DiagnosticPanelRenderer.tsx"
    text = renderer.read_text()

    assert "Small sample size: treat as weak evidence." in text
    assert "Reliability is promising but not durable without more samples." in text
    assert "Negative average return with positive excess return needs review." in text
    assert "DiagnosticTable" in text
    assert "Engine" in text
    assert "Hit Rate" in text
    assert "Excess vs Benchmark" in text
    assert "Confidence Penalty" in text


def test_frontend_blocks_heavy_learning_post_during_initial_render():
    api_file = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "api.ts"
    text = api_file.read_text()

    assert "blocked_heavy_frontend_recalculation" in text
    assert "LEARNING_INITIAL_RENDER_GUARD_MS" in text
    assert '"/api/capital-allocation/recalculate"' in text
    assert '"/api/alpha-recovery/recalculate"' in text
    assert '"/api/meta-cognition/recalculate"' in text
