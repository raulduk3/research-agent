"""Fail-closed stdlib HTTP adapter for the version-one storage boundary."""

from __future__ import annotations

import base64
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
    validate_utc_date,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.contracts.digests import DIGEST_ISLANDS
from research_agent.contracts.preference import validate_iso_week
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

SNAPSHOT_READ_KINDS = frozenset(
    {
        "cards",
        "graph",
        "passages",
        "questions",
        "members",
        "family",
        "overviews",
        "passage_index",
        "extraction",
        "source",
    }
)
# A 768-coordinate overview vector is about 15 KiB of JSON; 32 of them keep
# one read well inside the 1 MiB response limit.
MAXIMUM_OVERVIEW_READS = 32
# One member row is about 250 bytes of JSON.
SNAPSHOT_MEMBER_PAGE = 1000
SNAPSHOT_READ_ROLES = frozenset({"tools"})
# Per-run reads beside the inspector's, each with its own role and scope: the
# tool service applies a run's specification to each call (#287), and a run
# worker, holding the orchestrator's certificate, loads what it drives (#306).
RUN_READS: Mapping[str, tuple[frozenset[str], str]] = {
    "specification": (frozenset({"tools"}), "runs:specification"),
    "worker": (frozenset({"orchestrator"}), "runs:worker"),
}
# A run worker and the tool service describe a run's snapshot (#306).
SNAPSHOT_DESCRIPTION_ROLES = frozenset({"orchestrator", "tools"})
INSPECTOR_READ_ROLES = frozenset({"inspector"})
RUN_LIST_FILTERS = frozenset({"configuration_id", "batch_id", "paper_id"})
DIGEST_READ_ROLES = frozenset({"rating_app"})
DIGEST_PROVENANCE_READ_ROLES = frozenset({"inspector"})
ASSESSMENT_READ_ROLES = frozenset({"reader"})
RATED_ENTRY_READ_ROLES = frozenset({"inspector"})
PAPER_REQUEST_READ_ROLES = frozenset({"ingest"})
OWNER_ROLES = frozenset({"owner"})
OWNER_WRITE_OPERATIONS = frozenset({"admit", "seed", "retire"})
# A genome's island (`genomes.island`) selects the owner's run listing (#326);
# the islands are the digest's.
OWNER_RUN_ISLANDS = DIGEST_ISLANDS
OWNER_READ_KINDS: Mapping[str, str] = {
    "genomes": "genome",
    "admissions": "admission",
    "retirements": "retirement",
}


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
    "digests": frozenset({"orchestrator"}),
    "paper_requests": frozenset({"tools"}),
    "settlements": frozenset({"orchestrator"}),
    "trace": frozenset({"tools"}),
    "jev_asks": frozenset({"tools"}),
}
# An operation whose roles differ from its domain's: the tool service records
# a paper request, and only ingest moves it (decision 0025).
RECORD_OPERATION_ROLES: Mapping[tuple[str, str], frozenset[str]] = {
    ("paper_requests", "transition"): frozenset({"ingest"}),
    # The tool service forwards a run's submit call; the orchestrator keeps
    # the operator path (#287). Voiding a run stays the orchestrator's.
    ("runs", "submit"): frozenset({"orchestrator", "tools"}),
}
# A run's two endings share the run's route and role; the submission owner
# seals a submit and the run owner records a void (#286).
RUN_ENDING_OPERATIONS = frozenset({"submit", "void"})
# The tool service appends a run's trace under the run's own path (#297).
TRACE_ROUTES: Mapping[str, str] = {"requests": "request", "terminals": "terminal"}
# The tool service reserves, settles and keeps a run's asks under the run's
# own path (decision 0031), all under the one ``jev_asks:write`` scope.
ASK_ROUTES: Mapping[str, str] = {
    "reservations": "reserve",
    "settlements": "settle",
    "answers": "record",
}
ASK_SCOPE = "jev_asks:write"
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


class TraceCommands(RecordCommands, Protocol):
    def read(self, run_id: str) -> dict[str, Any] | None: ...


class AskCommands(RecordCommands, Protocol):
    def recorded(self, run_id: str, work_key: str) -> bytes | None: ...

    def answered(self, run_id: str) -> int: ...


