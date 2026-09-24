"""Typed mutually-authenticated HTTPS client for the storage boundary."""

from __future__ import annotations

import base64
import hashlib
import math
import socket
import ssl
from collections.abc import Callable, Collection
from dataclasses import dataclass
from http.client import HTTPException, HTTPResponse, HTTPSConnection
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping, cast, get_args
from urllib.parse import quote
from uuid import UUID, uuid4

from research_agent.contracts import (
    CanonicalJsonError,
    ContractValidationError,
    ProducerVersion,
    canonical_json,
    canonical_loads,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.contracts.digests import validate_digest_store_payload
from research_agent.contracts.jobs import ERROR_CODES, JOB_KINDS, validate_job_payload
from research_agent.contracts.preference import validate_iso_week
from research_agent.contracts.questions import validate_sheet_payload
from research_agent.contracts.runs import validate_run_budgets, validate_run_payload
from research_agent.contracts.snapshots import validate_snapshot_payload
from research_agent.contracts.tools import PAPER_REQUEST_OUTCOMES
from research_agent.contracts.submissions import (
    validate_accept_submission_payload,
    validate_rating_payload,
    validate_submission_payload,
)
from research_agent.storage.assessments import validate_ask_payload
from research_agent.storage.http import (
    ASK_SCOPE,
    ARTIFACT_KINDS,
    ARTIFACT_MEDIA_TYPES,
    MAXIMUM_OVERVIEW_READS,
    OWNER_RUN_ISLANDS,
)
from research_agent.storage.raters import RATER_ISLANDS, validate_rater_payload
from research_agent.storage.requests import (
    OPEN_PAPER_REQUEST_STATUSES,
    PAPER_REQUEST_STATUSES,
    validate_paper_request_payload,
)
from research_agent.storage.resources import validate_resources_payload
from research_agent.storage.settlements import (
    validate_day,
    validate_settlement_payload,
)
from research_agent.storage.trace import validate_trace_payload

_SCOPES = frozenset(
    {
        "jobs:claim",
        "jobs:renew",
        "jobs:checkpoint",
        "jobs:complete",
        "artifacts:publish",
        "artifacts:read",
        "runs:create",
        "runs:append_event",
        "runs:submit",
        "runs:void",
        "snapshots:seal",
        "snapshots:read",
        "sheets:seal",
        "submissions:submit",
        "ratings:record",
        "ratings:rated",
        "raters:provision",
        "raters:read",
        "runs:read",
        "runs:specification",
        "runs:worker",
        "submissions:read",
        "manifests:read",
        "configurations:read",
        "forecasts:read",
        "digests:store",
        "digests:read",
        "digests:provenance",
        "assessments:read",
        "owner:admit",
        "owner:seed",
        "owner:retire",
        "owner:read",
        "paper_requests:record",
        "paper_requests:read",
        "paper_requests:transition",
        "settlements:record",
        "trace:request",
        "trace:terminal",
        ASK_SCOPE,
        "resources:record",
    }
)
_JSON_RESPONSE_LIMIT = 1024 * 1024
# A view's passage cosine matrix grows with the square of its passage count.
_EMBEDDING_VIEW_LIMIT = 16 * 1024 * 1024
# An extraction carries one located block per paragraph, heading or float.
_EXTRACTION_LIMIT = 16 * 1024 * 1024
# A run's 12 calls each carry two payloads of at most 256 KiB, base64-encoded.
_TRACE_LIMIT = 16 * 1024 * 1024
# A page of 50 runs with their turns and endings, and each pinned card record.
_OWNER_PAPER_LIMIT = 16 * 1024 * 1024
# The four emphasis parts of a genome a run worker loads (AG-16, #322).
_GENOME_PARTS = ("prompt", "scan_policy", "read_policy", "probability_assignment_rule")

RefusalReason = Literal[
    "not_owner",
    "unknown_source_genome",
    "cycle_disabled",
    "invalid_edit",
    "corpus_identifier",
    "duplicate_genome",
    "unknown_genome",
    "already_retired",
    "founder_not_retirable",
    "population_floor",
    "budget_not_funded",
]
_REFUSAL_REASONS = frozenset(get_args(RefusalReason))


@dataclass(frozen=True, slots=True)
class ResponseMetadata:
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    @property
    def replayed(self) -> bool:
        return any(
            name.lower() == "x-replayed" and value == "true"
            for name, value in self.headers
        )


@dataclass(frozen=True, slots=True)
class CommandResult:
    request_id: str
    data: Mapping[str, Any]
    response: ResponseMetadata


@dataclass(frozen=True, slots=True)
class RaterPrincipalRecord:
    """One provisioned rater principal read back through storage (PL-22)."""

    rater_id: UUID
    island: str
    salt: str
    credential_hash: str


@dataclass(frozen=True, slots=True)
class PaperRequestRecord:
    """One open paper request as the acquisition side reads it (decision 0025)."""

    request_id: UUID
    family_id: UUID
    run_id: UUID
    snapshot_hash: str
    requested_at: str
    status: str


@dataclass(frozen=True, slots=True)
class RunSpecificationRecord:
    """What the tool service applies to one run's calls (#287, TDD-2.1.36)."""

    run_id: UUID
    snapshot_hash: str
    allowed_tools: frozenset[str]
    paper_id: str
    issued_question_ids: frozenset[str]
    active: bool


@dataclass(frozen=True, slots=True)
class RunWorkerRecord:
    """What a run worker loads to drive one run (#306)."""

    run_id: UUID
    configuration_id: UUID
    attempt: int
    genome_hash: str
    snapshot_hash: str
    budgets: Mapping[str, int]
    allowed_tools: frozenset[str]
    paper_id: str
    issued_question_ids: tuple[str, ...]
    prompt: str
    scan_policy: str
    read_policy: str
    probability_assignment_rule: str


@dataclass(frozen=True, slots=True)
class SnapshotDescription:
    """A sealed snapshot as a run's first message states it (#306, AG-25)."""

    snapshot_hash: str
    sealed_at: str
    pinned_family_count: int
    sheet_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnerActionResult:
    """What an owner sees after one command; never filled in speculatively."""

    accepted: bool
    configuration_id: str | None
    reason: RefusalReason | None


@dataclass(frozen=True, slots=True)
class OwnerAdmissionRecord:
    configuration_id: str
    owner_id: str
    kind: Literal["edit", "seed"]
    source_configuration_id: str | None
    requested_at: str


@dataclass(frozen=True, slots=True)
class RetirementRecord:
    configuration_id: str
    owner_id: str
    requested_at: str


@dataclass(frozen=True, slots=True)
class ArtifactBytes:
    artifact_hash: str
    media_type: str
    payload: bytes
    response: ResponseMetadata


@dataclass(frozen=True, slots=True)
class QueryResult:
    """One read-only inspector response, exactly as storage returned it."""

    request_id: str
    data: Mapping[str, Any]
    response: ResponseMetadata


class StorageClientError(Exception):
    """Typed storage error with the server's exact response retained."""

    def __init__(
        self,
        *,
        status_code: int,
        request_id: str,
        code: str,
        message: str,
        retryable: bool,
        evidence_ids: tuple[str, ...],
        headers: tuple[tuple[str, str], ...],
        body: bytes,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.code = code
        self.retryable = retryable
        self.evidence_ids = evidence_ids
        self.headers = headers
        self.body = body


class StorageTransportError(Exception):
    """One ambiguous transport attempt failed and was not retried."""


class _BoundHTTPSConnection(HTTPSConnection):
    def __init__(
        self,
        connect_host: str,
        port: int,
        *,
        server_hostname: str,
        context: ssl.SSLContext,
        timeout: float,
    ) -> None:
        super().__init__(server_hostname, port, timeout=timeout, context=context)
        self._connect_host = connect_host
        self._server_hostname = server_hostname
        self._tls_context = context

    def connect(self) -> None:
        raw = socket.create_connection((self._connect_host, self.port), self.timeout)
        try:
            self.sock = self._tls_context.wrap_socket(
                raw, server_hostname=self._server_hostname
            )
        except BaseException:
            raw.close()
            raise


class StorageClient:
    """A scope-restricted client that performs exactly one request per call."""

    def __init__(
        self,
        *,
        connect_host: str,
        port: int,
        server_hostname: str,
        ca_file: Path,
        client_cert_file: Path,
        client_key_file: Path,
        scopes: frozenset[str],
        timeout_seconds: float = 30.0,
        maximum_artifact_bytes: int = 1024**3,
    ) -> None:
        if (
            not connect_host
            or not server_hostname
            or not scopes
            or not scopes <= _SCOPES
        ):
            raise ValueError("storage client endpoint or scopes are invalid")
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
            or not math.isfinite(timeout_seconds)
            or isinstance(maximum_artifact_bytes, bool)
            or not isinstance(maximum_artifact_bytes, int)
            or not 1 <= maximum_artifact_bytes <= 128 * 1024**3
        ):
            raise ValueError("storage client port or timeout is invalid")
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(client_cert_file, client_key_file)
        self._connect_host = connect_host
        self._port = port
        self._server_hostname = server_hostname
        self._context = context
        self._scopes = scopes
        self._timeout = float(timeout_seconds)
        self._maximum_artifact_bytes = maximum_artifact_bytes

    def claim(
        self,
        *,
        worker_id: UUID,
        kinds: tuple[str, ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._uuid(worker_id, "worker_id")
        response = self._command(
            "claim",
            "/v1/jobs/claim",
            {"worker_id": str(worker_id), "kinds": list(kinds)},
            command_id,
            request_id,
            idempotency_key,
        )
        lease = response.data["lease"]
        if lease is not None and lease["kind"] not in kinds:
            raise StorageTransportError("claimed job kind was not requested")
        return response

    def renew(
        self,
        *,
        job_id: UUID,
        worker_id: UUID,
        lease_epoch: int,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._uuid(job_id, "job_id")
        self._uuid(worker_id, "worker_id")
        return self._command(
            "renew",
            f"/v1/jobs/{job_id}/renew",
            {"worker_id": str(worker_id), "lease_epoch": lease_epoch},
            command_id,
            request_id,
            idempotency_key,
        )

    def checkpoint(
        self,
        *,
        job_id: UUID,
        worker_id: UUID,
        lease_epoch: int,
        checkpoint_hash: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._uuid(job_id, "job_id")
        self._uuid(worker_id, "worker_id")
        return self._command(
            "checkpoint",
            f"/v1/jobs/{job_id}/checkpoint",
            {
                "fence": {
                    "worker_id": str(worker_id),
                    "lease_epoch": lease_epoch,
                },
                "checkpoint": checkpoint_hash,
            },
            command_id,
            request_id,
            idempotency_key,
        )

    def complete(
        self,
        *,
        job_id: UUID,
        worker_id: UUID,
        lease_epoch: int,
        result: Mapping[str, Any],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._uuid(job_id, "job_id")
        self._uuid(worker_id, "worker_id")
        response = self._command(
            "complete",
            f"/v1/jobs/{job_id}/complete",
            {
                "fence": {
                    "worker_id": str(worker_id),
                    "lease_epoch": lease_epoch,
                },
                "result": dict(result),
            },
            command_id,
            request_id,
            idempotency_key,
        )
        if response.data["job_id"] != str(job_id):
            raise StorageTransportError("completed job id differs from request")
        return response

    def create_run(
        self,
        *,
        run_id: UUID,
        slot: Mapping[str, Any],
        genome_hash: str,
        seed: int,
        snapshot_hash: str,
        budgets: Mapping[str, int],
        allowed_tools: tuple[str, ...],
        model_identity: Mapping[str, Any],
        checkpoint_dates: tuple[str, ...],
        issued_question_ids: tuple[str, ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._uuid(run_id, "run_id")
        return self._record_command(
            "runs",
            "create",
            "/v1/runs",
            {
                "run_id": str(run_id),
                "slot": dict(slot),
                "genome_hash": genome_hash,
                "seed": seed,
                "snapshot_hash": snapshot_hash,
                "budgets": dict(budgets),
                "allowed_tools": list(allowed_tools),
                "model_identity": dict(model_identity),
                "checkpoint_dates": list(checkpoint_dates),
                "issued_question_ids": list(issued_question_ids),
            },
            validate_run_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def append_run_event(
        self,
        *,
        run_id: UUID,
        attempt: int,
        ordinal: int,
        kind: str,
        payload_hash: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._uuid(run_id, "run_id")
        return self._record_command(
            "runs",
            "append_event",
            f"/v1/runs/{run_id}/events",
            {
                "run_id": str(run_id),
                "attempt": attempt,
                "ordinal": ordinal,
                "kind": kind,
                "payload_hash": payload_hash,
            },
            validate_run_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def submit_run(
        self,
        *,
        run_id: UUID,
        submission_id: UUID,
        answers: tuple[Mapping[str, Any], ...],
        nomination: Mapping[str, Any],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Seal one run's answers and nomination, ending the run (AG-26).

        A refused attempt returns ``accepted`` false with its reason; a run
        already ended as void is a 409 ``state_conflict``.
        """

        self._uuid(run_id, "run_id")
        self._uuid(submission_id, "submission_id")
        return self._record_command(
            "runs",
            "submit",
            f"/v1/runs/{run_id}/submit",
            {
                "run_id": str(run_id),
                "submission_id": str(submission_id),
                "answers": [dict(answer) for answer in answers],
                "nomination": dict(nomination),
            },
            lambda _, payload: validate_accept_submission_payload(
                "accept_submission", payload
            ),
            command_id,
            request_id,
            idempotency_key,
        )

    def void_run(
        self,
        *,
        run_id: UUID,
        reason: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """End a run with no accepted submission as void (AG-15).

        ``voided`` is false, with the run's terminal ``state``, when the run
        had already ended; nothing is recorded then.
        """

        self._uuid(run_id, "run_id")
        return self._record_command(
            "runs",
            "void",
            f"/v1/runs/{run_id}/void",
            {"run_id": str(run_id), "reason": reason},
            lambda _, payload: validate_run_payload("finish_without_submit", payload),
            command_id,
            request_id,
            idempotency_key,
        )

    def seal_snapshot(
        self,
        *,
        paper_manifest_hash: str,
        index_identity_hashes: tuple[str, ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        return self._record_command(
            "snapshots",
            "seal",
            "/v1/snapshots",
            {
                "paper_manifest_hash": paper_manifest_hash,
                "index_identity_hashes": list(index_identity_hashes),
            },
            validate_snapshot_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def seal_sheet(
        self,
        *,
        questions: tuple[Mapping[str, Any], ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        return self._record_command(
            "sheets",
            "seal",
            "/v1/sheets",
            {"questions": [dict(question) for question in questions]},
            validate_sheet_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def submit(
        self,
        *,
        sheet_hash: str,
        submitter_id: UUID,
        claims: tuple[Mapping[str, Any], ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._uuid(submitter_id, "submitter_id")
        return self._record_command(
            "submissions",
            "submit",
            "/v1/submissions",
            {
                "sheet_hash": sheet_hash,
                "submitter_id": str(submitter_id),
                "claims": [dict(claim) for claim in claims],
            },
            validate_submission_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def record_rating(
        self,
        *,
        rater_id: UUID,
        paper_hash: str,
        digest_entry_id: UUID,
        value: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._uuid(rater_id, "rater_id")
        self._uuid(digest_entry_id, "digest_entry_id")
        return self._record_command(
            "ratings",
            "record",
            "/v1/ratings",
            {
                "rater_id": str(rater_id),
                "paper_hash": paper_hash,
                "digest_entry_id": str(digest_entry_id),
                "value": value,
            },
            validate_rating_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def provision_rater(
        self,
        *,
        rater_id: UUID,
        island: str,
        salt: str,
        credential_hash: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._uuid(rater_id, "rater_id")
        return self._record_command(
            "raters",
            "provision",
            "/v1/raters",
            {
                "rater_id": str(rater_id),
                "island": island,
                "salt": salt,
                "credential_hash": credential_hash,
            },
            validate_rater_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def list_raters(self) -> tuple[RaterPrincipalRecord, ...]:
        self._require("raters:read")
        response = self._request(
            "GET", "/v1/raters", None, {}, maximum_bytes=_JSON_RESPONSE_LIMIT
        )
        if response.status_code != 200:
            self._raise_error(response)
        envelope = self._envelope(response.body)
        if envelope["status"] != "ok" or envelope["error"] is not None:
            raise StorageTransportError("storage success envelope is invalid")
        data = envelope["data"]
        if not isinstance(data, dict) or set(data) != {"principals"}:
            raise StorageTransportError("rater principals response data is invalid")
        principals = data["principals"]
        if not isinstance(principals, list) or len(principals) > 2:
            raise StorageTransportError("rater principals response data is invalid")
        try:
            records = tuple(
                RaterPrincipalRecord(
                    rater_id=UUID(validate_uuid4(principal["rater_id"])),
                    island=principal["island"],
                    salt=principal["salt"],
                    credential_hash=principal["credential_hash"],
                )
                for principal in principals
            )
        except (AttributeError, ContractValidationError, KeyError, TypeError) as error:
            raise StorageTransportError(
                "rater principals response data is invalid"
            ) from error
        if any(record.island not in RATER_ISLANDS for record in records) or len(
            {record.rater_id for record in records}
        ) != len(records):
            raise StorageTransportError("rater principals response data is invalid")
        return records

    def record_paper_request(
        self,
        *,
        run_id: UUID,
        family_id: UUID,
        snapshot_hash: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Record that *run_id* asked for a family its snapshot lacks.

        The answer's ``outcome`` is ``requested``, ``already_requested`` or
        ``request_budget_exhausted``; the last records a refused row, so every
        outcome but ``already_requested`` carries a receipt.
        """

        self._uuid(run_id, "run_id")
        self._uuid(family_id, "family_id")
        return self._record_command(
            "paper_requests",
            "record",
            "/v1/paper-requests",
            {
                "run_id": str(run_id),
                "family_id": str(family_id),
                "snapshot_hash": snapshot_hash,
            },
            validate_paper_request_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def list_open_paper_requests(self) -> tuple[PaperRequestRecord, ...]:
        """Every requested or acquiring paper request, oldest first."""

        self._require("paper_requests:read")
        rows = self._read("/v1/paper-requests").data
        if set(rows) != {"requests"} or not isinstance(rows["requests"], list):
            raise StorageTransportError("paper requests response data is invalid")
        keys = {
            "request_id",
            "family_id",
            "run_id",
            "snapshot_hash",
            "requested_at",
            "status",
        }
        try:
            records = tuple(
                PaperRequestRecord(
                    request_id=UUID(validate_uuid4(row["request_id"])),
                    family_id=UUID(validate_uuid4(row["family_id"])),
                    run_id=UUID(validate_uuid4(row["run_id"])),
                    snapshot_hash=validate_sha256(row["snapshot_hash"]),
                    requested_at=validate_utc_instant(row["requested_at"]),
                    status=row["status"],
                )
                for row in rows["requests"]
                if isinstance(row, dict) and set(row) == keys
            )
        except (ContractValidationError, TypeError) as error:
            raise StorageTransportError(
                "paper requests response data is invalid"
            ) from error
        if len(records) != len(rows["requests"]) or any(
            record.status not in OPEN_PAPER_REQUEST_STATUSES for record in records
        ):
            raise StorageTransportError("paper requests response data is invalid")
        return records

    def transition_paper_request(
        self,
        *,
        paper_request_id: UUID,
        status: str,
        reason: str | None,
        paper_version_id: UUID | None,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Move one paper request: ``acquiring``, ``acquired``, ``failed`` or
        ``refused``.

        The answer's ``status`` is the status storage recorded: asking for
        ``acquiring`` past the day's acquisition budget records ``refused``
        with reason ``request_budget_exhausted`` instead.
        """

        self._uuid(paper_request_id, "paper_request_id")
        return self._record_command(
            "paper_requests",
            "transition",
            "/v1/paper-requests/transitions",
            {
                "request_id": str(paper_request_id),
                "status": status,
                "reason": reason,
                "paper_version_id": None
                if paper_version_id is None
                else str(paper_version_id),
            },
            validate_paper_request_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def record_settlement(
        self,
        *,
        run_id: UUID,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        usage_source: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Record the one settlement of an ended run (#251).

        ``usage_source`` is ``provider`` or ``loop_count``, as the loop's
        ``RunOutcome`` reports it; storage records no price.
        """

        self._uuid(run_id, "run_id")
        return self._record_command(
            "settlements",
            "record",
            "/v1/settlements",
            {
                "run_id": str(run_id),
                "provider": provider,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "usage_source": usage_source,
            },
            validate_settlement_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def append_trace_request(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        tool: str,
        request_hash: str,
        decision: Literal["admitted", "refused"],
        reason: str | None,
        request_payload: bytes,
        request_truncated: bool,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Record one tool call before it runs; the answer holds its sequence.

        A refused call is recorded with its ``reason`` and takes no terminal
        event; an admitted one needs exactly one ``append_trace_terminal``.
        ``request_payload`` is the request's bytes, whole or, when
        ``request_truncated``, cut to ``TRACE_PAYLOAD_BOUND`` (#308).
        """

        self._uuid(run_id, "run_id")
        self._uuid(call_id, "call_id")
        return self._record_command(
            "trace",
            "request",
            f"/v1/runs/{run_id}/trace/requests",
            {
                "run_id": str(run_id),
                "call_id": str(call_id),
                "tool": tool,
                "request_hash": request_hash,
                "decision": decision,
                "reason": reason,
                "request_payload": base64.b64encode(request_payload).decode("ascii"),
                "request_truncated": request_truncated,
            },
            validate_trace_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def append_trace_terminal(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        outcome: Literal["response", "error"],
        response_hash: str,
        error_code: str | None,
        retrieved_ids: tuple[str, ...],
        budget_deltas: Mapping[str, int],
        response_payload: bytes,
        response_truncated: bool,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Resolve one admitted tool call with its response or error.

        ``response_payload`` is the envelope's bytes, bounded as a
        request's are.
        """

        self._uuid(run_id, "run_id")
        self._uuid(call_id, "call_id")
        return self._record_command(
            "trace",
            "terminal",
            f"/v1/runs/{run_id}/trace/terminals",
            {
                "run_id": str(run_id),
                "call_id": str(call_id),
                "outcome": outcome,
                "response_hash": response_hash,
                "error_code": error_code,
                "retrieved_ids": list(retrieved_ids),
                "budget_deltas": dict(budget_deltas),
                "response_payload": base64.b64encode(response_payload).decode("ascii"),
                "response_truncated": response_truncated,
            },
            validate_trace_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def reserve_ask(
        self,
        *,
        run_id: UUID,
        work_key: str,
        day: str,
        worst_case_micros: int,
        daily_attempt_cap: int,
        daily_limit_micros: int,
        ask_pool_micros: int,
        request_payload: bytes,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Count one ask against the day's cap, Jev sublimit and ask pool.

        The answer's ``reservation_id`` is null when the day refuses the
        ask; otherwise ``request_payload``, the Jev request's bytes, is
        stored under ``request_hash`` (decision 0031).
        """

        self._uuid(run_id, "run_id")
        return self._record_command(
            "jev_asks",
            "reserve",
            f"/v1/runs/{run_id}/asks/reservations",
            {
                "run_id": str(run_id),
                "work_key": work_key,
                "day": day,
                "worst_case_micros": worst_case_micros,
                "daily_attempt_cap": daily_attempt_cap,
                "daily_limit_micros": daily_limit_micros,
                "ask_pool_micros": ask_pool_micros,
                "request_payload": base64.b64encode(request_payload).decode("ascii"),
            },
            validate_ask_payload,
            command_id,
            request_id,
            idempotency_key,
            scope=ASK_SCOPE,
        )

    def settle_ask(
        self,
        *,
        run_id: UUID,
        reservation_id: UUID,
        billing_state: str,
        response_payload: bytes | None,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Record how one ask's reservation ended, with Jev's response bytes
        when it answered; the answer's ``response_hash`` names them."""

        self._uuid(run_id, "run_id")
        self._uuid(reservation_id, "reservation_id")
        return self._record_command(
            "jev_asks",
            "settle",
            f"/v1/runs/{run_id}/asks/settlements",
            {
                "run_id": str(run_id),
                "reservation_id": str(reservation_id),
                "billing_state": billing_state,
                "response_payload": None
                if response_payload is None
                else base64.b64encode(response_payload).decode("ascii"),
            },
            validate_ask_payload,
            command_id,
            request_id,
            idempotency_key,
            scope=ASK_SCOPE,
        )

    def record_ask(
        self,
        *,
        run_id: UUID,
        work_key: str,
        answer: bytes,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Keep one answered ask of the run, once."""

        self._uuid(run_id, "run_id")
        return self._record_command(
            "jev_asks",
            "record",
            f"/v1/runs/{run_id}/asks/answers",
            {
                "run_id": str(run_id),
                "work_key": work_key,
                "answer": base64.b64encode(answer).decode("ascii"),
            },
            validate_ask_payload,
            command_id,
            request_id,
            idempotency_key,
            scope=ASK_SCOPE,
        )

    def read_answered_asks(self, run_id: UUID) -> int:
        """How many distinct asks the run has been answered."""

        self._require(ASK_SCOPE)
        run = self._uuid(run_id, "run_id")
        data = self._read(f"/v1/runs/{run}/asks").data
        if set(data) != {"run_id", "answered"} or data["run_id"] != str(run):
            raise StorageTransportError("answered asks response is invalid")
        try:
            return validate_non_negative_int(data["answered"])
        except ContractValidationError as error:
            raise StorageTransportError("answered asks response is invalid") from error

    def read_kept_ask(self, run_id: UUID, work_key: str) -> bytes | None:
        """The answer kept for the run's ask under *work_key*, or ``None``."""

        self._require(ASK_SCOPE)
        run = self._uuid(run_id, "run_id")
        key = validate_sha256(work_key)
        try:
            data = self._read(f"/v1/runs/{run}/asks/{key}").data
        except StorageClientError as error:
            if error.status_code == 404:
                return None
            raise
        if set(data) != {"run_id", "work_key", "answer"} or (
            data["run_id"],
            data["work_key"],
        ) != (str(run), key):
            raise StorageTransportError("kept ask response is invalid")
        try:
            return base64.b64decode(data["answer"], validate=True)
        except (TypeError, ValueError) as error:
            raise StorageTransportError("kept ask response is invalid") from error

    def read_run_trace(self, run_id: UUID) -> QueryResult:
        """A run's trace in call order, both payloads resolved, for the owner (#308)."""

        self._require("owner:read")
        run = self._uuid(run_id, "run_id")
        return self._read(f"/v1/runs/{run}/trace", maximum_bytes=_TRACE_LIMIT)

    def read_trace_since(self, cursor: int, *, limit: int = 100) -> QueryResult:
        """Trace calls, terminals, run endings and settlements recorded after
        *cursor*, in ledger order, for the owner (#327)."""

        self._require("owner:read")
        if cursor < 0 or not 1 <= limit <= 500:
            raise ContractValidationError("cursor or limit is out of range")
        return self._read(
            f"/v1/owner/trace/since?cursor={cursor}&limit={limit}",
            maximum_bytes=_TRACE_LIMIT,
        )

    def record_run_resources(
        self,
        *,
        run_id: UUID,
        resources: Mapping[str, Any],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        """Record a settled run's resources once (#330); *resources* is the
        record without its ``run_id``, which the route carries."""

        run = self._uuid(run_id, "run_id")
        return self._record_command(
            "resources",
            "record",
            f"/v1/runs/{run}/resources",
            {"run_id": str(run), **resources},
            validate_resources_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def read_owner_paper(
        self, paper_family_id: UUID, *, cursor: tuple[str, str] | None = None
    ) -> QueryResult:
        """One page of a paper family's runs, its requests and the card
        records its runs' snapshots pin, for the owner (#301)."""

        self._require("owner:read")
        family = self._uuid(paper_family_id, "paper_family_id")
        path = f"/v1/owner/papers/{family}"
        if cursor is not None:
            path += f"?cursor={quote(f'{cursor[0]},{cursor[1]}', safe='')}"
        return self._read(path, maximum_bytes=_OWNER_PAPER_LIMIT)

    def read_owner_run(self, run_id: UUID) -> QueryResult:
        """One run with its model turns by hash, ending and verdicts (#301)."""

        self._require("owner:read")
        run = self._uuid(run_id, "run_id")
        return self._read(f"/v1/owner/runs/{run}")

    def list_owner_runs(
        self,
        *,
        day: str | None = None,
        island: str | None = None,
        since: str | None = None,
        cursor: tuple[str, str] | None = None,
    ) -> QueryResult:
        """One page of the runs created on a UTC day or on an island, oldest
        first, each with its genome's lineage and island, for the owner (#326)."""

        self._require("owner:read")
        if (day is None) == (island is None):
            raise ContractValidationError("exactly one of day, island is required")
        arguments: list[tuple[str, str]] = []
        if day is not None:
            validate_day(day)
            arguments.append(("day", day))
        if island is not None:
            if island not in OWNER_RUN_ISLANDS:
                raise ContractValidationError("island is not an admitted value")
            arguments.append(("island", island))
        if since is not None:
            arguments.append(("since", validate_utc_instant(since)))
        if cursor is not None:
            arguments.append(("cursor", f"{cursor[0]},{cursor[1]}"))
        query = "&".join(f"{name}={quote(value, safe='')}" for name, value in arguments)
        return self._read(f"/v1/owner/runs?{query}")

    def list_owner_islands(self) -> QueryResult:
        """Each island's genome, founder, lineage and run counts (#344)."""

        self._require("owner:read")
        return self._read("/v1/owner/islands")

    def read_owner_island(self, island: str) -> QueryResult:
        """One island's genomes with their run and cost counts (#344)."""

        self._require("owner:read")
        if island not in OWNER_RUN_ISLANDS:
            raise ContractValidationError("island is not an admitted value")
        return self._read(f"/v1/owner/islands/{island}")

    def list_owner_reports(self) -> QueryResult:
        """Each island and ISO week with a digest, with its record counts (#344)."""

        self._require("owner:read")
        return self._read("/v1/owner/reports")

    def list_owner_impact(self) -> QueryResult:
        """Each island and ISO week with a rating, with what it set in motion
        (#344)."""

        self._require("owner:read")
        return self._read("/v1/owner/impact")

    def list_owner_models(self) -> QueryResult:
        """Each agent model manifest a stored run pins, with its runs (#344)."""

        self._require("owner:read")
        return self._read("/v1/owner/models")

    def list_owner_agents(self) -> QueryResult:
        """Each genome with its run, forecast and credit counts (#344)."""

        self._require("owner:read")
        return self._read("/v1/owner/agents")

    def read_owner_agent_runs(
        self, configuration_id: UUID, *, cursor: tuple[str, str] | None = None
    ) -> QueryResult:
        """One genome's runs with their endings, newest first, and its runs
        per UTC day (#344)."""

        self._require("owner:read")
        configuration = self._uuid(configuration_id, "configuration_id")
        path = f"/v1/owner/agents/{configuration}/runs"
        if cursor is not None:
            path += f"?cursor={quote(f'{cursor[0]},{cursor[1]}', safe='')}"
        return self._read(path)

    def list_owner_questions(self) -> QueryResult:
        """Each sheet question with its run, submission and resolution counts
        (#344)."""

        self._require("owner:read")
        return self._read("/v1/owner/questions")

    def read_owner_question(self, question_id: UUID) -> QueryResult:
        """One question with the runs that forecast it and its resolutions
        (#344)."""

        self._require("owner:read")
        question = self._uuid(question_id, "question_id")
        return self._read(f"/v1/owner/questions/{question}")

    def read_owner_run_record(self, run_id: UUID) -> QueryResult:
        """One run's island, ending, tool calls and nominations (#344)."""

        self._require("owner:read")
        run = self._uuid(run_id, "run_id")
        return self._read(f"/v1/owner/runs/{run}/record")

    def read_run_settlement(self, run_id: UUID) -> QueryResult:
        """One run's settlement: provider, model, tokens, usage source (#326)."""

        self._require("owner:read")
        run = self._uuid(run_id, "run_id")
        return self._read(f"/v1/owner/runs/{run}/settlement")

    def read_costs(self, day: str) -> QueryResult:
        """Settled spend of one UTC day and its month, for the owner (#251)."""

        self._require("owner:read")
        validate_day(day)
        return self._read(f"/v1/owner/costs?day={day}")

    def read_embedding_view(self, paper_family_id: UUID) -> QueryResult:
        """A paper family's current embedding view, for the owner (#298)."""

        self._require("owner:read")
        family = self._uuid(paper_family_id, "paper_family_id")
        return self._read(
            f"/v1/owner/papers/{family}/embedding",
            maximum_bytes=_EMBEDDING_VIEW_LIMIT,
        )

    def store_digest(
        self,
        *,
        digest_hash: str,
        batch_id: str,
        island: str,
        source_watermark: int,
        shuffle_seed: str,
        entries: tuple[Mapping[str, Any], ...],
        nominations: tuple[Mapping[str, Any], ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        return self._record_command(
            "digests",
            "store",
            "/v1/digests",
            {
                "digest_hash": digest_hash,
                "batch_id": batch_id,
                "island": island,
                "source_watermark": source_watermark,
                "shuffle_seed": shuffle_seed,
                "entries": [dict(entry) for entry in entries],
                "nominations": [dict(nomination) for nomination in nominations],
            },
            validate_digest_store_payload,
            command_id,
            request_id,
            idempotency_key,
        )

    def read_digest_for_rater(self, *, island: str, batch_id: str) -> QueryResult:
        self._require("digests:read")
        validate_sha256(batch_id)
        return self._read(
            f"/v1/digests?island={quote(island, safe='')}&batch_id={batch_id}"
        )

    def read_digest_with_provenance(self, digest_hash: str) -> QueryResult:
        self._require("digests:provenance")
        validate_sha256(digest_hash)
        return self._read(f"/v1/digests/{digest_hash}")

    def read_assessment_pointers(
        self, paper_version_id: UUID, *, snapshot_hash: str | None = None
    ) -> QueryResult:
        """The paper version's current Jev section hash and, when a snapshot is
        named, the hash that snapshot pinned; either is `None` when absent."""

        self._require("assessments:read")
        self._uuid(paper_version_id, "paper_version_id")
        path = f"/v1/assessments/pointers?paper_version_id={paper_version_id}"
        if snapshot_hash is not None:
            path += f"&snapshot_hash={validate_sha256(snapshot_hash)}"
        return self._read(path)

    def list_rated_entries(self, rater_id: UUID) -> QueryResult:
        """The entries one rater has rated, never the rating values."""

        self._require("ratings:rated")
        self._uuid(rater_id, "rater_id")
        return self._read(f"/v1/ratings?rater_id={rater_id}")

    def list_own_ratings(self, rater_id: UUID, *, batch_id: str) -> QueryResult:
        """One rater's ratings of a batch, each with its value and ``rated_at``.

        The caller answers only for its session's rater (#252).
        """

        self._require("raters:read")
        self._uuid(rater_id, "rater_id")
        validate_sha256(batch_id)
        return self._read(f"/v1/ratings?rater_id={rater_id}&batch_id={batch_id}")

    def list_own_credits(self, rater_id: UUID, *, iso_week: str) -> QueryResult:
        """One rater's preference credit of a week, one share per rating and genome."""

        self._require("raters:read")
        self._uuid(rater_id, "rater_id")
        validate_iso_week(iso_week)
        return self._read(f"/v1/preference?rater_id={rater_id}&iso_week={iso_week}")

    def publish_artifact(
        self,
        payload: bytes,
        *,
        expected_hash: str,
        media_type: str,
        kind: str,
        input_hashes: tuple[str, ...],
        producer_version: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
        source_available_at: str | None,
        job_id: UUID,
        lease_epoch: int,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._require("artifacts:publish")
        if not isinstance(payload, bytes):
            raise ContractValidationError("artifact payload must be bytes")
        validate_sha256(expected_hash)
        if media_type not in ARTIFACT_MEDIA_TYPES or kind not in ARTIFACT_KINDS:
            raise ContractValidationError("artifact media type or kind is invalid")
        for input_hash in input_hashes:
            validate_sha256(input_hash)
        validate_sha256(config_hash)
        validate_sha256(retention_policy_hash)
        if source_available_at is not None:
            validate_utc_instant(source_available_at)
        validate_positive_int(lease_epoch)
        for value, name in (
            (job_id, "job_id"),
            (command_id, "command_id"),
            (request_id, "request_id"),
            (idempotency_key, "idempotency_key"),
        ):
            self._uuid(value, name)
        metadata = {
            "schema_version": 1,
            "command_id": str(command_id),
            "request_id": str(request_id),
            "expected_hash": expected_hash,
            "byte_length": len(payload),
            "media_type": media_type,
            "kind": kind,
            "input_hashes": list(input_hashes),
            "producer_version": producer_version.to_dict(),
            "config_hash": config_hash,
            "source_available_at": source_available_at,
            "retention_policy_hash": retention_policy_hash,
        }
        metadata_bytes = canonical_json(metadata)
        counter = 0
        while True:
            boundary = (
                "research-agent-"
                + hashlib.sha256(
                    command_id.bytes + counter.to_bytes(8, "big")
                ).hexdigest()
            )
            marker = boundary.encode()
            if marker not in payload and marker not in metadata_bytes:
                break
            counter += 1
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n'
                "Content-Type: application/json\r\n\r\n"
            ).encode()
            + metadata_bytes
            + (
                f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="payload"; '
                'filename="payload"\r\nContent-Type: application/octet-stream\r\n\r\n'
            ).encode()
            + payload
            + f"\r\n--{boundary}--\r\n".encode()
        )
        response = self._request(
            "POST",
            "/v1/artifacts",
            body,
            {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Idempotency-Key": str(idempotency_key),
                "X-Job-Id": str(job_id),
                "X-Lease-Epoch": str(lease_epoch),
            },
            maximum_bytes=_JSON_RESPONSE_LIMIT,
        )
        result = self._json_result(response, request_id, {200, 201}, "artifact")
        if result.data["artifact_hash"] != expected_hash or result.data[
            "byte_length"
        ] != len(payload):
            raise StorageTransportError("published artifact differs from request")
        return result

    def read_artifact(
        self, artifact_hash: str, *, job_id: UUID, lease_epoch: int
    ) -> ArtifactBytes:
        self._require("artifacts:read")
        validate_sha256(artifact_hash)
        validate_positive_int(lease_epoch)
        self._uuid(job_id, "job_id")
        response = self._request(
            "GET",
            f"/v1/artifacts/{artifact_hash}",
            None,
            {"X-Job-Id": str(job_id), "X-Lease-Epoch": str(lease_epoch)},
            maximum_bytes=self._maximum_artifact_bytes,
        )
        if response.status_code != 200:
            self._raise_error(response)
        headers = {name.lower(): value for name, value in response.headers}
        if (
            headers.get("content-length") != str(len(response.body))
            or headers.get("etag") != f'"{artifact_hash}"'
            or "content-type" not in headers
            or hashlib.sha256(response.body).hexdigest() != artifact_hash
        ):
            raise StorageTransportError("artifact response metadata is invalid")
        return ArtifactBytes(
            artifact_hash,
            headers["content-type"],
            response.body,
            response,
        )

    def snapshot_cards(
        self, snapshot_hash: str, *, paper_ids: tuple[UUID, ...]
    ) -> QueryResult:
        """Paper cards of one to five papers pinned by a sealed snapshot."""

        return self._snapshot_read(
            snapshot_hash, "cards", self._paper_query(paper_ids, 1, 5)
        )

    def snapshot_graph(
        self,
        snapshot_hash: str,
        *,
        paper_id: UUID,
        direction: Literal["references", "citations"] = "references",
        limit: int = 20,
    ) -> QueryResult:
        """One paper's pinned citation graph in one direction."""

        if direction not in ("references", "citations"):
            raise ContractValidationError("direction is not an admitted value")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 20
        ):
            raise ContractValidationError("limit must be from 1 to 20")
        query = self._paper_query((paper_id,), 1, 1)
        return self._snapshot_read(
            snapshot_hash, "graph", f"{query}&direction={direction}&limit={limit}"
        )

    def snapshot_passages(
        self, snapshot_hash: str, *, paper_id: UUID, passage_ids: tuple[str, ...]
    ) -> QueryResult:
        """One to twenty passages of one paper, by text hash, from its pinned index."""

        if not 1 <= len(passage_ids) <= 20:
            raise ContractValidationError("passage_id must be repeated 1 to 20 times")
        passages = "".join(
            f"&passage_id={validate_sha256(passage_id)}" for passage_id in passage_ids
        )
        return self._snapshot_read(
            snapshot_hash, "passages", self._paper_query((paper_id,), 1, 1) + passages
        )

    def snapshot_questions(
        self, snapshot_hash: str, *, paper_ids: tuple[UUID, ...]
    ) -> QueryResult:
        """The questions a sealed snapshot issues."""

        return self._snapshot_read(
            snapshot_hash, "questions", self._paper_query(paper_ids, 1, 20)
        )

    def snapshot_members(
        self, snapshot_hash: str, *, cursor: str | None = None
    ) -> QueryResult:
        """One page of the members a sealed snapshot pins: family, version and
        the overview and passage index hashes pinned for it. Pass the page's
        ``next_cursor`` back for the next page; it is null on the last."""

        if cursor is None:
            return self._snapshot_read(snapshot_hash, "members", "")
        family_id, separator, version_id = cursor.partition(",")
        if not separator:
            raise ContractValidationError("cursor is not an admitted value")
        return self._snapshot_read(
            snapshot_hash,
            "members",
            f"cursor={validate_uuid4(family_id)},{validate_uuid4(version_id)}",
        )

    def snapshot_family(self, snapshot_hash: str, *, family_id: UUID) -> QueryResult:
        """The one version of a family a sealed snapshot pins, with its hashes."""

        family = self._uuid(family_id, "family_id")
        return self._snapshot_read(snapshot_hash, "family", f"family_id={family}")

    def snapshot_overviews(
        self, snapshot_hash: str, *, overview_hashes: tuple[str, ...]
    ) -> QueryResult:
        """Up to ``MAXIMUM_OVERVIEW_READS`` pinned overview vectors, by their
        pinned hash, in requested order."""

        if not 1 <= len(overview_hashes) <= MAXIMUM_OVERVIEW_READS:
            raise ContractValidationError(
                f"overview_hash must be repeated 1 to {MAXIMUM_OVERVIEW_READS} times"
            )
        if len(set(overview_hashes)) != len(overview_hashes):
            raise ContractValidationError("overview_hash must not repeat")
        return self._snapshot_read(
            snapshot_hash,
            "overviews",
            "&".join(
                f"overview_hash={validate_sha256(item)}" for item in overview_hashes
            ),
        )

    def snapshot_passage_index(
        self, snapshot_hash: str, *, passage_index_hash: str
    ) -> QueryResult:
        """A pinned passage index, by its pinned hash."""

        return self._snapshot_read(
            snapshot_hash,
            "passage_index",
            f"passage_index_hash={validate_sha256(passage_index_hash)}",
        )

    def snapshot_extraction(
        self, snapshot_hash: str, *, family_id: UUID
    ) -> QueryResult:
        """The extraction a pinned family's card was built from (#287)."""

        self._require("snapshots:read")
        validate_sha256(snapshot_hash)
        family = self._uuid(family_id, "family_id")
        return self._read(
            f"/v1/snapshots/{snapshot_hash}/extraction?family_id={family}",
            maximum_bytes=_EXTRACTION_LIMIT,
        )

    def snapshot_source(self, snapshot_hash: str, *, family_id: UUID) -> ArtifactBytes:
        """The source document a pinned family's card names, as exact bytes."""

        self._require("snapshots:read")
        validate_sha256(snapshot_hash)
        family = self._uuid(family_id, "family_id")
        response = self._request(
            "GET",
            f"/v1/snapshots/{snapshot_hash}/source?family_id={family}",
            None,
            {},
            maximum_bytes=self._maximum_artifact_bytes,
        )
        if response.status_code != 200:
            self._raise_error(response)
        headers = {name.lower(): value for name, value in response.headers}
        etag = headers.get("etag", "")
        source_hash = etag[1:-1] if len(etag) == 66 else ""
        if (
            headers.get("content-length") != str(len(response.body))
            or "content-type" not in headers
            or hashlib.sha256(response.body).hexdigest() != source_hash
        ):
            raise StorageTransportError("source response metadata is invalid")
        return ArtifactBytes(
            source_hash, headers["content-type"], response.body, response
        )

    def _snapshot_read(self, snapshot_hash: str, kind: str, query: str) -> QueryResult:
        self._require("snapshots:read")
        validate_sha256(snapshot_hash)
        path = f"/v1/snapshots/{snapshot_hash}/{kind}"
        return self._read(f"{path}?{query}" if query else path)

    def read_run_specification(self, run_id: UUID) -> RunSpecificationRecord:
        """The run's own specification as the tool service applies it (#287).

        Storage answers 404 for a run it does not hold.
        """

        self._require("runs:specification")
        self._uuid(run_id, "run_id")
        data = self._read(f"/v1/runs/{run_id}/specification").data
        keys = {
            "run_id",
            "snapshot_hash",
            "allowed_tools",
            "paper_id",
            "issued_question_ids",
            "active",
        }
        try:
            if (
                set(data) != keys
                or not isinstance(data["allowed_tools"], list)
                or not isinstance(data["issued_question_ids"], list)
                or not isinstance(data["paper_id"], str)
                or not isinstance(data["active"], bool)
                or data["run_id"] != str(run_id)
                or not all(isinstance(tool, str) for tool in data["allowed_tools"])
            ):
                raise ContractValidationError("run specification is invalid")
            return RunSpecificationRecord(
                run_id=run_id,
                snapshot_hash=validate_sha256(data["snapshot_hash"]),
                allowed_tools=frozenset(data["allowed_tools"]),
                paper_id=data["paper_id"],
                issued_question_ids=frozenset(
                    validate_uuid4(item) for item in data["issued_question_ids"]
                ),
                active=data["active"],
            )
        except (ContractValidationError, TypeError) as error:
            raise StorageTransportError(
                "run specification response data is invalid"
            ) from error

    def read_run_worker(self, run_id: UUID) -> RunWorkerRecord:
        """What a run worker loads to drive one run (#306).

        Storage answers 404 for a run it does not hold and 422
        ``unavailable_input`` when the run's configuration has no stored genome.
        """

        self._require("runs:worker")
        self._uuid(run_id, "run_id")
        data = self._read(f"/v1/runs/{run_id}/worker").data
        keys = {
            "run_id",
            "configuration_id",
            "attempt",
            "genome_hash",
            "snapshot_hash",
            "budgets",
            "allowed_tools",
            "paper_id",
            "issued_question_ids",
            *_GENOME_PARTS,
        }
        try:
            if (
                set(data) != keys
                or data["run_id"] != str(run_id)
                or not isinstance(data["allowed_tools"], list)
                or not all(isinstance(tool, str) for tool in data["allowed_tools"])
                or not isinstance(data["issued_question_ids"], list)
                or not isinstance(data["paper_id"], str)
                or not all(
                    isinstance(data[part], str) and data[part] for part in _GENOME_PARTS
                )
            ):
                raise ContractValidationError("run worker record is invalid")
            return RunWorkerRecord(
                run_id=run_id,
                configuration_id=UUID(validate_uuid4(data["configuration_id"])),
                attempt=validate_non_negative_int(data["attempt"]),
                genome_hash=validate_sha256(data["genome_hash"]),
                snapshot_hash=validate_sha256(data["snapshot_hash"]),
                budgets=MappingProxyType(validate_run_budgets(data["budgets"])),
                allowed_tools=frozenset(data["allowed_tools"]),
                paper_id=data["paper_id"],
                issued_question_ids=tuple(
                    validate_uuid4(item) for item in data["issued_question_ids"]
                ),
                prompt=data["prompt"],
                scan_policy=data["scan_policy"],
                read_policy=data["read_policy"],
                probability_assignment_rule=data["probability_assignment_rule"],
            )
        except (ContractValidationError, TypeError) as error:
            raise StorageTransportError(
                "run worker response data is invalid"
            ) from error

    def read_snapshot(self, snapshot_hash: str) -> SnapshotDescription:
        """A sealed snapshot's hash, seal time, pinned family count and sheets.

        Storage answers 404 for a snapshot it has not sealed (#306).
        """

        self._require("snapshots:read")
        validate_sha256(snapshot_hash)
        data = self._read(f"/v1/snapshots/{snapshot_hash}").data
        try:
            if (
                set(data)
                != {"snapshot_hash", "sealed_at", "pinned_family_count", "sheet_hashes"}
                or data["snapshot_hash"] != snapshot_hash
                or not isinstance(data["sheet_hashes"], list)
            ):
                raise ContractValidationError("snapshot description is invalid")
            return SnapshotDescription(
                snapshot_hash=snapshot_hash,
                sealed_at=validate_utc_instant(data["sealed_at"]),
                pinned_family_count=validate_non_negative_int(
                    data["pinned_family_count"]
                ),
                sheet_hashes=tuple(
                    validate_sha256(item) for item in data["sheet_hashes"]
                ),
            )
        except (ContractValidationError, TypeError) as error:
            raise StorageTransportError(
                "snapshot description response data is invalid"
            ) from error

    def _paper_query(self, paper_ids: tuple[UUID, ...], lower: int, upper: int) -> str:
        if not lower <= len(paper_ids) <= upper:
            raise ContractValidationError(
                f"paper_id must be repeated {lower} to {upper} times"
            )
        return "&".join(
            f"paper_id={self._uuid(paper_id, 'paper_id')}" for paper_id in paper_ids
        )

    def read_run(self, run_id: UUID) -> QueryResult:
        self._require("runs:read")
        self._uuid(run_id, "run_id")
        return self._read(f"/v1/runs/{run_id}")

    def list_runs_by_configuration(
        self, *, configuration_id: UUID, cursor: tuple[str, str] | None = None
    ) -> QueryResult:
        self._require("runs:read")
        self._uuid(configuration_id, "configuration_id")
        path = f"/v1/runs?configuration_id={configuration_id}"
        if cursor is not None:
            path += f"&cursor={quote(f'{cursor[0]},{cursor[1]}', safe='')}"
        return self._read(path)

    def list_runs_by_batch(
        self, *, batch_id: str, cursor: tuple[str, str] | None = None
    ) -> QueryResult:
        self._require("runs:read")
        validate_sha256(batch_id)
        path = f"/v1/runs?batch_id={batch_id}"
        if cursor is not None:
            path += f"&cursor={quote(f'{cursor[0]},{cursor[1]}', safe='')}"
        return self._read(path)

    def list_runs_by_paper(
        self, *, paper_id: str, cursor: tuple[str, str] | None = None
    ) -> QueryResult:
        self._require("runs:read")
        if not 1 <= len(paper_id) <= 128 or "\x00" in paper_id:
            raise ContractValidationError("paper_id is invalid")
        path = f"/v1/runs?paper_id={quote(paper_id, safe='')}"
        if cursor is not None:
            path += f"&cursor={quote(f'{cursor[0]},{cursor[1]}', safe='')}"
        return self._read(path)

    def read_sheet(self, sheet_hash: str) -> QueryResult:
        self._require("forecasts:read")
        validate_sha256(sheet_hash)
        return self._read(f"/v1/sheets/{sheet_hash}")

    def list_submissions_by_submitter(self, *, submitter_id: UUID) -> QueryResult:
        self._require("submissions:read")
        self._uuid(submitter_id, "submitter_id")
        return self._read(f"/v1/submissions?submitter_id={submitter_id}")

    def read_manifest(self, manifest_hash: str) -> QueryResult:
        self._require("manifests:read")
        validate_sha256(manifest_hash)
        return self._read(f"/v1/manifests/{manifest_hash}")

    def list_configurations(
        self, *, cursor: tuple[str, str] | None = None
    ) -> QueryResult:
        self._require("configurations:read")
        path = "/v1/configurations"
        if cursor is not None:
            path += f"?cursor={quote(f'{cursor[0]},{cursor[1]}', safe='')}"
        return self._read(path)

    def read_configuration(self, configuration_id: UUID) -> QueryResult:
        self._require("configurations:read")
        self._uuid(configuration_id, "configuration_id")
        return self._read(f"/v1/configurations/{configuration_id}")

    def list_forecasts_by_configuration(
        self, *, configuration_id: UUID, cursor: tuple[str, str] | None = None
    ) -> QueryResult:
        self._require("forecasts:read")
        self._uuid(configuration_id, "configuration_id")
        path = f"/v1/configurations/{configuration_id}/forecasts"
        if cursor is not None:
            path += f"?cursor={quote(f'{cursor[0]},{cursor[1]}', safe='')}"
        return self._read(path)

    def admit_edited_genome(
        self,
        *,
        owner_id: UUID,
        source_configuration_id: UUID,
        new_configuration_id: UUID,
        changes: Mapping[str, str],
        lineage_id: str,
        corpus_identifiers: Collection[str],
        completed_weekly_cycles: int | None,
        profile_hash: str | None,
        command_id: UUID,
    ) -> OwnerActionResult:
        return self._owner_result(
            self._owner_command(
                "admit",
                {
                    "owner_id": str(self._uuid(owner_id, "owner_id")),
                    "source_configuration_id": str(
                        self._uuid(source_configuration_id, "source_configuration_id")
                    ),
                    "new_configuration_id": str(
                        self._uuid(new_configuration_id, "new_configuration_id")
                    ),
                    "changes": dict(changes),
                    "lineage_id": lineage_id,
                    "corpus_identifiers": sorted(corpus_identifiers),
                    "completed_weekly_cycles": completed_weekly_cycles,
                    "profile_hash": profile_hash,
                },
                command_id,
            )
        )

    def seed_variant(
        self,
        *,
        owner_id: UUID,
        new_configuration_id: UUID,
        island: str,
        lineage_id: str,
        emphasis: Mapping[str, str],
        template_configuration_id: UUID,
        corpus_identifiers: Collection[str],
        profile_hash: str,
        budget_funded: bool,
        command_id: UUID,
    ) -> OwnerActionResult:
        return self._owner_result(
            self._owner_command(
                "seed",
                {
                    "owner_id": str(self._uuid(owner_id, "owner_id")),
                    "new_configuration_id": str(
                        self._uuid(new_configuration_id, "new_configuration_id")
                    ),
                    "island": island,
                    "lineage_id": lineage_id,
                    "emphasis": dict(emphasis),
                    "template_configuration_id": str(
                        self._uuid(
                            template_configuration_id, "template_configuration_id"
                        )
                    ),
                    "corpus_identifiers": sorted(corpus_identifiers),
                    "profile_hash": profile_hash,
                    "budget_funded": budget_funded,
                },
                command_id,
            )
        )

    def retire_genome(
        self, *, owner_id: UUID, configuration_id: UUID, command_id: UUID
    ) -> OwnerActionResult:
        return self._owner_result(
            self._owner_command(
                "retire",
                {
                    "owner_id": str(self._uuid(owner_id, "owner_id")),
                    "configuration_id": str(
                        self._uuid(configuration_id, "configuration_id")
                    ),
                },
                command_id,
            )
        )

    def read_genome_view(self, configuration_id: UUID) -> dict[str, object] | None:
        self._uuid(configuration_id, "configuration_id")
        data = self._owner_read(f"/v1/owner/genomes/{configuration_id}", "genome")
        return None if data is None else dict(data)

    def admission_history(self, configuration_id: UUID) -> OwnerAdmissionRecord | None:
        self._uuid(configuration_id, "configuration_id")
        data = self._owner_read(f"/v1/owner/admissions/{configuration_id}", "admission")
        return None if data is None else self._admission_record(data)

    def retirement_status(self, configuration_id: UUID) -> RetirementRecord | None:
        self._uuid(configuration_id, "configuration_id")
        data = self._owner_read(
            f"/v1/owner/retirements/{configuration_id}", "retirement"
        )
        return None if data is None else self._retirement_record(data)

    def retrospective(
        self,
    ) -> tuple[tuple[OwnerAdmissionRecord, ...], tuple[RetirementRecord, ...]]:
        self._require("owner:read")
        result = self._read("/v1/owner/retrospective")
        data = result.data
        if set(data) != {"admissions", "retirements"} or not all(
            isinstance(data[name], list) for name in data
        ):
            raise StorageTransportError("owner retrospective response is invalid")
        return (
            tuple(self._admission_record(row) for row in data["admissions"]),
            tuple(self._retirement_record(row) for row in data["retirements"]),
        )

    def _owner_command(
        self, operation: str, payload: dict[str, Any], command_id: UUID
    ) -> dict[str, Any]:
        self._require(f"owner:{operation}")
        self._uuid(command_id, "command_id")
        request_id = uuid4()
        body = canonical_json(
            {
                "schema_version": 1,
                "command_id": str(command_id),
                "request_id": str(request_id),
                "payload": payload,
            }
        )
        response = self._request(
            "POST",
            f"/v1/owner/{operation}",
            body,
            {"Content-Type": "application/json"},
            maximum_bytes=_JSON_RESPONSE_LIMIT,
        )
        if response.status_code != 200:
            try:
                self._raise_error(response)
            except StorageClientError as error:
                if error.code == "invalid_input":
                    raise ContractValidationError(str(error)) from error
                raise
        envelope = self._envelope(response.body)
        if (
            envelope["request_id"] != str(request_id)
            or envelope["status"] != "ok"
            or envelope["error"] is not None
            or not isinstance(envelope["data"], dict)
        ):
            raise StorageTransportError("storage success envelope is invalid")
        return cast(dict[str, Any], envelope["data"])

    def _owner_read(self, path: str, key: str) -> Mapping[str, Any] | None:
        self._require("owner:read")
        data = self._read(path).data
        if set(data) != {key}:
            raise StorageTransportError("owner read response is invalid")
        value = data[key]
        if value is not None and not isinstance(value, dict):
            raise StorageTransportError("owner read response is invalid")
        return cast("Mapping[str, Any] | None", value)

    @staticmethod
    def _owner_result(data: dict[str, Any]) -> OwnerActionResult:
        accepted, identifier, reason = (
            data.get("accepted"),
            data.get("configuration_id"),
            data.get("reason"),
        )
        if (
            set(data) != {"accepted", "configuration_id", "reason"}
            or not isinstance(accepted, bool)
            or not (identifier is None or isinstance(identifier, str))
            or not (reason is None or reason in _REFUSAL_REASONS)
            or accepted != (reason is None)
        ):
            raise StorageTransportError("owner command response is invalid")
        return OwnerActionResult(
            accepted, identifier, cast("RefusalReason | None", reason)
        )

    @staticmethod
    def _admission_record(row: object) -> OwnerAdmissionRecord:
        keys = {
            "configuration_id",
            "owner_id",
            "kind",
            "source_configuration_id",
            "requested_at",
        }
        if (
            not isinstance(row, dict)
            or set(row) != keys
            or row["kind"]
            not in (
                "edit",
                "seed",
            )
        ):
            raise StorageTransportError("owner admission record is invalid")
        return OwnerAdmissionRecord(**row)

    @staticmethod
    def _retirement_record(row: object) -> RetirementRecord:
        keys = {"configuration_id", "owner_id", "requested_at"}
        if not isinstance(row, dict) or set(row) != keys:
            raise StorageTransportError("owner retirement record is invalid")
        return RetirementRecord(**row)

    def _read(
        self, path: str, *, maximum_bytes: int = _JSON_RESPONSE_LIMIT
    ) -> QueryResult:
        response = self._request("GET", path, None, {}, maximum_bytes=maximum_bytes)
        if response.status_code != 200:
            self._raise_error(response)
        envelope = self._envelope(response.body)
        if (
            envelope["status"] != "ok"
            or envelope["error"] is not None
            or not isinstance(envelope["data"], dict)
        ):
            raise StorageTransportError("storage success envelope is invalid")
        data = cast(dict[str, Any], envelope["data"])
        return QueryResult(
            envelope["request_id"], MappingProxyType(dict(data)), response
        )

    def _command(
        self,
        operation: str,
        path: str,
        payload: object,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        self._require(f"jobs:{operation}")
        validated = validate_job_payload(operation, payload)
        for value, name in (
            (command_id, "command_id"),
            (request_id, "request_id"),
            (idempotency_key, "idempotency_key"),
        ):
            self._uuid(value, name)
        body = canonical_json(
            {
                "schema_version": 1,
                "command_id": str(command_id),
                "request_id": str(request_id),
                "payload": validated,
            }
        )
        response = self._request(
            "POST",
            path,
            body,
            {
                "Content-Type": "application/json",
                "Idempotency-Key": str(idempotency_key),
            },
            maximum_bytes=_JSON_RESPONSE_LIMIT,
        )
        return self._json_result(response, request_id, {200}, operation)

    def _record_command(
        self,
        domain: str,
        operation: str,
        path: str,
        payload: object,
        validator: Callable[[str, object], dict[str, Any]],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
        *,
        scope: str | None = None,
    ) -> CommandResult:
        self._require(scope or f"{domain}:{operation}")
        validated = validator(operation, payload)
        for value, name in (
            (command_id, "command_id"),
            (request_id, "request_id"),
            (idempotency_key, "idempotency_key"),
        ):
            self._uuid(value, name)
        body = canonical_json(
            {
                "schema_version": 1,
                "command_id": str(command_id),
                "request_id": str(request_id),
                "payload": validated,
            }
        )
        response = self._request(
            "POST",
            path,
            body,
            {
                "Content-Type": "application/json",
                "Idempotency-Key": str(idempotency_key),
            },
            maximum_bytes=_JSON_RESPONSE_LIMIT,
        )
        return self._json_result(response, request_id, {200}, f"{domain}:{operation}")

    def _json_result(
        self,
        response: ResponseMetadata,
        request_id: UUID,
        statuses: set[int],
        operation: str,
    ) -> CommandResult:
        if response.status_code not in statuses:
            self._raise_error(response)
        envelope = self._envelope(response.body)
        if (
            (envelope["request_id"] != str(request_id) and not response.replayed)
            or envelope["status"] != "ok"
            or envelope["error"] is not None
            or not isinstance(envelope["data"], dict)
        ):
            raise StorageTransportError("storage success envelope is invalid")
        data = cast(dict[str, Any], envelope["data"])
        self._validate_success(operation, data)
        return CommandResult(
            envelope["request_id"], MappingProxyType(dict(data)), response
        )

    def _raise_error(self, response: ResponseMetadata) -> None:
        envelope = self._envelope(response.body)
        error = envelope["error"]
        code = error.get("code") if isinstance(error, dict) else None
        if (
            not isinstance(envelope["status"], str)
            or envelope["status"] not in {"error", "unavailable"}
            or envelope["data"] is not None
            or not isinstance(error, dict)
            or set(error) != {"code", "message", "retryable", "evidence_ids"}
            or not isinstance(code, str)
            or code not in ERROR_CODES
            or not isinstance(error["message"], str)
            or not 1 <= len(error["message"]) <= 512
            or not isinstance(error["retryable"], bool)
            or not isinstance(error["evidence_ids"], list)
            or len(error["evidence_ids"]) > 20
        ):
            raise StorageTransportError("storage error envelope is invalid")
        try:
            evidence = tuple(validate_sha256(item) for item in error["evidence_ids"])
        except (ContractValidationError, TypeError) as invalid:
            raise StorageTransportError(
                "storage error envelope is invalid"
            ) from invalid
        if len(set(evidence)) != len(evidence):
            raise StorageTransportError("storage error evidence is duplicated")
        raise StorageClientError(
            status_code=response.status_code,
            request_id=envelope["request_id"],
            code=error["code"],
            message=error["message"],
            retryable=error["retryable"],
            evidence_ids=evidence,
            headers=response.headers,
            body=response.body,
        )

    @staticmethod
    def _envelope(body: bytes) -> dict[str, Any]:
        try:
            value = canonical_loads(body)
        except CanonicalJsonError as error:
            raise StorageTransportError("storage returned malformed JSON") from error
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "request_id",
            "status",
            "data",
            "error",
        }:
            raise StorageTransportError("storage response envelope is not closed")
        if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
            raise StorageTransportError("storage response version is unsupported")
        try:
            validate_uuid4(value["request_id"])
        except ContractValidationError as error:
            raise StorageTransportError(
                "storage response request id is invalid"
            ) from error
        return cast(dict[str, Any], value)

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
        *,
        maximum_bytes: int,
    ) -> ResponseMetadata:
        connection = _BoundHTTPSConnection(
            self._connect_host,
            self._port,
            server_hostname=self._server_hostname,
            context=self._context,
            timeout=self._timeout,
        )
        try:
            connection.request(method, path, body=body, headers=dict(headers))
            raw: HTTPResponse = connection.getresponse()
            response_headers = tuple(raw.getheaders())
            lengths = [
                value
                for name, value in response_headers
                if name.lower() == "content-length"
            ]
            if (
                len(lengths) != 1
                or not lengths[0].isascii()
                or not lengths[0].isdigit()
                or len(lengths[0]) > 20
            ):
                raise StorageTransportError("storage response length is invalid")
            declared = int(lengths[0])
            if declared > maximum_bytes:
                raise StorageTransportError("storage response exceeds admitted limit")
            response_body = raw.read(maximum_bytes + 1)
            if len(response_body) != declared or len(response_body) > maximum_bytes:
                raise StorageTransportError("storage response length is invalid")
            return ResponseMetadata(raw.status, response_headers, response_body)
        except StorageTransportError:
            raise
        except (HTTPException, OSError, ssl.SSLError) as error:
            raise StorageTransportError(
                "storage request outcome is unknown; request was not retried"
            ) from error
        finally:
            connection.close()

    def _require(self, scope: str) -> None:
        if scope not in self._scopes:
            raise PermissionError(f"storage client scope does not permit {scope}")

    @staticmethod
    def _uuid(value: object, name: str) -> UUID:
        if not isinstance(value, UUID):
            raise ContractValidationError(f"{name} must be a UUIDv4")
        validate_uuid4(str(value))
        return value

    @classmethod
    def _receipt(cls, value: object) -> None:
        if not isinstance(value, dict) or set(value) != {
            "record_ids",
            "artifact_hashes",
            "ledger_first",
            "ledger_last",
            "committed_at",
        }:
            raise StorageTransportError("storage commit receipt is invalid")
        records, artifacts = value["record_ids"], value["artifact_hashes"]
        if (
            not isinstance(records, list)
            or not isinstance(artifacts, list)
            or len(records) > 1_000_000
            or len(artifacts) > 1_000_000
        ):
            raise StorageTransportError("storage commit receipt arrays are invalid")
        try:
            if not all(isinstance(item, str) for item in records):
                raise StorageTransportError("storage record ids are invalid")
            record_ids = tuple(
                str(cls._uuid(UUID(item), "record_id")) for item in records
            )
            hashes = tuple(validate_sha256(item) for item in artifacts)
            first, last = value["ledger_first"], value["ledger_last"]
            if (first is None) != (last is None):
                raise StorageTransportError("storage ledger receipt range is invalid")
            if first is not None and (
                validate_positive_int(first) > validate_positive_int(last)
            ):
                raise StorageTransportError("storage ledger receipt range is invalid")
            validate_utc_instant(value["committed_at"])
        except (
            AttributeError,
            ContractValidationError,
            TypeError,
            ValueError,
        ) as error:
            raise StorageTransportError("storage commit receipt is invalid") from error
        if len(set(record_ids)) != len(record_ids) or len(set(hashes)) != len(hashes):
            raise StorageTransportError("storage commit receipt values are duplicated")

    @staticmethod
    def _ask_success(operation: str, data: dict[str, Any]) -> None:
        if operation == "jev_asks:reserve":
            if set(data) != {"reservation_id", "request_hash"} or (
                data["reservation_id"] is None
            ) != (data["request_hash"] is None):
                raise StorageTransportError("ask reservation response is invalid")
            if data["reservation_id"] is not None:
                validate_uuid4(data["reservation_id"])
                validate_sha256(data["request_hash"])
        elif operation == "jev_asks:settle":
            if set(data) != {"reservation_id", "response_hash"}:
                raise StorageTransportError("ask settlement response is invalid")
            validate_uuid4(data["reservation_id"])
            if data["response_hash"] is not None:
                validate_sha256(data["response_hash"])
        elif operation == "jev_asks:record":
            if set(data) != {"run_id", "work_key"}:
                raise StorageTransportError("kept ask response is invalid")
            validate_uuid4(data["run_id"])
            validate_sha256(data["work_key"])
        else:
            raise StorageTransportError("storage operation is unsupported")

    @classmethod
    def _validate_success(cls, operation: str, data: dict[str, Any]) -> None:
        try:
            if operation == "claim":
                if set(data) != {"lease"}:
                    raise StorageTransportError("claim response data is invalid")
                lease = data["lease"]
                if lease is None:
                    return
                if not isinstance(lease, dict) or set(lease) != {
                    "job_id",
                    "kind",
                    "lease_epoch",
                    "expires_at",
                    "input_manifest",
                    "checkpoint",
                }:
                    raise StorageTransportError("job lease is invalid")
                cls._uuid(UUID(lease["job_id"]), "job_id")
                if not isinstance(lease["kind"], str) or lease["kind"] not in JOB_KINDS:
                    raise StorageTransportError("job lease kind is invalid")
                validate_positive_int(lease["lease_epoch"])
                validate_utc_instant(lease["expires_at"])
                validate_sha256(lease["input_manifest"])
                if lease["checkpoint"] is not None:
                    validate_sha256(lease["checkpoint"])
                return
            if operation == "renew":
                if set(data) != {"expires_at", "receipt"}:
                    raise StorageTransportError("renew response data is invalid")
                validate_utc_instant(data["expires_at"])
            elif operation == "checkpoint":
                if set(data) != {"checkpoint_id", "receipt"}:
                    raise StorageTransportError("checkpoint response data is invalid")
                cls._uuid(UUID(data["checkpoint_id"]), "checkpoint_id")
            elif operation == "complete":
                if set(data) != {"job_id", "state", "receipt"}:
                    raise StorageTransportError("complete response data is invalid")
                cls._uuid(UUID(data["job_id"]), "job_id")
                if data["state"] not in {"committed", "failed", "skipped"}:
                    raise StorageTransportError("complete response state is invalid")
            elif operation == "artifact":
                if set(data) != {
                    "artifact_hash",
                    "byte_length",
                    "created_at",
                    "receipt",
                }:
                    raise StorageTransportError("artifact receipt data is invalid")
                validate_sha256(data["artifact_hash"])
                if (
                    isinstance(data["byte_length"], bool)
                    or not isinstance(data["byte_length"], int)
                    or data["byte_length"] < 0
                ):
                    raise StorageTransportError("artifact receipt length is invalid")
                validate_utc_instant(data["created_at"])
            elif operation == "runs:create":
                if set(data) != {"run_id", "created_at", "receipt"}:
                    raise StorageTransportError("run create response data is invalid")
                cls._uuid(UUID(data["run_id"]), "run_id")
                validate_utc_instant(data["created_at"])
            elif operation == "runs:append_event":
                if set(data) != {"run_id", "attempt", "ordinal", "receipt"}:
                    raise StorageTransportError("run event response data is invalid")
                cls._uuid(UUID(data["run_id"]), "run_id")
                validate_positive_int(data["attempt"])
                validate_non_negative_int(data["ordinal"])
            elif operation == "runs:submit":
                if "accepted" not in data or not isinstance(data["accepted"], bool):
                    raise StorageTransportError("run submit response data is invalid")
                if not data["accepted"]:
                    if (
                        set(data) != {"accepted", "reason", "receipt"}
                        or not isinstance(data["reason"], str)
                        or not 1 <= len(data["reason"]) <= 512
                    ):
                        raise StorageTransportError(
                            "run submit response data is invalid"
                        )
                else:
                    if set(data) != {"accepted", "run_id", "submission_id", "receipt"}:
                        raise StorageTransportError(
                            "run submit response data is invalid"
                        )
                    validate_uuid4(data["run_id"])
                    validate_uuid4(data["submission_id"])
                    receipt = data["receipt"]
                    # Resubmitting the same bytes returns the original
                    # acceptance time, not a new commit receipt.
                    if isinstance(receipt, dict) and "replay" in receipt:
                        if (
                            set(receipt) != {"replay", "accepted_at"}
                            or receipt["replay"] is not True
                        ):
                            raise StorageTransportError(
                                "run submit replay receipt is invalid"
                            )
                        validate_utc_instant(receipt["accepted_at"])
                        return
            elif operation == "runs:void":
                if "voided" not in data or not isinstance(data["voided"], bool):
                    raise StorageTransportError("run void response data is invalid")
                if not data["voided"]:
                    if set(data) != {"voided", "run_id", "state"} or data[
                        "state"
                    ] not in {"submitted", "void"}:
                        raise StorageTransportError("run void response data is invalid")
                    validate_uuid4(data["run_id"])
                    return
                if set(data) != {"voided", "run_id", "reason", "ended_at", "receipt"}:
                    raise StorageTransportError("run void response data is invalid")
                validate_uuid4(data["run_id"])
                validate_utc_instant(data["ended_at"])
            elif operation == "snapshots:seal":
                if set(data) != {"snapshot_hash", "sealed_at", "receipt"}:
                    raise StorageTransportError(
                        "snapshot seal response data is invalid"
                    )
                validate_sha256(data["snapshot_hash"])
                validate_utc_instant(data["sealed_at"])
            elif operation == "sheets:seal":
                if set(data) != {"sheet_hash", "sealed_at", "receipt"}:
                    raise StorageTransportError("sheet seal response data is invalid")
                validate_sha256(data["sheet_hash"])
                validate_utc_instant(data["sealed_at"])
            elif operation == "submissions:submit":
                if "accepted" not in data or not isinstance(data["accepted"], bool):
                    raise StorageTransportError("submit response data is invalid")
                if data["accepted"]:
                    if set(data) != {"accepted", "submission_ids", "receipt"}:
                        raise StorageTransportError("submit response data is invalid")
                    for submission_id in data["submission_ids"]:
                        cls._uuid(UUID(submission_id), "submission_id")
                elif set(data) != {"accepted", "reason", "receipt"}:
                    raise StorageTransportError("submit response data is invalid")
                elif (
                    not isinstance(data["reason"], str)
                    or not 1 <= len(data["reason"]) <= 512
                ):
                    raise StorageTransportError("submit response reason is invalid")
            elif operation == "ratings:record":
                if set(data) != {"rating_id", "rated_at", "receipt"}:
                    raise StorageTransportError(
                        "rating record response data is invalid"
                    )
                cls._uuid(UUID(data["rating_id"]), "rating_id")
                validate_utc_instant(data["rated_at"])
            elif operation == "raters:provision":
                if set(data) != {"rater_id", "provisioned_at", "receipt"}:
                    raise StorageTransportError(
                        "rater provision response data is invalid"
                    )
                cls._uuid(UUID(data["rater_id"]), "rater_id")
                validate_utc_instant(data["provisioned_at"])
            elif operation == "paper_requests:record":
                if set(data) != {"outcome", "request_id", "family_id", "receipt"}:
                    raise StorageTransportError(
                        "paper request response data is invalid"
                    )
                if data["outcome"] not in PAPER_REQUEST_OUTCOMES:
                    raise StorageTransportError(
                        "paper request response outcome is invalid"
                    )
                validate_uuid4(data["family_id"])
                exhausted = data["outcome"] == "request_budget_exhausted"
                if exhausted != (data["request_id"] is None):
                    raise StorageTransportError(
                        "paper request response data is invalid"
                    )
                if not exhausted:
                    validate_uuid4(data["request_id"])
                # A requested row and a refused one are both recorded.
                if (data["outcome"] == "already_requested") != (
                    data["receipt"] is None
                ):
                    raise StorageTransportError(
                        "paper request response receipt is invalid"
                    )
                if data["receipt"] is None:
                    return
            elif operation == "paper_requests:transition":
                if set(data) != {
                    "request_id",
                    "status",
                    "reason",
                    "paper_version_id",
                    "receipt",
                }:
                    raise StorageTransportError(
                        "paper request transition response data is invalid"
                    )
                validate_uuid4(data["request_id"])
                if data["status"] not in PAPER_REQUEST_STATUSES - {"requested"}:
                    raise StorageTransportError(
                        "paper request transition status is invalid"
                    )
                if data["paper_version_id"] is not None:
                    validate_uuid4(data["paper_version_id"])
            elif operation == "settlements:record":
                if set(data) != {"run_id", "settled_at", "receipt"}:
                    raise StorageTransportError("settlement response data is invalid")
                validate_uuid4(data["run_id"])
                validate_utc_instant(data["settled_at"])
            elif operation == "resources:record":
                if set(data) != {"run_id", "recorded_at", "receipt"}:
                    raise StorageTransportError("resources response data is invalid")
                validate_uuid4(data["run_id"])
                validate_utc_instant(data["recorded_at"])
            elif operation in {"trace:request", "trace:terminal"}:
                instant = "started_at" if operation == "trace:request" else "ended_at"
                if set(data) != {
                    "run_id",
                    "call_id",
                    "call_sequence",
                    instant,
                    "receipt",
                }:
                    raise StorageTransportError("trace response data is invalid")
                validate_uuid4(data["run_id"])
                validate_uuid4(data["call_id"])
                validate_positive_int(data["call_sequence"])
                validate_utc_instant(data[instant])
            elif operation.startswith("jev_asks:"):
                # An ask's rows are Jev work records, not ledger events: its
                # answer carries no commit receipt.
                cls._ask_success(operation, data)
                return
            elif operation == "digests:store":
                if set(data) != {"digest_hash", "built_at", "receipt"}:
                    raise StorageTransportError("digest store response data is invalid")
                validate_sha256(data["digest_hash"])
                validate_utc_instant(data["built_at"])
            else:
                raise StorageTransportError("storage operation is unsupported")
            cls._receipt(data["receipt"])
        except StorageTransportError:
            raise
        except (
            AttributeError,
            ContractValidationError,
            TypeError,
            ValueError,
        ) as error:
            raise StorageTransportError("storage success data is invalid") from error
