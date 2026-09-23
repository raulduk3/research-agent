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


_MAX_RATIONALE_CHARS = 2000
_MAX_ANSWERS = 5


def _bounded_rationale(value: object) -> str:
    text = validate_non_empty_string(value)
    if len(text) > _MAX_RATIONALE_CHARS:
        raise ContractValidationError(
            f"rationale must be at most {_MAX_RATIONALE_CHARS} characters"
        )
    return text


def _paper_id(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or "\x00" in value:
        raise ContractValidationError("paper_id is invalid")
    return value


def _answer(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError("Answer must be a JSON object")
    answer = _closed(
        value, {"question_id", "probability", "rationale", "evidence_ids"}, "Answer"
    )
    return {
        "question_id": validate_uuid4(answer["question_id"]),
        "probability": validate_probability(answer["probability"]),
        "rationale": _bounded_rationale(answer["rationale"]),
        "evidence_ids": _evidence_hashes(answer["evidence_ids"]),
    }


def parse_answers(value: object) -> list[dict[str, Any]]:
    """Validate one submit call's per-question forecast answers (AG-26).

    Shape only: a finite [0,1] probability, a rationale of at most 2000
    characters and one to five distinct evidence ids each, with distinct
    question ids across the whole list. Zero answers is admitted for a
    questionless engineering slot (TDD-3.1.57); coverage against the run's
    own issued question set is the caller's job (``tools/dispatch.py``,
    ``storage/submissions.py#accept_submission``), since this module does
    not know a run's own slot.
    """

    if not isinstance(value, list) or not 0 <= len(value) <= _MAX_ANSWERS:
        raise ContractValidationError(
            f"answers must be a JSON array with 0 to {_MAX_ANSWERS} items"
        )
    answers = [_answer(item) for item in value]
    identifiers = [answer["question_id"] for answer in answers]
    if len(set(identifiers)) != len(identifiers):
        raise ContractValidationError("answers must name distinct question_id")
    return answers


def parse_nomination(value: object) -> dict[str, Any]:
    """Validate a submit call's one nomination for the run's own paper (AG-26).

    Shape only: ``recommend`` is a boolean, ``preference`` a finite [0,1]
    probability (the sealed ``rater_like_7d`` forecast) and ``rationale``
    at most 2000 characters. Whether ``paper_id`` actually equals the
    run's own paper is the caller's job, not this parser's.
    """

    if not isinstance(value, dict):
        raise ContractValidationError("Nomination must be a JSON object")
    nomination = _closed(
        value, {"paper_id", "recommend", "preference", "rationale"}, "Nomination"
    )
    recommend = nomination["recommend"]
    if not isinstance(recommend, bool):
        raise ContractValidationError("Nomination.recommend must be a boolean")
    return {
        "paper_id": _paper_id(nomination["paper_id"]),
        "recommend": recommend,
        "preference": validate_probability(nomination["preference"]),
        "rationale": _bounded_rationale(nomination["rationale"]),
    }


def parse_submit_args(value: object) -> dict[str, Any]:
    """Validate a submit call's complete answer/nomination schema (AG-26, TDD-3.1.51).

    ``submission_id`` names this attempt for idempotent retry: storage
    returns the original receipt for a retry with the same
    ``(run_id, submission_id)`` and identical bytes rather than resealing.
    """

    args = _closed(value, {"submission_id", "answers", "nomination"}, "submit")
    return {
        "submission_id": validate_uuid4(args["submission_id"]),
        "answers": parse_answers(args["answers"]),
        "nomination": parse_nomination(args["nomination"]),
    }


def validate_accept_submission_payload(
    operation: str, payload: object
) -> dict[str, Any]:
    """Validate and copy the outer envelope of an ``accept_submission`` command.

    Wraps :func:`parse_submit_args` with the ``run_id`` the answers and
    nomination are sealed against (AG-26, TDD-3.1.57).
    """

    if operation != "accept_submission":
        raise ContractValidationError("unknown submission operation")
    value = _closed(
        payload,
        {"run_id", "submission_id", "answers", "nomination"},
        "accept_submission payload",
    )
    args = parse_submit_args(
        {
            "submission_id": value["submission_id"],
            "answers": value["answers"],
            "nomination": value["nomination"],
        }
    )
    return {"run_id": validate_uuid4(value["run_id"]), **args}


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
