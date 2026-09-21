import pytest
from uuid import UUID

from research_agent.learning.coverage import FamilySupport, summarize_support


def family_id(index: int) -> str:
    return str(UUID(int=index, version=4))


def test_joint_support_not_separate_marginal_counts_gates_pilot() -> None:
    rows = tuple(
        FamilySupport(family_id(index), True, index < 70, (index >= 30,) * 3)
        for index in range(100)
    )
    result = summarize_support(rows, intended=100)
    assert result.features_complete == 70 and result.known_labels == (70, 70, 70)
    assert result.jointly_eligible == (40, 40, 40)
    assert not result.pilot_coverage_met


def test_missing_rows_stay_in_denominator_and_targets_are_separate() -> None:
    rows = tuple(
        FamilySupport(family_id(index), True, True, (True, True, index < 69))
        for index in range(70)
    )
    result = summarize_support(rows, intended=100)
    assert result.shortfall == 30
    assert result.jointly_eligible == (70, 70, 69)
    assert not result.pilot_coverage_met
    assert summarize_support(
        rows[:-1] + (FamilySupport(family_id(69), True, True, (True,) * 3),),
        intended=100,
    ).pilot_coverage_met
    # A smaller denominator is not a qualifying pilot even at perfect coverage.
    assert not summarize_support(rows, intended=70).pilot_coverage_met


def test_duplicates_and_numeric_boolean_coercion_are_refused() -> None:
    row = FamilySupport(family_id(0), True, True, (True,) * 3)
    with pytest.raises(ValueError):
        summarize_support((row, row), intended=100)
    with pytest.raises(ValueError):
        FamilySupport(family_id(0), False, True, (True,) * 3)
    with pytest.raises(ValueError):
        FamilySupport(family_id(0), 1, False, (True,) * 3)  # type: ignore[arg-type]


def test_invalid_family_identity_cannot_fill_coverage_denominator() -> None:
    with pytest.raises(ValueError):
        FamilySupport("not-a-family-id", True, True, (True,) * 3)
