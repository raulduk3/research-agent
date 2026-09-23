"""The documents stage prefers the arXiv PDF bucket over a second arXiv
request (#207): source always comes from `export.arxiv.org`, but the PDF
comes from the bucket when it is permitted and holds the version, falling
back to arXiv only when the bucket lacks it. A sampled PDF is also fetched
from arXiv so the two can be compared for byte equality.

Real PostgreSQL, the real storage service over mTLS and real HTTPS requests
to a loopback server standing in for both `export.arxiv.org` and the bucket;
only the remote content is synthetic.
"""

from __future__ import annotations

import ssl
import subprocess
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest import access
from research_agent.ingest.arxiv import (
    BUCKET_SOURCE,
    bucket_pdf_path,
    fetch_bucket_pdf,
    fetch_document,
)
from research_agent.ingest.fetch import BoundedResponse
from research_agent.ingest.pilot import (
    Identity,
    ParallelGate,
    PilotWorker,
    RateGate,
    Sources,
    sampled_for_equivalence,
)
from research_agent.ingest.pilot_local import (
    LocalStorage,
    local_storage,
    worker_principal,
)
from research_agent.storage.client import StorageClient, StorageTransportError

pytestmark = pytest.mark.integration

IDENTITY = Identity(
    ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)
# A later deploy of the same worker: a new source commit, same everything
# else (#216). A job resumed under this identity must not collide with a
# command a prior identity already completed for identical document bytes.
REDEPLOYED_IDENTITY = Identity(
    ProducerVersion("a" * 64, "2" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)
# Not sampled for the arXiv equivalence check (#207): the ordinary bucket path.
NOT_SAMPLED_FAMILY = "2305.01937"
# Hash-sampled for the equivalence check; found by brute force over ids.
SAMPLED_FAMILY = "2305.00032"
assert not sampled_for_equivalence(NOT_SAMPLED_FAMILY)
assert sampled_for_equivalence(SAMPLED_FAMILY)


class Remote:
    """Loopback HTTPS source with a request log, standing in for both
    `export.arxiv.org` and the bucket host: they never share a real host, but
    a test server only needs to tell their paths apart."""

    def __init__(
        self,
        *,
        bucket_status: int = 200,
        bucket_body: bytes = b"%PDF-1.5 bucket copy",
        arxiv_pdf_body: bytes = b"%PDF-1.5 arxiv copy",
    ) -> None:
        self.log: Counter[str] = Counter()
        self.bucket_status = bucket_status
        self.bucket_body = bucket_body
        self.arxiv_pdf_body = arxiv_pdf_body

    def respond(self, path: str) -> tuple[int, bytes]:
        self.log[path] += 1
        if path.startswith("/arxiv-dataset/"):
            body = self.bucket_body if self.bucket_status == 200 else b""
            return self.bucket_status, body
        if path.startswith("/pdf/"):
            return 200, self.arxiv_pdf_body
        if path.startswith("/src/"):
            return 200, b"source bytes"
        return 404, b""


@contextmanager
def _remote(
    tmp_path: Path,
    *,
    bucket_status: int = 200,
    bucket_body: bytes = b"%PDF-1.5 bucket copy",
    arxiv_pdf_body: bytes = b"%PDF-1.5 arxiv copy",
) -> Iterator[tuple[Remote, int, ssl.SSLContext]]:
    key, cert = tmp_path / "remote.key", tmp_path / "remote.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days",
            "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    remote = Remote(
        bucket_status=bucket_status,
        bucket_body=bucket_body,
        arxiv_pdf_body=arxiv_pdf_body,
    )

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            status, body = remote.respond(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("localhost", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield remote, server.server_port, ssl.create_default_context(cafile=str(cert))
    finally:
        server.shutdown()
        server.server_close()


def _sources(
    port: int, context: ssl.SSLContext, *, with_bucket: bool = True
) -> Sources:
    def document(path: str) -> BoundedResponse:
        return fetch_document(path, host="localhost", port=port, context=context)

    def pdf_bucket(path: str) -> BoundedResponse:
        return fetch_bucket_pdf(path, host="localhost", port=port, context=context)

    def _unreachable(*_: object, **__: object) -> Any:
        raise AssertionError("the documents stage never touches openalex")

    return Sources(
        listing=_unreachable,
        document=document,
        openalex_match=_unreachable,
        openalex_cites=_unreachable,
        arxiv_gate=RateGate(0.001),
        openalex_gate=RateGate(0.001),
        pdf_bucket=pdf_bucket if with_bucket else None,
        bucket_gate=ParallelGate(8),
    )


def _run_documents_job(
    storage: LocalStorage,
    worker: UUID,
    sources: Sources,
    *,
    family_id: str = NOT_SAMPLED_FAMILY,
) -> dict[str, Any]:
    storage.enqueue(
        {"stage": "documents", "family": {"family_id": family_id, "license_url": None}}
    )
    pilot = PilotWorker(
        storage.client, worker_id=worker, identity=IDENTITY, sources=sources
    )
    summary = pilot.run()
    assert summary.jobs_completed == 1
    rows = storage.job_rows()
    assert len(rows) == 1
    _, state, manifest = rows[0]
    assert state == "committed"
    assert manifest is not None
    return storage.report(manifest)


def test_a_retained_bucket_pdf_costs_no_second_arxiv_request(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with (
        _remote(tmp_path) as (remote, port, context),
        local_storage(
            dsn=postgres_dsn, artifact_root=artifact_root, tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):  # fmt: skip
        report = _run_documents_job(
            storage, worker_principal(tls), _sources(port, context)
        )
        assert report["src"] == "retained"
        assert report["pdf"] == "retained"
        assert report["pdf_bucket"] == "retained"
        assert report["pdf_source"] == BUCKET_SOURCE
        assert "pdf_equivalence" not in report
        assert remote.log[f"/pdf/{NOT_SAMPLED_FAMILY}v1"] == 0
        assert remote.log[bucket_pdf_path(NOT_SAMPLED_FAMILY)] == 1
        assert remote.log[f"/src/{NOT_SAMPLED_FAMILY}v1"] == 1


def test_a_version_absent_from_the_bucket_falls_back_to_arxiv(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with (
        _remote(tmp_path, bucket_status=404) as (remote, port, context),
        local_storage(
            dsn=postgres_dsn, artifact_root=artifact_root, tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):  # fmt: skip
        report = _run_documents_job(
            storage, worker_principal(tls), _sources(port, context)
        )
        assert report["pdf_bucket"] == "absent"
        assert report["pdf"] == "retained"
        assert report["pdf_source"] == "arxiv"
        assert remote.log[f"/pdf/{NOT_SAMPLED_FAMILY}v1"] == 1


def test_without_a_permitted_bucket_every_pdf_comes_from_arxiv(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with (
        _remote(tmp_path) as (remote, port, context),
        local_storage(
            dsn=postgres_dsn, artifact_root=artifact_root, tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):  # fmt: skip
        report = _run_documents_job(
            storage,
            worker_principal(tls),
            _sources(port, context, with_bucket=False),
        )
        assert "pdf_bucket" not in report
        assert report["pdf"] == "retained"
        assert report["pdf_source"] == "arxiv"
        assert not any(path.startswith("/arxiv-dataset/") for path in remote.log)
        assert remote.log[f"/pdf/{NOT_SAMPLED_FAMILY}v1"] == 1


def test_a_build_whose_registry_lacks_the_bucket_source_makes_no_bucket_request(
    postgres_dsn: str,
    artifact_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(access.REGISTRY, "arxiv_gcs_pdf")
    tls = tmp_path / "tls"
    with (
        _remote(tmp_path) as (remote, port, context),
        local_storage(
            dsn=postgres_dsn, artifact_root=artifact_root, tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):  # fmt: skip
        report = _run_documents_job(
            storage, worker_principal(tls), _sources(port, context)
        )
        assert report["pdf_bucket"] == "not_permitted"
        assert report["pdf_source"] == "arxiv"
        assert not any(path.startswith("/arxiv-dataset/") for path in remote.log)


def test_a_sampled_pdf_equivalence_mismatch_is_recorded_without_failing_the_family(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with (
        _remote(
            tmp_path,
            bucket_body=b"%PDF-1.5 bucket copy",
            arxiv_pdf_body=b"%PDF-1.5 a different copy",
        ) as (remote, port, context),
        local_storage(
            dsn=postgres_dsn, artifact_root=artifact_root, tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):  # fmt: skip
        report = _run_documents_job(
            storage,
            worker_principal(tls),
            _sources(port, context),
            family_id=SAMPLED_FAMILY,
        )
        assert report["pdf"] == "retained"
        assert report["pdf_source"] == BUCKET_SOURCE
        assert report["pdf_equivalence"] == "mismatch"
        assert remote.log[f"/pdf/{SAMPLED_FAMILY}v1"] == 1


def test_a_sampled_pdf_equivalence_match_is_recorded_as_equal(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    same = b"%PDF-1.5 identical bytes"
    tls = tmp_path / "tls"
    with (
        _remote(tmp_path, bucket_body=same, arxiv_pdf_body=same) as (
            remote,
            port,
            context,
        ),
        local_storage(
            dsn=postgres_dsn, artifact_root=artifact_root, tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):  # fmt: skip
        report = _run_documents_job(
            storage,
            worker_principal(tls),
            _sources(port, context),
            family_id=SAMPLED_FAMILY,
        )
        assert report["pdf_equivalence"] == "equal"
        assert remote.log[f"/pdf/{SAMPLED_FAMILY}v1"] == 1


class _CrashBeforePdfCheckpoint:
    """A `StorageClient` that behaves normally for the src checkpoint but
    whose every `checkpoint` call after that never reaches storage --
    exhausting `_send`'s one retry so the run dies with the pdf artifact
    already published and its checkpoint never recorded, exactly as a
    worker process killed at that instant would leave things."""

    def __init__(self, inner: StorageClient) -> None:
        self._inner = inner
        self._checkpoints = 0

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if name != "checkpoint":
            return attribute

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self._checkpoints += 1
            if self._checkpoints == 1:
                return attribute(*args, **kwargs)
            raise StorageTransportError("simulated: request never reached storage")

        return wrapped


def _expire_running_leases(storage: LocalStorage) -> None:
    storage.database.transaction(
        lambda connection: connection.execute(
            "UPDATE jobs SET expires_at = clock_timestamp() - interval '1 second'"
            " WHERE state = 'running'"
        )
    )


def test_a_job_resumed_under_a_redeployed_identity_still_publishes(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    """A family whose pdf artifact committed under one producer identity but
    was never checkpointed resumes under a later identity (a deploy landed
    mid-job, #216) and republishes the identical bytes. That resend must not
    collide with the command the earlier identity already completed."""
    tls = tmp_path / "tls"
    with _remote(tmp_path) as (remote, port, context):
        with local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=IDENTITY,
        ) as storage:
            worker = worker_principal(tls)
            storage.enqueue(
                {
                    "stage": "documents",
                    "family": {
                        "family_id": NOT_SAMPLED_FAMILY,
                        "license_url": None,
                    },
                }
            )
            dying = PilotWorker(
                _CrashBeforePdfCheckpoint(storage.client),
                worker_id=worker,
                identity=IDENTITY,
                sources=_sources(port, context),
            )
            with pytest.raises(StorageTransportError):
                dying.run()
            assert [state for _, state, _ in storage.job_rows()] == ["running"]
            _expire_running_leases(storage)

        with local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=REDEPLOYED_IDENTITY,
        ) as storage:
            resumed = PilotWorker(
                storage.client,
                worker_id=worker_principal(tls),
                identity=REDEPLOYED_IDENTITY,
                sources=_sources(port, context),
            )
            assert resumed.run().jobs_completed == 1
            rows = storage.job_rows()
            assert len(rows) == 1
            _, state, manifest = rows[0]
            assert state == "committed"
            assert manifest is not None
            report = storage.report(manifest)
            assert report["src"] == "retained"
            assert report["pdf"] == "retained"
            assert report["pdf_bucket"] == "retained"
            assert report["pdf_source"] == BUCKET_SOURCE
