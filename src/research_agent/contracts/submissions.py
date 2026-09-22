"""Strict wire contracts for storage-owned sealed submissions."""

from __future__ import annotations

from typing import Any

from .primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_probability,
    validate_sha256,
    validate_uuid4,
)


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _evidence_hashes(value: object) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 5:
        raise ContractValidationError(
            "evidence_hashes must be a JSON array with 1 to 5 items"
        )
    hashes = [validate_sha256(item) for item in value]
    if len(set(hashes)) != len(hashes):
        raise ContractValidationError("evidence_hashes must be distinct")
    return hashes


def _claim(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError("Claim must be a JSON object")
    kind = value.get("kind")
    if kind == "forecast":
        claim = _closed(
            value,
            {"kind", "question_id", "evidence_hashes", "confidence"},
            "forecast Claim",
        )
        return {
            "kind": "forecast",
            "question_id": validate_uuid4(claim["question_id"]),
            "evidence_hashes": _evidence_hashes(claim["evidence_hashes"]),
            "confidence": validate_probability(claim["confidence"]),
        }
    if kind == "void":
        claim = _closed(value, {"kind", "question_id", "reason"}, "void Claim")
        reason = validate_non_empty_string(claim["reason"])
        if len(reason) > 512:
            raise ContractValidationError("Claim.reason is too long")
        return {
            "kind": "void",
            "question_id": validate_uuid4(claim["question_id"]),
            "reason": reason,
        }
    raise ContractValidationError("Claim.kind is not an admitted value")


def parse_claims(value: object) -> list[dict[str, Any]]:
    """Validate the deep shape of a submit call's claims.

    Raises ``ContractValidationError`` for any shape, coverage or probability
    failure (SR-07 to SR-11). Callers append a durable rejection audit event
    for this failure rather than refusing the command before it is recorded.
    """

    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ContractValidationError("claims must be a JSON array with 1 to 20 items")
    claims = [_claim(item) for item in value]
    identifiers = [claim["question_id"] for claim in claims]
    if len(set(identifiers)) != len(identifiers):
        raise ContractValidationError("claims must name distinct question_id")
    return claims


def validate_submission_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the outer envelope of a submission operation.

    The inner claims are not deeply validated here; see ``parse_claims``.
    """

    if operation != "submit":
        raise ContractValidationError("unknown submission operation")
    value = _closed(payload, {"sheet_hash", "submitter_id", "claims"}, "submit payload")
    claims = value["claims"]
    if not isinstance(claims, list) or not 1 <= len(claims) <= 20:
        raise ContractValidationError("claims must be a JSON array with 1 to 20 items")
    for claim in claims:
        if not isinstance(claim, dict):
            raise ContractValidationError("claims must be JSON objects")
    return {
        "sheet_hash": validate_sha256(value["sheet_hash"]),
        "submitter_id": validate_uuid4(value["submitter_id"]),
        "claims": claims,
    }


RATING_VALUES = frozenset({"like", "dislike", "skip"})


def validate_rating_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a rating-record operation."""

    if operation != "record":
        raise ContractValidationError("unknown rating operation")
    value = _closed(
        payload,
        {"rater_id", "paper_hash", "digest_entry_id", "value"},
        "record payload",
    )
    rating = value["value"]
    if not isinstance(rating, str) or rating not in RATING_VALUES:
        raise ContractValidationError("rating value is not an admitted value")
    return {
        "rater_id": validate_uuid4(value["rater_id"]),
        "paper_hash": validate_sha256(value["paper_hash"]),
        "digest_entry_id": validate_uuid4(value["digest_entry_id"]),
        "value": rating,
    }
