"""Permission registry gate: refuse a fetch or redirect before it is built."""

from __future__ import annotations

import ssl
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from research_agent.ingest.access import (
    REGISTRY,
    SourceNotPermitted,
    authorize_fetch,
    authorize_redirect,
)
from research_agent.ingest.fetch import bounded_get


def test_permitted_source_and_host_is_authorized() -> None:
    authorize_fetch("arxiv", "oaipmh.arxiv.org")
    authorize_fetch("arxiv", "export.arxiv.org")
    authorize_fetch("arxiv_gcs_pdf", "storage.googleapis.com")
    authorize_fetch("openalex", "api.openalex.org")
    authorize_fetch("openalex_snapshot", "openalex.s3.amazonaws.com")


def test_snapshot_host_outside_the_reviewed_bucket_is_refused() -> None:
    with pytest.raises(SourceNotPermitted):
        authorize_fetch("openalex_snapshot", "api.openalex.org")


def test_unregistered_source_is_refused() -> None:
    with pytest.raises(SourceNotPermitted):
        authorize_fetch("semantic-scholar", "api.semanticscholar.org")


def test_host_outside_the_reviewed_source_is_refused() -> None:
    with pytest.raises(SourceNotPermitted):
        authorize_fetch("arxiv", "arxiv.org")
    with pytest.raises(SourceNotPermitted):
        authorize_fetch("arxiv_gcs_pdf", "arxiv.org")


def test_redirect_to_an_unapproved_route_is_refused() -> None:
    with pytest.raises(SourceNotPermitted):
        authorize_redirect("arxiv", "https://paywall.example.com/article")


def test_redirect_to_a_permitted_host_is_authorized() -> None:
    authorize_redirect("arxiv", "https://export.arxiv.org/src/2306.00001v1")


def test_redirect_with_no_scheme_or_host_is_refused() -> None:
    with pytest.raises(SourceNotPermitted):
        authorize_redirect("arxiv", "/src/2306.00001v1")


def test_registry_grants_no_source_without_a_completed_license_review() -> None:
    assert all(entry.license_reviewed for entry in REGISTRY.values())


@contextmanager
def _redirecting_server(
    tmp_path: Path,
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
            self.send_response(302)
            self.send_header("Location", "https://paywall.example.com/article")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client_context = ssl.create_default_context(cafile=str(cert))
    try:
        yield server.server_address[1], client_context, paths
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_a_redirect_from_an_allowed_source_to_a_paywalled_route_triggers_no_second_request(
    tmp_path: Path,
) -> None:
    with _redirecting_server(tmp_path) as (port, context, paths):
        response = bounded_get(
            "localhost",
            port,
            "/src/2306.00001v1",
            context=context,
            accept="*/*",
            max_bytes=1024,
            timeout_seconds=5.0,
        )
        # bounded_get never follows a redirect itself: a 3xx is refused, not chased.
        assert response.status == 302
        assert response.failure == "rejected"
        location = dict(response.headers)["location"]
        with pytest.raises(SourceNotPermitted):
            authorize_redirect("arxiv", location)
        # Exactly the one request the caller made; nothing followed the redirect.
        assert paths == ["/src/2306.00001v1"]
