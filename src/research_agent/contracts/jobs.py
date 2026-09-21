"""Strict wire contracts for storage-owned durable jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from .canonical import CanonicalJsonError, canonical_json, canonical_loads
from .primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)


JOB_KINDS = frozenset(
    {
        "capture",
        "extract",
        "embed",
        "label",
        "fit",
        "calibrate",
        "predict",
        "assess",
        "qualify",
        "baseline",
        "score",
        "audit",
    }
)

ERROR_CODES = frozenset(
    {
        "malformed_json",
        "unauthenticated",
        "forbidden",
        "not_found",
        "invalid_input",
        "idempotency_conflict",
        "state_conflict",
        "lease_expired",
        "stale_lease",
        "incompatible_manifest",
        "unavailable_input",
        "deadline_exceeded",
        "budget_exceeded",
        "integrity_failure",
        "capacity_exceeded",
        "temporarily_unavailable",
        "incompatible_snapshot",
        "evidence_not_retrieved",
        "incomplete_answers",
        "upstream_rejected",
        "upstream_ambiguous",
        "unavailable_source",
        "funding_disabled",
    }
)


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _bounded_list(value: object, lower: int, upper: int, name: str) -> list[Any]:
    if not isinstance(value, list) or not lower <= len(value) <= upper:
        raise ContractValidationError(
            f"{name} must be a JSON array with {lower} to {upper} items"
        )
    return value


def _literal(value: object, choices: frozenset[str], name: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ContractValidationError(f"{name} is not an admitted value")
    return value


def _hashes(value: object, lower: int, upper: int, name: str) -> list[str]:
    result = [
        validate_sha256(item) for item in _bounded_list(value, lower, upper, name)
    ]
    if len(result) != len(set(result)):
        raise ContractValidationError(f"{name} must contain distinct hashes")
    return result


def _fence(value: object) -> dict[str, Any]:
    fence = _closed(value, {"worker_id", "lease_epoch"}, "LeaseFence")
    return {
        "worker_id": validate_uuid4(fence["worker_id"]),
        "lease_epoch": validate_positive_int(fence["lease_epoch"]),
    }


def _error(value: object) -> dict[str, Any]:
    error = _closed(value, {"code", "message", "retryable", "evidence_ids"}, "Error")
    message = validate_non_empty_string(error["message"])
    if len(message) > 512:
        raise ContractValidationError(
            "Error.message must contain at most 512 characters"
        )
    if not isinstance(error["retryable"], bool):
        raise ContractValidationError("Error.retryable must be a boolean")
    return {
        "code": _literal(error["code"], ERROR_CODES, "Error.code"),
        "message": message,
        "retryable": error["retryable"],
        "evidence_ids": _hashes(error["evidence_ids"], 0, 20, "Error.evidence_ids"),
    }


def _result(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError("JobResult must be a JSON object")
    kind = value.get("kind")
    if kind == "committed":
        result = _closed(value, {"kind", "output_hashes"}, "committed JobResult")
        return {
            "kind": "committed",
            "output_hashes": _hashes(
                result["output_hashes"], 1, 1000, "JobResult.output_hashes"
            ),
        }
    if kind == "failed":
        result = _closed(value, {"kind", "error"}, "failed JobResult")
        return {"kind": "failed", "error": _error(result["error"])}
    if kind == "skipped":
        result = _closed(
            value,
            {"kind", "reason", "evidence_hashes"},
            "skipped JobResult",
        )
        return {
            "kind": "skipped",
            "reason": _literal(
                result["reason"],
                frozenset({"unavailable_input", "ineligible", "disabled"}),
                "JobResult.reason",
            ),
            "evidence_hashes": _hashes(
                result["evidence_hashes"], 0, 20, "JobResult.evidence_hashes"
            ),
        }
    raise ContractValidationError("JobResult.kind is not an admitted value")


def validate_job_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a durable-job operation.

    ``enqueue`` is storage-internal. The other names correspond to the payload
    inside the version-one ``Command`` envelope for their storage routes.
    """

    if operation == "claim":
        value = _closed(payload, {"worker_id", "kinds"}, "claim payload")
        kinds = [
            _literal(item, JOB_KINDS, "JobKind")
            for item in _bounded_list(value["kinds"], 1, 12, "kinds")
        ]
        if len(kinds) != len(set(kinds)):
            raise ContractValidationError("kinds must be distinct")
        return {"worker_id": validate_uuid4(value["worker_id"]), "kinds": kinds}
    if operation == "renew":
        return _fence(payload)
    if operation == "checkpoint":
        value = _closed(payload, {"fence", "checkpoint"}, "checkpoint payload")
        return {
            "fence": _fence(value["fence"]),
            "checkpoint": validate_sha256(value["checkpoint"]),
        }
    if operation == "complete":
        value = _closed(payload, {"fence", "result"}, "complete payload")
        return {"fence": _fence(value["fence"]), "result": _result(value["result"])}
    if operation == "enqueue":
        value = _closed(
            payload,
            {"job_id", "kind", "input_manifest", "scheduled_at"},
            "enqueue payload",
        )
        return {
            "job_id": validate_uuid4(value["job_id"]),
            "kind": _literal(value["kind"], JOB_KINDS, "JobKind"),
            "input_manifest": validate_sha256(value["input_manifest"]),
            "scheduled_at": validate_utc_instant(value["scheduled_at"]),
        }
    raise ContractValidationError("unknown job operation")


