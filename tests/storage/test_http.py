from __future__ import annotations

import io
import json
import hashlib
import ssl
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.client import HTTPResponse, HTTPSConnection
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_json
from research_agent.contracts import ProducerVersion
from research_agent.snapshots.documents import DocumentPins
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, StorageError, UnavailableInput
from research_agent.storage.http import (
    JobCommands,
    OwnerCommands,
    RecordCommands,
    RunCommands,
    ServiceCapability,
    SubmissionCommands,
    create_storage_server,
)
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.jobs import JobRepository
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.authorization import StorageAuthorization


PRINCIPAL = UUID("123e4567-e89b-42d3-a456-426614174000")
OTHER = "123e4567-e89b-42d3-a456-426614174001"
COMMAND = "123e4567-e89b-42d3-a456-426614174002"
REQUEST = "123e4567-e89b-42d3-a456-426614174003"
KEY = "123e4567-e89b-42d3-a456-426614174004"
HASH = "a" * 64
SOURCE = b"%PDF-1.4 pinned source"
PIN = DocumentPins(
    paper_family_id="123e4567-e89b-42d3-a456-426614174020",
    paper_version_id="123e4567-e89b-42d3-a456-426614174021",
    card_hash="b" * 64,
    overview_hash=HASH,
    passage_index_hash="c" * 64,
    graph_hash=None,
)


class Jobs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, CommandIdentity, object, UUID | None]] = []
        self.response = StoredResponse(
            200,
            canonical_json(
                {
                    "schema_version": 1,
                    "request_id": REQUEST,
                    "status": "ok",
                    "data": {"lease": None},
                    "error": None,
                }
            ),
            False,
        )

    def execute(
        self,
        operation: str,
        *,
        identity: CommandIdentity,
        payload: object,
        job_id: UUID | None = None,
    ) -> StoredResponse:
        self.calls.append((operation, identity, payload, job_id))
        return self.response


