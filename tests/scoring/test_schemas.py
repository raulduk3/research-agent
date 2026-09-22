from uuid import uuid4

import pytest

from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
)
from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.learning import TARGET_IDS
from research_agent.scoring.schemas import ScoreInput, ScoringResolution, ScoringRow

FORBIDDEN_CONTENT_FIELDS = {
    "text",
    "paper_card",
    "card",
    "image",
    "images",
    "model_output",
    "abstract",
}
AS_OF = "2026-01-01T00:00:00.000000Z"
SEALED_AT = "2025-12-31T00:00:00.000000Z"
RESOLVED_AT = "2026-06-01T00:00:00.000000Z"
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, AS_OF)


def row(
    *, resolution: ScoringResolution | None = None, eligible: bool = True
) -> ScoringRow:
    return ScoringRow(
        forecast_id=str(uuid4()),
        question_id=str(uuid4()),
        family_id=str(uuid4()),
        publication_week="2026-W01",
        target_id=TARGET_IDS[0],
        target_definition_hash="d" * 64,
        probability=0.4,
        sealed_at=SEALED_AT,
        eligible=eligible,
        ineligible_reason=None if eligible else "late",
        resolution=resolution,
    )


def score_input(rows: tuple[ScoringRow, ...]) -> ScoreInput:
    return ScoreInput(
        1,
        (),
        META.producer_version,
        META.config_hash,
        AS_OF,
        7,
        AS_OF,
        "e" * 64,
        rows,
        len(rows),
    )


def test_scoring_row_admits_a_family_id_but_no_paper_content_field() -> None:
    assert "family_id" in ScoringRow._FIELDS
    assert not FORBIDDEN_CONTENT_FIELDS & ScoringRow._FIELDS


def test_score_input_admits_no_paper_content_field() -> None:
    assert not FORBIDDEN_CONTENT_FIELDS & ScoreInput._FIELDS


def test_score_input_round_trips_through_canonical_json() -> None:
    original = score_input((row(resolution=ScoringResolution(True, RESOLVED_AT)),))
    restored = ScoreInput.from_json(original.to_canonical_json())
    assert restored == original


def test_score_input_rejects_an_unknown_field() -> None:
    original = score_input((row(),))
    decoded = canonical_loads(original.to_canonical_json())
    payload = dict(decoded)  # type: ignore[arg-type]
    payload["extra"] = "not allowed"
    with pytest.raises(ContractValidationError):
        ScoreInput.from_json(canonical_json(payload))


def test_score_input_rejects_duplicate_forecast_ids() -> None:
    duplicate = row()
    with pytest.raises(ContractValidationError):
        score_input((duplicate, duplicate))


def test_score_input_rejects_an_intended_count_below_its_rows() -> None:
    with pytest.raises(ContractValidationError):
        ScoreInput(
            1,
            (),
            META.producer_version,
            META.config_hash,
            AS_OF,
            7,
            AS_OF,
            "e" * 64,
            (row(),),
            0,
        )


def test_scoring_row_rejects_an_unregistered_target_id() -> None:
    with pytest.raises(ContractValidationError):
        ScoringRow(
            forecast_id=str(uuid4()),
            question_id=str(uuid4()),
            family_id=str(uuid4()),
            publication_week="2026-W01",
            target_id="not_a_target",
            target_definition_hash="d" * 64,
            probability=0.4,
            sealed_at=SEALED_AT,
            eligible=True,
            ineligible_reason=None,
            resolution=None,
        )


def test_scoring_row_requires_a_reason_when_ineligible() -> None:
    with pytest.raises(ContractValidationError):
        ScoringRow(
            forecast_id=str(uuid4()),
            question_id=str(uuid4()),
            family_id=str(uuid4()),
            publication_week="2026-W01",
            target_id=TARGET_IDS[0],
            target_definition_hash="d" * 64,
            probability=0.4,
            sealed_at=SEALED_AT,
            eligible=False,
            ineligible_reason=None,
            resolution=None,
        )
