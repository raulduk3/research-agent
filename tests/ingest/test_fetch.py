"""Loopback TLS protocol tests for the bounded OpenAlex page fetcher."""

from __future__ import annotations

import ssl
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from research_agent.contracts import RecordMeta
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.fetch import (
    FetchedOpenAlexPage,
    FetchedSnapshotRange,
    _fetch_page,
    _fetch_range,
    _match_request,
    _request,
)


def _metadata() -> RecordMeta:
    return RecordMeta(
        1,
        (),
        ProducerVersion("1" * 64, "2" * 40, 1),
        "3" * 64,
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )


@contextmanager
def _server(
    tmp_path: Path,
    status: int,
    body: bytes,
    *,
    delay: float = 0,
    body_delay: float = 0,
    framing: str = "length",
) -> Iterator[tuple[int, ssl.SSLContext, list[str]]]:
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0" if framing == "http10" else "HTTP/1.1"

        def do_GET(self) -> None:
            paths.append(self.path)
            if delay:
                time.sleep(delay)
            if framing == "header_drip":
                self.close_connection = True
                try:
                    self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                    self.wfile.flush()
                    for character in b"X-Slow: abcdefghijklmnopqrstuvwxyz\r\n\r\n":
                        self.wfile.write(bytes((character,)))
                        self.wfile.flush()
                        time.sleep(0.025)
                except (BrokenPipeError, ssl.SSLError):
                    pass
                return
            self.send_response(status)
            if framing == "connection_close":
                self.send_header("Connection", "close")
            self.send_header("Content-Type", "application/json")
            self.send_header("X-RateLimit-Remaining", "17")
            if framing in {"chunked", "malformed_chunk"}:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header(
                    "Content-Length",
                    str(len(body) + (10 if framing == "truncated" else 0)),
                )
            self.end_headers()
            try:
                if body_delay:
                    time.sleep(body_delay)
                if framing == "chunked":
                    self.wfile.write(
                        f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
                    )
                elif framing == "malformed_chunk":
                    self.wfile.write(b"ZZZ\r\n" + body)
                else:
                    self.wfile.write(body)
                self.wfile.flush()
            except BrokenPipeError:
                pass
            if framing == "truncated":
                self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("localhost", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client_context = ssl.create_default_context(cafile=str(cert))
    try:
        yield server.server_port, client_context, paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def _range_server(
    tmp_path: Path, data: bytes, *, respect_range: bool = True
) -> Iterator[tuple[int, ssl.SSLContext, list[str]]]:
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            paths.append(self.path)
            range_header = self.headers.get("Range")
            if not respect_range or range_header is None:
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            spec = range_header.removeprefix("bytes=")
            if spec.startswith("-"):
                length = int(spec[1:])
                start, end = max(0, len(data) - length), len(data) - 1
            else:
                start_text, end_text = spec.split("-", 1)
                start = int(start_text)
                end = int(end_text) if end_text else len(data) - 1
            end = min(end, len(data) - 1)
            chunk = data[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.end_headers()
            self.wfile.write(chunk)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("localhost", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client_context = ssl.create_default_context(cafile=str(cert))
    try:
        yield server.server_port, client_context, paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _fetch_snapshot(
    port: int,
    context: ssl.SSLContext,
    *,
    key: str = "data/parquet/works/part.parquet",
    range_spec: str = "0-3",
) -> FetchedSnapshotRange:
    return _fetch_range(
        key=key,
        range_spec=range_spec,
        provenance=_metadata(),
        permission_evidence_hash="4" * 64,
        retention_policy_hash="5" * 64,
        host="localhost",
        port=port,
        context=context,
    )


def test_snapshot_range_fetch_retains_exact_bytes_and_content_range(
    tmp_path: Path,
) -> None:
    data = b"0123456789"
    with _range_server(tmp_path, data) as (port, context, paths):
        result = _fetch_snapshot(port, context, range_spec="2-5")
    assert result.payload == b"2345"
    assert result.access.failure is None
    assert result.access.http_status == 206
    assert result.access.source == "openalex"
    assert result.content_range == (2, 5, len(data))
    assert paths == ["/data/parquet/works/part.parquet"]


def test_snapshot_suffix_range_reports_total_size(tmp_path: Path) -> None:
    data = b"0123456789"
    with _range_server(tmp_path, data) as (port, context, _):
        result = _fetch_snapshot(port, context, range_spec="-1")
    assert result.payload == b"9"
    assert result.content_range == (9, 9, len(data))


def test_snapshot_range_fetch_fails_when_the_server_ignores_range(
    tmp_path: Path,
) -> None:
    data = b"0123456789"
    with _range_server(tmp_path, data, respect_range=False) as (port, context, _):
        result = _fetch_snapshot(port, context, range_spec="2-5")
    assert result.payload is None
    assert result.access.failure == "rejected"
    assert result.access.http_status == 200


def test_snapshot_range_fetch_fails_without_a_content_range_header(
    tmp_path: Path,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(206)
            self.send_header("Content-Length", "4")
            self.end_headers()
            self.wfile.write(b"2345")

        def log_message(self, format: str, *args: object) -> None:
            pass

    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    server = ThreadingHTTPServer(("localhost", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client_context = ssl.create_default_context(cafile=str(cert))
    try:
        result = _fetch_snapshot(server.server_port, client_context, range_spec="2-5")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.payload is None
    assert result.access.failure == "invalid_payload"
    assert result.content_range is None


@pytest.mark.parametrize(
    ("key", "range_spec"),
    [
        ("../etc/passwd", "0-1"),
        ("data/jsonl/works/part.jsonl", "0-1"),
        ("data/parquet/works/part.parquet", ""),
        ("data/parquet/works/part.parquet", "-"),
    ],
)
def test_snapshot_range_fetch_refuses_an_invalid_key_or_range(
    key: str, range_spec: str
) -> None:
    with pytest.raises(ValueError):
        _fetch_range(
            key=key,
            range_spec=range_spec,
            provenance=_metadata(),
            permission_evidence_hash="4" * 64,
            retention_policy_hash="5" * 64,
            host="localhost",
            port=1,
            context=ssl.create_default_context(),
        )


def _fetch(
    port: int,
    context: ssl.SSLContext,
    *,
    max_bytes: int = 8 * 1024 * 1024,
    timeout_seconds: float = 30,
) -> FetchedOpenAlexPage:
    return _fetch_page(
        query=_request(("W123",), None, 100),
        provenance=_metadata(),
        permission_evidence_hash="4" * 64,
        retention_policy_hash="5" * 64,
        host="localhost",
        port=port,
        context=context,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
    )


def test_tls_fetch_retains_exact_bytes_query_and_observed_budget(
    tmp_path: Path,
) -> None:
    raw = b'{"meta":{"next_cursor":null},"results":[]}'
    with _server(tmp_path, 200, raw) as (port, context, paths):
        result = _fetch(port, context)
    assert result.payload == raw
    assert result.access.failure is None
    assert result.access.http_status == 200
    assert result.observed_budget_headers == (("x-ratelimit-remaining", "17"),)
    assert result.elapsed_seconds >= 0
    assert len(paths) == 1
    query = parse_qs(urlsplit(paths[0]).query)
    assert query == {
        "filter": ["cites:W123"],
        "select": ["id,ids,doi,publication_date,primary_topic,referenced_works"],
        "per_page": ["100"],
        "cursor": ["*"],
    }


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (429, b"limited", "rejected"),
        (302, b"redirect", "rejected"),
        (200, b"not JSON", "invalid_payload"),
        (200, b'{"meta":{},"results":[]}', "invalid_payload"),
    ],
)
def test_failure_is_preserved_without_payload(
    tmp_path: Path, status: int, body: bytes, expected: str
) -> None:
    with _server(tmp_path, status, body) as (port, context, paths):
        result = _fetch(port, context)
    assert result.access.failure == expected
    assert result.access.http_status == status
    assert result.payload is None
    assert len(paths) == 1


def test_oversize_and_timeout_are_bounded(tmp_path: Path) -> None:
    with _server(tmp_path, 200, b"x" * 256) as (port, context, _):
        result = _fetch(port, context, max_bytes=64)
    assert result.access.failure == "invalid_payload"
    assert result.payload is None
    with _server(
        tmp_path, 200, b'{"meta":{"next_cursor":null},"results":[]}', delay=0.2
    ) as (port, context, _):
        result = _fetch(port, context, timeout_seconds=0.05)
    assert result.access.failure == "timeout"
    assert result.access.capture_completed_at >= result.access.capture_started_at


@pytest.mark.parametrize("framing", ["length", "chunked", "http10", "connection_close"])
def test_http_framing_retains_payload_without_wire_chunk_bytes(
    tmp_path: Path, framing: str
) -> None:
    raw = b'{"meta":{"next_cursor":null},"results":[]}'
    with _server(tmp_path, 200, raw, framing=framing) as (port, context, _):
        result = _fetch(port, context, timeout_seconds=1)
    assert result.payload == raw
    assert result.access.failure is None


def test_truncated_content_length_cannot_be_complete(tmp_path: Path) -> None:
    raw = b'{"meta":{"next_cursor":null},"results":[]}'
    with _server(tmp_path, 200, raw, framing="truncated") as (port, context, _):
        result = _fetch(port, context, timeout_seconds=1)
    assert result.payload is None
    assert result.access.failure in {"transport", "timeout", "invalid_payload"}


def test_header_drip_hits_absolute_deadline(tmp_path: Path) -> None:
    with _server(tmp_path, 200, b"", framing="header_drip") as (port, context, _):
        result = _fetch(port, context, timeout_seconds=0.13)
    assert result.payload is None
    assert result.access.failure == "timeout"
    assert result.elapsed_seconds < 0.3


def test_body_delay_within_deadline_succeeds_and_excess_fails(tmp_path: Path) -> None:
    raw = b'{"meta":{"next_cursor":null},"results":[]}'
    with _server(tmp_path, 200, raw, body_delay=0.07) as (port, context, _):
        result = _fetch(port, context, timeout_seconds=0.5)
    assert result.payload == raw
    with _server(tmp_path, 200, raw, body_delay=0.2) as (port, context, _):
        result = _fetch(port, context, timeout_seconds=0.05)
    assert result.payload is None
    assert result.access.failure == "timeout"


def test_malformed_chunk_fails_capture(tmp_path: Path) -> None:
    with _server(tmp_path, 200, b"garbage", framing="malformed_chunk") as (
        port,
        context,
        _,
    ):
        result = _fetch(port, context, timeout_seconds=1)
    assert result.payload is None
    assert result.access.failure in {"transport", "invalid_payload"}


def test_tls_verification_rejects_untrusted_certificate(tmp_path: Path) -> None:
    with _server(tmp_path, 200, b'{"meta":{"next_cursor":null},"results":[]}') as (
        port,
        _,
        _,
    ):
        result = _fetch(port, ssl.create_default_context())
    assert result.access.failure == "transport"
    assert result.payload is None


def test_query_cannot_add_paid_or_arbitrary_parameters() -> None:
    with pytest.raises(ValueError):
        _request(("W123&api_key=secret",), None, 100)
    for value in ("2305.10601&api_key=secret", "2305.10601v1", "cs/0101001", ""):
        with pytest.raises(ValueError):
            _match_request(value)


def test_arxiv_match_query_is_one_exact_doi() -> None:
    path, parameters = _match_request("2305.10601")
    query = parse_qs(urlsplit(path).query)
    assert query == {
        "filter": ["doi:10.48550/arxiv.2305.10601"],
        "select": ["id,ids,doi,publication_date,primary_topic,referenced_works"],
        "per_page": ["2"],
        "cursor": ["*"],
    }
    assert b"api_key" not in parameters
