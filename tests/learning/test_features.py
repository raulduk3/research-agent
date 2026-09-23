from __future__ import annotations

import math
import struct
from typing import Any, cast
from uuid import uuid4

import pytest

from research_agent.contracts.cards import (
    AvailabilityValue,
    CardBuildInput,
    CardOverview,
    HeadCardValue,
    JevCardAssessment,
)
from research_agent.contracts.learning import (
    EMBEDDING_FEATURE_DIMENSION,
    METADATA_DIMENSION,
    PRIMARY_CATEGORY_IDS,
    TARGET_IDS,
)
from research_agent.contracts.passages import SourceLocator
from research_agent.learning.features import (
    CardMetadata,
    PassageEmbedding,
    Standardization,
    apply_head_input,
    assemble_features,
    assemble_metadata_block,
    card_metadata,
    detect_code_link,
    fit_standardization,
    overlap_adjusted_weights,
)
from research_agent.reader.cards import assemble_card

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


# --- declared metadata block (#149) ---------------------------------------


def _metadata(**changes: Any) -> CardMetadata:
    fields: dict[str, Any] = dict(
        author_count=4,
        categories=("cs.LG", "cs.AI"),
        abstract_tokens=100,
        title_tokens=8,
        first_available_weekday=2,
        code_link=True,
        version_count=3,
    )
    fields.update(changes)
    return CardMetadata(**fields)


def test_assemble_metadata_block_matches_the_closed_order() -> None:
    block = assemble_metadata_block(_metadata())
    assert len(block) == METADATA_DIMENSION
    primary_one_hot = tuple(
        1.0 if category == "cs.LG" else 0.0 for category in PRIMARY_CATEGORY_IDS
    )
    weekday_one_hot = tuple(1.0 if day == 2 else 0.0 for day in range(7))
    expected = (
        math.log1p(4),
        2.0,
        *primary_one_hot,
        math.log1p(100),
        8.0,
        *weekday_one_hot,
        1.0,
        3.0,
    )
    assert block == pytest.approx(expected, abs=1e-6)


def test_assemble_metadata_block_requires_a_card_metadata() -> None:
    with pytest.raises(TypeError):
        assemble_metadata_block(cast(Any, {"author_count": 1}))


def test_card_metadata_rejects_a_primary_category_outside_the_registry() -> None:
    with pytest.raises(ValueError):
        _metadata(categories=("cs.CV",))


def test_card_metadata_rejects_an_out_of_range_weekday() -> None:
    with pytest.raises(ValueError):
        _metadata(first_available_weekday=7)


def test_card_metadata_rejects_a_nonpositive_version_count() -> None:
    with pytest.raises(ValueError):
        _metadata(version_count=0)


def test_card_metadata_rejects_a_non_boolean_code_link() -> None:
    with pytest.raises(ValueError):
        _metadata(code_link=1)


def test_standardization_requires_the_full_metadata_width() -> None:
    with pytest.raises(ValueError):
        Standardization((0.0,) * (METADATA_DIMENSION - 1), (1.0,) * METADATA_DIMENSION)


def test_standardization_rejects_a_nonpositive_scale() -> None:
    std = [1.0] * METADATA_DIMENSION
    std[0] = 0.0
    with pytest.raises(ValueError):
        Standardization((0.0,) * METADATA_DIMENSION, tuple(std))


def test_standardization_requires_the_identity_transform_on_fixed_columns() -> None:
    # Index 2 sits inside the closed primary-category one-hot block, which
    # never fits from data: only author/category/token/version counts do.
    mean = [0.0] * METADATA_DIMENSION
    mean[2] = 1.0
    with pytest.raises(ValueError):
        Standardization(tuple(mean), (1.0,) * METADATA_DIMENSION)


def test_fit_standardization_computes_free_columns_and_fixes_the_rest() -> None:
    rows = [
        [2.0, 1.0, 1, 0, 0, 0, 3.0, 4.0, 1, 0, 0, 0, 0, 0, 0, 0, 1.0],
        [4.0, 1.0, 1, 0, 0, 0, 5.0, 6.0, 1, 0, 0, 0, 0, 0, 0, 0, 3.0],
    ]
    standardization = fit_standardization(rows)
    assert standardization.mean[0] == pytest.approx(3.0)
    assert standardization.std[0] == pytest.approx(1.0)
    assert standardization.mean[16] == pytest.approx(2.0)
    # A fixed one-hot column keeps the identity transform regardless of data.
    assert standardization.mean[2] == 0.0 and standardization.std[2] == 1.0


def test_fit_standardization_falls_back_to_unit_scale_for_zero_variance() -> None:
    rows = [[1.0] + [0.0] * (METADATA_DIMENSION - 1) for _ in range(3)]
    standardization = fit_standardization(rows)
    assert standardization.mean[0] == pytest.approx(1.0)
    assert standardization.std[0] == pytest.approx(1.0)


def test_fit_standardization_requires_at_least_one_row() -> None:
    with pytest.raises(ValueError):
        fit_standardization([])


