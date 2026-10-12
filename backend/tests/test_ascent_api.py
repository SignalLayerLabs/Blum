from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routers.ascent import router
from app.core.database import Base, get_db
from app.models import AscentGeneration


@pytest.fixture
def client(monkeypatch, tmp_path):
    import app.api.routers.ascent as module
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(ascent_enabled=True, ascent_admin_key="test-only"))
    from app.services.ascent.engine import AscentEvolutionEngine
    monkeypatch.setattr(module, "AscentEvolutionEngine", lambda: AscentEvolutionEngine(
        artifact_root=tmp_path, enabled=True, source_revision="a" * 40))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    with Session(engine) as db:
        app.dependency_overrides[get_db] = lambda: db
        yield TestClient(app), db


def test_observatory_get_is_read_only_with_honest_empty_state(client):
    browser, db = client
    result = browser.get("/api/ascent/status")
    assert result.status_code == 200
    assert result.json()["status"] == "NO_EXPERIMENTS"
    assert result.json()["training_triggered"] is False
    assert not db.scalars(select(AscentGeneration)).all()


@pytest.mark.parametrize("headers", [{}, {"X-BLUM-Admin-Key": "wrong"}])
def test_unauthorized_run_is_blocked_before_evidence_or_workspace_mutation(client, headers):
    browser, db = client
    response = browser.post("/api/ascent/run", json={}, headers=headers)
    assert response.status_code == 403
    assert not db.scalars(select(AscentGeneration)).all()


def test_empty_admin_configuration_never_authorizes_an_empty_key(client, monkeypatch):
    import app.api.routers.ascent as module
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(ascent_enabled=True, ascent_admin_key=""))
    assert client[0].post("/api/ascent/run", json={}, headers={"X-BLUM-Admin-Key": ""}).status_code == 403


def test_authenticated_run_records_missing_evidence_without_fake_metrics(client):
    response = client[0].post("/api/ascent/run", json={}, headers={"X-BLUM-Admin-Key": "test-only"})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "BLOCKED"
    assert result["production_eligible"] is False
    assert "candidate" not in result
    assert client[0].get("/api/ascent/status").json()["generations"][0]["status"] == "BLOCKED"


def test_api_rejects_arbitrary_code_budget_overrides_and_promotion_requests(client):
    browser, _ = client
    headers = {"X-BLUM-Admin-Key": "test-only"}
    assert browser.post("/api/ascent/run", json={"source": "import os"}, headers=headers).status_code == 422
    assert browser.post("/api/ascent/run", json={"max_candidates": 9999}, headers=headers).status_code == 422
    assert browser.post("/api/ascent/promote/anything", headers=headers).status_code == 404
