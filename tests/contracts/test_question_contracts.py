from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.questions import sheet_identity, validate_sheet_payload

QUESTION_ID = "123e4567-e89b-42d3-a456-426614174000"
OTHER_QUESTION_ID = "123e4567-e89b-42d3-a456-426614174001"
HASH = "a" * 64
QUESTION = {
    "question_id": QUESTION_ID,
    "target_definition_hash": HASH,
    "resolver_id": "citation-reach-v1",
    "resolver_version": 1,
    "horizon": "2027-09-01T00:00:00.000000Z",
}
PAYLOAD = {"questions": [QUESTION]}


def test_seal_accepts_the_normative_shape() -> None:
    assert validate_sheet_payload("seal", PAYLOAD) == PAYLOAD


def test_seal_rejects_empty_and_duplicate_question_ids() -> None:
    with pytest.raises(ContractValidationError):
        validate_sheet_payload("seal", {"questions": []})
    with pytest.raises(ContractValidationError):
        validate_sheet_payload("seal", {"questions": [QUESTION, QUESTION]})


def test_seal_rejects_unknown_question_fields() -> None:
    with pytest.raises(ContractValidationError):
        validate_sheet_payload("seal", {"questions": [{**QUESTION, "extra": True}]})


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(ContractValidationError):
        validate_sheet_payload("delete", PAYLOAD)


def test_sheet_identity_changes_when_any_question_is_altered() -> None:
    other_question = {**QUESTION, "question_id": OTHER_QUESTION_ID}
    original = sheet_identity([QUESTION])
    again = sheet_identity([QUESTION])
    altered = sheet_identity([other_question])
    extended = sheet_identity([QUESTION, other_question])
    assert original == again
    assert original != altered
    assert original != extended
