"""Strict contracts for forecast admission and prospective eligibility.

Covers the four-way prospective disposition (EN-02), the typed refusal
record shared by disabled forecast types and unissued questions (EN-24 to
EN-27, EN-30), and the recorded admission of the fixed automatic-citations-v1
registry (EN-31).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .learning import TARGET_IDS
from .primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
)

PROSPECTIVE_STATUSES = frozenset(
    {"eligible", "preexisting_event", "timing_ambiguous", "missed_deadline"}
)
ADMISSION_REFUSAL_REASONS = frozenset({"unadmitted_type", "unissued_question"})


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or "\x00" in value:
        raise ContractValidationError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class ProspectiveEligibility:
    """The disposition ``forecasts.eligibility.check_prospective`` returns (EN-02).

    ``witness_hashes`` names the content hashes of the citation family
    records that establish ``preexisting_event`` or ``timing_ambiguous``;
    the other two statuses cite no evidence.
    """

    status: str
    witness_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in PROSPECTIVE_STATUSES:
            raise ContractValidationError("prospective status is not an admitted value")
        if not isinstance(self.witness_hashes, tuple) or len(
            set(self.witness_hashes)
        ) != len(self.witness_hashes):
            raise ContractValidationError("witness_hashes must be distinct")
        for value in self.witness_hashes:
            validate_sha256(value)
        if self.status in {"eligible", "missed_deadline"} and self.witness_hashes:
            raise ContractValidationError(
                f"{self.status} disposition cannot cite witness evidence"
            )
        if (
            self.status in {"preexisting_event", "timing_ambiguous"}
            and not self.witness_hashes
        ):
            raise ContractValidationError(
                f"{self.status} disposition requires witness evidence"
            )


@dataclass(frozen=True, slots=True)
class AdmissionRefusal:
    """The typed refusal for a disallowed forecast type or question (EN-24 to EN-27, EN-30)."""

    reason: str
    attempted_type: str
    request_hash: str

    def __post_init__(self) -> None:
        if self.reason not in ADMISSION_REFUSAL_REASONS:
            raise ContractValidationError("refusal reason is not an admitted value")
        validate_non_empty_string(self.attempted_type)
        if len(self.attempted_type) > 128:
            raise ContractValidationError("attempted_type is too long")
        validate_sha256(self.request_hash)


def validate_target_request(value: object) -> dict[str, Any]:
    """Validate the shape of a proposed-forecast-type admission request (EN-24 to EN-27).

    Shape only: admission itself -- whether ``requested_type`` is one of
    the three launch target ids -- is ``forecasts.admission.validate_target``'s
    job, not this parser's.
    """

    request = _closed(
        value,
        {"requested_type", "resolver_id", "target_definition_hash"},
        "ForecastTypeRequest",
    )
    return {
        "requested_type": _identifier(request["requested_type"], "requested_type"),
        "resolver_id": _identifier(request["resolver_id"], "resolver_id"),
        "target_definition_hash": validate_sha256(request["target_definition_hash"]),
    }


def validate_issued_question_request(value: object) -> dict[str, Any]:
    """Validate the shape of an issued-question admission request (EN-30).

    ``question_id`` is nullable: a forecast without an issued identity is
    an otherwise well-formed request, refused by
    ``forecasts.admission.validate_issued_question`` rather than by shape.
    """

    request = _closed(
        value,
        {"paper_id", "requested_type", "question_id"},
        "IssuedQuestionRequest",
    )
    question_id = request["question_id"]
    if question_id is not None:
        question_id = _identifier(question_id, "question_id")
    return {
        "paper_id": _identifier(request["paper_id"], "paper_id"),
        "requested_type": _identifier(request["requested_type"], "requested_type"),
        "question_id": question_id,
    }


@dataclass(frozen=True, slots=True)
class RegistryAdmission:
    """The recorded admission of the fixed automatic-citations-v1 registry (EN-31)."""

    admitted_target_ids: tuple[str, ...]
    target_definition_hashes: tuple[str, ...]
    resolver_build_hashes: tuple[str, ...]
    conformance_report_hash: str

    def __post_init__(self) -> None:
        if self.admitted_target_ids != TARGET_IDS:
            raise ContractValidationError(
                "registry admission covers the wrong target ids"
            )
        if len(self.target_definition_hashes) != len(TARGET_IDS) or len(
            self.resolver_build_hashes
        ) != len(TARGET_IDS):
            raise ContractValidationError("registry admission hashes are incomplete")
        for value in (*self.target_definition_hashes, *self.resolver_build_hashes):
            validate_sha256(value)
        validate_sha256(self.conformance_report_hash)
