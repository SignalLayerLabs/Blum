"""Bounded public retrieval with validated IP pinning and original TLS identity."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import ipaddress
import socket
import ssl
import threading
import time
from types import MappingProxyType
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import zlib

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.util import connection
from urllib3.exceptions import HTTPError as UrllibHTTPError

from app.services.market_clock import utc_naive

MAX_BYTES = 2 * 1024 * 1024
_HOST_LOCKS = [threading.Lock() for _ in range(64)]
_DNS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="evidence-dns")
_DNS_SLOTS = threading.BoundedSemaphore(2)


def resolve_addresses(host, port):
    return tuple(
        {
            answer[4][0]
            for answer in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }
    )


def is_public(address):
    ip = ipaddress.ip_address(address)
    return (
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_unspecified
        and (not getattr(ip, "ipv4_mapped", None) or is_public(str(ip.ipv4_mapped)))
    )


def public_target(url, deadline):
    p = urlsplit(url)
    if (
        len(url) > 4096
        or p.scheme not in {"http", "https"}
        or not p.hostname
        or p.username
        or p.password
    ):
        raise ValueError("INVALID_DESTINATION")
    host = p.hostname.encode("idna").decode("ascii").lower()
    if (
        "%" in host
        or host == "localhost"
        or host.endswith((".localhost", ".local", ".internal"))
    ):
        raise ValueError("NON_PUBLIC_DESTINATION")
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("INVALID_PORT")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _DNS_SLOTS.acquire(timeout=max(0, deadline - time.monotonic())):
            raise TimeoutError()
        future = _DNS.submit(resolve_addresses, host, port)
        future.add_done_callback(lambda _: _DNS_SLOTS.release())
        try:
            addresses = future.result(timeout=max(0, deadline - time.monotonic()))
        except FutureTimeout as exc:
            raise TimeoutError() from exc
    else:
        addresses = (host,)
    if not addresses or not all(is_public(ip) for ip in addresses):
        raise ValueError("NON_PUBLIC_DESTINATION")
    return p, host, port, sorted(addresses)[0]


class _PinnedDeadline:
    def __init__(self, *args, pinned_ip, budget_deadline, tracker, **kwargs):
        self.pinned_ip, self.budget_deadline, self.tracker = (
            pinned_ip,
            budget_deadline,
            tracker,
        )
        self.abort_timer = None
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        remaining = self.budget_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        sock = connection.create_connection(
            (self.pinned_ip, self.port),
            timeout=min(remaining, self.timeout),
            source_address=self.source_address,
            socket_options=self.socket_options,
        )

        # A deadline must also interrupt slow header/body trickles, not merely an
        # individual read. TLS keeps the original host/SNI; only TCP is IP-pinned.
        def abort():
            current = self.sock or sock
            try:
                current.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            current.close()

        self.abort_timer = threading.Timer(
            max(0, self.budget_deadline - time.monotonic()), abort
        )
        self.abort_timer.daemon = True
        self.abort_timer.start()
        self.tracker.append(self)
        return sock


class _PinnedHTTP(_PinnedDeadline, HTTPConnection):
    pass


class _PinnedHTTPS(_PinnedDeadline, HTTPSConnection):
    pass


class _PinnedAdapter(HTTPAdapter):
    def __init__(self, *, scheme, host, port, ip, deadline):
        super().__init__(max_retries=0)
        self.connections = []
        pool_cls = HTTPSConnectionPool if scheme == "https" else HTTPConnectionPool
        tls = (
            {
                "ssl_context": ssl.create_default_context(
                    cafile=requests.certs.where()
                ),
                "assert_hostname": host,
                "cert_reqs": "CERT_REQUIRED",
            }
            if scheme == "https"
            else {}
        )
        self.pool = pool_cls(
            host,
            port,
            maxsize=1,
            block=True,
            retries=False,
            pinned_ip=ip,
            budget_deadline=deadline,
            tracker=self.connections,
            **tls,
        )
        self.pool.ConnectionCls = _PinnedHTTPS if scheme == "https" else _PinnedHTTP

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        return self.pool

    def get_connection(self, url, proxies=None):
        return self.pool

    def close(self):
        for conn in self.connections:
            if conn.abort_timer:
                conn.abort_timer.cancel()
            conn.close()
        self.pool.close()
        super().close()


def safe_url(url):
    try:
        p = urlsplit(url)
    except ValueError:
        return ""
    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower()
        not in {"api_key", "apikey", "token", "key", "access_token", "signature"}
    ]
    return urlunsplit(
        (p.scheme, p.netloc.rsplit("@", 1)[-1], p.path, urlencode(query), "")
    )


@dataclass(frozen=True)
class FetchResult:
    status: str
    body: bytes = b""
    content_type: str = ""
    final_url: str = ""
    headers: dict = field(default_factory=dict)
    observed_at: datetime = field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    http_status: int | None = None
    error_code: str | None = None
    retry_at: datetime | None = None

    def __post_init__(self):
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


class PublicEvidenceFetcher:
    def __init__(self, *, user_agent="Blum-Public-Evidence/1.0"):
        if len(user_agent) > 250 or "\r" in user_agent or "\n" in user_agent:
            raise ValueError("Invalid public source user agent")
        self.user_agent = user_agent

    def fetch(
        self, url: str, *, deadline: float, etag: str | None = None
    ) -> FetchResult:
        deadline = min(deadline, time.monotonic() + 10)
        current = url
        response_code = None
        try:
            for redirect in range(4):
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                parts, host, port, ip = public_target(current, deadline)
                lock = _HOST_LOCKS[hash(host) % len(_HOST_LOCKS)]
                if not lock.acquire(timeout=max(0, deadline - time.monotonic())):
                    raise TimeoutError()
                try:
                    with requests.Session() as session:
                        session.trust_env = (
                            False  # No proxy can re-resolve/bypass destination checks.
                        )
                        adapter = _PinnedAdapter(
                            scheme=parts.scheme,
                            host=host,
                            port=port,
                            ip=ip,
                            deadline=deadline,
                        )
                        session.mount(parts.scheme + "://", adapter)
                        headers = {
                            "User-Agent": self.user_agent,
                            "Accept-Encoding": "gzip",
                        }
                        if etag:
                            if len(etag) > 1024 or "\r" in etag or "\n" in etag:
                                raise ValueError("INVALID_ETAG")
                            headers["If-None-Match"] = etag
                        remaining = max(0.001, deadline - time.monotonic())
                        with session.get(
                            current,
                            headers=headers,
                            timeout=(min(3, remaining), remaining),
                            stream=True,
                            allow_redirects=False,
                        ) as response:
                            response_code = response.status_code
                            metadata = {
                                k.lower(): str(v)[:4096]
                                for k, v in response.headers.items()
                                if k.lower()
                                in {
                                    "etag",
                                    "last-modified",
                                    "retry-after",
                                    "cache-control",
                                }
                            }
                            if response_code in {301, 302, 303, 307, 308}:
                                if redirect == 3 or not response.headers.get(
                                    "Location"
                                ):
                                    raise ValueError("REDIRECT_LIMIT")
                                destination = urljoin(
                                    current, response.headers["Location"]
                                )
                                if (
                                    parts.scheme == "https"
                                    and urlsplit(destination).scheme != "https"
                                ):
                                    raise ValueError("INSECURE_REDIRECT")
                                current = destination
                                continue
                            now = datetime.now(UTC).replace(tzinfo=None)
                            content_type = (
                                response.headers.get("Content-Type", "")
                                .split(";")[0]
                                .lower()
                                .strip()
                            )
                            common = {
                                "content_type": content_type,
                                "final_url": safe_url(current),
                                "headers": metadata,
                                "observed_at": now,
                                "http_status": response_code,
                            }
                            if response_code == 304:
                                return FetchResult("NOT_MODIFIED", **common)
                            if response_code != 200:
                                retry = (
                                    self._retry_at(metadata.get("retry-after"), now)
                                    if response_code in {429, 503}
                                    else None
                                )
                                return FetchResult(
                                    (
                                        "QUOTA_LIMITED"
                                        if response_code == 429
                                        else "UNAVAILABLE"
                                    ),
                                    error_code=f"HTTP_{response_code}",
                                    retry_at=retry,
                                    **common,
                                )
                            if content_type not in {
                                "text/plain",
                                "text/html",
                                "text/xml",
                                "application/xml",
                                "application/rss+xml",
                                "application/atom+xml",
                                "application/json",
                                "text/csv",
                                "application/csv",
                            }:
                                raise ValueError("UNSUPPORTED_CONTENT_TYPE")
                            if (
                                int(response.headers.get("Content-Length", "0"))
                                > MAX_BYTES
                            ):
                                raise ValueError("BODY_TOO_LARGE")
                            encoding = response.headers.get(
                                "Content-Encoding", "identity"
                            ).lower()
                            if encoding not in {"gzip", "identity", ""}:
                                raise ValueError("UNSUPPORTED_ENCODING")
                            decoder = (
                                zlib.decompressobj(16 + zlib.MAX_WBITS)
                                if encoding == "gzip"
                                else None
                            )
                            output, wire_bytes = bytearray(), 0
                            while True:
                                if time.monotonic() >= deadline:
                                    raise TimeoutError()
                                chunk = response.raw.read1(
                                    16 * 1024, decode_content=False
                                )
                                if not chunk:
                                    break
                                wire_bytes += len(chunk)
                                if wire_bytes > MAX_BYTES:
                                    raise ValueError("BODY_TOO_LARGE")
                                decoded = (
                                    decoder.decompress(
                                        chunk, MAX_BYTES - len(output) + 1
                                    )
                                    if decoder
                                    else chunk
                                )
                                output.extend(decoded)
                                if len(output) > MAX_BYTES:
                                    raise ValueError("BODY_TOO_LARGE")
                            if decoder and (not decoder.eof or decoder.unused_data):
                                raise ValueError("INVALID_GZIP")
                            common["observed_at"] = datetime.now(UTC).replace(
                                tzinfo=None
                            )
                            return FetchResult(
                                "AVAILABLE", body=bytes(output), **common
                            )
                finally:
                    lock.release()
        except (TimeoutError, requests.Timeout):
            code = (
                "DEADLINE_EXCEEDED"
                if time.monotonic() >= deadline - 0.01
                else "REQUEST_TIMEOUT"
            )
        except ValueError as exc:
            code = (
                str(exc)
                if str(exc)
                in {
                    "NON_PUBLIC_DESTINATION",
                    "INVALID_DESTINATION",
                    "INVALID_PORT",
                    "INVALID_ETAG",
                    "REDIRECT_LIMIT",
                    "INSECURE_REDIRECT",
                    "UNSUPPORTED_CONTENT_TYPE",
                    "BODY_TOO_LARGE",
                    "UNSUPPORTED_ENCODING",
                    "INVALID_GZIP",
                }
                else "INVALID_RESPONSE"
            )
        except (OSError, requests.RequestException, UrllibHTTPError, zlib.error):
            code = (
                "DEADLINE_EXCEEDED"
                if time.monotonic() >= deadline - 0.01
                else "REQUEST_FAILED"
            )
        return FetchResult(
            "UNAVAILABLE",
            final_url=safe_url(current),
            http_status=response_code,
            error_code=code,
        )

    @staticmethod
    def _retry_at(value, now):
        try:
            return now + timedelta(seconds=max(1, int(value)))
        except (TypeError, ValueError, OverflowError):
            try:
                return max(
                    now + timedelta(seconds=1), utc_naive(parsedate_to_datetime(value))
                )
            except (TypeError, ValueError, OverflowError):
                return now + timedelta(minutes=5)