class Records:
    def __init__(self) -> None:
        self.calls: list[tuple[str, CommandIdentity, object]] = []
        self.response = StoredResponse(
            200,
            canonical_json(
                {
                    "schema_version": 1,
                    "request_id": REQUEST,
                    "status": "ok",
                    "data": {},
                    "error": None,
                }
            ),
            False,
        )

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        self.calls.append((operation, identity, payload))
        return self.response

    def finish_without_submit(
        self, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        return self.execute("finish_without_submit", identity=identity, payload=payload)

    def accept_submission(
        self, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        return self.execute("accept_submission", identity=identity, payload=payload)


class Artifacts:
    def read(self, artifact_hash: str) -> tuple[tuple[int, str], io.BytesIO]:
        assert artifact_hash == HASH
        return (7, "text/plain"), io.BytesIO(b"payload")

    def publish_command(self, *args: object, **kwargs: object) -> StoredResponse:
        raise AssertionError("malformed upload must not publish")


class Queries:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def run(self, run_id: str) -> dict[str, object] | None:
        self.calls.append(("run", (run_id,)))
        if run_id != OTHER:
            return None
        return {"run_id": run_id, "events": []}

    def run_specification(self, run_id: str) -> dict[str, object] | None:
        self.calls.append(("run_specification", (run_id,)))
        if run_id != OTHER:
            return None
        return {"run_id": run_id, "snapshot_hash": HASH, "active": True}

    def runs_by_configuration(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("runs_by_configuration", (configuration_id, cursor)))
        return ({"run_id": OTHER},), None

    def runs_by_batch(
        self, batch_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("runs_by_batch", (batch_id, cursor)))
        return (), None

    def runs_by_paper(
        self, paper_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("runs_by_paper", (paper_id, cursor)))
        return ({"run_id": OTHER, "paper_id": paper_id},), None

    def sheet(self, sheet_hash: str) -> dict[str, object] | None:
        self.calls.append(("sheet", (sheet_hash,)))
        if sheet_hash != HASH:
            return None
        return {"sheet_hash": HASH, "questions": [{"question_id": OTHER}]}

    def submissions_by_submitter(
        self, submitter_id: str
    ) -> tuple[dict[str, object], ...]:
        self.calls.append(("submissions_by_submitter", (submitter_id,)))
        return ({"submission_id": OTHER},)

    def manifest(self, artifact_hash: str) -> dict[str, object] | None:
        self.calls.append(("manifest", (artifact_hash,)))
        if artifact_hash != HASH:
            return None
        return {"artifact_hash": HASH, "manifest_kind": "unknown", "fields": {}}

    def configurations(
        self, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("configurations", (cursor,)))
        return (
            ({"configuration_id": OTHER},),
            ("2026-09-22T00:00:00.000000Z", OTHER),
        )

    def configuration(self, configuration_id: str) -> dict[str, object] | None:
        self.calls.append(("configuration", (configuration_id,)))
        if configuration_id != OTHER:
            return None
        return {"configuration_id": OTHER, "parts": []}

    def forecasts_by_configuration(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("forecasts_by_configuration", (configuration_id, cursor)))
        return ({"submission_id": OTHER, "resolution": None},), None


class Documents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def cards(
        self, snapshot_hash: str, paper_version_ids: tuple[str, ...]
    ) -> tuple[dict[str, object], ...]:
        self.calls.append(("cards", paper_version_ids))
        return tuple({"paper_version_id": item} for item in paper_version_ids)

    def graph(self, snapshot_hash: str, paper_version_id: str) -> dict[str, object]:
        self.calls.append(("graph", (paper_version_id,)))
        return {"incoming": []}

    def passage_index(
        self, snapshot_hash: str, paper_version_id: str
    ) -> dict[str, object]:
        self.calls.append(("passage_index", (paper_version_id,)))
        return {"passages": [{"text_hash": HASH, "text": "matched text"}]}

    def questions(self, snapshot_hash: str) -> tuple[dict[str, object], ...]:
        self.calls.append(("questions", ()))
        return ({"question_id": OTHER},)

    def members(
        self,
        snapshot_hash: str,
        *,
        after: tuple[str, str] | None = None,
        limit: int | None = None,
    ) -> tuple[DocumentPins, ...]:
        self.calls.append(("members", () if after is None else after))
        return (PIN,)

    def family_pin(self, snapshot_hash: str, paper_family_id: str) -> DocumentPins:
        self.calls.append(("family_pin", (paper_family_id,)))
        if paper_family_id != PIN.paper_family_id:
            raise UnavailableInput("paper family is not pinned in this snapshot")
        return PIN

    def overviews(
        self, snapshot_hash: str, overview_hashes: tuple[str, ...]
    ) -> tuple[dict[str, object], ...]:
        self.calls.append(("overviews", overview_hashes))
        return tuple({"vector": [1.0, 0.0]} for _ in overview_hashes)

    def passage_index_by_hash(
        self, snapshot_hash: str, passage_index_hash: str
    ) -> dict[str, object]:
        self.calls.append(("passage_index_by_hash", (passage_index_hash,)))
        return {"passages": []}

    def extraction(self, snapshot_hash: str, paper_family_id: str) -> dict[str, object]:
        self.calls.append(("extraction", (paper_family_id,)))
        if paper_family_id != PIN.paper_family_id:
            raise UnavailableInput("paper family is not pinned in this snapshot")
        return {
            "paper_version_id": PIN.paper_version_id,
            "extraction_hash": HASH,
            "extraction": {"blocks": []},
        }

    def source(
        self, snapshot_hash: str, paper_family_id: str
    ) -> tuple[str, tuple[int, str], io.BytesIO]:
        self.calls.append(("source", (paper_family_id,)))
        if paper_family_id != PIN.paper_family_id:
            raise UnavailableInput("paper family is not pinned in this snapshot")
        return (
            hashlib.sha256(SOURCE).hexdigest(),
            (len(SOURCE), "application/pdf"),
            io.BytesIO(SOURCE),
        )


class EmbeddingViews:
    """A family's stored views: PIN's family has one, OTHER's is unreadable."""

    def __init__(self, view: dict[str, object] | None = None) -> None:
        self.view = view or {"paper_id": PIN.paper_family_id, "dims": 2}
        self.calls: list[str] = []

    def current(self, paper_family_id: str) -> dict[str, object] | None:
        self.calls.append(paper_family_id)
        if paper_family_id == OTHER:
            raise UnavailableInput("stored view is not valid JSON")
        return self.view if paper_family_id == PIN.paper_family_id else None


class Authorization(StorageAuthorization):
    def __init__(self) -> None:
        pass

    def job_fence_allowed(self, **kwargs: object) -> bool:
        return True

    def command_completed(self, **kwargs: object) -> bool:
        return False

    def job_scope_active(self, **kwargs: object) -> bool:
        return True

    def artifact_in_job_scope(self, *, artifact_hash: str, **kwargs: object) -> bool:
        return artifact_hash == HASH


def _tls_material(
    root: Path,
) -> tuple[ssl.SSLContext, ssl.SSLContext, str, ssl.SSLContext, str, ssl.SSLContext]:
    ca_key, ca_cert = root / "ca.key", root / "ca.pem"
    server_key, server_csr, server_cert = (
        root / "server.key",
        root / "server.csr",
        root / "server.pem",
    )
    client_key, client_csr, client_cert = (
        root / "client.key",
        root / "client.csr",
        root / "client.pem",
    )
    wrong_key, wrong_csr, wrong_cert = (
        root / "wrong.key",
        root / "wrong.csr",
        root / "wrong.pem",
    )
    commands = (
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
            "/CN=test-ca",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_cert),
        ],
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=storage",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-keyout",
            str(server_key),
            "-out",
            str(server_csr),
        ],
        [
            "openssl",
            "x509",
            "-req",
            "-days",
            "1",
            "-in",
            str(server_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-copy_extensions",
            "copy",
            "-out",
            str(server_cert),
        ],
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=reader",
            "-keyout",
            str(client_key),
            "-out",
            str(client_csr),
        ],
        [
            "openssl",
            "x509",
            "-req",
            "-days",
            "1",
            "-in",
            str(client_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(client_cert),
        ],
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=tools",
            "-keyout",
            str(wrong_key),
            "-out",
            str(wrong_csr),
        ],
        [
            "openssl",
            "x509",
            "-req",
            "-days",
            "1",
            "-in",
            str(wrong_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(wrong_cert),
        ],
    )
    for command_line in commands:
        subprocess.run(command_line, check=True, capture_output=True)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(server_cert, server_key)
    server_context.load_verify_locations(ca_cert)
    server_context.verify_mode = ssl.CERT_REQUIRED
    client_context = ssl.create_default_context(cafile=str(ca_cert))
    client_context.load_cert_chain(client_cert, client_key)
    der = ssl.PEM_cert_to_DER_cert(client_cert.read_text())
    wrong_context = ssl.create_default_context(cafile=str(ca_cert))
    wrong_context.load_cert_chain(wrong_cert, wrong_key)
    wrong_der = ssl.PEM_cert_to_DER_cert(wrong_cert.read_text())
    no_certificate_context = ssl.create_default_context(cafile=str(ca_cert))
    return (
        server_context,
        client_context,
        hashlib.sha256(der).hexdigest(),
        wrong_context,
        hashlib.sha256(wrong_der).hexdigest(),
        no_certificate_context,
    )


