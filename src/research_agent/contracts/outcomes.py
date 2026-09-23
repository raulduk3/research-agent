"""Strict wire contract for storage-owned resolution settlement (EN-04, EN-08)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

RESOLUTION_STATUS_VALUES = frozenset({"true", "false", "unresolvable"})
WITNESS_LIMIT = 5
_MAX_REASON_CHARS = 128
_MAX_RESOLVER_ID_CHARS = 128

OPERATIONAL_FINDING_KIND_VALUES = frozenset({"resolver_unavailable"})
_MAX_FINDING_DETAIL_CHARS = 256


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _witness_ids(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > WITNESS_LIMIT:
        raise ContractValidationError(
            f"witness_ids must be a JSON array with at most {WITNESS_LIMIT} items"
        )
    witnesses = [validate_non_empty_string(item) for item in value]
    if len(set(witnesses)) != len(witnesses):
        raise ContractValidationError("witness_ids must be distinct")
    return witnesses


def _bounded(value: object, *, limit: int, name: str) -> str:
    text = validate_non_empty_string(value)
    if len(text) > limit:
        raise ContractValidationError(f"{name} must be at most {limit} characters")
    return text


@dataclass(frozen=True, slots=True)
class OperationalFinding:
    """A durable record of a condition dispatch cannot settle on its own (TDD-3.1.15).

    A pinned question names a resolver build that dispatch cannot load, so
    settlement stops rather than substituting a newer registry; this is the
    closed, typed record dispatch schedules for that condition instead of a
    free-text log line, keeping the finding an inspectable, storable value.
    """

    kind: str
    pinned_registry_hash: str
    detail: str
    detected_at: str

    def __post_init__(self) -> None:
        if self.kind not in OPERATIONAL_FINDING_KIND_VALUES:
            raise ContractValidationError("operational finding kind is not admitted")
        validate_sha256(self.pinned_registry_hash)
        _bounded(self.detail, limit=_MAX_FINDING_DETAIL_CHARS, name="detail")
        validate_utc_instant(self.detected_at)


def validate_resolution_store_payload(
    operation: str, payload: object
) -> dict[str, Any]:
    """Validate and copy the exact payload for a resolution-append operation.

    Shape only: cross-checks against the sealed forecast, the question's
    pinned resolver identity and any prior resolution for the same forecast
    are storage's job (``storage/resolutions.py``), since this parser has no
    database access.
    """

    if operation != "append":
        raise ContractValidationError("unknown resolution operation")
    value = _closed(
        payload,
        {
            "forecast_id",
            "question_id",
            "as_of",
            "resolver_id",
            "resolver_build_digest",
            "target_definition_hash",
            "observation_protocol_version",
            "observation_hash",
            "status",
            "witness_ids",
            "completion_proof_hash",
            "lower_bound",
            "upper_bound",
            "reason",
            "resolution_version",
            "supersedes_resolution_id",
        },
        "resolution append payload",
    )
    status = value["status"]
    if status not in RESOLUTION_STATUS_VALUES:
        raise ContractValidationError("status is not an admitted resolution value")
    witnesses = _witness_ids(value["witness_ids"])
    if status == "true" and not witnesses:
        raise ContractValidationError("a true resolution requires positive witnesses")
    if status != "true" and witnesses:
        raise ContractValidationError(
            "only a true resolution carries positive witnesses"
        )
    completion_proof_hash = value["completion_proof_hash"]
    if status == "false" and completion_proof_hash is None:
        raise ContractValidationError("a false resolution requires a completion proof")
    lower_bound = validate_non_negative_int(value["lower_bound"])
    upper_bound = value["upper_bound"]
    if upper_bound is not None:
        upper_bound = validate_non_negative_int(upper_bound)
        if upper_bound < lower_bound:
            raise ContractValidationError("upper_bound is below lower_bound")
    supersedes_resolution_id = value["supersedes_resolution_id"]
    resolution_version = validate_positive_int(value["resolution_version"])
    if resolution_version == 1 and supersedes_resolution_id is not None:
        raise ContractValidationError(
            "the first resolution version cannot supersede another"
        )
    if resolution_version > 1 and supersedes_resolution_id is None:
        raise ContractValidationError(
            "a correction must name the resolution it supersedes"
        )
    return {
        "forecast_id": validate_uuid4(value["forecast_id"]),
        "question_id": validate_uuid4(value["question_id"]),
        "as_of": validate_utc_instant(value["as_of"]),
        "resolver_id": _bounded(
            value["resolver_id"], limit=_MAX_RESOLVER_ID_CHARS, name="resolver_id"
        ),
        "resolver_build_digest": validate_sha256(value["resolver_build_digest"]),
        "target_definition_hash": validate_sha256(value["target_definition_hash"]),
        "observation_protocol_version": validate_positive_int(
            value["observation_protocol_version"]
        ),
        "observation_hash": validate_sha256(value["observation_hash"]),
        "status": status,
        "witness_ids": witnesses,
        "completion_proof_hash": validate_sha256(completion_proof_hash)
        if completion_proof_hash is not None
        else None,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "reason": _bounded(value["reason"], limit=_MAX_REASON_CHARS, name="reason"),
        "resolution_version": resolution_version,
        "supersedes_resolution_id": validate_uuid4(supersedes_resolution_id)
        if supersedes_resolution_id is not None
        else None,
    }
