"""SDD-SR-24, TDD-2.1.13: a sealed forecast's rationale is recorded, never scored.

The scorer's only entry is `ScoreInput`/`ScoringRow` (SDD-IN-02), a closed
schema with no rationale field. Two sealed answers that differ only in their
rationale therefore reach the scorer as the same row and score identically,
and a row that tries to carry a rationale is refused before it is input.
"""

from __future__ import annotations

from typing import Any

import pytest

from research_agent.contracts import ContractValidationError, ProducerVersion
from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.submissions import parse_answers
from research_agent.scoring.schemas import ScoreInput, ScoringResolution, ScoringRow
from research_agent.scoring.service import ScoringService

AS_OF = "2026-01-01T00:00:00.000000Z"
SEALED_AT = "2025-12-31T00:00:00.000000Z"
RESOLVED_AT = "2026-06-01T00:00:00.000000Z"
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
FORECAST_ID = "123e4567-e89b-42d3-a456-426614174010"
FAMILY_ID = "123e4567-e89b-42d3-a456-426614174020"
QUESTION_ID = "123e4567-e89b-42d3-a456-426614174000"


def _sealed_answer(rationale: str) -> dict[str, Any]:
    [answer] = parse_answers(
        [
            {
                "question_id": QUESTION_ID,
                "probability": 0.35,
                "rationale": rationale,
                "evidence_ids": ["e" * 64],
            }
        ]
    )
    return answer


def _row(answer: dict[str, Any]) -> ScoringRow:
    return ScoringRow(
        forecast_id=FORECAST_ID,
        question_id=answer["question_id"],
        family_id=FAMILY_ID,
        publication_week="2026-W01",
        target_id=TARGET_IDS[0],
        target_definition_hash="d" * 64,
        probability=answer["probability"],
        sealed_at=SEALED_AT,
        eligible=True,
        ineligible_reason=None,
        resolution=ScoringResolution(True, RESOLVED_AT),
        settled_cost=None,
    )


def _score_input(row: ScoringRow) -> ScoreInput:
    return ScoreInput(1, (), PRODUCER, "c" * 64, AS_OF, 7, AS_OF, "e" * 64, (row,), 1)


def test_two_submissions_differing_only_in_rationale_score_identically() -> None:
    terse = _sealed_answer("citations will follow the benchmark")
    verbose = _sealed_answer("I am certain this is right. " * 70)
    assert terse["rationale"] != verbose["rationale"]

    service = ScoringService("scorer")
    terse_record = service.score(_score_input(_row(terse)), computed_at=AS_OF)
    verbose_record = service.score(_score_input(_row(verbose)), computed_at=AS_OF)

    assert terse_record.to_canonical_json() == verbose_record.to_canonical_json()
    assert terse_record.mean_brier == pytest.approx((0.35 - 1.0) ** 2)


def test_the_score_record_carries_no_rationale() -> None:
    record = ScoringService("scorer").score(
        _score_input(_row(_sealed_answer("worth reading"))), computed_at=AS_OF
    )
    assert "rationale" not in record.to_dict()
    assert all("rationale" not in loss.to_dict() for loss in record.losses)


def test_a_scoring_row_carrying_a_rationale_is_refused_before_it_becomes_input() -> (
    None
):
    assert "rationale" not in ScoringRow._FIELDS
    decoded = canonical_loads(
        _score_input(_row(_sealed_answer("worth reading"))).to_canonical_json()
    )
    rows = list(decoded["rows"])  # type: ignore[index]
    rows[0] = {**rows[0], "rationale": "worth reading"}
    with pytest.raises(ContractValidationError):
        ScoreInput.from_json(canonical_json({**decoded, "rows": rows}))  # type: ignore[dict-item]