@contextmanager
def server(
    jobs: JobCommands,
    tls: tuple[
        ssl.SSLContext, ssl.SSLContext, str, ssl.SSLContext, str, ssl.SSLContext
    ],
    *,
    artifact: bool = False,
    artifact_repository: ArtifactRepository | None = None,
    documents: Documents | None = None,
    queries: Queries | None = None,
    authorization: StorageAuthorization | None = None,
    role: str = "reader",
    extra_scopes: frozenset[str] = frozenset(),
    runs: RunCommands | None = None,
    snapshots: RecordCommands | None = None,
    sheets: RecordCommands | None = None,
    submissions: SubmissionCommands | None = None,
    ratings: RecordCommands | None = None,
    owners: OwnerCommands | None = None,
    trace: RecordCommands | None = None,
    embedding_views: EmbeddingViews | None = None,
) -> Iterator[tuple[tuple[str, int], ssl.SSLContext, ssl.SSLContext, ssl.SSLContext]]:
    (
        server_context,
        client_context,
        fingerprint,
        wrong_context,
        wrong_fingerprint,
        no_certificate_context,
    ) = tls
    capability = ServiceCapability(
        PRINCIPAL,
        role,
        frozenset({"jobs:claim", "jobs:renew", "artifacts:read", "artifacts:publish"})
        | extra_scopes,
        job_kinds=frozenset({"extract"}),
        producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        jobs,
        {
            fingerprint: capability,
            wrong_fingerprint: ServiceCapability(
                PRINCIPAL,
                "scorer",
                frozenset({"jobs:claim", "artifacts:read"}),
                job_kinds=frozenset({"extract"}),
                producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
                config_hash="c" * 64,
                retention_policy_hash="d" * 64,
            ),
        },
        tls_context=server_context,
        authorization=authorization or Authorization(),
        artifacts=artifact_repository or (Artifacts() if artifact else None),
        documents=documents,
        queries=queries,
        runs=runs,
        snapshots=snapshots,
        sheets=sheets,
        submissions=submissions,
        ratings=ratings,
        owners=owners,
        trace=trace,
        embedding_views=embedding_views,
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        host, port = httpd.server_address[:2]
        yield (
            (str(host), int(port)),
            client_context,
            wrong_context,
            no_certificate_context,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def request(
    address: tuple[str, int],
    context: ssl.SSLContext,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[HTTPResponse, bytes]:
    connection = HTTPSConnection(*address, timeout=2, context=context)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def command(payload: object) -> bytes:
    return canonical_json(
        {
            "schema_version": 1,
            "command_id": COMMAND,
            "request_id": REQUEST,
            "payload": payload,
        }
    )


def headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Idempotency-Key": KEY,
        "X-Job-Id": OTHER,
        "X-Lease-Epoch": "1",
    }


def multipart(metadata: dict[str, object], payload: bytes) -> tuple[bytes, str]:
    boundary = "research-agent-boundary"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode()
        + canonical_json(metadata)
        + (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="payload"; filename="payload"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={boundary}"


def test_real_http_dispatches_strict_authenticated_command(tmp_path: Path) -> None:
    jobs = Jobs()
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, no_certificate):
        with pytest.raises((ssl.SSLError, BrokenPipeError)):
            request(address, no_certificate, "GET", f"/v1/artifacts/{HASH}")
        response, body = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
    assert response.status == 200
    assert json.loads(body)["status"] == "ok"
    assert jobs.calls[0][0] == "claim"
    assert jobs.calls[0][1] == CommandIdentity(
        PRINCIPAL, UUID(KEY), UUID(COMMAND), UUID(REQUEST)
    )


def test_scope_and_worker_binding_fail_before_repository(tmp_path: Path) -> None:
    jobs = Jobs()
    with server(jobs, _tls_material(tmp_path)) as (
        address,
        context,
        wrong_context,
        _,
    ):
        wrong_role, _ = request(
            address,
            wrong_context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
        forbidden_scope, _ = request(
            address,
            context,
            "POST",
            f"/v1/jobs/{OTHER}/complete",
            command(
                {"fence": {"worker_id": str(PRINCIPAL), "lease_epoch": 1}, "result": {}}
            ),
            headers(),
        )
        forged_worker, forged_body = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": OTHER, "kinds": ["extract"]}),
            headers(),
        )
        forbidden_kind, _ = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["fit"]}),
            headers(),
        )
    assert wrong_role.status == 403
    assert forbidden_scope.status == 403
    assert forged_worker.status == 403
    assert forbidden_kind.status == 403
    assert json.loads(forged_body)["error"]["code"] == "forbidden"
    assert jobs.calls == []


def test_closed_command_content_type_size_and_unknown_routes_fail_closed(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    valid = json.loads(command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}))
    valid["extra"] = True
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, _):
        wrong_type, _ = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            b"{}",
            {**headers(), "Content-Type": "text/plain"},
        )
        unknown_field, _ = request(
            address, context, "POST", "/v1/jobs/claim", canonical_json(valid), headers()
        )
        unknown_route, _ = request(
            address, context, "POST", "/v1/jobs/enqueue", command({}), headers()
        )
        upload, upload_body = request(
            address, context, "POST", "/v1/artifacts", b"", headers()
        )
    assert wrong_type.status == 422
    assert unknown_field.status == 422
    assert unknown_route.status == 404
    assert upload.status == 403
    assert json.loads(upload_body)["error"]["code"] == "forbidden"
    assert jobs.calls == []


def test_unsupported_method_returns_typed_reply(tmp_path: Path) -> None:
    jobs = Jobs()
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, _):
        response, body = request(address, context, "PUT", "/v1/jobs/claim", b"{}")
    assert response.status == 404
    assert response.getheader("Content-Type") == "application/json"
    assert json.loads(body)["error"]["code"] == "not_found"


def test_successful_replay_header_is_emitted(tmp_path: Path) -> None:
    jobs = Jobs()
    jobs.response = StoredResponse(200, jobs.response.body, True)
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, _):
        response, _ = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
    assert response.getheader("X-Replayed") == "true"


def test_artifact_read_requires_hash_specific_visibility(tmp_path: Path) -> None:
    jobs = Jobs()
    with server(jobs, _tls_material(tmp_path), artifact=True) as (
        address,
        context,
        wrong_context,
        _,
    ):
        visible, body = request(
            address,
            context,
            "GET",
            f"/v1/artifacts/{HASH}",
            headers={"X-Job-Id": OTHER, "X-Lease-Epoch": "1"},
        )
        hidden, hidden_body = request(
            address,
            context,
            "GET",
            f"/v1/artifacts/{'b' * 64}",
            headers={"X-Job-Id": OTHER, "X-Lease-Epoch": "1"},
        )
        wrong_role, wrong_role_body = request(
            address,
            wrong_context,
            "GET",
            f"/v1/artifacts/{HASH}",
            headers={"X-Job-Id": OTHER, "X-Lease-Epoch": "1"},
        )
    assert visible.status == 200
    assert visible.getheader("ETag") == f'"{HASH}"'
    assert body == b"payload"
    assert hidden.status == 404
    assert json.loads(hidden_body)["error"]["code"] == "not_found"
    assert wrong_role.status == 404
    assert json.loads(wrong_role_body)["error"]["code"] == "not_found"


