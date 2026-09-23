"""SDD-IN-04: pick-set non-overlap against captured service picks."""

from uuid import uuid4

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.scoring.attention import PickNonOverlap, pick_nonoverlap


def _ids(count: int) -> list[str]:
    return [str(uuid4()) for _ in range(count)]


def test_identical_sets_score_zero_and_disjoint_sets_score_one() -> None:
    picks = _ids(3)
    assert pick_nonoverlap(picks, picks, source_id="s").value == 0.0
    assert pick_nonoverlap(picks, _ids(3), source_id="s").value == 1.0


def test_partial_overlap_divides_by_the_nomination_count() -> None:
    shared, own = _ids(1), _ids(3)
    captured = shared + _ids(5)
    result = pick_nonoverlap(shared + own, captured, source_id="s")
    assert result.value == pytest.approx(1 - 1 / 4)


def test_duplicated_nominations_count_once() -> None:
    a, b = _ids(2)
    result = pick_nonoverlap([a, a, a, b], [a], source_id="s")
    assert result.value == 0.5
    assert result == pick_nonoverlap([b, a], [a, a], source_id="s")


def test_missing_captures_or_nominations_are_null_with_a_reason() -> None:
    picks = _ids(2)
    no_source = pick_nonoverlap(picks, [], source_id="s")
    no_picks = pick_nonoverlap([], picks, source_id="s")
    assert (no_source.value, no_source.reason) == (None, "no_source_captures")
    assert (no_picks.value, no_picks.reason) == (None, "no_nominations")


def test_the_diagnostic_has_no_fitness_field_and_hashes_both_sets() -> None:
    fields = set(PickNonOverlap.__slots__)
    assert fields == {"source_id", "value", "reason", "nomination_hash", "capture_hash"}
    picks = _ids(2)
    result = pick_nonoverlap(picks, picks, source_id="s")
    assert result.nomination_hash == result.capture_hash


def test_a_non_uuid_family_id_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        pick_nonoverlap(["not-a-uuid"], _ids(1), source_id="s")
