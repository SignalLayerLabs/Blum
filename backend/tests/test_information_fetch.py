from concurrent.futures import ThreadPoolExecutor
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import ssl
import subprocess
import threading
import time

import pytest

from app.services.information.fetch import PublicEvidenceFetcher


@pytest.fixture
def server(monkeypatch):
    import app.services.information.fetch as module

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.path, dict(self.headers)))
            path = self.path.split("?")[0]
            if path == "/slow":
                time.sleep(0.4)
            if path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1/secret")
                self.end_headers()
                return
            if path == "/rebind":
                self.send_response(302)
                self.send_header("Location", "/ok")
                self.end_headers()
                return
            if path == "/conditional" and self.headers.get("If-None-Match") == '"abc"':
                self.send_response(304)
                self.end_headers()
                return
            status = {"/quota": 429, "/denied": 403}.get(path, 200)
            body = "Inflazione · 日本語".encode()
            if path in {"/big", "/gzip"}:
                body = b"x" * (2 * 1024 * 1024 + 1)
            if path == "/gzip":
                body = gzip.compress(body)
            if path == "/empty":
                body = b""
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("ETag", '"abc"')
            self.send_header("Retry-After", "120")
            self.send_header("Set-Cookie", "private=do-not-store")
            if path == "/gzip":
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                if path == "/trickle":
                    for char in body:
                        self.wfile.write(bytes([char]))
                        self.wfile.flush()
                        time.sleep(0.03)
                    return
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    original = module.connection.create_connection
    destinations = []

    def routed(address, *args, **kwargs):
        destinations.append(address)
        assert (
            address[0] == "93.184.216.34"
        ), "transport must use the validated IP, not resolve the host again"
        return original(("127.0.0.1", srv.server_port), *args, **kwargs)

    monkeypatch.setattr(module.connection, "create_connection", routed)
    monkeypatch.setattr(
        module, "resolve_addresses", lambda host, port: ("93.184.216.34",)
    )
    yield requests, destinations
    srv.shutdown()
    srv.server_close()


def fetch(path, **kwargs):
    return PublicEvidenceFetcher().fetch(
        "http://example.test" + path, deadline=time.monotonic() + 2, **kwargs
    )


def test_information_fetch_utf8_conditional_request_and_header_allowlist(server):
    first = fetch("/ok")
    assert first.status == "AVAILABLE" and first.body.decode() == "Inflazione · 日本語"
    assert first.headers["etag"] == '"abc"' and "set-cookie" not in first.headers
    cached = fetch("/conditional", etag='"abc"')
    assert cached.status == "NOT_MODIFIED" and cached.body == b""
    assert server[0][-1][1]["Host"] == "example.test"


@pytest.mark.parametrize(
    "path,status,code",
    [
        ("/denied", "UNAVAILABLE", "HTTP_403"),
        ("/quota", "QUOTA_LIMITED", "HTTP_429"),
        ("/big", "UNAVAILABLE", "BODY_TOO_LARGE"),
        ("/gzip", "UNAVAILABLE", "BODY_TOO_LARGE"),
        ("/redirect", "UNAVAILABLE", "NON_PUBLIC_DESTINATION"),
    ],
)
def test_information_fetch_failures_are_explicit_and_bounded(
    server, path, status, code
):
    result = fetch(path)
    assert result.status == status and result.error_code == code and result.body == b""


def test_information_fetch_retry_after_and_empty(server):
    result = fetch("/quota")
    assert (result.retry_at - result.observed_at).total_seconds() >= 119
    assert fetch("/empty").body == b""


def test_information_fetch_dns_rebinding_is_revalidated_before_each_redirect(
    server, monkeypatch
):
    import app.services.information.fetch as module

    answers = iter([("93.184.216.34",), ("127.0.0.1",)])
    monkeypatch.setattr(module, "resolve_addresses", lambda host, port: next(answers))
    result = fetch("/rebind")
    assert result.error_code == "NON_PUBLIC_DESTINATION"
    assert len(server[1]) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/",
        "http://[::ffff:127.0.0.1]/",
        "file:///etc/passwd",
        "http://u:p@example.org/",
        "http://example.org:22/",
    ],
)
def test_information_fetch_rejects_non_public_and_credential_destinations(url):
    result = PublicEvidenceFetcher().fetch(url, deadline=time.monotonic() + 1)
    assert result.status == "UNAVAILABLE" and result.body == b""