@pytest.mark.integration
def test_real_http_reaches_postgres_job_transaction(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    jobs = JobRepository(
        Database(postgres_dsn),
        ArtifactStore(artifact_root),
        producer=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, _):
        response, body = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
        replay, replay_body = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
    assert response.status == 200
    assert json.loads(body)["data"] == {"lease": None}
    assert replay.status == 200
    assert replay.getheader("X-Replayed") == "true"
    assert replay_body == body


@pytest.mark.integration
def test_real_http_artifact_upload_is_idempotent(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    jobs = JobRepository(
        database,
        store,
        producer=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    artifacts = ArtifactRepository(database, store)
    seed = b'{"seed":1}'
    seed_publication = artifacts.publish(
        [seed],
        expected_hash=hashlib.sha256(seed).hexdigest(),
        byte_length=len(seed),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    jobs.execute(
        "enqueue",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "job_id": OTHER,
            "kind": "extract",
            "input_manifest": seed_publication.manifest_hash,
            "scheduled_at": (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        },
    )
    jobs.execute(
        "claim",
        identity=CommandIdentity(PRINCIPAL, uuid4(), uuid4(), uuid4()),
        payload={"worker_id": str(PRINCIPAL), "kinds": ["extract"]},
    )
    payload = b'{"http-upload":1}'
    metadata: dict[str, object] = {
        "schema_version": 1,
        "command_id": COMMAND,
        "request_id": REQUEST,
        "expected_hash": hashlib.sha256(payload).hexdigest(),
        "byte_length": len(payload),
        "media_type": "application/json",
        "kind": "manifest",
        "input_hashes": [],
        "producer_version": {
            "image_digest": "a" * 64,
            "source_commit": "b" * 40,
            "contract_version": 1,
        },
        "config_hash": "c" * 64,
        "source_available_at": None,
        "retention_policy_hash": "d" * 64,
    }
    body, content_type = multipart(metadata, payload)
    upload_headers = {
        "Content-Type": content_type,
        "Idempotency-Key": KEY,
        "X-Job-Id": OTHER,
        "X-Lease-Epoch": "1",
    }
    with server(
        jobs,
        _tls_material(tmp_path),
        artifact_repository=artifacts,
        authorization=StorageAuthorization(database),
    ) as (
        address,
        context,
        _,
        _,
    ):
        first, first_body = request(
            address, context, "POST", "/v1/artifacts", body, upload_headers
        )
        replay, replay_body = request(
            address, context, "POST", "/v1/artifacts", body, upload_headers
        )
    assert first.status == 201
    assert replay.status == 201
    assert replay.getheader("X-Replayed") == "true"
    assert replay_body == first_body
    assert json.loads(first_body)["data"]["artifact_hash"] == metadata["expected_hash"]


def test_record_routes_dispatch_to_their_owner_with_required_scope(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    runs, snapshots, sheets, submissions, ratings = (
        Records(),
        Records(),
        Records(),
        Records(),
        Records(),
    )
    with server(
        jobs,
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset(
            {"runs:create", "runs:append_event", "snapshots:seal", "sheets:seal"}
        ),
        runs=runs,
        snapshots=snapshots,
        sheets=sheets,
        submissions=submissions,
        ratings=ratings,
    ) as (address, context, _, _):
        run_response, _ = request(
            address, context, "POST", "/v1/runs", command({}), headers()
        )
        event_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/events",
            command({}),
            headers(),
        )
        snapshot_response, _ = request(
            address, context, "POST", "/v1/snapshots", command({}), headers()
        )
        sheet_response, _ = request(
            address, context, "POST", "/v1/sheets", command({}), headers()
        )
        forbidden_submission, _ = request(
            address, context, "POST", "/v1/submissions", command({}), headers()
        )
        forbidden_rating, _ = request(
            address, context, "POST", "/v1/ratings", command({}), headers()
        )
        malformed_run_id, _ = request(
            address,
            context,
            "POST",
            "/v1/runs/not-a-uuid/events",
            command({}),
            headers(),
        )
    assert run_response.status == 200
    assert event_response.status == 200
    assert snapshot_response.status == 200
    assert sheet_response.status == 200
    assert forbidden_submission.status == 403
    assert forbidden_rating.status == 403
    assert malformed_run_id.status == 404
    assert runs.calls[0][0] == "create"
    assert runs.calls[1][0] == "append_event"
    assert snapshots.calls[0][0] == "seal"
    assert sheets.calls[0][0] == "seal"
    assert submissions.calls == []
    assert ratings.calls == []


class Refusing(Records):
    """A record owner whose every command fails with one storage error."""

    def __init__(self, error: StorageError) -> None:
        super().__init__()
        self.error = error

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        self.calls.append((operation, identity, payload))
        raise self.error


def test_run_endings_dispatch_submit_and_void_to_their_owners(
    tmp_path: Path,
) -> None:
    runs, submissions = Records(), Records()
    ending = {"run_id": OTHER, "reason": "model_stopped"}
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset({"runs:submit", "runs:void"}),
        runs=runs,
        submissions=submissions,
    ) as (address, context, _, _):
        submit_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/submit",
            command({"run_id": OTHER}),
            headers(),
        )
        void_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/void",
            command(ending),
            headers(),
        )
        mismatched, mismatched_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{PRINCIPAL}/void",
            command(ending),
            headers(),
        )
    assert submit_response.status == 200
    assert void_response.status == 200
    assert submissions.calls[0][0] == "accept_submission"
    assert runs.calls[0][0] == "finish_without_submit"
    assert runs.calls[0][2] == ending
    assert mismatched.status == 422
    assert json.loads(mismatched_body)["error"]["code"] == "invalid_input"
    assert len(runs.calls) == 1


def test_run_endings_need_their_role_and_their_scope(
    tmp_path: Path,
) -> None:
    runs, submissions = Records(), Records()
    scopes = frozenset({"runs:submit", "runs:void"})
    # The tool service forwards a run's submit (#287) but never voids a run.
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=scopes,
        runs=runs,
        submissions=submissions,
    ) as (address, context, _, _):
        tools = [
            request(
                address,
                context,
                "POST",
                f"/v1/runs/{OTHER}/{ending}",
                command({"run_id": OTHER}),
                headers(),
            )[0].status
            for ending in ("submit", "void")
        ]
    assert tools == [200, 403]
    assert [call[0] for call in submissions.calls] == ["accept_submission"]
    assert runs.calls == []
    submissions.calls.clear()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="reader",
        extra_scopes=scopes,
        runs=runs,
        submissions=submissions,
    ) as (address, context, _, _):
        wrong_role = [
            request(
                address,
                context,
                "POST",
                f"/v1/runs/{OTHER}/{ending}",
                command({"run_id": OTHER}),
                headers(),
            )[0].status
            for ending in ("submit", "void")
        ]
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset({"runs:create"}),
        runs=runs,
        submissions=submissions,
    ) as (address, context, _, _):
        missing_scope = [
            request(
                address,
                context,
                "POST",
                f"/v1/runs/{OTHER}/{ending}",
                command({"run_id": OTHER}),
                headers(),
            )[0].status
            for ending in ("submit", "void")
        ]
    assert wrong_role == [403, 403]
    assert missing_scope == [403, 403]
    assert runs.calls == [] and submissions.calls == []


