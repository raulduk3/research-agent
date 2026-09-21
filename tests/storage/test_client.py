from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    canonical_json,
)
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import (
    ResponseMetadata,
    StorageClient,
    StorageClientError,
    StorageTransportError,
)
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.jobs import JobRepository
from test_http import KEY, OTHER, PRINCIPAL, _tls_material, server


def client(
    tmp_path: Path, address: tuple[str, int], scopes: frozenset[str]
) -> StorageClient:
    return StorageClient(
        connect_host=address[0],
        port=address[1],
        server_hostname="localhost",
        ca_file=tmp_path / "ca.pem",
        client_cert_file=tmp_path / "client.pem",
        client_key_file=tmp_path / "client.key",
        scopes=scopes,
        timeout_seconds=2,
    )


def jobs(database: Database, store: ArtifactStore) -> JobRepository:
    return JobRepository(
        database,
        store,
        producer=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )


def test_client_rejects_unknown_scope_before_opening_a_connection(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="scopes"):
        StorageClient(
            connect_host="127.0.0.1",
            port=443,
            server_hostname="localhost",
            ca_file=tmp_path / "absent-ca",
            client_cert_file=tmp_path / "absent-cert",
            client_key_file=tmp_path / "absent-key",
            scopes=frozenset({"sql:execute"}),
        )