def test_information_fetch_deadline_covers_slow_headers(server):
    start = time.monotonic()
    result = PublicEvidenceFetcher().fetch(
        "http://example.test/slow", deadline=start + 0.1
    )
    assert result.error_code == "DEADLINE_EXCEEDED"
    assert time.monotonic() - start < 0.35


def test_information_fetch_never_retains_query_secrets(server):
    result = fetch("/ok?api_key=private-value&series_id=DGS10")
    assert "private-value" not in result.final_url and "DGS10" in result.final_url


def test_information_fetch_deadline_interrupts_body_trickle(server):
    start = time.monotonic()
    result = PublicEvidenceFetcher().fetch(
        "http://example.test/trickle", deadline=start + 0.12
    )
    assert result.error_code == "DEADLINE_EXCEEDED" and result.body == b""
    assert time.monotonic() - start < 0.35


@pytest.mark.parametrize("url", ["http://u:p@127.0.0.1/", "http://[broken/"])
def test_information_fetch_invalid_url_cannot_escape_error_or_leak_credentials(url):
    result = PublicEvidenceFetcher().fetch(url, deadline=time.monotonic() + 1)
    assert result.status == "UNAVAILABLE" and "u:p" not in result.final_url


def test_information_pinned_https_preserves_sni_and_verifies_original_hostname(
    tmp_path, monkeypatch
):
    import app.services.information.fetch as module
    import requests.adapters

    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    generated = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=example.test",
            "-addext",
            "subjectAltName=DNS:example.test",
        ],
        capture_output=True,
        timeout=10,
    )
    assert generated.returncode == 0, generated.stderr.decode()
    seen_sni = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"verified")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    context.set_servername_callback(lambda sock, name, ctx: seen_sni.append(name))
    srv.socket = context.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    original = module.connection.create_connection
    errors = []
    original_send = module._PinnedAdapter.send

    def diagnostic_send(self, *args, **kwargs):
        try:
            return original_send(self, *args, **kwargs)
        except Exception as exc:
            errors.append(
                str(exc)
            )  # Fixture URLs and generated local certificate only.
            raise

    monkeypatch.setattr(module._PinnedAdapter, "send", diagnostic_send)
    monkeypatch.setattr(
        module.connection,
        "create_connection",
        lambda addr, *a, **kw: original(("127.0.0.1", srv.server_port), *a, **kw),
    )
    monkeypatch.setattr(
        module, "resolve_addresses", lambda host, port: ("93.184.216.34",)
    )
    monkeypatch.setattr(module.requests.certs, "where", lambda: str(cert))
    try:
        valid = PublicEvidenceFetcher().fetch(
            "https://example.test/", deadline=time.monotonic() + 2
        )
        wrong = PublicEvidenceFetcher().fetch(
            "https://wrong.test/", deadline=time.monotonic() + 2
        )
        assert valid.body == b"verified" and valid.status == "AVAILABLE", errors
        assert "example.test" in seen_sni
        assert wrong.status == "UNAVAILABLE" and wrong.error_code == "REQUEST_FAILED"
    finally:
        srv.shutdown()
        srv.server_close()


def test_information_fetch_connect_timeout_does_not_claim_total_budget_exhausted(
    server, monkeypatch
):
    import app.services.information.fetch as module

    def timeout(*args, **kwargs):
        raise module.requests.ConnectTimeout()

    monkeypatch.setattr(module._PinnedAdapter, "send", timeout)
    result = fetch("/ok")
    assert result.status == "UNAVAILABLE" and result.error_code == "REQUEST_TIMEOUT"