def test_run_ending_conflict_and_unknown_run_come_through_unchanged(
    tmp_path: Path,
) -> None:
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset({"runs:submit", "runs:void"}),
        runs=Refusing(UnavailableInput("void names an unknown run")),
        submissions=Refusing(StateConflict("run is void and accepts no submission")),
    ) as (address, context, _, _):
        submit_response, submit_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/submit",
            command({"run_id": OTHER}),
            headers(),
        )
        void_response, void_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/void",
            command({"run_id": OTHER, "reason": "model_stopped"}),
            headers(),
        )
    assert submit_response.status == 409
    assert json.loads(submit_body)["error"]["code"] == "state_conflict"
    assert void_response.status == 422
    assert json.loads(void_body)["error"]["code"] == "unavailable_input"


def test_rating_route_requires_rating_app_role_and_scope(tmp_path: Path) -> None:
    jobs = Jobs()
    ratings = Records()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="rating_app",
        extra_scopes=frozenset({"ratings:record"}),
        ratings=ratings,
    ) as (address, context, _, _):
        response, _ = request(
            address, context, "POST", "/v1/ratings", command({}), headers()
        )
    assert response.status == 200
    assert ratings.calls[0][0] == "record"


def test_rating_app_may_seal_a_human_forecast_but_gains_no_other_authority(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    runs, snapshots, sheets, submissions = (
        Records(),
        Records(),
        Records(),
        Records(),
    )
    with server(
        jobs,
        _tls_material(tmp_path),
        role="rating_app",
        # Every scope a sealing route could check is granted here too, so a
        # 403 on runs/snapshots below can only come from the role gate, not
        # a missing scope.
        extra_scopes=frozenset(
            {
                "ratings:record",
                "sheets:seal",
                "submissions:submit",
                "runs:create",
                "snapshots:seal",
            }
        ),
        runs=runs,
        snapshots=snapshots,
        sheets=sheets,
        submissions=submissions,
    ) as (address, context, _, _):
        sheet_response, _ = request(
            address, context, "POST", "/v1/sheets", command({}), headers()
        )
        submission_response, _ = request(
            address, context, "POST", "/v1/submissions", command({}), headers()
        )
        forbidden_run, _ = request(
            address, context, "POST", "/v1/runs", command({}), headers()
        )
        forbidden_snapshot, _ = request(
            address, context, "POST", "/v1/snapshots", command({}), headers()
        )
    assert sheet_response.status == 200
    assert submission_response.status == 200
    assert forbidden_run.status == 403
    assert forbidden_snapshot.status == 403
    assert sheets.calls[0][0] == "seal"
    assert submissions.calls[0][0] == "submit"
    assert runs.calls == []
    assert snapshots.calls == []


def test_snapshot_read_routes_dispatch_to_documents_with_required_scope(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    documents = Documents()
    paper_a = "123e4567-e89b-42d3-a456-426614174010"
    paper_b = "123e4567-e89b-42d3-a456-426614174011"
    with server(
        jobs,
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"snapshots:read"}),
        documents=documents,
    ) as (address, context, wrong_context, _):
        cards_response, cards_body = request(
            address,
            context,
            "GET",
            f"/v1/snapshots/{HASH}/cards?paper_id={paper_a}&paper_id={paper_b}",
        )
        graph_response, graph_body = request(
            address,
            context,
            "GET",
            f"/v1/snapshots/{HASH}/graph?paper_id={paper_a}&direction=citations&limit=5",
        )
        passages_response, passages_body = request(
            address,
            context,
            "GET",
            f"/v1/snapshots/{HASH}/passages?paper_id={paper_a}&passage_id={HASH}",
        )
        questions_response, questions_body = request(
            address,
            context,
            "GET",
            f"/v1/snapshots/{HASH}/questions?paper_id={paper_a}",
        )
        wrong_role_response, wrong_role_body = request(
            address,
            wrong_context,
            "GET",
            f"/v1/snapshots/{HASH}/cards?paper_id={paper_a}",
        )
        bad_query_response, bad_query_body = request(
            address, context, "GET", f"/v1/snapshots/{HASH}/graph?paper_id=not-a-uuid"
        )
    assert cards_response.status == 200
    cards_data = json.loads(cards_body)["data"]
    assert cards_data["snapshot_id"] == HASH
    assert [card["paper_version_id"] for card in cards_data["cards"]] == [
        paper_a,
        paper_b,
    ]
    assert documents.calls[0] == ("cards", (paper_a, paper_b))

    assert graph_response.status == 200
    graph_data = json.loads(graph_body)["data"]
    assert graph_data["direction"] == "citations"
    assert graph_data["graph"] == {"incoming": []}
    assert documents.calls[1] == ("graph", (paper_a,))

    assert passages_response.status == 200
    passages_data = json.loads(passages_body)["data"]
    assert passages_data["passages"] == [{"text_hash": HASH, "text": "matched text"}]

    assert questions_response.status == 200
    questions_data = json.loads(questions_body)["data"]
    assert questions_data["questions"] == [{"question_id": OTHER}]

    assert wrong_role_response.status == 404
    assert json.loads(wrong_role_body)["error"]["code"] == "not_found"

    assert bad_query_response.status == 422
    assert json.loads(bad_query_body)["error"]["code"] == "invalid_input"


def test_snapshot_read_routes_reject_a_route_outside_the_four_enumerated(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    documents = Documents()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"snapshots:read"}),
        documents=documents,
    ) as (address, context, _, _):
        response, body = request(
            address, context, "GET", f"/v1/snapshots/{HASH}/passages/extra"
        )
    assert response.status == 404
    assert json.loads(body)["error"]["code"] == "not_found"


