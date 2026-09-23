"""SDD-AG-07: the scorer reads sealed forecasts and resolutions, never a run's
agent-authored fields.

`ScoreInput`/`ScoringRow` (SDD-IN-02) are the scorer's sole typed entry to
ledger data: forecast identity, target version, numeric probability, result
and exclusion/lineage identities, in a closed schema that admits no other
key. Nothing an agent's run record carries -- a note, a claimed score, a
nominated rank, a Jev answer -- has a field to occupy.
"""

from __future__ import annotations

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
from research_agent.scoring.scores import score_ledger

AS_OF = "2026-01-01T00:00:00.000000Z"
SEALED_AT = "2025-12-31T00:00:00.000000Z"
RESOLVED_AT = "2026-06-01T00:00:00.000000Z"
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, AS_OF)

AGENT_AUTHORED_FIELDS = (
    "agent_notes",
    "self_praise",
    "claimed_score",
    "nominated_rank",
    "jev_answer",
)


def _row(*, resolution: ScoringResolution | None) -> ScoringRow:
    return ScoringRow(
        forecast_id=str(uuid4()),
        question_id=str(uuid4()),
        family_id=str(uuid4()),
        publication_week="2026-W01",
        target_id=TARGET_IDS[0],
        target_definition_hash="d" * 64,
        probability=0.4,
        sealed_at=SEALED_AT,
        eligible=True,
        ineligible_reason=None,
        resolution=resolution,
        settled_cost=None,
    )


def _score_input(rows: tuple[ScoringRow, ...]) -> ScoreInput:
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


@pytest.mark.parametrize("field", AGENT_AUTHORED_FIELDS)
def test_scoring_row_has_no_field_an_agent_run_could_fill_with_self_praise(
    field: str,
) -> None:
    assert field not in ScoringRow._FIELDS


@pytest.mark.parametrize("field", AGENT_AUTHORED_FIELDS)
def test_a_claimed_perfect_score_added_to_a_forecast_row_is_refused_before_it_becomes_input(
    field: str,
) -> None:
    original = _score_input((_row(resolution=ScoringResolution(True, RESOLVED_AT)),))
    decoded = canonical_loads(original.to_canonical_json())
    rows = list(decoded["rows"])  # type: ignore[index]
    tampered_row = dict(rows[0])
    tampered_row[field] = "1.0" if field == "claimed_score" else "not real"
    rows[0] = tampered_row
    payload = dict(decoded)  # type: ignore[arg-type]
    payload["rows"] = rows
    with pytest.raises(ContractValidationError):
        ScoreInput.from_json(canonical_json(payload))


def test_adding_self_praise_changes_neither_the_manifest_hash_nor_the_losses() -> None:
    resolution = ScoringResolution(True, RESOLVED_AT)
    honest_row = _row(resolution=resolution)
    honest_input = _score_input((honest_row,))
    honest_record = score_ledger(
        honest_input, producer_id="agent-genome-1", computed_at=AS_OF
    )

    # There is no argument position on `score_ledger` or `ScoreInput` through
    # which a run's final-message self-rating could reach the computation:
    # the same row, scored again, gives byte-identical losses and hash.
    replay_record = score_ledger(
        honest_input, producer_id="agent-genome-1", computed_at=AS_OF
    )
    assert replay_record.input_manifest_hash == honest_record.input_manifest_hash
    assert replay_record.losses == honest_record.losses


def test_unsealed_prose_produces_no_input_row() -> None:
    with pytest.raises(ContractValidationError):
        ScoringRow.from_json(
            canonical_json({"note": "I forecast this correctly, trust me"})
        )
