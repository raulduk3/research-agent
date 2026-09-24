"""SDD-IN-03: unresolved forecasts never enter loss and only grow the denominator."""

from uuid import uuid4

import pytest

from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
)
from research_agent.contracts.learning import TARGET_IDS
from research_agent.scoring.schemas import ScoreInput, ScoringResolution, ScoringRow
from research_agent.scoring.scores import score_ledger
from research_agent.scoring.support import resolved_support

TARGET_ID = TARGET_IDS[0]
TARGET_HASH = "d" * 64
AS_OF = "2026-01-01T00:00:00.000000Z"
SEALED_AT = "2025-12-31T00:00:00.000000Z"
RESOLVED_AT = "2026-06-01T00:00:00.000000Z"
COMPUTED_AT = "2026-06-02T00:00:00.000000Z"
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, AS_OF)


def row(
    *,
    probability: float = 0.5,
    eligible: bool = True,
    outcome: bool | None = None,
    target_definition_hash: str = TARGET_HASH,
    resolved_at: str = RESOLVED_AT,
) -> ScoringRow:
    return ScoringRow(
        forecast_id=str(uuid4()),
        question_id=str(uuid4()),
        family_id=str(uuid4()),
        publication_week="2026-W01",
        target_id=TARGET_ID,
        target_definition_hash=target_definition_hash,
        probability=probability,
        sealed_at=SEALED_AT,
        eligible=eligible,
        ineligible_reason=None if eligible else "late",
        resolution=None if outcome is None else ScoringResolution(outcome, resolved_at),
        settled_cost=None,
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


def _support(rows: tuple[ScoringRow, ...]):  # type: ignore[no-untyped-def]
    return resolved_support(
        rows, target_id=TARGET_ID, target_definition_hash=TARGET_HASH
    )


def test_unresolved_rows_grow_the_denominator_and_leave_losses_unchanged() -> None:
    resolved = (
        row(probability=0.8, outcome=True),
        row(probability=0.3, outcome=False),
    )
    baseline = score_ledger(
        score_input(resolved), producer_id="scorer", computed_at=COMPUTED_AT
    )
    with_unknowns = score_ledger(
        score_input(resolved + (row(probability=0.9), row(probability=0.1))),
        producer_id="scorer",
        computed_at=COMPUTED_AT,
    )
    assert [loss.squared_error for loss in with_unknowns.losses] == [
        loss.squared_error for loss in baseline.losses
    ]
    assert with_unknowns.mean_brier == baseline.mean_brier
    assert (baseline.unresolved_count, with_unknowns.unresolved_count) == (0, 2)
    assert (baseline.eligible_count, with_unknowns.eligible_count) == (2, 4)


def test_ineligible_rows_are_excluded_even_when_resolved() -> None:
    support = _support(
        (row(outcome=True), row(outcome=False, eligible=False), row(outcome=None))
    )
    assert len(support.resolved) == 1
    assert (support.unresolved_count, support.excluded_count) == (1, 1)
    assert support.intended_count == 3


def test_a_different_target_definition_is_refused_not_masked() -> None:
    with pytest.raises(ContractValidationError):
        _support((row(outcome=True, target_definition_hash="f" * 64),))


def test_a_resolution_dated_before_its_seal_is_malformed() -> None:
    with pytest.raises(ContractValidationError):
        _support((row(outcome=True, resolved_at="2025-01-01T00:00:00.000000Z"),))