def test_snapshot_member_reads_serve_the_tools_role_only(tmp_path: Path) -> None:
    documents = Documents()
    family = PIN.paper_family_id
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"snapshots:read"}),
        documents=documents,
    ) as (address, context, wrong_context, _):
        base = f"/v1/snapshots/{HASH}"
        members = request(address, context, "GET", f"{base}/members")
        paged = request(
            address, context, "GET", f"{base}/members?cursor={family},{OTHER}"
        )
        bad_cursor = request(address, context, "GET", f"{base}/members?cursor={OTHER}")
        member = request(address, context, "GET", f"{base}/family?family_id={family}")
        absent = request(address, context, "GET", f"{base}/family?family_id={OTHER}")
        overviews = request(
            address,
            context,
            "GET",
            f"{base}/overviews?overview_hash={HASH}&overview_hash={'b' * 64}",
        )
        index = request(
            address, context, "GET", f"{base}/passage_index?passage_index_hash={HASH}"
        )
        repeated = request(
            address,
            context,
            "GET",
            f"{base}/overviews?overview_hash={HASH}&overview_hash={HASH}",
        )
        extra = request(address, context, "GET", f"{base}/members?paper_id={OTHER}")
        wrong_role = request(address, wrong_context, "GET", f"{base}/members")
    member_row = {
        "paper_family_id": family,
        "paper_version_id": PIN.paper_version_id,
        "card_hash": "b" * 64,
        "overview_hash": HASH,
        "passage_index_hash": "c" * 64,
        "graph_hash": None,
    }
    assert members[0].status == 200
    assert json.loads(members[1])["data"] == {
        "snapshot_id": HASH,
        "members": [member_row],
        "next_cursor": None,
    }
    assert json.loads(paged[1])["data"]["members"] == [member_row]
    assert bad_cursor[0].status == 422
    assert json.loads(member[1])["data"]["member"] == member_row
    assert absent[0].status == 422
    assert json.loads(absent[1])["error"]["code"] == "unavailable_input"
    assert [
        item["overview_hash"] for item in json.loads(overviews[1])["data"]["overviews"]
    ] == [HASH, "b" * 64]
    assert json.loads(index[1])["data"]["passage_index"] == {"passages": []}
    assert repeated[0].status == 422 and extra[0].status == 422
    assert wrong_role[0].status == 404
    assert json.loads(wrong_role[1])["error"]["code"] == "not_found"
    assert documents.calls[1] == ("members", (family, OTHER))
    assert [call[0] for call in documents.calls] == [
        "members",
        "members",
        "family_pin",
        "family_pin",
        "overviews",
        "passage_index_by_hash",
    ]


def test_snapshot_extraction_and_source_reads_serve_the_tools_role_only(
    tmp_path: Path,
) -> None:
    documents = Documents()
    family = PIN.paper_family_id
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"snapshots:read"}),
        documents=documents,
    ) as (address, context, wrong_context, _):
        base = f"/v1/snapshots/{HASH}"
        extraction = request(
            address, context, "GET", f"{base}/extraction?family_id={family}"
        )
        source = request(address, context, "GET", f"{base}/source?family_id={family}")
        absent = request(address, context, "GET", f"{base}/source?family_id={OTHER}")
        extra = request(
            address,
            context,
            "GET",
            f"{base}/source?family_id={family}&paper_id={OTHER}",
        )
        missing = request(address, context, "GET", f"{base}/extraction")
        wrong_role = request(
            address, wrong_context, "GET", f"{base}/source?family_id={family}"
        )
    assert json.loads(extraction[1])["data"] == {
        "snapshot_id": HASH,
        "paper_version_id": PIN.paper_version_id,
        "extraction_hash": HASH,
        "extraction": {"blocks": []},
    }
    assert source[0].status == 200
    assert source[1] == SOURCE
    assert source[0].getheader("Content-Type") == "application/pdf"
    assert source[0].getheader("ETag") == f'"{hashlib.sha256(SOURCE).hexdigest()}"'
    assert absent[0].status == 422
    assert json.loads(absent[1])["error"]["code"] == "unavailable_input"
    assert extra[0].status == 422 and missing[0].status == 422
    assert wrong_role[0].status == 404
    assert [call[0] for call in documents.calls] == ["extraction", "source", "source"]


def test_run_specification_serves_the_tools_role_with_its_own_scope(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"runs:specification"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        found = request(address, context, "GET", f"/v1/runs/{OTHER}/specification")
        unknown = request(
            address, context, "GET", f"/v1/runs/{PRINCIPAL}/specification"
        )
        queried = request(
            address, context, "GET", f"/v1/runs/{OTHER}/specification?x=1"
        )
        # runs:specification does not widen runs:read: the inspector route
        # stays closed to the tool service.
        inspector_route = request(address, context, "GET", f"/v1/runs/{OTHER}")
        wrong_role = request(
            address, wrong_context, "GET", f"/v1/runs/{OTHER}/specification"
        )
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        without_scope = request(
            address, context, "GET", f"/v1/runs/{OTHER}/specification"
        )
    assert json.loads(found[1])["data"] == {
        "run_id": OTHER,
        "snapshot_hash": HASH,
        "active": True,
    }
    assert unknown[0].status == 404
    assert queried[0].status == 404
    assert inspector_route[0].status == 404
    assert wrong_role[0].status == 404
    assert without_scope[0].status == 404
    assert queries.calls == [
        ("run_specification", (OTHER,)),
        ("run_specification", (str(PRINCIPAL),)),
    ]


def test_embedding_view_read_serves_the_owner_role_only(tmp_path: Path) -> None:
    views = EmbeddingViews()
    base = "/v1/owner/papers"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        embedding_views=views,
    ) as (address, context, wrong_context, _):
        found = request(
            address, context, "GET", f"{base}/{PIN.paper_family_id}/embedding"
        )
        absent = request(address, context, "GET", f"{base}/{KEY}/embedding")
        unreadable = request(address, context, "GET", f"{base}/{OTHER}/embedding")
        queried = request(
            address, context, "GET", f"{base}/{PIN.paper_family_id}/embedding?x=1"
        )
        malformed = request(address, context, "GET", f"{base}/not-a-uuid/embedding")
        wrong_role = request(
            address, wrong_context, "GET", f"{base}/{PIN.paper_family_id}/embedding"
        )
    assert found[0].status == 200
    assert json.loads(found[1])["data"] == views.view
    assert absent[0].status == 404
    assert json.loads(absent[1])["error"]["code"] == "not_found"
    assert unreadable[0].status == 422
    assert json.loads(unreadable[1])["error"]["code"] == "unavailable_input"
    assert queried[0].status == 404 and malformed[0].status == 404
    assert wrong_role[0].status == 403
    assert json.loads(wrong_role[1])["error"]["code"] == "forbidden"
    # Neither the refused role nor a malformed route reached the repository.
    assert views.calls == [PIN.paper_family_id, KEY, OTHER]


