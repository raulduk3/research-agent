from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.environment.sealing import (
    bind_question,
    validate_evidence,
    validate_horizon,
    validate_probability,
)

QUESTION_ID = "123e4567-e89b-42d3-a456-426614174000"
OTHER_QUESTION_ID = "123e4567-e89b-42d3-a456-426614174001"
QUESTION_RECORD = {
    "question_id": QUESTION_ID,
    "target_definition_hash": "a" * 64,
    "resolver_id": "citation-resolver",
    "resolver_version": 1,
    "horizon": "2025-01-01T00:00:00.000000Z",
}
FIRST_PUBLIC_AT = "2024-01-02T00:00:00.000000Z"
EVIDENCE_A = "b" * 64
EVIDENCE_B = "c" * 64


def test_bind_question_resolves_an_issued_question() -> None:
    resolved = bind_question({QUESTION_ID: QUESTION_RECORD}, QUESTION_ID)
    assert resolved == QUESTION_RECORD


def test_bind_question_rejects_a_question_the_sheet_never_issued() -> None:
    with pytest.raises(ContractValidationError):
        bind_question({QUESTION_ID: QUESTION_RECORD}, OTHER_QUESTION_ID)


def test_validate_evidence_accepts_ids_this_run_actually_retrieved() -> None:
    retrieved = frozenset({EVIDENCE_A, EVIDENCE_B})
    assert validate_evidence([EVIDENCE_A], retrieved) == (EVIDENCE_A,)
    assert validate_evidence([EVIDENCE_A, EVIDENCE_B], retrieved) == (
        EVIDENCE_A,
        EVIDENCE_B,
    )


def test_validate_evidence_rejects_an_id_this_run_never_retrieved() -> None:
    with pytest.raises(ContractValidationError):
        validate_evidence([EVIDENCE_A], frozenset({EVIDENCE_B}))


def test_validate_evidence_rejects_another_runs_evidence() -> None:
    # Evidence another run retrieved is absent from this run's own set,
    # so it is refused exactly as an id nobody ever retrieved would be.
    with pytest.raises(ContractValidationError):
        validate_evidence([EVIDENCE_A], frozenset())


def test_validate_evidence_rejects_empty_and_duplicate_and_oversized() -> None:
    retrieved = frozenset({EVIDENCE_A, EVIDENCE_B})
    with pytest.raises(ContractValidationError):
        validate_evidence([], retrieved)
    with pytest.raises(ContractValidationError):
        validate_evidence([EVIDENCE_A, EVIDENCE_A], retrieved)
    with pytest.raises(ContractValidationError):
        validate_evidence([EVIDENCE_A] * 6, retrieved)


def test_validate_horizon_accepts_the_exact_365_day_window() -> None:
    horizon = "2025-01-01T00:00:00.000000Z"
    assert validate_horizon(FIRST_PUBLIC_AT, horizon) == horizon


def test_validate_horizon_rejects_a_455_day_window() -> None:
    with pytest.raises(ContractValidationError):
        validate_horizon(FIRST_PUBLIC_AT, "2025-04-01T00:00:00.000000Z")


def test_validate_horizon_rejects_a_shorter_window() -> None:
    with pytest.raises(ContractValidationError):
        validate_horizon(FIRST_PUBLIC_AT, "2024-06-02T00:00:00.000000Z")


def test_validate_probability_accepts_interior_and_boundary_values() -> None:
    assert validate_probability(0) == 0
    assert validate_probability(1) == 1
    assert validate_probability(0.33) == 0.33


def test_validate_probability_rejects_bool_string_and_out_of_range() -> None:
    with pytest.raises(ContractValidationError):
        validate_probability(True)
    with pytest.raises(ContractValidationError):
        validate_probability("0.5")
    with pytest.raises(ContractValidationError):
        validate_probability(1.5)
    with pytest.raises(ContractValidationError):
        validate_probability(float("nan"))