@dataclass(frozen=True, slots=True)
class JobCheckpoint:
    """Version-one checkpoint manifest described by the recovery contract."""

    schema_version: int
    job_id: str
    stage: str
    input_hashes: tuple[str, ...]
    config_hash: str
    completed_work_keys: tuple[str, ...]
    continuation_cursor: str | None
    output_hashes: tuple[str, ...]

    _FIELDS: ClassVar[set[str]] = {
        "schema_version",
        "job_id",
        "stage",
        "input_hashes",
        "config_hash",
        "completed_work_keys",
        "continuation_cursor",
        "output_hashes",
    }

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ContractValidationError("JobCheckpoint.schema_version must be 1")
        validate_uuid4(self.job_id)
        stage = validate_non_empty_string(self.stage)
        if len(stage) > 64:
            raise ContractValidationError("JobCheckpoint.stage is too long")
        if not isinstance(self.input_hashes, tuple) or len(self.input_hashes) > 1000:
            raise ContractValidationError(
                "input_hashes must contain at most 1000 hashes"
            )
        for item in self.input_hashes:
            validate_sha256(item)
        validate_sha256(self.config_hash)
        if (
            not isinstance(self.completed_work_keys, tuple)
            or len(self.completed_work_keys) > 1_000_000
        ):
            raise ContractValidationError(
                "completed_work_keys must contain at most 1000000 hashes"
            )
        for item in self.completed_work_keys:
            validate_sha256(item)
        if self.continuation_cursor is not None:
            cursor = validate_non_empty_string(self.continuation_cursor)
            if len(cursor) > 4096:
                raise ContractValidationError("continuation_cursor is too long")
        if not isinstance(self.output_hashes, tuple) or len(self.output_hashes) > 1000:
            raise ContractValidationError(
                "output_hashes must contain at most 1000 hashes"
            )
        for item in self.output_hashes:
            validate_sha256(item)

        for values in (self.input_hashes, self.completed_work_keys, self.output_hashes):
            if isinstance(values, tuple) and len(values) != len(set(values)):
                raise ContractValidationError("checkpoint hashes must be distinct")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "stage": self.stage,
            "input_hashes": list(self.input_hashes),
            "config_hash": self.config_hash,
            "completed_work_keys": list(self.completed_work_keys),
            "continuation_cursor": self.continuation_cursor,
            "output_hashes": list(self.output_hashes),
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "JobCheckpoint":
        try:
            value = canonical_loads(raw)
        except CanonicalJsonError as error:
            raise ContractValidationError("invalid JobCheckpoint JSON") from error
        fields = _closed(value, cls._FIELDS, "JobCheckpoint")
        for name in ("input_hashes", "completed_work_keys", "output_hashes"):
            if not isinstance(fields[name], list):
                raise ContractValidationError(
                    f"JobCheckpoint.{name} must be a JSON array"
                )
        return cls(
            schema_version=fields["schema_version"],
            job_id=fields["job_id"],
            stage=fields["stage"],
            input_hashes=tuple(fields["input_hashes"]),
            config_hash=fields["config_hash"],
            completed_work_keys=tuple(fields["completed_work_keys"]),
            continuation_cursor=fields["continuation_cursor"],
            output_hashes=tuple(fields["output_hashes"]),
        )
