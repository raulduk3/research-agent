"""Fail-closed stdlib HTTP adapter for the version-one storage boundary."""

from __future__ import annotations

import hashlib
import hmac
import ssl
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import MappingProxyType
from typing import IO, Any, BinaryIO, Protocol, cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from research_agent.contracts import (
    CanonicalJsonError,
    ContractValidationError,
    ProducerVersion,
    canonical_json,
    canonical_loads,
    validate_non_negative_int,
    validate_sha256,
    validate_uuid4,
)
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.authorization import JobScope, StorageAuthorization
from research_agent.storage.artifacts import PublicationAdmission
from research_agent.storage.errors import (
    IdempotencyConflict,
    IntegrityFailure,
    LeaseExpired,
    StaleLease,
    StateConflict,
    StorageError,
    TransactionUnavailable,
    UnavailableInput,
)
from research_agent.storage.idempotency import StoredResponse

SNAPSHOT_READ_KINDS = frozenset({"cards", "graph", "passages", "questions"})
SNAPSHOT_READ_ROLES = frozenset({"tools"})


MAXIMUM_JSON_BYTES = 1024 * 1024
JOB_ROLE_KINDS = {
    "ingest": frozenset({"capture", "assess"}),
    "reader": frozenset({"extract"}),
    "models": frozenset({"embed", "fit", "calibrate", "predict"}),
    "scorer": frozenset({"score"}),
    "baseline_producer": frozenset({"baseline"}),
}
ARTIFACT_READ_ROLES = frozenset(
    {
        "ingest",
        "reader",
        "models",
        "tools",
        "orchestrator",
        "operator",
        "backup_integration",
        "restore_verifier",
    }
)
ARTIFACT_PUBLISH_ROLES = frozenset(
    {
        "ingest",
        "reader",
        "models",
        "tools",
        "scorer",
        "orchestrator",
        "baseline_producer",
        "operator",
    }
)
ARTIFACT_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/pdf",
        "application/octet-stream",
        "image/png",
        "text/plain",
    }
)
ARTIFACT_KINDS = frozenset(
    {
        "source_response",
        "source_document",
        "extraction",
        "vector_payload",
        "model_weights",
        "tokenizer",
        "manifest",
        "tool_request",
        "tool_response",
        "provider_response",
        "study_evidence",
        "signature_evidence",
    }
)
RECORD_ROLES: Mapping[str, frozenset[str]] = {
    "runs": frozenset({"orchestrator"}),
    "snapshots": frozenset({"orchestrator"}),
    "sheets": frozenset({"orchestrator", "rating_app"}),
    "submissions": frozenset({"orchestrator", "baseline_producer", "rating_app"}),
    "ratings": frozenset({"rating_app"}),
    "raters": frozenset({"operator"}),
}
RATER_READ_ROLES = frozenset({"rating_app"})
ARTIFACT_ROLE_KINDS = {
    "ingest": frozenset({"source_response", "source_document", "manifest"}),
    "reader": frozenset({"extraction", "vector_payload", "manifest"}),
    "models": frozenset({"vector_payload", "model_weights", "tokenizer", "manifest"}),
    "tools": frozenset(
        {"tool_request", "tool_response", "provider_response", "manifest"}
    ),
    "scorer": frozenset({"manifest"}),
    "baseline_producer": frozenset({"manifest"}),
    "orchestrator": frozenset({"manifest"}),
    "operator": frozenset({"manifest", "study_evidence", "signature_evidence"}),
}


class JobCommands(Protocol):
    def execute(
        self,
        operation: str,
        *,
        identity: CommandIdentity,
        payload: object,
        job_id: UUID | None = None,
    ) -> StoredResponse: ...


class RecordCommands(Protocol):
    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse: ...


class RaterCommands(RecordCommands, Protocol):
    def list_principals(self) -> tuple[dict[str, Any], ...]: ...


