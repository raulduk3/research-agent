from __future__ import annotations

import math
import struct
from typing import Any, cast

import pytest

from research_agent.learning.features import (
    PassageEmbedding,
    assemble_features,
    overlap_adjusted_weights,
)

REPRESENTATION = "a" * 64
OTHER_REPRESENTATION = "b" * 64
VERSION = "123e4567-e89b-42d3-a456-426614174000"
LATER_VERSION = "123e4567-e89b-42d3-a456-426614174001"


def _passage(
    section: int, start: int, end: int, vector: tuple[float, ...]
) -> PassageEmbedding:
    return PassageEmbedding(section, start, end, REPRESENTATION, vector)


def _assemble(
    overview: tuple[float, ...],
    passages: tuple[PassageEmbedding, ...],
    **changes: object,
) -> Any:
    arguments: dict[str, object] = {
        "representation_hash": REPRESENTATION,
        "representation_dimension": 2,
        "overview_representation_hash": REPRESENTATION,
        "source_version_id": VERSION,
        "original_version_id": VERSION,
        "extraction_coverage": "complete",
    }
    arguments.update(changes)
    return assemble_features(overview, passages, **arguments)  # type: ignore[arg-type]


def _f32(value: float) -> float:
    return cast(float, struct.unpack("<f", struct.pack("<f", value))[0])


def test_overlap_adjustment_and_combined_feature_match_contract() -> None:
    passages = (_passage(0, 0, 384, (1.0, 0.0)), _passage(0, 320, 500, (0.0, 1.0)))
    result = _assemble((1.0, 0.0), passages)
    assert result.passage_weights == pytest.approx((352.0, 148.0))
    norm = math.hypot(352.0, 148.0)
    pool = (_f32(352.0 / norm), _f32(148.0 / norm))
    assert result.pooled_passage == pool
    assert result.combined == tuple(
        _f32(value)
        for value in (
            1 / math.sqrt(2),
            0.0,
            pool[0] / math.sqrt(2),
            pool[1] / math.sqrt(2),
        )
    )


def test_disjoint_sections_weight_each_content_token_once() -> None:
    passages = (_passage(0, 0, 3, (1.0, 0.0)), _passage(1, 0, 2, (0.0, 1.0)))
    assert overlap_adjusted_weights(passages) == pytest.approx((3.0, 2.0))


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"extraction_coverage": "partial"}, "complete original"),
        ({"source_version_id": LATER_VERSION}, "first public"),
        ({"overview_representation_hash": OTHER_REPRESENTATION}, "identity"),
        ({"representation_dimension": 3}, "dimension"),
    ),
)
def test_eligibility_identity_must_match(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _assemble((1.0, 0.0), (_passage(0, 0, 1, (1.0, 0.0)),), **changes)


@pytest.mark.parametrize(
    "passages",
    (
        (_passage(0, 1, 2, (1.0, 0.0)),),
        (_passage(0, 0, 100, (1.0, 0.0)), _passage(0, 320, 400, (1.0, 0.0))),
        (_passage(0, 0, 385, (1.0, 0.0)),),
        (
            _passage(0, 0, 384, (1.0, 0.0)),
            _passage(0, 320, 384, (1.0, 0.0)),
        ),
        (
            PassageEmbedding(
                cast(Any, 0.0),
                0,
                1,
                REPRESENTATION,
                (1.0, 0.0),
            ),
        ),
    ),
)
def test_nonconforming_chunk_spans_are_rejected(
    passages: tuple[PassageEmbedding, ...],
) -> None:
    with pytest.raises(ValueError):
        overlap_adjusted_weights(passages)


@pytest.mark.parametrize("vector", ((0.0, 0.0), (math.nan, 0.0), (1.0,), (0.5, 0.5)))
def test_invalid_or_incompatible_vectors_are_rejected(
    vector: tuple[float, ...],
) -> None:
    with pytest.raises(ValueError):
        _assemble((1.0, 0.0), (_passage(0, 0, 1, vector),))


def test_passage_representation_and_boolean_coordinates_are_rejected() -> None:
    wrong = PassageEmbedding(0, 0, 1, OTHER_REPRESENTATION, (1.0, 0.0))
    with pytest.raises(ValueError, match="identity"):
        _assemble((1.0, 0.0), (wrong,))
    with pytest.raises(ValueError, match="finite numeric"):
        _assemble((True, 0.0), (_passage(0, 0, 1, (1.0, 0.0)),))


def test_opposing_passages_reject_zero_pool() -> None:
    with pytest.raises(ValueError, match="pooled passage vector must be nonzero"):
        _assemble(
            (1.0, 0.0), (_passage(0, 0, 1, (1.0, 0.0)), _passage(1, 0, 1, (-1.0, 0.0)))
        )


def test_mutable_inputs_and_boolean_dimension_are_rejected() -> None:
    passage = _passage(0, 0, 1, (1.0, 0.0))
    with pytest.raises(TypeError, match="immutable"):
        assemble_features(
            [1.0, 0.0],  # type: ignore[arg-type]
            (passage,),
            representation_hash=REPRESENTATION,
            representation_dimension=2,
            overview_representation_hash=REPRESENTATION,
            source_version_id=VERSION,
            original_version_id=VERSION,
            extraction_coverage="complete",
        )
    with pytest.raises(ValueError, match="positive integer"):
        _assemble((1.0, 0.0), (passage,), representation_dimension=True)
