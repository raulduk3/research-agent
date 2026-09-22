from uuid import uuid4

import pytest

from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
)
from research_agent.contracts.learning import TARGET_IDS
from research_agent.scoring.schemas import ScoreInput, ScoringResolution, ScoringRow
from research_agent.scoring.scores import ScoreRecord, score_ledger, target_skill

AS_OF = "2026-01-01T00:00:00.000000Z"
SEALED_AT = "2025-12-31T00:00:00.000000Z"
RESOLVED_AT = "2026-06-01T00:00:00.000000Z"
COMPUTED_AT = "2026-06-02T00:00:00.000000Z"
LATER_COMPUTED_AT = "2027-01-01T00:00:00.000000Z"
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, AS_OF)
TARGET_ID = TARGET_IDS[0]
TARGET_HASH = "d" * 64


def row(
    *,
    forecast_id: str | None = None,
    question_id: str | None = None,
    probability: float = 0.5,
    eligible: bool = True,
    outcome: bool | None = None,
    target_id: str = TARGET_ID,
    target_definition_hash: str = TARGET_HASH,
) -> ScoringRow:
    resolution = None if outcome is None else ScoringResolution(outcome, RESOLVED_AT)
    return ScoringRow(
        forecast_id=forecast_id or str(uuid4()),
        question_id=question_id or str(uuid4()),
        family_id=str(uuid4()),
        publication_week="2026-W01",
        target_id=target_id,
        target_definition_hash=target_definition_hash,
        probability=probability,
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


def scored(
    rows: tuple[ScoringRow, ...],
    *,
    producer_id: str = "genome-1",
    computed_at: str = COMPUTED_AT,
) -> ScoreRecord:
    return score_ledger(
        score_input(rows), producer_id=producer_id, computed_at=computed_at
    )


def test_score_ledger_computes_the_binary_brier_loss() -> None:
    rows = (row(probability=0.9, outcome=True), row(probability=0.2, outcome=False))
    record = scored(rows)
    assert record.resolved_count == 2
    assert record.mean_brier == pytest.approx(((0.1**2) + (0.2**2)) / 2)
    assert record.disposition == "available"


def test_score_ledger_excludes_ineligible_and_never_scores_unresolved_rows() -> None:
    rows = (
        row(probability=0.9, outcome=True),
        row(probability=0.9, outcome=None),
        row(probability=0.9, eligible=False),
    )
    record = scored(rows)
    assert record.eligible_count == 2
    assert record.resolved_count == 1
    assert record.unresolved_count == 1
    assert record.excluded_count == 1
    assert record.mean_brier == pytest.approx(0.01)


def test_score_ledger_is_deterministic_across_wall_clock_and_row_order() -> None:
    rows = (
        row(probability=0.7, outcome=True),
        row(probability=0.3, outcome=False),
        row(probability=0.5, outcome=None),
    )
    first = scored(rows)
    second = scored(tuple(reversed(rows)))
    third = scored(rows, computed_at=LATER_COMPUTED_AT)
    assert first.to_canonical_json() == second.to_canonical_json()
    assert first.to_canonical_json() != third.to_canonical_json()
    assert first == ScoreRecord.from_json(first.to_canonical_json())


def test_score_ledger_refuses_an_empty_input() -> None:
    with pytest.raises(ContractValidationError):
        scored(())


def test_score_ledger_refuses_mixed_targets() -> None:
    rows = (
        row(outcome=True, target_id=TARGET_IDS[0]),
        row(outcome=True, target_id=TARGET_IDS[1]),
    )
    with pytest.raises(ContractValidationError):
        scored(rows)


def test_score_ledger_reports_no_resolved_support_with_no_resolutions() -> None:
    record = scored((row(outcome=None),))
    assert record.disposition == "no_resolved_support"
    assert record.mean_brier is None
    assert record.losses == ()


def test_target_skill_uses_only_the_matched_resolved_support() -> None:
    shared_question = str(uuid4())
    agent_only_question = str(uuid4())
    baseline_only_question = str(uuid4())

    agent = scored(
        (
            row(question_id=shared_question, probability=0.9, outcome=True),
            row(question_id=agent_only_question, probability=0.9, outcome=True),
        )
    )
    baseline = scored(
        (
            row(question_id=shared_question, probability=0.5, outcome=True),
            row(question_id=baseline_only_question, probability=0.5, outcome=False),
        ),
        producer_id="base-rate",
    )

    skill = target_skill(agent, baseline)
    assert skill.support_count == 1
    assert skill.agent_mean_brier == pytest.approx(0.01)
    assert skill.baseline_mean_brier == pytest.approx(0.25)
    assert skill.skill == pytest.approx(1.0 - 0.01 / 0.25)
    assert skill.disposition == "available"


def test_target_skill_is_unavailable_with_no_shared_support() -> None:
    agent = scored((row(probability=0.9, outcome=True),))
    baseline = scored((row(probability=0.5, outcome=False),), producer_id="base-rate")
    skill = target_skill(agent, baseline)
    assert skill.disposition == "unavailable"
    assert skill.skill is None


def test_target_skill_is_unavailable_with_a_zero_baseline_loss() -> None:
    shared_question = str(uuid4())
    agent = scored((row(question_id=shared_question, probability=0.6, outcome=True),))
    baseline = scored(
        (row(question_id=shared_question, probability=1.0, outcome=True),),
        producer_id="base-rate",
    )
    skill = target_skill(agent, baseline)
    assert skill.disposition == "unavailable"
    assert skill.skill is None
    assert skill.baseline_mean_brier == 0.0
