"""Execute the deployed verifier against a public rollout that settles later."""
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from app.core.release import source_content_hash


SCRIPT = Path(__file__).parents[2] / "scripts/verify_deployment.py"
REVISION = "a" * 40


class Response(io.BytesIO):
    status = 200

    def __init__(self, value, content_type="application/json"):
        super().__init__(json.dumps(value).encode() if content_type == "application/json" else b"<html></html>")
        self.headers = {"Content-Type": content_type}


def run_verifier(monkeypatch, failures, backend_only=False):
    clock = [0]
    calls = {"public_readiness": 0, "snapshots": 0, "sleep": []}

    def sleep(seconds):
        calls["sleep"].append(seconds)
        clock[0] += seconds

    def urlopen(request, timeout):
        url = request.full_url
        if url.endswith("/startup/status"):
            return Response({"api_ready": True, "ui_ready": True, "last_error": ""})
        if url.endswith("/api/runtime/release"):
            return Response({"source_revision": REVISION, "version": "2.3.0", "source_content_hash": source_content_hash()})
        if url.endswith("/api/release"):
            calls["public_readiness"] += 1
            if calls["public_readiness"] <= failures:
                raise urllib.error.HTTPError(url, 503, "rollout", {}, None)
            return Response({"source_revision": REVISION, "source_content_hash": source_content_hash(), "backend_ready": True})
        if request.get_method() == "POST":
            raise urllib.error.HTTPError(url, 405, "read only", {}, None)
        if "/api/" in url:
            calls["snapshots"] += 1
            return Response({})
        return Response({}, "text/html")

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(time, "sleep", sleep)
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: REVISION + "\n")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--timeout", "35"] + (["--backend-only"] if backend_only else []))
    monkeypatch.setattr(sys, "path", list(sys.path))
    return calls


def test_public_rollout_polls_before_verifying_product_snapshots(monkeypatch):
    calls = run_verifier(monkeypatch, failures=2)
    runpy.run_path(str(SCRIPT), run_name="__main__")
    assert calls == {"public_readiness": 3, "snapshots": 6, "sleep": [10, 10]}


def test_persistent_public_failure_still_exits_nonzero_at_readiness_deadline(monkeypatch):
    calls = run_verifier(monkeypatch, failures=100)
    with pytest.raises(SystemExit, match="verification failed") as error:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert error.value.code != 0
    assert calls["public_readiness"] == 4
    assert calls["snapshots"] == 0


def test_backend_only_readiness_does_not_probe_cloudflare(monkeypatch):
    calls = run_verifier(monkeypatch, failures=100, backend_only=True)
    runpy.run_path(str(SCRIPT), run_name="__main__")
    assert calls == {"public_readiness": 0, "snapshots": 0, "sleep": []}