class ArtifactReads(Protocol):
    def read(self, artifact_hash: str) -> tuple[tuple[int, str], BinaryIO]: ...

    def publish_command(
        self,
        chunks: Any,
        *,
        identity: CommandIdentity,
        expected_hash: str,
        byte_length: int,
        maximum_length: int,
        media_type: str,
        kind: str,
        input_hashes: tuple[str, ...],
        producer_version: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
        source_available_at: str | None,
        admission: PublicationAdmission,
    ) -> StoredResponse: ...


class SnapshotReads(Protocol):
    def cards(
        self, snapshot_hash: str, paper_version_ids: tuple[str, ...]
    ) -> tuple[dict[str, Any], ...]: ...

    def graph(self, snapshot_hash: str, paper_version_id: str) -> dict[str, Any]: ...

    def passage_index(
        self, snapshot_hash: str, paper_version_id: str
    ) -> dict[str, Any]: ...

    def questions(self, snapshot_hash: str) -> tuple[dict[str, Any], ...]: ...


@dataclass(frozen=True, slots=True)
class ServiceCapability:
    """Immutable local result of service credential provisioning."""

    principal_id: UUID
    role: str
    scopes: frozenset[str]
    job_kinds: frozenset[str] = frozenset()
    producer_version: ProducerVersion | None = None
    config_hash: str | None = None
    retention_policy_hash: str | None = None

    def __post_init__(self) -> None:
        validate_uuid4(str(self.principal_id))
        if self.role not in {
            "storage",
            "ingest",
            "reader",
            "models",
            "tools",
            "scorer",
            "orchestrator",
            "rating_app",
            "baseline_producer",
            "operator",
            "billing_reconciler",
            "anchor_integration",
            "backup_integration",
            "restore_verifier",
            "health_monitor",
        }:
            raise ValueError("unknown service role")
        if self.config_hash is not None:
            validate_sha256(self.config_hash)
        if self.retention_policy_hash is not None:
            validate_sha256(self.retention_policy_hash)


class StorageHttpApplication:
    """Authenticate capabilities and dispatch only implemented storage routes."""

    def __init__(
        self,
        jobs: JobCommands,
        capabilities: Mapping[str, ServiceCapability],
        *,
        authorization: StorageAuthorization,
        artifacts: ArtifactReads | None = None,
        documents: SnapshotReads | None = None,
        runs: RecordCommands | None = None,
        snapshots: RecordCommands | None = None,
        sheets: RecordCommands | None = None,
        submissions: RecordCommands | None = None,
        ratings: RecordCommands | None = None,
        raters: RaterCommands | None = None,
    ) -> None:
        if not capabilities:
            raise ValueError("at least one certificate identity is required")
        for fingerprint in capabilities:
            validate_sha256(fingerprint)
        self.jobs = jobs
        self.capabilities = MappingProxyType(dict(capabilities))
        self.authorization = authorization
        self.artifacts = artifacts
        self.documents = documents
        self.raters = raters
        self.records: dict[str, RecordCommands | None] = {
            "runs": runs,
            "snapshots": snapshots,
            "sheets": sheets,
            "submissions": submissions,
            "ratings": ratings,
            "raters": raters,
        }

    def authenticate(self, certificate: bytes | None) -> ServiceCapability | None:
        if certificate is None:
            return None
        supplied = hashlib.sha256(certificate).hexdigest()
        match: ServiceCapability | None = None
        for fingerprint, capability in self.capabilities.items():
            if hmac.compare_digest(supplied, fingerprint):
                match = capability
        return match


