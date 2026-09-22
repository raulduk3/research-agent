from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.submissions import (
    parse_claims,
    validate_rating_payload,
    validate_submission_payload,
)

QUESTION_ID = "123e4567-e89b-42d3-a456-426614174000"
OTHER_QUESTION_ID = "123e4567-e89b-42d3-a456-426614174001"
SHEET_HASH = "a" * 64
SUBMITTER_ID = "123e4567-e89b-42d3-a456-426614174002"
EVIDENCE_HASH = "b" * 64
RATER_ID = "123e4567-e89b-42d3-a456-426614174003"
PAPER_HASH = "c" * 64
DIGEST_ENTRY_ID = "123e4567-e89b-42d3-a456-426614174004"
FORECAST_CLAIM = {
    "kind": "forecast",
    "question_id": QUESTION_ID,
    "evidence_hashes": [EVIDENCE_HASH],
    "confidence": 0.75,
}
VOID_CLAIM = {
    "kind": "void",
    "question_id": OTHER_QUESTION_ID,
    "reason": "no resolver is registered for this target",
}


def test_submit_envelope_accepts_the_normative_shape() -> None:
    payload = {
        "sheet_hash": SHEET_HASH,
        "submitter_id": SUBMITTER_ID,
        "claims": [FORECAST_CLAIM],
    }
    assert validate_submission_payload("submit", payload) == payload


def test_parse_claims_accepts_the_forecast_and_void_union() -> None:
    claims = parse_claims([FORECAST_CLAIM, VOID_CLAIM])
    assert claims == [FORECAST_CLAIM, VOID_CLAIM]


def test_parse_claims_rejects_unknown_kind_and_mixed_fields() -> None:
    with pytest.raises(ContractValidationError):
        parse_claims([{**FORECAST_CLAIM, "kind": "other"}])
    with pytest.raises(ContractValidationError):
        parse_claims([{**FORECAST_CLAIM, "reason": "not admitted here"}])


def test_parse_claims_rejects_out_of_range_confidence_and_evidence_bounds() -> None:
    with pytest.raises(ContractValidationError):
        parse_claims([{**FORECAST_CLAIM, "confidence": 1.5}])
    with pytest.raises(ContractValidationError):
        parse_claims([{**FORECAST_CLAIM, "evidence_hashes": []}])
    with pytest.raises(ContractValidationError):
        parse_claims([{**FORECAST_CLAIM, "evidence_hashes": [EVIDENCE_HASH] * 6}])
    with pytest.raises(ContractValidationError):
        parse_claims(
            [{**FORECAST_CLAIM, "evidence_hashes": [EVIDENCE_HASH, EVIDENCE_HASH]}]
        )


def test_parse_claims_rejects_duplicate_question_ids() -> None:
    with pytest.raises(ContractValidationError):
        parse_claims([FORECAST_CLAIM, FORECAST_CLAIM])


def test_rating_payload_accepts_the_admitted_values_only() -> None:
    payload = {
        "rater_id": RATER_ID,
        "paper_hash": PAPER_HASH,
        "digest_entry_id": DIGEST_ENTRY_ID,
        "value": "like",
    }
    assert validate_rating_payload("record", payload) == payload
    with pytest.raises(ContractValidationError):
        validate_rating_payload("record", {**payload, "value": "love"})


def test_unknown_operations_are_rejected() -> None:
    with pytest.raises(ContractValidationError):
        validate_submission_payload("delete", {})
    with pytest.raises(ContractValidationError):
        validate_rating_payload("delete", {})