def test_embedding_view_read_needs_the_owner_read_scope(tmp_path: Path) -> None:
    views = EmbeddingViews()
    with server(
        Jobs(), _tls_material(tmp_path), role="owner", embedding_views=views
    ) as (address, context, _, _):
        response = request(
            address,
            context,
            "GET",
            f"/v1/owner/papers/{PIN.paper_family_id}/embedding",
        )
    assert response[0].status == 403
    assert views.calls == []


def test_trace_routes_admit_only_the_tools_role_on_the_run_path(
    tmp_path: Path,
) -> None:
    trace = Records()
    scopes = frozenset({"trace:request", "trace:terminal"})
    requested = {"run_id": OTHER, "call_id": COMMAND}
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=scopes,
        trace=trace,
    ) as (address, context, _, _):
        request_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/trace/requests",
            command(requested),
            headers(),
        )
        terminal_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/trace/terminals",
            command(requested),
            headers(),
        )
        other_run, other_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{PRINCIPAL}/trace/requests",
            command(requested),
            headers(),
        )
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=scopes,
        trace=trace,
    ) as (address, context, _, _):
        forbidden, forbidden_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/trace/requests",
            command(requested),
            headers(),
        )
    assert request_response.status == 200 and terminal_response.status == 200
    assert other_run.status == 422
    assert json.loads(other_body)["error"]["message"] == (
        "payload run_id differs from route"
    )
    assert forbidden.status == 403
    assert json.loads(forbidden_body)["error"]["code"] == "forbidden"
    assert [call[0] for call in trace.calls] == ["request", "terminal"]


def test_inspector_routes_dispatch_to_queries_with_required_role_and_scope(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    queries = Queries()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read", "submissions:read", "manifests:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        run_response, run_body = request(address, context, "GET", f"/v1/runs/{OTHER}")
        runs_response, runs_body = request(
            address, context, "GET", f"/v1/runs?configuration_id={OTHER}"
        )
        submissions_response, submissions_body = request(
            address, context, "GET", f"/v1/submissions?submitter_id={OTHER}"
        )
        manifest_response, manifest_body = request(
            address, context, "GET", f"/v1/manifests/{HASH}"
        )
        missing_run, missing_run_body = request(
            address, context, "GET", f"/v1/runs/{PRINCIPAL}"
        )
        wrong_role_response, wrong_role_body = request(
            address, wrong_context, "GET", f"/v1/runs/{OTHER}"
        )
    assert run_response.status == 200
    assert json.loads(run_body)["data"]["run_id"] == OTHER
    assert runs_response.status == 200
    assert json.loads(runs_body)["data"]["runs"] == [{"run_id": OTHER}]
    assert json.loads(runs_body)["data"]["next_cursor"] is None
    assert submissions_response.status == 200
    assert json.loads(submissions_body)["data"]["submissions"] == [
        {"submission_id": OTHER}
    ]
    assert manifest_response.status == 200
    assert json.loads(manifest_body)["data"]["artifact_hash"] == HASH
    assert missing_run.status == 404
    assert json.loads(missing_run_body)["error"]["code"] == "not_found"
    assert wrong_role_response.status == 404
    assert json.loads(wrong_role_body)["error"]["code"] == "not_found"
    assert queries.calls[0] == ("run", (OTHER,))
    assert queries.calls[1] == ("runs_by_configuration", (OTHER, None))
    assert queries.calls[2] == ("submissions_by_submitter", (OTHER,))
    assert queries.calls[3] == ("manifest", (HASH,))


def test_inspector_run_listing_round_trips_a_cursor(tmp_path: Path) -> None:
    jobs = Jobs()
    queries = Queries()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        response, body = request(
            address,
            context,
            "GET",
            f"/v1/runs?configuration_id={OTHER}&cursor="
            f"2026-09-22T00%3A00%3A00.000000Z%2C{OTHER}",
        )
    assert response.status == 200
    assert queries.calls[0] == (
        "runs_by_configuration",
        (OTHER, ("2026-09-22T00:00:00.000000Z", OTHER)),
    )


def test_inspector_routes_reject_malformed_query_parameters(tmp_path: Path) -> None:
    jobs = Jobs()
    queries = Queries()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read", "submissions:read", "manifests:read"}),
        queries=queries,
    ) as (address, context, _, _):
        bad_configuration, bad_configuration_body = request(
            address, context, "GET", "/v1/runs?configuration_id=not-a-uuid"
        )
        bad_cursor, bad_cursor_body = request(
            address,
            context,
            "GET",
            f"/v1/runs?configuration_id={OTHER}&cursor=not-a-cursor",
        )
        bad_submitter, bad_submitter_body = request(
            address, context, "GET", "/v1/submissions?submitter_id=not-a-uuid"
        )
        manifest_with_query, manifest_with_query_body = request(
            address, context, "GET", f"/v1/manifests/{HASH}?extra=1"
        )
    assert bad_configuration.status == 422
    assert json.loads(bad_configuration_body)["error"]["code"] == "invalid_input"
    assert bad_cursor.status == 422
    assert json.loads(bad_cursor_body)["error"]["code"] == "invalid_input"
    assert bad_submitter.status == 422
    assert json.loads(bad_submitter_body)["error"]["code"] == "invalid_input"
    assert manifest_with_query.status == 404
    assert json.loads(manifest_with_query_body)["error"]["code"] == "not_found"
    assert queries.calls == []