def create_storage_server(
    address: tuple[str, int],
    jobs: JobCommands,
    capabilities: Mapping[str, ServiceCapability],
    *,
    tls_context: ssl.SSLContext,
    authorization: StorageAuthorization,
    artifacts: ArtifactReads | None = None,
    documents: SnapshotReads | None = None,
    runs: RecordCommands | None = None,
    snapshots: RecordCommands | None = None,
    sheets: RecordCommands | None = None,
    submissions: RecordCommands | None = None,
    ratings: RecordCommands | None = None,
    raters: RaterCommands | None = None,
) -> ThreadingHTTPServer:
    if tls_context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("storage HTTP requires verified client certificates")
    application = StorageHttpApplication(
        jobs,
        capabilities,
        authorization=authorization,
        artifacts=artifacts,
        documents=documents,
        runs=runs,
        snapshots=snapshots,
        sheets=sheets,
        submissions=submissions,
        ratings=ratings,
        raters=raters,
    )

    class Handler(_StorageRequestHandler):
        app = application

    server = ThreadingHTTPServer(address, Handler)
    server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    return server


class _StorageRequestHandler(BaseHTTPRequestHandler):
    app: StorageHttpApplication
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        request_id = str(uuid4())
        capability = self.app.authenticate(self._peer_certificate())
        if capability is None:
            self._error(401, request_id, "unauthenticated", "authentication required")
            return
        path = urlsplit(self.path)
        if path.query or path.fragment:
            self._error(404, request_id, "not_found", "route not found")
            return
        route = self._job_route(path.path)
        if route is None:
            record_route = self._record_route(path.path)
            if record_route is not None:
                self._post_record(capability, request_id, *record_route)
            elif path.path == "/v1/artifacts":
                self._post_artifact(capability, request_id)
            else:
                self._error(404, request_id, "not_found", "route not found")
            return
        operation, job_id = route
        if (
            capability.role not in JOB_ROLE_KINDS
            or f"jobs:{operation}" not in capability.scopes
        ):
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        command = self._read_command(request_id)
        if command is None:
            return
        request_id = command["request_id"]
        key = self._idempotency_key(request_id)
        if key is None:
            return
        payload = command["payload"]
        if operation == "claim" and not self._claim_kinds_are_admitted(
            payload,
            capability.job_kinds & JOB_ROLE_KINDS[capability.role],
        ):
            self._error(
                403,
                request_id,
                "forbidden",
                "capability does not permit requested job kinds",
            )
            return
        if not self._worker_is_principal(operation, payload, capability.principal_id):
            self._error(
                403, request_id, "forbidden", "worker identity is not principal"
            )
            return
        identity = CommandIdentity(
            capability.principal_id,
            key,
            UUID(command["command_id"]),
            UUID(request_id),
        )
        if operation != "claim" and job_id is not None:
            epoch = self._lease_epoch(operation, payload)
            if epoch is not None and not self.app.authorization.job_fence_allowed(
                principal_id=capability.principal_id,
                role_kinds=capability.job_kinds & JOB_ROLE_KINDS[capability.role],
                job_id=job_id,
                lease_epoch=epoch,
                command_id=identity.command_id,
                idempotency_key=identity.key,
            ):
                self._error(403, request_id, "forbidden", "job scope is not admitted")
                return
        try:
            response = self.app.jobs.execute(
                operation, identity=identity, payload=payload, job_id=job_id
            )
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_json(
            response.status_code,
            response.body,
            replayed=response.replayed,
        )

    def _post_record(
        self,
        capability: ServiceCapability,
        request_id: str,
        domain: str,
        operation: str,
    ) -> None:
        owner = self.app.records.get(domain)
        if (
            owner is None
            or capability.role not in RECORD_ROLES[domain]
            or f"{domain}:{operation}" not in capability.scopes
        ):
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        command = self._read_command(request_id)
        if command is None:
            return
        request_id = command["request_id"]
        key = self._idempotency_key(request_id)
        if key is None:
            return
        identity = CommandIdentity(
            capability.principal_id, key, UUID(command["command_id"]), UUID(request_id)
        )
        try:
            response = owner.execute(
                operation, identity=identity, payload=command["payload"]
            )
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_json(response.status_code, response.body, replayed=response.replayed)

    def _post_artifact(self, capability: ServiceCapability, request_id: str) -> None:
        if (
            self.app.artifacts is None
            or capability.role not in ARTIFACT_PUBLISH_ROLES
            or "artifacts:publish" not in capability.scopes
        ):
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        try:
            metadata, payload = self._read_artifact_upload()
            request_id = metadata["request_id"]
            if (
                capability.producer_version is None
                or capability.config_hash is None
                or capability.retention_policy_hash is None
                or metadata["producer_version"] != capability.producer_version
                or metadata["config_hash"] != capability.config_hash
                or metadata["retention_policy_hash"] != capability.retention_policy_hash
            ):
                payload.close()
                self._error(403, request_id, "forbidden", "deployment binding mismatch")
                return
            if metadata["kind"] not in ARTIFACT_ROLE_KINDS.get(
                capability.role, frozenset()
            ):
                payload.close()
                self._error(
                    403, request_id, "forbidden", "role cannot publish artifact kind"
                )
                return
            key = self._idempotency_key(request_id)
            if key is None:
                payload.close()
                return
            replay = self.app.authorization.command_completed(
                principal_id=capability.principal_id,
                command_id=UUID(metadata["command_id"]),
                idempotency_key=key,
            )
            scope = self._job_scope()
            role_kinds = capability.job_kinds & JOB_ROLE_KINDS.get(
                capability.role, frozenset()
            )
            if scope is None:
                payload.close()
                self._error(404, request_id, "not_found", "artifact not found")
                return
            if not replay and (
                not self.app.authorization.job_scope_active(
                    principal_id=capability.principal_id,
                    role_kinds=role_kinds,
                    scope=scope,
                )
                or any(
                    not self.app.authorization.artifact_in_job_scope(
                        principal_id=capability.principal_id,
                        role_kinds=role_kinds,
                        scope=scope,
                        artifact_hash=artifact_hash,
                    )
                    for artifact_hash in metadata["input_hashes"]
                )
            ):
                payload.close()
                self._error(404, request_id, "not_found", "artifact not found")
                return
            try:
                response = self.app.artifacts.publish_command(
                    iter(lambda: payload.read(64 * 1024), b""),
                    identity=CommandIdentity(
                        capability.principal_id,
                        key,
                        UUID(metadata["command_id"]),
                        UUID(request_id),
                    ),
                    expected_hash=metadata["expected_hash"],
                    byte_length=metadata["byte_length"],
                    maximum_length=128 * 1024**3
                    if metadata["kind"] == "model_weights"
                    else 1024**3,
                    media_type=metadata["media_type"],
                    kind=metadata["kind"],
                    input_hashes=tuple(metadata["input_hashes"]),
                    producer_version=metadata["producer_version"],
                    config_hash=metadata["config_hash"],
                    retention_policy_hash=metadata["retention_policy_hash"],
                    source_available_at=metadata["source_available_at"],
                    admission=PublicationAdmission(
                        scope.job_id,
                        scope.lease_epoch,
                        capability.principal_id,
                        role_kinds,
                    ),
                )
            finally:
                payload.close()
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except (EOFError, OSError, ValueError):
            self._error(
                400, request_id, "malformed_json", "malformed multipart request"
            )
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_json(response.status_code, response.body, replayed=response.replayed)

    def _read_artifact_upload(self) -> tuple[dict[str, Any], BinaryIO]:
        content_type = self.headers.get("Content-Type", "")
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError as error:
            raise ContractValidationError("valid Content-Length required") from error
        if (
            not content_type.startswith("multipart/form-data;")
            or not 0 <= length <= 128 * 1024**3 + 256 * 1024
        ):
            raise ContractValidationError("invalid multipart request")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from cgi import FieldStorage

            form = FieldStorage(
                fp=cast(IO[Any], self.rfile),
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                    "CONTENT_LENGTH": str(length),
                },
                keep_blank_values=True,
            )
        parts = form.list
        if (
            parts is None
            or len(parts) != 2
            or {part.name for part in parts} != {"metadata", "payload"}
        ):
            raise ContractValidationError(
                "multipart body must contain exactly metadata and payload"
            )
        by_name = {part.name: part for part in parts}
        metadata_part, payload_part = by_name["metadata"], by_name["payload"]
        if (
            metadata_part.type != "application/json"
            or payload_part.type != "application/octet-stream"
        ):
            raise ContractValidationError("multipart part content types are invalid")
        raw = metadata_part.file.read(128 * 1024 + 1)
        if isinstance(raw, str):
            raw = raw.encode()
        if len(raw) > 128 * 1024:
            raise ContractValidationError("artifact metadata exceeds 128 KiB")
        try:
            value = canonical_loads(raw)
        except CanonicalJsonError as error:
            raise ContractValidationError(
                "artifact metadata is malformed JSON"
            ) from error
        fields = {
            "schema_version",
            "command_id",
            "request_id",
            "expected_hash",
            "byte_length",
            "media_type",
            "kind",
            "input_hashes",
            "producer_version",
            "config_hash",
            "source_available_at",
            "retention_policy_hash",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise ContractValidationError(
                "ArtifactUpload has unknown or missing fields"
            )
        metadata: dict[str, Any] = dict(value)
        if isinstance(value["schema_version"], bool) or value["schema_version"] != 1:
            raise ContractValidationError("ArtifactUpload.schema_version must be 1")
        validate_uuid4(value["command_id"])
        validate_uuid4(value["request_id"])
        validate_sha256(value["expected_hash"])
        validate_non_negative_int(value["byte_length"])
        if (
            value["media_type"] not in ARTIFACT_MEDIA_TYPES
            or value["kind"] not in ARTIFACT_KINDS
        ):
            raise ContractValidationError(
                "ArtifactUpload media type or kind is invalid"
            )
        inputs = value["input_hashes"]
        if not isinstance(inputs, list) or len(inputs) > 1000:
            raise ContractValidationError("ArtifactUpload.input_hashes is invalid")
        metadata["input_hashes"] = [validate_sha256(item) for item in inputs]
        producer = value["producer_version"]
        if not isinstance(producer, dict):
            raise ContractValidationError("ArtifactUpload.producer_version is invalid")
        metadata["producer_version"] = ProducerVersion.from_json(
            canonical_json(producer)
        )
        validate_sha256(value["config_hash"])
        validate_sha256(value["retention_policy_hash"])
        if value["source_available_at"] is not None:
            from research_agent.contracts import validate_utc_instant

            validate_utc_instant(value["source_available_at"])
        self._artifact_form = form
        return metadata, payload_part.file

    def do_GET(self) -> None:  # noqa: N802
        request_id = str(uuid4())
        capability = self.app.authenticate(self._peer_certificate())
        if capability is None:
            self._error(401, request_id, "unauthenticated", "authentication required")
            return
        path = urlsplit(self.path)
        if path.fragment:
            self._error(404, request_id, "not_found", "route not found")
            return
        snapshot_route = self._snapshot_route(path.path)
        if snapshot_route is not None:
            self._get_snapshot(capability, request_id, snapshot_route, path.query)
            return
        if path.path == "/v1/raters":
            if path.query:
                self._error(404, request_id, "not_found", "route not found")
                return
            self._get_raters(capability, request_id)
            return
        prefix = "/v1/artifacts/"
        if path.query or not path.path.startswith(prefix):
            self._error(404, request_id, "not_found", "route not found")
            return
        artifact_hash = path.path[len(prefix) :]
        try:
            validate_sha256(artifact_hash)
        except ContractValidationError:
            self._error(404, request_id, "not_found", "artifact not found")
            return
        if (
            self.app.artifacts is None
            or capability.role not in ARTIFACT_READ_ROLES
            or "artifacts:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "artifact not found")
            return
        scope = self._job_scope()
        if scope is None or not self.app.authorization.artifact_in_job_scope(
            principal_id=capability.principal_id,
            role_kinds=capability.job_kinds
            & JOB_ROLE_KINDS.get(capability.role, frozenset()),
            scope=scope,
            artifact_hash=artifact_hash,
        ):
            self._error(404, request_id, "not_found", "artifact not found")
            return
        try:
            (length, media_type), stream = self.app.artifacts.read(artifact_hash)
        except (FileNotFoundError, UnavailableInput, IntegrityFailure):
            self._error(404, request_id, "not_found", "artifact not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(length))
        self.send_header("ETag", f'"{artifact_hash}"')
        self.send_header("Cache-Control", "private, no-transform")
        self.end_headers()
        with stream:
            remaining = length
            while remaining:
                chunk = stream.read(min(64 * 1024, remaining))
                if not chunk:
                    self.close_connection = True
                    return
                self.wfile.write(chunk)
                remaining -= len(chunk)

    @staticmethod
    def _snapshot_route(path: str) -> tuple[str, str] | None:
        parts = path.split("/")
        if len(parts) != 5 or parts[:3] != ["", "v1", "snapshots"]:
            return None
        if parts[4] not in SNAPSHOT_READ_KINDS:
            return None
        try:
            validate_sha256(parts[3])
        except ContractValidationError:
            return None
        return parts[3], parts[4]

    def _get_snapshot(
        self,
        capability: ServiceCapability,
        request_id: str,
        route: tuple[str, str],
        query: str,
    ) -> None:
        snapshot_hash, kind = route
        if (
            self.app.documents is None
            or capability.role not in SNAPSHOT_READ_ROLES
            or f"snapshots:{kind}" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=False)
        try:
            data = self._read_snapshot(kind, snapshot_hash, params)
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_json(
            200,
            canonical_json(
                {
                    "schema_version": 1,
                    "request_id": request_id,
                    "status": "ok",
                    "data": data,
                    "error": None,
                }
            ),
        )

    def _get_raters(self, capability: ServiceCapability, request_id: str) -> None:
        if (
            self.app.raters is None
            or capability.role not in RATER_READ_ROLES
            or "raters:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        data = {"principals": list(self.app.raters.list_principals())}
        self._send_json(
            200,
            canonical_json(
                {
                    "schema_version": 1,
                    "request_id": request_id,
                    "status": "ok",
                    "data": data,
                    "error": None,
                }
            ),
        )

    def _read_snapshot(
        self, kind: str, snapshot_hash: str, params: dict[str, list[str]]
    ) -> dict[str, Any]:
        assert self.app.documents is not None
        if kind == "cards":
            paper_ids = tuple(self._repeated_uuids(params, "paper_id", 1, 5))
            return {
                "snapshot_id": snapshot_hash,
                "cards": list(self.app.documents.cards(snapshot_hash, paper_ids)),
            }
        if kind == "graph":
            paper_id = self._single_uuid(params, "paper_id")
            direction = self._single_choice(
                params,
                "direction",
                frozenset({"references", "citations"}),
                "references",
            )
            self._single_limit(params, "limit", 20, 20)
            return {
                "snapshot_id": snapshot_hash,
                "direction": direction,
                "graph": self.app.documents.graph(snapshot_hash, paper_id),
            }
        if kind == "passages":
            paper_id = self._single_uuid(params, "paper_id")
            passage_ids = self._repeated_hashes(params, "passage_id", 1, 20)
            index = self.app.documents.passage_index(snapshot_hash, paper_id)
            entries = index.get("passages")
            by_hash = (
                {
                    entry.get("text_hash"): entry
                    for entry in entries
                    if isinstance(entries, list) and isinstance(entry, dict)
                }
                if isinstance(entries, list)
                else {}
            )
            selected: list[Any] = []
            for passage_id in passage_ids:
                entry = by_hash.get(passage_id)
                if entry is None:
                    raise UnavailableInput("passage_id is not in the pinned index")
                selected.append(entry)
            return {"snapshot_id": snapshot_hash, "passages": selected}
        self._repeated_uuids(params, "paper_id", 1, 20)
        return {
            "snapshot_id": snapshot_hash,
            "questions": list(self.app.documents.questions(snapshot_hash)),
        }

    @staticmethod
    def _repeated_uuids(
        params: dict[str, list[str]], name: str, lower: int, upper: int
    ) -> tuple[str, ...]:
        values = params.get(name, [])
        if not lower <= len(values) <= upper:
            raise ContractValidationError(
                f"{name} must be repeated {lower} to {upper} times"
            )
        for value in values:
            validate_uuid4(value)
        return tuple(values)

    @staticmethod
    def _repeated_hashes(
        params: dict[str, list[str]], name: str, lower: int, upper: int
    ) -> tuple[str, ...]:
        values = params.get(name, [])
        if not lower <= len(values) <= upper:
            raise ContractValidationError(
                f"{name} must be repeated {lower} to {upper} times"
            )
        for value in values:
            validate_sha256(value)
        return tuple(values)

    @staticmethod
    def _single_uuid(params: dict[str, list[str]], name: str) -> str:
        values = params.get(name, [])
        if len(values) != 1:
            raise ContractValidationError(f"{name} is required exactly once")
        return validate_uuid4(values[0])

    @staticmethod
    def _single_choice(
        params: dict[str, list[str]], name: str, admitted: frozenset[str], default: str
    ) -> str:
        values = params.get(name, [default])
        if len(values) != 1 or values[0] not in admitted:
            raise ContractValidationError(f"{name} is not an admitted value")
        return values[0]

    @staticmethod
    def _single_limit(
        params: dict[str, list[str]], name: str, default: int, upper: int
    ) -> int:
        values = params.get(name, [str(default)])
        if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
            raise ContractValidationError(f"{name} must be a positive integer")
        limit = int(values[0])
        if not 1 <= limit <= upper:
            raise ContractValidationError(f"{name} must be from 1 to {upper}")
        return limit

    def _read_command(self, request_id: str) -> dict[str, Any] | None:
        if self.headers.get("Content-Type") != "application/json":
            self._error(
                422,
                request_id,
                "invalid_input",
                "Content-Type must be application/json",
            )
            return None
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self._error(
                400, request_id, "malformed_json", "valid Content-Length required"
            )
            return None
        if length > MAXIMUM_JSON_BYTES:
            self._error(422, request_id, "invalid_input", "JSON request exceeds 1 MiB")
            self.close_connection = True
            return None
        raw = self.rfile.read(length)
        try:
            value = canonical_loads(raw)
        except CanonicalJsonError:
            self._error(400, request_id, "malformed_json", "malformed JSON command")
            return None
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "command_id",
            "request_id",
            "payload",
        }:
            self._error(
                422,
                request_id,
                "invalid_input",
                "Command has unknown or missing fields",
            )
            return None
        try:
            if (
                isinstance(value["schema_version"], bool)
                or value["schema_version"] != 1
            ):
                raise ContractValidationError("Command.schema_version must be 1")
            validate_uuid4(value["command_id"])
            validate_uuid4(value["request_id"])
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return None
        return value

    def _peer_certificate(self) -> bytes | None:
        connection = self.connection
        if not isinstance(connection, ssl.SSLSocket):
            return None
        return connection.getpeercert(binary_form=True)

    def _idempotency_key(self, request_id: str) -> UUID | None:
        value = self.headers.get("Idempotency-Key")
        try:
            validate_uuid4(value)
            assert value is not None
            return UUID(value)
        except (ContractValidationError, ValueError):
            self._error(
                422, request_id, "invalid_input", "Idempotency-Key must be a UUIDv4"
            )
            return None

    def _job_scope(self) -> JobScope | None:
        raw_job, raw_epoch = (
            self.headers.get("X-Job-Id"),
            self.headers.get("X-Lease-Epoch"),
        )
        try:
            validate_uuid4(raw_job)
            if raw_epoch is None or not raw_epoch.isascii() or not raw_epoch.isdigit():
                return None
            epoch = int(raw_epoch)
            if epoch <= 0:
                return None
            assert raw_job is not None
            return JobScope(UUID(raw_job), epoch)
        except (ContractValidationError, ValueError):
            return None

    @staticmethod
    def _lease_epoch(operation: str, payload: object) -> int | None:
        if not isinstance(payload, dict):
            return None
        fence = payload if operation == "renew" else payload.get("fence")
        if not isinstance(fence, dict):
            return None
        epoch = fence.get("lease_epoch")
        return epoch if isinstance(epoch, int) and not isinstance(epoch, bool) else None

    @staticmethod
    def _worker_is_principal(
        operation: str, payload: object, principal_id: UUID
    ) -> bool:
        if not isinstance(payload, dict):
            return True
        fence = payload if operation == "renew" else payload.get("fence")
        worker = payload.get("worker_id") if operation == "claim" else None
        if isinstance(fence, dict):
            worker = fence.get("worker_id")
        return worker is None or worker == str(principal_id)

    @staticmethod
    def _claim_kinds_are_admitted(payload: object, admitted: frozenset[str]) -> bool:
        if not isinstance(payload, dict) or not isinstance(payload.get("kinds"), list):
            return True
        kinds = payload["kinds"]
        return all(isinstance(kind, str) and kind in admitted for kind in kinds)

    @staticmethod
    def _record_route(path: str) -> tuple[str, str] | None:
        single_routes = {
            "/v1/runs": ("runs", "create"),
            "/v1/snapshots": ("snapshots", "seal"),
            "/v1/sheets": ("sheets", "seal"),
            "/v1/submissions": ("submissions", "submit"),
            "/v1/ratings": ("ratings", "record"),
            "/v1/raters": ("raters", "provision"),
        }
        if path in single_routes:
            return single_routes[path]
        parts = path.split("/")
        if len(parts) == 5 and parts[:3] == ["", "v1", "runs"] and parts[4] == "events":
            try:
                validate_uuid4(parts[3])
            except ContractValidationError:
                return None
            return "runs", "append_event"
        return None

    @staticmethod
    def _job_route(path: str) -> tuple[str, UUID | None] | None:
        if path == "/v1/jobs/claim":
            return "claim", None
        parts = path.split("/")
        if len(parts) != 5 or parts[:3] != ["", "v1", "jobs"]:
            return None
        if parts[4] not in {"renew", "checkpoint", "complete"}:
            return None
        try:
            validate_uuid4(parts[3])
            return parts[4], UUID(parts[3])
        except (ContractValidationError, ValueError):
            return None

    def _error(
        self,
        status: int,
        request_id: str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        body = canonical_json(
            {
                "schema_version": 1,
                "request_id": request_id,
                "status": "unavailable" if retryable else "error",
                "data": None,
                "error": {
                    "code": code,
                    "message": message[:512],
                    "retryable": retryable,
                    "evidence_ids": [],
                },
            }
        )
        self._send_json(status, body)

    def _send_json(self, status: int, body: bytes, *, replayed: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if replayed:
            self.send_header("X-Replayed", "true")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        # Request headers can contain credentials; the service logger owns safe metadata.
        return

    def _unsupported_method(self) -> None:
        self._error(404, str(uuid4()), "not_found", "route not found")

    do_PUT = _unsupported_method
    do_PATCH = _unsupported_method
    do_DELETE = _unsupported_method
    do_OPTIONS = _unsupported_method
    do_HEAD = _unsupported_method


def _storage_error(error: StorageError) -> tuple[int, str, bool]:
    if isinstance(error, IdempotencyConflict):
        return 409, "idempotency_conflict", False
    if isinstance(error, StateConflict):
        return 409, "state_conflict", False
    if isinstance(error, LeaseExpired):
        return 409, "lease_expired", False
    if isinstance(error, StaleLease):
        return 409, "stale_lease", False
    if isinstance(error, UnavailableInput):
        return 422, "unavailable_input", False
    if isinstance(error, IntegrityFailure):
        return 422, "integrity_failure", False
    if isinstance(error, TransactionUnavailable):
        return 503, "temporarily_unavailable", True
    return 503, "temporarily_unavailable", True