class RunCommands(RecordCommands, Protocol):
    def finish_without_submit(
        self, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse: ...


class SubmissionCommands(RecordCommands, Protocol):
    def accept_submission(
        self, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse: ...


class RatingCommands(RecordCommands, Protocol):
    def rated_entries(self, rater_id: str) -> tuple[dict[str, str], ...]: ...

    def ratings_in_batch(
        self, rater_id: str, batch_id: str
    ) -> tuple[dict[str, str], ...]: ...


class PreferenceReads(Protocol):
    def credits_for_rater(
        self, *, rater_id: str, iso_week: str
    ) -> list[dict[str, Any]]: ...


class RaterCommands(RecordCommands, Protocol):
    def list_principals(self) -> tuple[dict[str, Any], ...]: ...


class DigestCommands(RecordCommands, Protocol):
    def read_for_rater(
        self, *, island: str, batch_id: str
    ) -> dict[str, Any] | None: ...

    def read_with_provenance(self, digest_hash: str) -> dict[str, Any] | None: ...


class PaperRequestCommands(RecordCommands, Protocol):
    def open_requests(self) -> tuple[dict[str, Any], ...]: ...


class SettlementCommands(RecordCommands, Protocol):
    def costs(self, day: str) -> dict[str, Any]: ...


class EmbeddingViewReads(Protocol):
    def current(self, paper_family_id: str) -> dict[str, Any] | None: ...


class AssessmentReads(Protocol):
    def read(
        self, paper_version_id: str, snapshot_hash: str | None
    ) -> dict[str, str | None]: ...


class OwnerCommands(Protocol):
    def execute(
        self, operation: str, *, command_id: UUID, payload: object
    ) -> dict[str, Any]: ...

    def read(self, kind: str, configuration_id: UUID | None) -> dict[str, Any]: ...


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


class PinnedMember(Protocol):
    @property
    def paper_family_id(self) -> str: ...

    @property
    def paper_version_id(self) -> str: ...

    @property
    def card_hash(self) -> str: ...

    @property
    def overview_hash(self) -> str | None: ...

    @property
    def passage_index_hash(self) -> str | None: ...

    @property
    def graph_hash(self) -> str | None: ...


class SnapshotReads(Protocol):
    def members(
        self,
        snapshot_hash: str,
        *,
        after: tuple[str, str] | None = None,
        limit: int | None = None,
    ) -> tuple[PinnedMember, ...]: ...

    def family_pin(self, snapshot_hash: str, paper_family_id: str) -> PinnedMember: ...

    def overviews(
        self, snapshot_hash: str, overview_hashes: tuple[str, ...]
    ) -> tuple[dict[str, Any], ...]: ...

    def passage_index_by_hash(
        self, snapshot_hash: str, passage_index_hash: str
    ) -> dict[str, Any]: ...

    def cards(
        self, snapshot_hash: str, paper_version_ids: tuple[str, ...]
    ) -> tuple[dict[str, Any], ...]: ...

    def graph(self, snapshot_hash: str, paper_version_id: str) -> dict[str, Any]: ...

    def passage_index(
        self, snapshot_hash: str, paper_version_id: str
    ) -> dict[str, Any]: ...

    def questions(self, snapshot_hash: str) -> tuple[dict[str, Any], ...]: ...

    def extraction(
        self, snapshot_hash: str, paper_family_id: str
    ) -> dict[str, Any]: ...

    def source(
        self, snapshot_hash: str, paper_family_id: str
    ) -> tuple[str, tuple[int, str], BinaryIO]: ...


class InspectorReads(Protocol):
    def run(self, run_id: str) -> dict[str, Any] | None: ...

    def run_specification(self, run_id: str) -> dict[str, Any] | None: ...

    def run_worker(self, run_id: str) -> dict[str, Any] | None: ...

    def snapshot(self, snapshot_hash: str) -> dict[str, Any] | None: ...

    def runs_by_configuration(
        self, configuration_id: str, /, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]: ...

    def runs_by_batch(
        self, batch_id: str, /, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]: ...

    def runs_by_paper(
        self, paper_id: str, /, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]: ...

    def sheet(self, sheet_hash: str) -> dict[str, Any] | None: ...

    def submissions_by_submitter(
        self, submitter_id: str
    ) -> tuple[dict[str, Any], ...]: ...

    def manifest(self, manifest_hash: str) -> dict[str, Any] | None: ...

    def configurations(
        self, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]: ...

    def configuration(self, configuration_id: str) -> dict[str, Any] | None: ...

    def forecasts_by_configuration(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]: ...

    def owner_paper(
        self, paper_id: str, *, cursor: tuple[str, str] | None
    ) -> dict[str, Any] | None: ...

    def owner_run(self, run_id: str) -> dict[str, Any] | None: ...

    def owner_runs(
        self,
        *,
        day: str | None,
        island: str | None,
        since: str | None,
        cursor: tuple[str, str] | None,
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]: ...

    def run_settlement(self, run_id: str) -> dict[str, Any] | None: ...


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
            "inspector",
            "owner",
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
        queries: InspectorReads | None = None,
        runs: RunCommands | None = None,
        snapshots: RecordCommands | None = None,
        sheets: RecordCommands | None = None,
        submissions: SubmissionCommands | None = None,
        ratings: RatingCommands | None = None,
        raters: RaterCommands | None = None,
        digests: DigestCommands | None = None,
        owners: OwnerCommands | None = None,
        assessments: AssessmentReads | None = None,
        paper_requests: PaperRequestCommands | None = None,
        preference: PreferenceReads | None = None,
        settlements: SettlementCommands | None = None,
        trace: TraceCommands | None = None,
        embedding_views: EmbeddingViewReads | None = None,
        asks: AskCommands | None = None,
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
        self.queries = queries
        self.digests = digests
        self.owners = owners
        self.assessments = assessments
        self.ratings = ratings
        self.paper_requests = paper_requests
        self.preference = preference
        self.settlements = settlements
        self.embedding_views = embedding_views
        self.trace = trace
        self.asks = asks
        self.runs = runs
        self.submissions = submissions
        self.records: dict[str, RecordCommands | None] = {
            "runs": runs,
            "snapshots": snapshots,
            "sheets": sheets,
            "submissions": submissions,
            "ratings": ratings,
            "raters": raters,
            "digests": digests,
            "paper_requests": paper_requests,
            "settlements": settlements,
            "trace": trace,
            "jev_asks": asks,
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
    queries: InspectorReads | None = None,
    runs: RunCommands | None = None,
    snapshots: RecordCommands | None = None,
    sheets: RecordCommands | None = None,
    submissions: SubmissionCommands | None = None,
    ratings: RatingCommands | None = None,
    raters: RaterCommands | None = None,
    digests: DigestCommands | None = None,
    owners: OwnerCommands | None = None,
    assessments: AssessmentReads | None = None,
    paper_requests: PaperRequestCommands | None = None,
    preference: PreferenceReads | None = None,
    settlements: SettlementCommands | None = None,
    trace: TraceCommands | None = None,
    embedding_views: EmbeddingViewReads | None = None,
    asks: AskCommands | None = None,
) -> ThreadingHTTPServer:
    if tls_context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("storage HTTP requires verified client certificates")
    application = StorageHttpApplication(
        jobs,
        capabilities,
        authorization=authorization,
        artifacts=artifacts,
        documents=documents,
        queries=queries,
        runs=runs,
        snapshots=snapshots,
        sheets=sheets,
        submissions=submissions,
        ratings=ratings,
        raters=raters,
        digests=digests,
        owners=owners,
        assessments=assessments,
        paper_requests=paper_requests,
        preference=preference,
        settlements=settlements,
        trace=trace,
        embedding_views=embedding_views,
        asks=asks,
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
        owner_operation = self._owner_write_route(path.path)
        if owner_operation is not None:
            self._post_owner(capability, request_id, owner_operation)
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

    def _post_owner(
        self, capability: ServiceCapability, request_id: str, operation: str
    ) -> None:
        if (
            self.app.owners is None
            or capability.role not in OWNER_ROLES
            or f"owner:{operation}" not in capability.scopes
        ):
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        command = self._read_command(request_id)
        if command is None:
            return
        request_id = command["request_id"]
        try:
            data = self.app.owners.execute(
                operation,
                command_id=UUID(command["command_id"]),
                payload=command["payload"],
            )
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, data)

    def _post_record(
        self,
        capability: ServiceCapability,
        request_id: str,
        domain: str,
        operation: str,
        run_id: str | None,
    ) -> None:
        owner = (
            self.app.submissions
            if (domain, operation) == ("runs", "submit")
            else self.app.records.get(domain)
        )
        roles = RECORD_OPERATION_ROLES.get((domain, operation), RECORD_ROLES[domain])
        scope = ASK_SCOPE if domain == "jev_asks" else f"{domain}:{operation}"
        if (
            owner is None
            or capability.role not in roles
            or scope not in capability.scopes
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
        if (
            (domain == "runs" and operation in RUN_ENDING_OPERATIONS)
            or domain in {"trace", "jev_asks"}
        ) and (not isinstance(payload, dict) or payload.get("run_id") != run_id):
            self._error(
                422, request_id, "invalid_input", "payload run_id differs from route"
            )
            return
        identity = CommandIdentity(
            capability.principal_id, key, UUID(command["command_id"]), UUID(request_id)
        )
        try:
            if domain == "runs" and operation == "submit":
                assert self.app.submissions is not None
                response = self.app.submissions.accept_submission(
                    identity=identity, payload=payload
                )
            elif domain == "runs" and operation == "void":
                assert self.app.runs is not None
                response = self.app.runs.finish_without_submit(
                    identity=identity, payload=payload
                )
            else:
                response = owner.execute(operation, identity=identity, payload=payload)
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
        described = self._snapshot_description_route(path.path)
        if described is not None:
            self._get_snapshot_description(
                capability, request_id, described, path.query
            )
            return
        snapshot_route = self._snapshot_route(path.path)
        if snapshot_route is not None:
            self._get_snapshot(capability, request_id, snapshot_route, path.query)
            return
        if path.path == "/v1/owner/costs":
            self._get_costs(capability, request_id, path.query)
            return
        if path.path == "/v1/owner/runs":
            self._get_owner_runs(capability, request_id, path.query)
            return
        settled_run = self._run_settlement_route(path.path)
        if settled_run is not None:
            self._get_run_settlement(capability, request_id, settled_run, path.query)
            return
        owner_read = self._owner_read_route(path.path)
        if owner_read is not None:
            self._get_owner(capability, request_id, *owner_read, path.query)
            return
        embedding_paper = self._embedding_view_route(path.path)
        if embedding_paper is not None:
            self._get_embedding_view(
                capability, request_id, embedding_paper, path.query
            )
            return
        trace_run = self._run_trace_route(path.path)
        if trace_run is not None:
            self._get_run_trace(capability, request_id, trace_run, path.query)
            return
        ask_route = self._ask_read_route(path.path)
        if ask_route is not None:
            self._get_asks(capability, request_id, *ask_route, path.query)
            return
        owner_record = self._owner_record_route(path.path)
        if owner_record is not None:
            self._get_owner_record(capability, request_id, *owner_record, path.query)
            return
        if path.path == "/v1/raters":
            if path.query:
                self._error(404, request_id, "not_found", "route not found")
                return
            self._get_raters(capability, request_id)
        if path.path == "/v1/runs":
            self._get_runs(capability, request_id, path.query)
            return
        run_id = self._run_id_route(path.path)
        if run_id is not None:
            self._get_run(capability, request_id, run_id, path.query)
            return
        run_read = self._run_read_route(path.path)
        if run_read is not None:
            self._get_run_read(capability, request_id, *run_read, path.query)
            return
        sheet_hash = self._sheet_route(path.path)
        if sheet_hash is not None:
            self._get_sheet(capability, request_id, sheet_hash, path.query)
            return
        if path.path == "/v1/submissions":
            self._get_submissions_by_submitter(capability, request_id, path.query)
            return
        if path.path == "/v1/configurations":
            self._get_configurations(capability, request_id, path.query)
            return
        configuration_route = self._configuration_route(path.path)
        if configuration_route is not None:
            configuration_id, forecasts = configuration_route
            if forecasts:
                self._get_forecasts_by_configuration(
                    capability, request_id, configuration_id, path.query
                )
            else:
                self._get_configuration(
                    capability, request_id, configuration_id, path.query
                )
            return
        if path.path == "/v1/paper-requests":
            self._get_paper_requests(capability, request_id, path.query)
            return
        if path.path == "/v1/assessments/pointers":
            self._get_assessment_pointers(capability, request_id, path.query)
            return
        if path.path == "/v1/digests":
            self._get_digest_for_rater(capability, request_id, path.query)
            return
        if path.path == "/v1/ratings":
            if "batch_id" in parse_qs(path.query, keep_blank_values=True):
                self._get_own_ratings(capability, request_id, path.query)
            else:
                self._get_rated_entries(capability, request_id, path.query)
            return
        if path.path == "/v1/preference":
            self._get_own_credits(capability, request_id, path.query)
            return
        digest_hash = self._digest_hash_route(path.path)
        if digest_hash is not None:
            self._get_digest_with_provenance(capability, request_id, digest_hash)
            return
        manifest_hash = self._manifest_route(path.path)
        if manifest_hash is not None:
            self._get_manifest(capability, request_id, manifest_hash, path.query)
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
        self._stream(artifact_hash, length, media_type, stream)

    def _stream(
        self, artifact_hash: str, length: int, media_type: str, stream: BinaryIO
    ) -> None:
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
            or "snapshots:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=False)
        if kind == "source":
            self._get_snapshot_source(request_id, snapshot_hash, params)
            return
        try:
            data = self._read_snapshot(kind, snapshot_hash, params)
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, data)

    def _get_snapshot_source(
        self, request_id: str, snapshot_hash: str, params: dict[str, list[str]]
    ) -> None:
        """The pinned card's source document, as raw verified bytes (#287)."""

        assert self.app.documents is not None
        try:
            if set(params) != {"family_id"}:
                raise ContractValidationError(
                    "snapshot source read parameters are invalid"
                )
            family_id = self._single_uuid(params, "family_id")
            source_hash, (length, media_type), stream = self.app.documents.source(
                snapshot_hash, family_id
            )
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._stream(source_hash, length, media_type, stream)

    def _get_run_read(
        self,
        capability: ServiceCapability,
        request_id: str,
        run_id: str,
        kind: str,
        query: str,
    ) -> None:
        """A run's specification (#287) or what its worker loads (#306)."""

        roles, scope = RUN_READS[kind]
        if (
            query
            or self.app.queries is None
            or capability.role not in roles
            or scope not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        try:
            record = (
                self.app.queries.run_specification(run_id)
                if kind == "specification"
                else self.app.queries.run_worker(run_id)
            )
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if record is None:
            self._error(404, request_id, "not_found", "run not found")
            return
        self._send_ok(request_id, record)

    def _get_snapshot_description(
        self,
        capability: ServiceCapability,
        request_id: str,
        snapshot_hash: str,
        query: str,
    ) -> None:
        """A sealed snapshot's hash, seal time, family count and sheets (#306)."""

        if (
            query
            or self.app.queries is None
            or capability.role not in SNAPSHOT_DESCRIPTION_ROLES
            or "snapshots:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        try:
            description = self.app.queries.snapshot(snapshot_hash)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if description is None:
            self._error(404, request_id, "not_found", "snapshot not found")
            return
        self._send_ok(request_id, description)

    def _get_run(
        self,
        capability: ServiceCapability,
        request_id: str,
        run_id: str,
        query: str,
    ) -> None:
        if (
            query
            or self.app.queries is None
            or capability.role not in INSPECTOR_READ_ROLES
            or "runs:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        try:
            run = self.app.queries.run(run_id)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if run is None:
            self._error(404, request_id, "not_found", "run not found")
            return
        self._send_ok(request_id, run)

    def _get_sheet(
        self,
        capability: ServiceCapability,
        request_id: str,
        sheet_hash: str,
        query: str,
    ) -> None:
        if (
            query
            or self.app.queries is None
            or capability.role not in INSPECTOR_READ_ROLES
            or "forecasts:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        try:
            sheet = self.app.queries.sheet(sheet_hash)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if sheet is None:
            self._error(404, request_id, "not_found", "sheet not found")
            return
        self._send_ok(request_id, sheet)

    def _get_runs(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        """One page of runs selected by exactly one of three stored columns."""

        if (
            self.app.queries is None
            or capability.role not in INSPECTOR_READ_ROLES
            or "runs:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=False)
        queries = self.app.queries
        try:
            filters = set(params) - {"cursor"}
            if len(filters) != 1 or not filters <= RUN_LIST_FILTERS:
                raise ContractValidationError(
                    "exactly one of configuration_id, batch_id, paper_id is required"
                )
            cursor = self._single_cursor(params)
            if "configuration_id" in filters:
                value = self._single_uuid(params, "configuration_id")
                read = queries.runs_by_configuration
            elif "batch_id" in filters:
                value = self._single_hash(params, "batch_id")
                read = queries.runs_by_batch
            else:
                value = self._single_paper_id(params)
                read = queries.runs_by_paper
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        try:
            runs, next_cursor = read(value, cursor=cursor)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(
            request_id,
            {
                "runs": list(runs),
                "next_cursor": f"{next_cursor[0]},{next_cursor[1]}"
                if next_cursor is not None
                else None,
            },
        )

    def _get_owner(
        self,
        capability: ServiceCapability,
        request_id: str,
        kind: str,
        configuration_id: UUID | None,
        query: str,
    ) -> None:
        if (
            query
            or self.app.owners is None
            or capability.role not in OWNER_ROLES
            or "owner:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        try:
            data = self.app.owners.read(kind, configuration_id)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, data)

    def _get_costs(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        """Settled spend of one UTC day and its month, for the owner alone (#251).

        Any other role is refused 403 rather than told the route is absent:
        the read exists, and only the owner may have it.
        """

        if self.app.settlements is None:
            self._error(404, request_id, "not_found", "route not found")
            return
        if capability.role not in OWNER_ROLES or "owner:read" not in capability.scopes:
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        params = parse_qs(query, keep_blank_values=True)
        try:
            if set(params) != {"day"} or len(params["day"]) != 1:
                raise ContractValidationError("only one day is admitted")
            data = self.app.settlements.costs(params["day"][0])
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, data)

    def _get_embedding_view(
        self,
        capability: ServiceCapability,
        request_id: str,
        paper_family_id: str,
        query: str,
    ) -> None:
        """A family's current embedding view, for the owner alone (#298).

        Like the cost read, any other role is refused 403; a family with no
        recorded view is 404.
        """

        if query or self.app.embedding_views is None:
            self._error(404, request_id, "not_found", "route not found")
            return
        if capability.role not in OWNER_ROLES or "owner:read" not in capability.scopes:
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        try:
            data = self.app.embedding_views.current(paper_family_id)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if data is None:
            self._error(404, request_id, "not_found", "paper has no embedding view")
            return
        self._send_ok(request_id, data)

    def _get_run_trace(
        self,
        capability: ServiceCapability,
        request_id: str,
        run_id: str,
        query: str,
    ) -> None:
        """A run's trace with its stored payloads, for the owner alone (#308).

        Like the cost read, any other role is refused 403; a run storage
        does not hold is 404.
        """

        if query or self.app.trace is None:
            self._error(404, request_id, "not_found", "route not found")
            return
        if capability.role not in OWNER_ROLES or "owner:read" not in capability.scopes:
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        try:
            data = self.app.trace.read(run_id)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if data is None:
            self._error(404, request_id, "not_found", "run not found")
            return
        self._send_ok(request_id, data)

    def _get_asks(
        self,
        capability: ServiceCapability,
        request_id: str,
        run_id: str,
        work_key: str | None,
        query: str,
    ) -> None:
        """A run's count of answered asks, or the answer kept under one work
        key, for the tool service alone (decision 0031); a key with no kept
        answer is 404."""

        if query or self.app.asks is None:
            self._error(404, request_id, "not_found", "route not found")
            return
        if capability.role not in RECORD_ROLES["jev_asks"] or (
            ASK_SCOPE not in capability.scopes
        ):
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        try:
            if work_key is None:
                data: dict[str, Any] = {
                    "run_id": run_id,
                    "answered": self.app.asks.answered(run_id),
                }
            else:
                answer = self.app.asks.recorded(run_id, work_key)
                if answer is None:
                    self._error(404, request_id, "not_found", "no kept answer")
                    return
                data = {
                    "run_id": run_id,
                    "work_key": work_key,
                    "answer": base64.b64encode(answer).decode("ascii"),
                }
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, data)

    def _get_owner_record(
        self,
        capability: ServiceCapability,
        request_id: str,
        kind: str,
        record_id: str,
        query: str,
    ) -> None:
        """A paper family's page of runs, requests and cards, or one run, for
        the owner alone (#301).

        Like the trace read, any other role is refused 403. Only the paper
        read takes a query, its runs page's ``cursor``; a paper or run
        storage holds nothing about is 404.
        """

        if self.app.queries is None:
            self._error(404, request_id, "not_found", "route not found")
            return
        if capability.role not in OWNER_ROLES or "owner:read" not in capability.scopes:
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        params = parse_qs(query, keep_blank_values=True)
        try:
            if kind == "run":
                if query:
                    raise ContractValidationError("a run read takes no query")
                data = self.app.queries.owner_run(record_id)
            else:
                if set(params) - {"cursor"}:
                    raise ContractValidationError("only cursor is admitted")
                data = self.app.queries.owner_paper(
                    record_id, cursor=self._single_cursor(params)
                )
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if data is None:
            self._error(404, request_id, "not_found", f"{kind} not found")
            return
        self._send_ok(request_id, data)

    def _get_owner_runs(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        """Runs of one UTC day or one island, oldest first, for the owner
        alone (#326); any other role is refused 403 like the trace read."""

        if self.app.queries is None:
            self._error(404, request_id, "not_found", "route not found")
            return
        if capability.role not in OWNER_ROLES or "owner:read" not in capability.scopes:
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        params = parse_qs(query, keep_blank_values=True)
        try:
            selectors = set(params) & {"day", "island"}
            if len(selectors) != 1 or set(params) - {
                "day",
                "island",
                "since",
                "cursor",
            }:
                raise ContractValidationError("exactly one of day, island is required")
            if any(len(values) != 1 for values in params.values()):
                raise ContractValidationError("each argument is admitted once")
            day = params.get("day", [None])[0]
            island = params.get("island", [None])[0]
            since = params.get("since", [None])[0]
            if day is not None:
                validate_utc_date(day)
            if island is not None and island not in OWNER_RUN_ISLANDS:
                raise ContractValidationError("island is not an admitted value")
            if since is not None:
                validate_utc_instant(since)
            runs, next_cursor = self.app.queries.owner_runs(
                day=day,
                island=island,
                since=since,
                cursor=self._single_cursor(params),
            )
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(
            request_id,
            {
                "runs": list(runs),
                "next_cursor": f"{next_cursor[0]},{next_cursor[1]}"
                if next_cursor is not None
                else None,
            },
        )

    def _get_run_settlement(
        self,
        capability: ServiceCapability,
        request_id: str,
        run_id: str,
        query: str,
    ) -> None:
        """One run's settlement, for the owner alone (#326); 404 for a run
        not held or not yet settled."""

        if query or self.app.queries is None:
            self._error(404, request_id, "not_found", "route not found")
            return
        if capability.role not in OWNER_ROLES or "owner:read" not in capability.scopes:
            self._error(
                403, request_id, "forbidden", "capability does not permit route"
            )
            return
        try:
            data = self.app.queries.run_settlement(run_id)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if data is None:
            self._error(404, request_id, "not_found", "run has no settlement")
            return
        self._send_ok(request_id, data)

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

    def _get_paper_requests(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        if (
            query
            or self.app.paper_requests is None
            or capability.role not in PAPER_REQUEST_READ_ROLES
            or "paper_requests:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        try:
            requests = self.app.paper_requests.open_requests()
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, {"requests": list(requests)})

    def _get_submissions_by_submitter(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        if (
            self.app.queries is None
            or capability.role not in INSPECTOR_READ_ROLES
            or "submissions:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=False)
        try:
            submitter_id = self._single_uuid(params, "submitter_id")
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        try:
            submissions = self.app.queries.submissions_by_submitter(submitter_id)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, {"submissions": list(submissions)})

    def _get_assessment_pointers(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        if (
            self.app.assessments is None
            or capability.role not in ASSESSMENT_READ_ROLES
            or "assessments:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=False)
        if set(params) - {"paper_version_id", "snapshot_hash"}:
            self._error(422, request_id, "invalid_input", "unknown query parameter")
            return
        try:
            paper_version_id = self._single_uuid(params, "paper_version_id")
            snapshot_hash = (
                self._single_hash(params, "snapshot_hash")
                if "snapshot_hash" in params
                else None
            )
            pointers = self.app.assessments.read(paper_version_id, snapshot_hash)
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, pointers)

    def _get_digest_for_rater(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        if (
            self.app.digests is None
            or capability.role not in DIGEST_READ_ROLES
            or "digests:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=False)
        island_values = params.get("island", [])
        if len(island_values) != 1 or island_values[0] not in DIGEST_ISLANDS:
            self._error(422, request_id, "invalid_input", "island is not admitted")
            return
        try:
            batch_id = self._single_hash(params, "batch_id")
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        try:
            digest = self.app.digests.read_for_rater(
                island=island_values[0], batch_id=batch_id
            )
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if digest is None:
            self._error(404, request_id, "not_found", "digest not found")
            return
        self._send_ok(request_id, digest)

    def _get_rated_entries(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        if (
            self.app.ratings is None
            or capability.role not in RATED_ENTRY_READ_ROLES
            or "ratings:rated" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=True)
        try:
            if set(params) != {"rater_id"} or len(params["rater_id"]) != 1:
                raise ContractValidationError("only rater_id is admitted")
            rater_id = validate_uuid4(params["rater_id"][0])
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        try:
            entries = self.app.ratings.rated_entries(rater_id)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, {"entries": list(entries)})

    def _get_own_ratings(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        """A rater's own ratings of one batch, values included (#252).

        Storage trusts the rating app's certificate for the rater it names;
        the app answers only for its session's rater.
        """

        if (
            self.app.ratings is None
            or capability.role not in RATER_READ_ROLES
            or "raters:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=True)
        try:
            if set(params) != {"rater_id", "batch_id"}:
                raise ContractValidationError("only rater_id and batch_id are admitted")
            rater_id = self._single_uuid(params, "rater_id")
            batch_id = self._single_hash(params, "batch_id")
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        try:
            ratings = self.app.ratings.ratings_in_batch(rater_id, batch_id)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, {"ratings": list(ratings)})

    def _get_own_credits(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        """A rater's preference credit of one week, one share per row (#252)."""

        if (
            self.app.preference is None
            or capability.role not in RATER_READ_ROLES
            or "raters:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=True)
        try:
            if set(params) != {"rater_id", "iso_week"} or len(params["iso_week"]) != 1:
                raise ContractValidationError("only rater_id and iso_week are admitted")
            rater_id = self._single_uuid(params, "rater_id")
            iso_week = validate_iso_week(params["iso_week"][0])
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        try:
            credits = self.app.preference.credits_for_rater(
                rater_id=rater_id, iso_week=iso_week
            )
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(request_id, {"credits": credits})

    def _get_digest_with_provenance(
        self, capability: ServiceCapability, request_id: str, digest_hash: str
    ) -> None:
        if (
            self.app.digests is None
            or capability.role not in DIGEST_PROVENANCE_READ_ROLES
            or "digests:provenance" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        try:
            digest = self.app.digests.read_with_provenance(digest_hash)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if digest is None:
            self._error(404, request_id, "not_found", "digest not found")
            return
        self._send_ok(request_id, digest)

    def _get_manifest(
        self,
        capability: ServiceCapability,
        request_id: str,
        manifest_hash: str,
        query: str,
    ) -> None:
        if (
            query
            or self.app.queries is None
            or capability.role not in INSPECTOR_READ_ROLES
            or "manifests:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        try:
            manifest = self.app.queries.manifest(manifest_hash)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if manifest is None:
            self._error(404, request_id, "not_found", "manifest not found")
            return
        self._send_ok(request_id, manifest)

    def _get_configurations(
        self, capability: ServiceCapability, request_id: str, query: str
    ) -> None:
        if (
            self.app.queries is None
            or capability.role not in INSPECTOR_READ_ROLES
            or "configurations:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=True)
        try:
            if set(params) - {"cursor"}:
                raise ContractValidationError("only cursor is admitted")
            cursor = self._single_cursor(params)
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        try:
            configurations, next_cursor = self.app.queries.configurations(cursor=cursor)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(
            request_id,
            {
                "configurations": list(configurations),
                "next_cursor": f"{next_cursor[0]},{next_cursor[1]}"
                if next_cursor is not None
                else None,
            },
        )

    def _get_configuration(
        self,
        capability: ServiceCapability,
        request_id: str,
        configuration_id: str,
        query: str,
    ) -> None:
        if (
            query
            or self.app.queries is None
            or capability.role not in INSPECTOR_READ_ROLES
            or "configurations:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        try:
            configuration = self.app.queries.configuration(configuration_id)
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        if configuration is None:
            self._error(404, request_id, "not_found", "configuration not found")
            return
        self._send_ok(request_id, configuration)

    def _get_forecasts_by_configuration(
        self,
        capability: ServiceCapability,
        request_id: str,
        configuration_id: str,
        query: str,
    ) -> None:
        if (
            self.app.queries is None
            or capability.role not in INSPECTOR_READ_ROLES
            or "forecasts:read" not in capability.scopes
        ):
            self._error(404, request_id, "not_found", "route not found")
            return
        params = parse_qs(query, keep_blank_values=True)
        try:
            if set(params) - {"cursor"}:
                raise ContractValidationError("only cursor is admitted")
            cursor = self._single_cursor(params)
        except ContractValidationError as error:
            self._error(422, request_id, "invalid_input", str(error))
            return
        try:
            forecasts, next_cursor = self.app.queries.forecasts_by_configuration(
                configuration_id, cursor=cursor
            )
        except StorageError as error:
            status, code, retryable = _storage_error(error)
            self._error(status, request_id, code, str(error), retryable=retryable)
            return
        self._send_ok(
            request_id,
            {
                "forecasts": list(forecasts),
                "next_cursor": f"{next_cursor[0]},{next_cursor[1]}"
                if next_cursor is not None
                else None,
            },
        )

    @staticmethod
    def _owner_write_route(path: str) -> str | None:
        parts = path.split("/")
        if (
            len(parts) == 4
            and parts[:3] == ["", "v1", "owner"]
            and parts[3] in OWNER_WRITE_OPERATIONS
        ):
            return parts[3]
        return None

    @staticmethod
    def _owner_read_route(path: str) -> tuple[str, UUID | None] | None:
        parts = path.split("/")
        if parts[:3] != ["", "v1", "owner"]:
            return None
        if parts[3:] == ["retrospective"]:
            return "retrospective", None
        if len(parts) != 5 or parts[3] not in OWNER_READ_KINDS:
            return None
        try:
            return OWNER_READ_KINDS[parts[3]], UUID(validate_uuid4(parts[4]))
        except ContractValidationError:
            return None

    @staticmethod
    def _owner_record_route(path: str) -> tuple[str, str] | None:
        parts = path.split("/")
        if len(parts) != 5 or parts[:3] != ["", "v1", "owner"]:
            return None
        kind = {"papers": "paper", "runs": "run"}.get(parts[3])
        if kind is None:
            return None
        try:
            return kind, validate_uuid4(parts[4])
        except ContractValidationError:
            return None

    @staticmethod
    def _embedding_view_route(path: str) -> str | None:
        parts = path.split("/")
        if (
            len(parts) != 6
            or parts[:4] != ["", "v1", "owner", "papers"]
            or parts[5] != "embedding"
        ):
            return None
        try:
            return validate_uuid4(parts[4])
        except ContractValidationError:
            return None

    @staticmethod
    def _configuration_route(path: str) -> tuple[str, bool] | None:
        parts = path.split("/")
        if len(parts) not in (4, 5) or parts[:3] != ["", "v1", "configurations"]:
            return None
        if len(parts) == 5 and parts[4] != "forecasts":
            return None
        try:
            return validate_uuid4(parts[3]), len(parts) == 5
        except ContractValidationError:
            return None

    @staticmethod
    def _run_id_route(path: str) -> str | None:
        parts = path.split("/")
        if len(parts) != 4 or parts[:3] != ["", "v1", "runs"]:
            return None
        try:
            return validate_uuid4(parts[3])
        except ContractValidationError:
            return None

    @staticmethod
    def _run_read_route(path: str) -> tuple[str, str] | None:
        parts = path.split("/")
        if (
            len(parts) != 5
            or parts[:3] != ["", "v1", "runs"]
            or parts[4] not in RUN_READS
        ):
            return None
        try:
            return validate_uuid4(parts[3]), parts[4]
        except ContractValidationError:
            return None

    @staticmethod
    def _snapshot_description_route(path: str) -> str | None:
        parts = path.split("/")
        if len(parts) != 4 or parts[:3] != ["", "v1", "snapshots"]:
            return None
        try:
            return validate_sha256(parts[3])
        except ContractValidationError:
            return None

    @staticmethod
    def _ask_read_route(path: str) -> tuple[str, str | None] | None:
        parts = path.split("/")
        if len(parts) not in {5, 6} or parts[:3] != ["", "v1", "runs"]:
            return None
        if parts[4] != "asks":
            return None
        try:
            run_id = validate_uuid4(parts[3])
            work_key = validate_sha256(parts[5]) if len(parts) == 6 else None
        except ContractValidationError:
            return None
        return run_id, work_key

    @staticmethod
    def _run_trace_route(path: str) -> str | None:
        parts = path.split("/")
        if len(parts) != 5 or parts[:3] != ["", "v1", "runs"] or parts[4] != "trace":
            return None
        try:
            return validate_uuid4(parts[3])
        except ContractValidationError:
            return None

    @staticmethod
    def _run_settlement_route(path: str) -> str | None:
        parts = path.split("/")
        if (
            len(parts) != 6
            or parts[:4] != ["", "v1", "owner", "runs"]
            or parts[5] != "settlement"
        ):
            return None
        try:
            return validate_uuid4(parts[4])
        except ContractValidationError:
            return None

    @staticmethod
    def _sheet_route(path: str) -> str | None:
        parts = path.split("/")
        if len(parts) != 4 or parts[:3] != ["", "v1", "sheets"]:
            return None
        try:
            return validate_sha256(parts[3])
        except ContractValidationError:
            return None

    @staticmethod
    def _manifest_route(path: str) -> str | None:
        parts = path.split("/")
        if len(parts) != 4 or parts[:3] != ["", "v1", "manifests"]:
            return None
        try:
            return validate_sha256(parts[3])
        except ContractValidationError:
            return None

    @staticmethod
    def _digest_hash_route(path: str) -> str | None:
        parts = path.split("/")
        if len(parts) != 4 or parts[:3] != ["", "v1", "digests"]:
            return None
        try:
            return validate_sha256(parts[3])
        except ContractValidationError:
            return None

    @staticmethod
    def _single_cursor(params: dict[str, list[str]]) -> tuple[str, str] | None:
        values = params.get("cursor", [])
        if not values:
            return None
        if len(values) != 1:
            raise ContractValidationError("cursor is not an admitted value")
        created_at, separator, run_id = values[0].partition(",")
        if not separator:
            raise ContractValidationError("cursor is not an admitted value")
        return validate_utc_instant(created_at), validate_uuid4(run_id)

    def _read_snapshot(
        self, kind: str, snapshot_hash: str, params: dict[str, list[str]]
    ) -> dict[str, Any]:
        assert self.app.documents is not None
        if kind in {"members", "family", "overviews", "passage_index"}:
            return self._read_snapshot_member(kind, snapshot_hash, params)
        if kind == "extraction":
            if set(params) != {"family_id"}:
                raise ContractValidationError(
                    "snapshot extraction read parameters are invalid"
                )
            family_id = self._single_uuid(params, "family_id")
            return {
                "snapshot_id": snapshot_hash,
                **self.app.documents.extraction(snapshot_hash, family_id),
            }
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

    def _read_snapshot_member(
        self, kind: str, snapshot_hash: str, params: dict[str, list[str]]
    ) -> dict[str, Any]:
        """Member reads name exactly their own parameters, nothing else (#297)."""

        assert self.app.documents is not None
        admitted = {
            "members": {"cursor"},
            "family": {"family_id"},
            "overviews": {"overview_hash"},
            "passage_index": {"passage_index_hash"},
        }[kind]
        required = set() if kind == "members" else admitted
        if not required <= set(params) <= admitted:
            raise ContractValidationError(
                f"snapshot {kind} read parameters are invalid"
            )
        if kind == "members":
            after = self._member_cursor(params)
            page = self.app.documents.members(
                snapshot_hash, after=after, limit=SNAPSHOT_MEMBER_PAGE + 1
            )
            members = page[:SNAPSHOT_MEMBER_PAGE]
            last = members[-1] if len(page) > SNAPSHOT_MEMBER_PAGE else None
            return {
                "snapshot_id": snapshot_hash,
                "members": [_member(pin) for pin in members],
                "next_cursor": None
                if last is None
                else f"{last.paper_family_id},{last.paper_version_id}",
            }
        if kind == "family":
            family_id = self._single_uuid(params, "family_id")
            return {
                "snapshot_id": snapshot_hash,
                "member": _member(
                    self.app.documents.family_pin(snapshot_hash, family_id)
                ),
            }
        if kind == "overviews":
            hashes = self._repeated_hashes(
                params, "overview_hash", 1, MAXIMUM_OVERVIEW_READS
            )
            if len(set(hashes)) != len(hashes):
                raise ContractValidationError("overview_hash must not repeat")
            vectors = self.app.documents.overviews(snapshot_hash, hashes)
            return {
                "snapshot_id": snapshot_hash,
                "overviews": [
                    {"overview_hash": overview_hash, "overview": vector}
                    for overview_hash, vector in zip(hashes, vectors, strict=True)
                ],
            }
        passage_index_hash = self._single_hash(params, "passage_index_hash")
        return {
            "snapshot_id": snapshot_hash,
            "passage_index_hash": passage_index_hash,
            "passage_index": self.app.documents.passage_index_by_hash(
                snapshot_hash, passage_index_hash
            ),
        }

    @staticmethod
    def _member_cursor(params: dict[str, list[str]]) -> tuple[str, str] | None:
        values = params.get("cursor", [])
        if not values:
            return None
        family_id, separator, version_id = values[0].partition(",")
        if len(values) != 1 or not separator:
            raise ContractValidationError("cursor is not an admitted value")
        return validate_uuid4(family_id), validate_uuid4(version_id)

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
    def _single_hash(params: dict[str, list[str]], name: str) -> str:
        values = params.get(name, [])
        if len(values) != 1:
            raise ContractValidationError(f"{name} is required exactly once")
        return validate_sha256(values[0])

    @staticmethod
    def _single_paper_id(params: dict[str, list[str]]) -> str:
        values = params.get("paper_id", [])
        if len(values) != 1:
            raise ContractValidationError("paper_id is required exactly once")
        if not 1 <= len(values[0]) <= 128 or "\x00" in values[0]:
            raise ContractValidationError("paper_id is invalid")
        return values[0]

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
    def _record_route(path: str) -> tuple[str, str, str | None] | None:
        single_routes = {
            "/v1/runs": ("runs", "create"),
            "/v1/snapshots": ("snapshots", "seal"),
            "/v1/sheets": ("sheets", "seal"),
            "/v1/submissions": ("submissions", "submit"),
            "/v1/ratings": ("ratings", "record"),
            "/v1/raters": ("raters", "provision"),
            "/v1/digests": ("digests", "store"),
            "/v1/paper-requests": ("paper_requests", "record"),
            "/v1/paper-requests/transitions": ("paper_requests", "transition"),
            "/v1/settlements": ("settlements", "record"),
        }
        if path in single_routes:
            return (*single_routes[path], None)
        run_routes = {"events": "append_event", "submit": "submit", "void": "void"}
        parts = path.split("/")
        if (
            len(parts) == 5
            and parts[:3] == ["", "v1", "runs"]
            and parts[4] in run_routes
        ):
            try:
                run_id = validate_uuid4(parts[3])
            except ContractValidationError:
                return None
            return "runs", run_routes[parts[4]], run_id
        if (
            len(parts) == 6
            and parts[:3] == ["", "v1", "runs"]
            and parts[4] == "trace"
            and parts[5] in TRACE_ROUTES
        ):
            try:
                run_id = validate_uuid4(parts[3])
            except ContractValidationError:
                return None
            return "trace", TRACE_ROUTES[parts[5]], run_id
        if (
            len(parts) == 6
            and parts[:3] == ["", "v1", "runs"]
            and parts[4] == "asks"
            and parts[5] in ASK_ROUTES
        ):
            try:
                run_id = validate_uuid4(parts[3])
            except ContractValidationError:
                return None
            return "jev_asks", ASK_ROUTES[parts[5]], run_id
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

    def _send_ok(self, request_id: str, data: dict[str, Any]) -> None:
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


def _member(pin: PinnedMember) -> dict[str, str | None]:
    return {
        "paper_family_id": pin.paper_family_id,
        "paper_version_id": pin.paper_version_id,
        "card_hash": pin.card_hash,
        "overview_hash": pin.overview_hash,
        "passage_index_hash": pin.passage_index_hash,
        "graph_hash": pin.graph_hash,
    }


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
