"""Typed mutually-authenticated HTTPS client for the storage boundary."""

from __future__ import annotations

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
from research_agent.contracts.questions import validate_sheet_payload
from research_agent.contracts.runs import validate_run_payload
from research_agent.contracts.snapshots import validate_snapshot_payload
from research_agent.contracts.submissions import (
    validate_rating_payload,
    validate_submission_payload,
)
from research_agent.storage.http import ARTIFACT_KINDS, ARTIFACT_MEDIA_TYPES
from research_agent.storage.raters import RATER_ISLANDS, validate_rater_payload

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
        "snapshots:seal",
        "sheets:seal",
        "submissions:submit",
        "ratings:record",
        "raters:provision",
        "raters:read",
        "runs:read",
        "submissions:read",
        "manifests:read",
        "configurations:read",
        "forecasts:read",
        "digests:store",
        "digests:read",
        "digests:provenance",
        "owner:admit",
        "owner:seed",
        "owner:retire",
        "owner:read",
    }
)
_JSON_RESPONSE_LIMIT = 1024 * 1024

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

    def _read(self, path: str) -> QueryResult:
        response = self._request(
            "GET", path, None, {}, maximum_bytes=_JSON_RESPONSE_LIMIT
        )
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
    ) -> CommandResult:
        self._require(f"{domain}:{operation}")
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
