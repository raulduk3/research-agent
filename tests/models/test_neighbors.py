"""Exact earlier neighbors and the two card distances (RD-06, RD-07, RD-13)."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.models.neighbors import (
    NeighborSelection,
    OverviewVector,
    ReferenceCentroid,
    earlier_neighbors,
    neighbor_distance,
    reference_centroid_distance,
)

REPRESENTATION = "a" * 64
OTHER_REPRESENTATION = "b" * 64
AS_OF = "2026-06-01T00:00:00.000000Z"
TARGET_PUBLIC = "2026-05-01T00:00:00.000000Z"
EARLIER = "2026-04-01T00:00:00.000000Z"
EARLIEST = "2026-03-01T00:00:00.000000Z"
LATER = "2026-05-15T00:00:00.000000Z"
AFTER_AS_OF = "2026-06-15T00:00:00.000000Z"
TARGET = "00000000-0000-4000-8000-000000000000"
TARGET_VECTOR = (1.0, 0.0, 0.0)


def _family(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def _version(number: int) -> str:
    return f"11111111-1111-4111-8111-{number:012d}"


def _vector(
    number: int,
    vector: tuple[float, ...],
    *,
    first_public_at: str | None = EARLIER,
    available_at: str = EARLIER,
    representation_hash: str = REPRESENTATION,
    version: int | None = None,
) -> OverviewVector:
    return OverviewVector(
        paper_family_id=_family(number),
        paper_version_id=_version(number if version is None else version),
        title=f"Paper {number}",
        card_id=f"{number % 10}" * 64,
        first_public_at=first_public_at,
        corpus_arrival_at=EARLIER,
        available_at=available_at,
        representation_hash=representation_hash,
        vector=vector,
    )


def _neighbors(
    candidates: tuple[OverviewVector, ...],
    *,
    vector: tuple[float, ...] | None = TARGET_VECTOR,
    first_public_at: str | None = TARGET_PUBLIC,
) -> NeighborSelection:
    return earlier_neighbors(
        paper_family_id=TARGET,
        first_public_at=first_public_at,
        as_of=AS_OF,
        representation_hash=REPRESENTATION,
        vector=vector,
        candidates=candidates,
    )


def _ids(selection: NeighborSelection) -> list[str]:
    return [neighbor.paper_family_id for neighbor in selection.neighbors]


# Unit vectors at known cosines to TARGET_VECTOR: 0.9, 0.6, 0.0 and -1.0.
_NEAR = (0.9, math.sqrt(1 - 0.81), 0.0)
_MIDDLE = (0.6, 0.8, 0.0)
_ORTHOGONAL = (0.0, 0.0, 1.0)
_OPPOSITE = (-1.0, 0.0, 0.0)


def test_neighbors_are_the_nearest_earlier_papers_nearest_first() -> None:
    selection = _neighbors(
        (
            _vector(3, _ORTHOGONAL),
            _vector(1, _NEAR),
            _vector(2, _MIDDLE),
        )
    )
    assert _ids(selection) == [_family(1), _family(2), _family(3)]
    assert [n.similarity for n in selection.neighbors] == pytest.approx([0.9, 0.6, 0])
    assert selection.arrivals == tuple((family, EARLIER) for family in _ids(selection))


def test_only_five_neighbors_are_kept() -> None:
    selection = _neighbors(
        tuple(_vector(number, (1.0, float(number), 0.0)) for number in range(1, 8))
    )
    assert _ids(selection) == [_family(number) for number in range(1, 6)]


def test_a_later_paper_nearer_than_all_is_not_a_neighbor() -> None:
    later = _vector(9, TARGET_VECTOR, first_public_at=LATER)
    same_time = _vector(8, TARGET_VECTOR, first_public_at=TARGET_PUBLIC)
    selection = _neighbors((later, same_time, _vector(1, _MIDDLE)))
    assert _ids(selection) == [_family(1)]


def test_the_paper_itself_is_never_its_own_neighbor() -> None:
    own = replace(_vector(1, TARGET_VECTOR), paper_family_id=TARGET)
    assert _ids(_neighbors((own, _vector(2, _MIDDLE)))) == [_family(2)]


def test_a_tie_is_broken_by_family_id() -> None:
    selection = _neighbors(
        (_vector(7, _MIDDLE), _vector(4, _MIDDLE), _vector(5, (0.6, 0.0, 0.8)))
    )
    assert _ids(selection) == [_family(4), _family(5), _family(7)]


def test_invisible_or_uncertain_papers_are_excluded() -> None:
    selection = _neighbors(
        (
            _vector(1, _NEAR, representation_hash=OTHER_REPRESENTATION),
            _vector(2, _NEAR, available_at=AS_OF),
            _vector(3, _NEAR, available_at=AFTER_AS_OF),
            _vector(4, _NEAR, first_public_at=None),
            _vector(5, (0.5, 0.5)),
            _vector(6, _ORTHOGONAL),
        )
    )
    assert _ids(selection) == [_family(6)]


def test_a_family_with_two_versions_is_listed_once_by_its_original() -> None:
    original = _vector(1, _MIDDLE, first_public_at=EARLIEST, version=10)
    revision = _vector(1, TARGET_VECTOR, first_public_at=EARLIER, version=11)
    selection = _neighbors((revision, original))
    assert _ids(selection) == [_family(1)]
    assert selection.neighbors[0].paper_version_id == _version(10)
    assert selection.neighbors[0].similarity == pytest.approx(0.6)


def test_a_missing_vector_or_time_leaves_the_neighbors_unsought() -> None:
    candidates = (_vector(1, _NEAR),)
    assert _neighbors(candidates, vector=None).reason == "missing_vector"
    assert _neighbors(candidates, vector=(0.0, 0.0, 0.0)).reason == "missing_vector"
    assert _neighbors(candidates, first_public_at=None).reason == "missing_source"
    unknown = earlier_neighbors(
        paper_family_id=TARGET,
        first_public_at=TARGET_PUBLIC,
        as_of=AS_OF,
        representation_hash=None,
        vector=TARGET_VECTOR,
        candidates=candidates,
    )
    assert unknown.reason == "incompatible_representation"
    assert unknown.neighbors == ()


def test_an_overview_vector_without_a_direction_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        _vector(1, (0.0, 0.0, 0.0))
    with pytest.raises(ContractValidationError):
        _vector(1, (math.nan, 1.0, 0.0))


def test_identical_neighbors_are_at_distance_zero() -> None:
    distance = neighbor_distance(_neighbors((_vector(1, (2.0, 0.0, 0.0)),)))
    assert distance.status == "available"
    assert distance.value == 0.0
    assert distance.evidence_hashes == (REPRESENTATION,)


def test_orthogonal_neighbors_are_at_distance_one() -> None:
    selection = _neighbors((_vector(1, _ORTHOGONAL), _vector(2, (0.0, 1.0, 0.0))))
    assert neighbor_distance(selection).value == 1.0


def test_the_distance_is_the_mean_over_the_selected_neighbors() -> None:
    selection = _neighbors(
        (_vector(1, _NEAR), _vector(2, _MIDDLE), _vector(3, _OPPOSITE))
    )
    by_hand = ((1 - 0.9) + (1 - 0.6) + (1 - -1.0)) / 3
    assert neighbor_distance(selection).value == pytest.approx(by_hand)


def test_a_later_paper_does_not_move_the_distance() -> None:
    earlier = (_vector(1, _MIDDLE),)
    later = _vector(2, TARGET_VECTOR, first_public_at=LATER)
    assert neighbor_distance(_neighbors(earlier)) == neighbor_distance(
        _neighbors((*earlier, later))
    )


def test_no_neighbors_leaves_the_distance_unavailable() -> None:
    empty = neighbor_distance(_neighbors((_vector(1, _NEAR, first_public_at=LATER),)))
    assert (empty.status, empty.value, empty.reason) == (
        "unavailable",
        None,
        "no_neighbors",
    )
    unsought = neighbor_distance(_neighbors((_vector(1, _NEAR),), vector=None))
    assert unsought.reason == "missing_vector"


def _centroid(
    references: tuple[str, ...] | None,
    candidates: tuple[OverviewVector, ...],
    vector: tuple[float, ...] | None = TARGET_VECTOR,
) -> ReferenceCentroid:
    return reference_centroid_distance(
        as_of=AS_OF,
        representation_hash=REPRESENTATION,
        vector=vector,
        reference_family_ids=references,
        candidates=candidates,
    )


def test_the_reference_centroid_distance_matches_the_hand_computation() -> None:
    # Unit references (0.6, 0.8, 0) and (0, 0, 1): mean (0.3, 0.4, 0.5) has
    # norm sqrt(0.5), so the cosine to (1, 0, 0) is 0.3 / sqrt(0.5).
    result = _centroid(
        (_family(1), _family(2)),
        (_vector(1, (3.0, 4.0, 0.0)), _vector(2, _ORTHOGONAL)),
    )
    assert result.distance.value == pytest.approx(1 - 0.3 / math.sqrt(0.5))
    assert (result.vector_count, result.missing_vector_count) == (2, 0)
    assert result.distance.evidence_hashes == (REPRESENTATION,)


def test_a_missing_reference_vector_is_counted_and_left_out() -> None:
    candidates = (
        _vector(1, _MIDDLE),
        _vector(2, _ORTHOGONAL, representation_hash=OTHER_REPRESENTATION),
        _vector(3, _OPPOSITE, available_at=AFTER_AS_OF),
    )
    result = _centroid((_family(1), _family(2), _family(3), _family(4)), candidates)
    assert result.distance.value == pytest.approx(1 - 0.6)
    assert (result.vector_count, result.missing_vector_count) == (1, 3)


def test_a_duplicate_alias_counts_once() -> None:
    candidates = (_vector(1, _MIDDLE), _vector(2, _ORTHOGONAL))
    once = _centroid((_family(1), _family(2)), candidates)
    twice = _centroid((_family(1), _family(2), _family(1)), candidates)
    assert twice == once


def test_cancelling_references_leave_a_zero_centroid() -> None:
    result = _centroid(
        (_family(1), _family(2)),
        (_vector(1, _MIDDLE), _vector(2, (-0.6, -0.8, 0.0))),
    )
    assert result.distance.reason == "zero_centroid"
    assert (result.vector_count, result.missing_vector_count) == (2, 0)


def test_no_usable_reference_leaves_the_centroid_distance_unavailable() -> None:
    candidates = (_vector(1, _MIDDLE),)
    assert _centroid((), candidates).distance.reason == "missing_source"
    assert _centroid(None, candidates).distance.reason == "missing_source"
    absent = _centroid((_family(5),), candidates)
    assert absent.distance.reason == "missing_vector"
    assert (absent.vector_count, absent.missing_vector_count) == (0, 1)
    assert _centroid((_family(1),), candidates, vector=None).distance.reason == (
        "missing_vector"
    )
