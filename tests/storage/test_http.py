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
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.http import (
    JobCommands,
    RecordCommands,
    ServiceCapability,
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


class Artifacts:
    def read(self, artifact_hash: str) -> tuple[tuple[int, str], io.BytesIO]:
        assert artifact_hash == HASH
        return (7, "text/plain"), io.BytesIO(b"payload")

    def publish_command(self, *args: object, **kwargs: object) -> StoredResponse:
        raise AssertionError("malformed upload must not publish")


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
    authorization: StorageAuthorization | None = None,
    role: str = "reader",
    extra_scopes: frozenset[str] = frozenset(),
    runs: RecordCommands | None = None,
    snapshots: RecordCommands | None = None,
    sheets: RecordCommands | None = None,
    submissions: RecordCommands | None = None,
    ratings: RecordCommands | None = None,
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
        runs=runs,
        snapshots=snapshots,
        sheets=sheets,
        submissions=submissions,
        ratings=ratings,
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
        extra_scopes=frozenset(
            {
                "snapshots:cards",
                "snapshots:graph",
                "snapshots:passages",
                "snapshots:questions",
            }
        ),
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
        extra_scopes=frozenset({"snapshots:cards"}),
        documents=documents,
    ) as (address, context, _, _):
        response, body = request(
            address, context, "GET", f"/v1/snapshots/{HASH}/passages/extra"
        )
    assert response.status == 404
    assert json.loads(body)["error"]["code"] == "not_found"
