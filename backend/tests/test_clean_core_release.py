from pathlib import Path

from app.main import app


ROOT = Path(__file__).resolve().parents[1] / "app"


def first_endpoint_module(path: str) -> str:
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint.__module__
    raise AssertionError(f"Route not found: {path}")


def test_product_routes_are_served_by_bounded_routers_before_legacy_router():
    assert first_endpoint_module("/api/trader-brain/brain") == "app.api.routers.brain"
    assert first_endpoint_module("/api/trader-brain/training-ground") == "app.api.routers.training"
    assert first_endpoint_module("/api/trader-brain/paper-trading") == "app.api.routers.paper_trading"
    assert first_endpoint_module("/api/trader-brain/alpha") == "app.api.routers.alpha"


def test_no_api_operation_is_registered_twice():
    operations = [
        (route.path, method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    ]

    assert len(operations) == len(set(operations))


def test_product_routers_depend_on_engine_facade_not_low_level_services():
    for relative in [
        "api/routers/brain.py",
        "api/routers/training.py",
        "api/routers/paper_trading.py",
        "api/routers/alpha.py",
    ]:
        text = (ROOT / relative).read_text()
        assert "from app.engine.facade import BlumEngineFacade" in text
        assert "app.services" not in text


def test_trader_brain_read_model_was_physically_moved_into_engine():
    engine_file = ROOT / "engine" / "brain" / "trader_brain.py"
    legacy_file = ROOT / "services" / "trader_brain.py"

    assert engine_file.exists()
    assert "class TraderBrainService" in engine_file.read_text()
    assert "from app.engine.brain.trader_brain import *" in legacy_file.read_text()




def test_primary_app_shell_does_not_fetch_heavy_snapshots_on_startup():
    text = (ROOT.parents[1] / "frontend" / "components" / "AppShell.tsx").read_text()

    assert 'api.learningSummary()' not in text
    assert 'api.dashboardSnapshot("paper_forward_snapshot")' not in text
    assert 'api.traderAlpha()' not in text
