"""Strict wire contracts for storage-owned issued question sheets."""

from __future__ import annotations

from typing import Any

from .canonical import canonical_json, sha256_hex
from .primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _resolver_id(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or "\x00" in value:
        raise ContractValidationError("Question.resolver_id is invalid")
    return value


def _question(value: object) -> dict[str, Any]:
    question = _closed(
        value,
        {
            "question_id",
            "target_definition_hash",
            "resolver_id",
            "resolver_version",
            "horizon",
        },
        "Question",
    )
    return {
        "question_id": validate_uuid4(question["question_id"]),
        "target_definition_hash": validate_sha256(question["target_definition_hash"]),
        "resolver_id": _resolver_id(question["resolver_id"]),
        "resolver_version": validate_non_negative_int(question["resolver_version"]),
        "horizon": validate_utc_instant(question["horizon"]),
    }


def _questions(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ContractValidationError(
            "questions must be a JSON array with 1 to 20 items"
        )
    questions = [_question(item) for item in value]
    identifiers = [question["question_id"] for question in questions]
    if len(set(identifiers)) != len(identifiers):
        raise ContractValidationError("questions must have distinct question_id")
    return questions


def validate_sheet_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a sheet-record operation."""

    if operation != "seal":
        raise ContractValidationError("unknown sheet operation")
    value = _closed(payload, {"questions"}, "seal payload")
    return {"questions": _questions(value["questions"])}


def sheet_identity(questions: list[dict[str, Any]]) -> str:
    """Return the content-addressed identity of a sealed sheet (EN-10).

    Recomputing this from the same ordered questions always reproduces the
    same hash; a sheet whose questions differ in any way seals to a different
    identity, so a claim citing the original identity cannot reach an altered
    sheet.
    """

    return sha256_hex(canonical_json({"schema_version": 1, "questions": questions}))