def test_fit_standardization_rejects_rows_of_the_wrong_width() -> None:
    with pytest.raises(ValueError):
        fit_standardization([[0.0] * (METADATA_DIMENSION - 1)])


def test_apply_head_input_concatenates_embedding_and_standardized_metadata() -> None:
    embedding = tuple(0.1 for _ in range(EMBEDDING_FEATURE_DIMENSION))
    metadata = tuple(float(index) for index in range(METADATA_DIMENSION))
    standardization = Standardization(
        (0.0,) * METADATA_DIMENSION, (1.0,) * METADATA_DIMENSION
    )
    row = apply_head_input(embedding, metadata, standardization)
    assert len(row) == EMBEDDING_FEATURE_DIMENSION + METADATA_DIMENSION
    assert row[:EMBEDDING_FEATURE_DIMENSION] == pytest.approx(embedding)
    assert row[EMBEDDING_FEATURE_DIMENSION:] == pytest.approx(metadata)


def test_apply_head_input_rejects_wrong_width_blocks() -> None:
    standardization = Standardization(
        (0.0,) * METADATA_DIMENSION, (1.0,) * METADATA_DIMENSION
    )
    with pytest.raises(ValueError):
        apply_head_input(
            (0.0,) * (EMBEDDING_FEATURE_DIMENSION - 1),
            (0.0,) * METADATA_DIMENSION,
            standardization,
        )
    with pytest.raises(ValueError):
        apply_head_input(
            (0.0,) * EMBEDDING_FEATURE_DIMENSION,
            (0.0,) * (METADATA_DIMENSION - 1),
            standardization,
        )


def test_apply_head_input_requires_a_standardization() -> None:
    with pytest.raises(TypeError):
        apply_head_input(
            (0.0,) * EMBEDDING_FEATURE_DIMENSION,
            (0.0,) * METADATA_DIMENSION,
            cast(Any, None),
        )


@pytest.mark.parametrize(
    ("abstract", "comments", "expected"),
    (
        ("code at https://github.com/org/repo", None, True),
        (None, "See our GitLab.com project", True),
        ("hosted on huggingface.co/datasets/x", None, True),
        ("mirrored at codeberg.org/org/repo", None, True),
        ("no link here", "nor here", False),
        (None, None, False),
    ),
)
def test_detect_code_link_matches_the_closed_host_list(
    abstract: str | None, comments: str | None, expected: bool
) -> None:
    assert detect_code_link(abstract, comments) is expected


def _card(**overrides: Any) -> Any:
    fields: dict[str, Any] = dict(
        paper_family_id=str(uuid4()),
        paper_version_id=str(uuid4()),
        as_of="2026-06-01T00:00:00.000000Z",
        corpus_arrival_at="2026-05-01T00:00:00.000000Z",
        overview=CardOverview("complete", "A title", "An abstract.", ()),
        overview_available=True,
        first_public_at="2026-05-01T00:00:00.000000Z",
        original_source=SourceLocator("a" * 64, "latex", None, None, None, None),
        passage_coverage="unavailable",
        passage_count=0,
        extraction_hash=None,
        representation_hash=None,
        head_feature_eligible=False,
        head_feature_unavailable_reason="missing_source",
        head_predictions=tuple(
            HeadCardValue(
                target_id,
                "b" * 64,
                "Will this paper cross the threshold?",
                None,
                "unavailable",
                "missing_source",
                None,
                None,
                None,
                None,
                "unknown_t0",
                None,
            )
            for target_id in TARGET_IDS
        ),
        neighbors=(),
        neighbor_arrivals=(),
        neighbor_embedding_distance=AvailabilityValue.unavailable("no_neighbors"),
        outcome_labels=(),
        graph_incoming_family_ids=None,
        graph_outgoing_family_ids=None,
        graph_parsed_reference_count=0,
        graph_matched_reference_ids=(),
        graph_reference_vector_count=0,
        graph_missing_reference_vector_count=0,
        graph_reference_centroid_distance=AvailabilityValue.unavailable(
            "missing_vector"
        ),
        graph_manifest_hash=None,
        author_ids=(),
        author_captures=(),
        jev=JevCardAssessment.unavailable("missing_source"),
        card_token_count=42,
        author_count=3,
        categories=("cs.AI",),
        version_count=1,
        title_tokens=2,
        abstract_tokens=5,
        code_link=True,
    )
    fields.update(overrides)
    return assemble_card(CardBuildInput(**fields))


def test_card_metadata_builds_from_the_card_fields() -> None:
    card = _card()
    metadata = card_metadata(card)
    assert metadata.author_count == 3
    assert metadata.categories == ("cs.AI",)
    assert metadata.version_count == 1
    assert metadata.title_tokens == 2
    assert metadata.abstract_tokens == 5
    assert metadata.code_link is True
    assert metadata.first_available_weekday == card.first_available_weekday


def test_card_metadata_refuses_a_card_with_no_known_first_availability() -> None:
    card = _card(first_public_at=None)
    with pytest.raises(ValueError):
        card_metadata(card)


def test_card_metadata_requires_a_paper_card_body() -> None:
    with pytest.raises(TypeError):
        card_metadata(cast(Any, {"author_count": 1}))