def test_run_listing_selects_by_batch_or_paper(tmp_path: Path) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        batch, batch_body = request(
            address, context, "GET", f"/v1/runs?batch_id={HASH}"
        )
        paper, paper_body = request(
            address,
            context,
            "GET",
            "/v1/runs?paper_id=arxiv%3A2409.00001&cursor="
            f"2026-09-22T00%3A00%3A00.000000Z%2C{OTHER}",
        )
    assert batch.status == 200
    assert json.loads(batch_body)["data"] == {"runs": [], "next_cursor": None}
    assert paper.status == 200
    assert json.loads(paper_body)["data"]["runs"] == [
        {"run_id": OTHER, "paper_id": "arxiv:2409.00001"}
    ]
    assert queries.calls == [
        ("runs_by_batch", (HASH, None)),
        (
            "runs_by_paper",
            ("arxiv:2409.00001", ("2026-09-22T00:00:00.000000Z", OTHER)),
        ),
    ]


def test_run_listing_requires_exactly_one_admitted_filter(tmp_path: Path) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        responses = [
            request(address, context, "GET", path)
            for path in (
                "/v1/runs",
                f"/v1/runs?batch_id={HASH}&paper_id=p",
                f"/v1/runs?batch_id={HASH}&batch_id={HASH}",
                f"/v1/runs?configuration_id={OTHER}&extra=1",
                "/v1/runs?batch_id=not-a-hash",
                f"/v1/runs?paper_id={'p' * 129}",
            )
        ]
    for response, body in responses:
        assert response.status == 422
        assert json.loads(body)["error"]["code"] == "invalid_input"
    assert queries.calls == []


def test_sheet_read_needs_the_inspector_role_and_forecasts_scope(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"forecasts:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        found, found_body = request(address, context, "GET", f"/v1/sheets/{HASH}")
        missing, _ = request(address, context, "GET", f"/v1/sheets/{'b' * 64}")
        with_query, _ = request(address, context, "GET", f"/v1/sheets/{HASH}?x=1")
        wrong_role, _ = request(address, wrong_context, "GET", f"/v1/sheets/{HASH}")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=Queries(),
    ) as (address, context, _, _):
        unscoped, _ = request(address, context, "GET", f"/v1/sheets/{HASH}")
    assert found.status == 200
    assert json.loads(found_body)["data"]["questions"] == [{"question_id": OTHER}]
    assert missing.status == 404
    assert with_query.status == 404
    assert wrong_role.status == 404
    assert unscoped.status == 404
    assert queries.calls == [("sheet", (HASH,)), ("sheet", ("b" * 64,))]


POPULATION_SCOPES = frozenset({"configurations:read", "forecasts:read"})


def test_population_routes_dispatch_to_queries_for_the_inspector_role(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=POPULATION_SCOPES,
        queries=queries,
    ) as (address, context, _, _):
        listing, listing_body = request(address, context, "GET", "/v1/configurations")
        single, single_body = request(
            address, context, "GET", f"/v1/configurations/{OTHER}"
        )
        missing, missing_body = request(
            address, context, "GET", f"/v1/configurations/{PRINCIPAL}"
        )
        forecasts, forecasts_body = request(
            address, context, "GET", f"/v1/configurations/{OTHER}/forecasts"
        )
    assert listing.status == 200
    assert json.loads(listing_body)["data"] == {
        "configurations": [{"configuration_id": OTHER}],
        "next_cursor": f"2026-09-22T00:00:00.000000Z,{OTHER}",
    }
    assert single.status == 200
    assert json.loads(single_body)["data"]["configuration_id"] == OTHER
    assert missing.status == 404
    assert json.loads(missing_body)["error"]["code"] == "not_found"
    assert forecasts.status == 200
    assert json.loads(forecasts_body)["data"] == {
        "forecasts": [{"submission_id": OTHER, "resolution": None}],
        "next_cursor": None,
    }
    assert queries.calls == [
        ("configurations", (None,)),
        ("configuration", (OTHER,)),
        ("configuration", (str(PRINCIPAL),)),
        ("forecasts_by_configuration", (OTHER, None)),
    ]


def test_population_routes_are_refused_without_the_inspector_role(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="scorer",
        extra_scopes=POPULATION_SCOPES,
        queries=queries,
    ) as (address, context, wrong_context, _):
        responses = [
            request(address, selected, "GET", path)
            for selected in (context, wrong_context)
            for path in (
                "/v1/configurations",
                f"/v1/configurations/{OTHER}",
                f"/v1/configurations/{OTHER}/forecasts",
            )
        ]
    for response, body in responses:
        assert response.status == 404
        assert json.loads(body)["error"]["code"] == "not_found"
    assert queries.calls == []


def test_population_routes_are_refused_without_their_scope(tmp_path: Path) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        responses = [
            request(address, context, "GET", path)
            for path in (
                "/v1/configurations",
                f"/v1/configurations/{OTHER}",
                f"/v1/configurations/{OTHER}/forecasts",
            )
        ]
    for response, _body in responses:
        assert response.status == 404
    assert queries.calls == []


def test_population_listings_round_trip_a_cursor_and_reject_malformed_ones(
    tmp_path: Path,
) -> None:
    queries = Queries()
    cursor = f"2026-09-22T00%3A00%3A00.000000Z%2C{OTHER}"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=POPULATION_SCOPES,
        queries=queries,
    ) as (address, context, _, _):
        listing, _ = request(
            address, context, "GET", f"/v1/configurations?cursor={cursor}"
        )
        forecasts, _ = request(
            address,
            context,
            "GET",
            f"/v1/configurations/{OTHER}/forecasts?cursor={cursor}",
        )
        bad_cursor, bad_cursor_body = request(
            address, context, "GET", "/v1/configurations?cursor=not-a-cursor"
        )
        extra, extra_body = request(
            address, context, "GET", "/v1/configurations?island=cs"
        )
        with_query, _ = request(
            address, context, "GET", f"/v1/configurations/{OTHER}?extra=1"
        )
        bad_id, _ = request(address, context, "GET", "/v1/configurations/not-a-uuid")
    assert listing.status == 200
    assert forecasts.status == 200
    assert bad_cursor.status == 422
    assert json.loads(bad_cursor_body)["error"]["code"] == "invalid_input"
    assert extra.status == 422
    assert json.loads(extra_body)["error"]["code"] == "invalid_input"
    assert with_query.status == 404
    assert bad_id.status == 404
    decoded = ("2026-09-22T00:00:00.000000Z", OTHER)
    assert queries.calls == [
        ("configurations", (decoded,)),
        ("forecasts_by_configuration", (OTHER, decoded)),
    ]