@pytest.mark.integration
def test_claim_replay_and_typed_error_cross_real_postgres_and_mtls(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    repository = jobs(Database(postgres_dsn), ArtifactStore(artifact_root))
    tls = _tls_material(tmp_path)
    with server(repository, tls) as (address, _, _, _):
        storage = client(
            tmp_path,
            address,
            frozenset({"jobs:claim", "jobs:renew"}),
        )
        command_id, request_id = uuid4(), uuid4()
        first = storage.claim(
            worker_id=PRINCIPAL,
            kinds=("extract",),
            command_id=command_id,
            request_id=request_id,
            idempotency_key=UUID(KEY),
        )
        replay = storage.claim(
            worker_id=PRINCIPAL,
            kinds=("extract",),
            command_id=command_id,
            request_id=uuid4(),
            idempotency_key=UUID(KEY),
        )
        with pytest.raises(StorageClientError) as raised:
            storage.renew(
                job_id=UUID(OTHER),
                worker_id=PRINCIPAL,
                lease_epoch=1,
                command_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            )
        wrong_hostname = StorageClient(
            connect_host=address[0],
            port=address[1],
            server_hostname="not-storage.invalid",
            ca_file=tmp_path / "ca.pem",
            client_cert_file=tmp_path / "client.pem",
            client_key_file=tmp_path / "client.key",
            scopes=frozenset({"jobs:claim"}),
            timeout_seconds=2,
        )
        with pytest.raises(StorageTransportError, match="not retried"):
            wrong_hostname.claim(
                worker_id=PRINCIPAL,
                kinds=("extract",),
                command_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            )
    assert first.data == {"lease": None}
    assert replay.response.replayed
    assert replay.request_id == str(request_id)
    assert replay.response.body == first.response.body
    assert raised.value.status_code == 409
    assert raised.value.code == "state_conflict"
    assert not raised.value.retryable
    assert raised.value.body


@pytest.mark.integration
def test_artifact_publish_and_read_use_job_fence_and_exact_bytes(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    job_repository = jobs(database, store)
    artifacts = ArtifactRepository(database, store)
    producer = ProducerVersion("a" * 64, "b" * 40, 1)
    seed = b'{"seed":1}'
    seed_publication = artifacts.publish(
        [seed],
        expected_hash=hashlib.sha256(seed).hexdigest(),
        byte_length=len(seed),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=producer,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    job_repository.execute(
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
    job_repository.execute(
        "claim",
        identity=CommandIdentity(PRINCIPAL, uuid4(), uuid4(), uuid4()),
        payload={"worker_id": str(PRINCIPAL), "kinds": ["extract"]},
    )
    tls = _tls_material(tmp_path)
    payload = b'{"client-upload":1}'
    digest = hashlib.sha256(payload).hexdigest()
    with server(
        job_repository,
        tls,
        artifact_repository=artifacts,
        authorization=StorageAuthorization(database),
    ) as (address, _, _, _):
        storage = client(
            tmp_path,
            address,
            frozenset({"artifacts:publish", "artifacts:read"}),
        )
        command_id, request_id, key = uuid4(), uuid4(), uuid4()
        first = storage.publish_artifact(
            payload,
            expected_hash=digest,
            media_type="application/json",
            kind="manifest",
            input_hashes=(),
            producer_version=producer,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            source_available_at=None,
            job_id=UUID(OTHER),
            lease_epoch=1,
            command_id=command_id,
            request_id=request_id,
            idempotency_key=key,
        )
        replay = storage.publish_artifact(
            payload,
            expected_hash=digest,
            media_type="application/json",
            kind="manifest",
            input_hashes=(),
            producer_version=producer,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            source_available_at=None,
            job_id=UUID(OTHER),
            lease_epoch=1,
            command_id=command_id,
            request_id=uuid4(),
            idempotency_key=key,
        )
        downloaded = storage.read_artifact(
            hashlib.sha256(seed).hexdigest(), job_id=UUID(OTHER), lease_epoch=1
        )
    assert first.response.status_code == 201
    assert replay.response.replayed
    assert replay.request_id == str(request_id)
    assert replay.response.body == first.response.body
    assert downloaded.payload == seed
    assert downloaded.media_type == "application/json"
    assert downloaded.response.body == seed


def test_client_validates_command_and_artifact_types_locally(tmp_path: Path) -> None:
    _tls_material(tmp_path)
    storage = client(
        tmp_path,
        ("127.0.0.1", 1),
        frozenset({"jobs:claim", "artifacts:publish"}),
    )
    with pytest.raises(ContractValidationError):
        storage.claim(
            worker_id=PRINCIPAL,
            kinds=("unknown",),
            command_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    with pytest.raises(ContractValidationError):
        storage.publish_artifact(
            b"x",
            expected_hash="a" * 64,
            media_type="application/x-python-pickle",
            kind="manifest",
            input_hashes=(),
            producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            source_available_at=None,
            job_id=uuid4(),
            lease_epoch=1,
            command_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )


def test_multipart_boundary_avoids_payload_collision(tmp_path: Path) -> None:
    _tls_material(tmp_path)
    storage = client(tmp_path, ("127.0.0.1", 1), frozenset({"artifacts:publish"}))
    command_id = uuid4()
    first_boundary = (
        "research-agent-"
        + hashlib.sha256(command_id.bytes + (0).to_bytes(8, "big")).hexdigest()
    )
    payload = f"prelude\r\n--{first_boundary}\r\npostlude".encode()
    seen: dict[str, object] = {}

    def capture(
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
        *,
        maximum_bytes: int,
    ):  # type: ignore[no-untyped-def]
        seen.update({"body": body, "headers": headers})
        from research_agent.storage.client import ResponseMetadata

        response_body = canonical_json(
            {
                "schema_version": 1,
                "request_id": str(request_id),
                "status": "ok",
                "data": {
                    "artifact_hash": hashlib.sha256(payload).hexdigest(),
                    "byte_length": len(payload),
                    "created_at": "2026-09-21T00:00:00.000000Z",
                    "receipt": {
                        "record_ids": [],
                        "artifact_hashes": [],
                        "ledger_first": None,
                        "ledger_last": None,
                        "committed_at": "2026-09-21T00:00:00.000000Z",
                    },
                },
                "error": None,
            }
        )
        return ResponseMetadata(201, (), response_body)

    # Only transport is intercepted; the real multipart builder and typed reply
    # decoder run unchanged, with a deliberately colliding binary payload.
    request_id = uuid4()
    storage._request = capture  # type: ignore[method-assign]
    storage.publish_artifact(
        payload,
        expected_hash=hashlib.sha256(payload).hexdigest(),
        media_type="application/octet-stream",
        kind="manifest",
        input_hashes=(),
        producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        source_available_at=None,
        job_id=uuid4(),
        lease_epoch=1,
        command_id=command_id,
        request_id=request_id,
        idempotency_key=uuid4(),
    )
    assert isinstance(seen["headers"], dict)
    assert first_boundary not in seen["headers"]["Content-Type"]
    assert isinstance(seen["body"], bytes)
    assert seen["body"].count(first_boundary.encode()) == 1


def test_malformed_error_envelopes_are_typed_transport_failures(tmp_path: Path) -> None:
    _tls_material(tmp_path)
    storage = client(tmp_path, ("127.0.0.1", 1), frozenset({"jobs:claim"}))
    for bad in ([], ["not-a-hash"]):
        body = canonical_json(
            {
                "schema_version": 1,
                "request_id": str(uuid4()),
                "status": "error",
                "data": None,
                "error": {
                    "code": bad,
                    "message": "invalid",
                    "retryable": False,
                    "evidence_ids": [] if bad == [] else bad,
                },
            }
        )
        with pytest.raises(StorageTransportError):
            storage._raise_error(ResponseMetadata(422, (), body))


def test_response_budget_rejects_nonfinite_timeout(
    tmp_path: Path,
) -> None:
    _tls_material(tmp_path)
    with pytest.raises(ValueError, match="timeout"):
        StorageClient(
            connect_host="127.0.0.1",
            port=443,
            server_hostname="localhost",
            ca_file=tmp_path / "ca.pem",
            client_cert_file=tmp_path / "client.pem",
            client_key_file=tmp_path / "client.key",
            scopes=frozenset({"jobs:claim"}),
            timeout_seconds=float("nan"),
        )


@pytest.mark.parametrize("declared_length", [str(1024 * 1024 + 1), "9" * 5000])
def test_real_mtls_response_limit_refuses_oversized_declared_length(
    tmp_path: Path,
    declared_length: str,
) -> None:
    server_context, _, _, _, _, _ = _tls_material(tmp_path)

    class OversizedHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", declared_length)
            self.end_headers()
            self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            pass

    server_socket = ThreadingHTTPServer(("127.0.0.1", 0), OversizedHandler)
    server_socket.socket = server_context.wrap_socket(
        server_socket.socket, server_side=True
    )
    thread = threading.Thread(target=server_socket.serve_forever)
    thread.start()
    try:
        storage = client(
            tmp_path,
            ("127.0.0.1", server_socket.server_port),
            frozenset({"jobs:claim"}),
        )
        with pytest.raises(
            StorageTransportError, match="(admitted limit|length is invalid)"
        ):
            storage.claim(
                worker_id=PRINCIPAL,
                kinds=("extract",),
                command_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            )
    finally:
        server_socket.shutdown()
        server_socket.server_close()
        thread.join()
