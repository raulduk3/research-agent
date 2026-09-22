from uuid import uuid4

import pytest

from research_agent.contracts.cards import AvailabilityValue
from research_agent.contracts.learning import (
    TARGET_IDS,
    AutomaticLabel,
    CountBounds,
    LabelCounts,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
)
from research_agent.reader.graph import graph_summary, neighbor_outcomes

T1, T2, T3 = TARGET_IDS
_CENTROID = AvailabilityValue.unavailable("missing_vector")
_META = RecordMeta(
    1,
    ("1" * 64,),
    ProducerVersion("2" * 64, "3" * 40, 1),
    "4" * 64,
    "2026-01-01T00:00:00.000000Z",
)
_BOUNDS = CountBounds(0, None)
_COUNTS = LabelCounts(_BOUNDS, _BOUNDS, _BOUNDS, _BOUNDS)


def _meta() -> dict[str, object]:
    return {
        "schema_version": _META.schema_version,
        "input_hashes": _META.input_hashes,
        "producer_version": _META.producer_version,
        "config_hash": _META.config_hash,
        "created_at": _META.created_at,
    }


def _label(
    family_id: str, target_id: str, state: str, resolved_at: str
) -> AutomaticLabel:
    reason = {
        "true": "sufficient_positive_witnesses",
        "false": "complete_negative_evidence",
        "unknown": "immature",
    }[state]
    return AutomaticLabel(
        **_meta(),
        paper_family_id=family_id,
        target_id=target_id,
        target_definition_hash="d" * 64,
        state=state,
        reason=reason,
        observation_hash="e" * 64,
        counts=_COUNTS,
        witness_family_ids=(),
        witness_subfield_ids=(),
        completion_page_hashes=(),
        maturity_at="2026-01-01T00:00:00.000000Z",
        resolved_at=resolved_at,
        supersedes_label_hash=None,
        correction_hash=None,
    )


# --- graph_summary -----------------------------------------------------------


def test_deduplicates_repeated_edge_aliases() -> None:
    values = graph_summary(
        incoming_family_ids=("f1", "f1", "f2"),
        outgoing_family_ids=("f3",),
        parsed_reference_count=4,
        matched_reference_ids=("r1", "r1", "r2"),
        reference_vector_count=3,
        missing_reference_vector_count=1,
        reference_centroid_distance=_CENTROID,
        graph_manifest_hash="a" * 64,
    )
    assert values.incoming_family_count == 2
    assert values.outgoing_family_count == 1
    assert values.matched_reference_count == 2
    assert values.reference_match_fraction == 0.5
    assert values.reference_centroid_distance is _CENTROID
    assert values.graph_manifest_hash == "a" * 64


def test_missing_graph_is_unavailable_not_a_false_zero() -> None:
    values = graph_summary(
        incoming_family_ids=None,
        outgoing_family_ids=None,
        parsed_reference_count=0,
        matched_reference_ids=(),
        reference_vector_count=0,
        missing_reference_vector_count=0,
        reference_centroid_distance=_CENTROID,
        graph_manifest_hash=None,
    )
    assert values.incoming_family_count is None
    assert values.outgoing_family_count is None


def test_empty_bibliography_gives_null_match_fraction() -> None:
    values = graph_summary(
        incoming_family_ids=(),
        outgoing_family_ids=(),
        parsed_reference_count=0,
        matched_reference_ids=(),
        reference_vector_count=0,
        missing_reference_vector_count=0,
        reference_centroid_distance=_CENTROID,
        graph_manifest_hash=None,
    )
    assert values.reference_match_fraction is None


def test_matched_cannot_exceed_parsed_bibliography() -> None:
    with pytest.raises(ContractValidationError):
        graph_summary(
            incoming_family_ids=(),
            outgoing_family_ids=(),
            parsed_reference_count=1,
            matched_reference_ids=("r1", "r2"),
            reference_vector_count=0,
            missing_reference_vector_count=1,
            reference_centroid_distance=_CENTROID,
            graph_manifest_hash=None,
        )


# --- neighbor_outcomes ---------------------------------------------------------

AS_OF = "2026-06-01T00:00:00.000000Z"
TARGET_ARRIVAL = "2026-05-01T00:00:00.000000Z"
BEFORE_TARGET = "2026-04-01T00:00:00.000000Z"
AFTER_TARGET = "2026-05-15T00:00:00.000000Z"
BEFORE_SEAL = "2026-05-20T00:00:00.000000Z"
AFTER_SEAL = "2026-06-02T00:00:00.000000Z"


def test_later_arriving_neighbor_is_excluded_despite_being_listed() -> None:
    earlier = str(uuid4())
    later = str(uuid4())
    results = neighbor_outcomes(
        neighbor_family_ids=(earlier, later),
        neighbor_arrivals=((earlier, BEFORE_TARGET), (later, AFTER_TARGET)),
        target_corpus_arrival_at=TARGET_ARRIVAL,
        labels=(
            _label(earlier, T1, "true", BEFORE_SEAL),
            _label(later, T1, "true", BEFORE_SEAL),
        ),
        as_of=AS_OF,
    )
    by_target = {value.target_id: value for value in results}
    assert by_target[T1].known_neighbor_count == 1
    assert by_target[T1].positive_neighbor_count == 1


def test_label_resolved_after_seal_does_not_count_as_known() -> None:
    neighbor = str(uuid4())
    results = neighbor_outcomes(
        neighbor_family_ids=(neighbor,),
        neighbor_arrivals=((neighbor, BEFORE_TARGET),),
        target_corpus_arrival_at=TARGET_ARRIVAL,
        labels=(_label(neighbor, T1, "true", AFTER_SEAL),),
        as_of=AS_OF,
    )
    by_target = {value.target_id: value for value in results}
    assert by_target[T1].known_neighbor_count == 0
    assert by_target[T1].probability is None
    assert by_target[T1].reason == "no_known_labels"


def test_a_correction_resolved_after_seal_is_invisible() -> None:
    neighbor = str(uuid4())
    results = neighbor_outcomes(
        neighbor_family_ids=(neighbor,),
        neighbor_arrivals=((neighbor, BEFORE_TARGET),),
        target_corpus_arrival_at=TARGET_ARRIVAL,
        labels=(
            _label(neighbor, T1, "true", BEFORE_SEAL),
            _label(neighbor, T1, "false", AFTER_SEAL),
        ),
        as_of=AS_OF,
    )
    by_target = {value.target_id: value for value in results}
    assert by_target[T1].known_neighbor_count == 1
    assert by_target[T1].positive_neighbor_count == 1


def test_unknown_state_does_not_count_as_a_known_outcome() -> None:
    neighbor = str(uuid4())
    results = neighbor_outcomes(
        neighbor_family_ids=(neighbor,),
        neighbor_arrivals=((neighbor, BEFORE_TARGET),),
        target_corpus_arrival_at=TARGET_ARRIVAL,
        labels=(_label(neighbor, T1, "unknown", BEFORE_SEAL),),
        as_of=AS_OF,
    )
    by_target = {value.target_id: value for value in results}
    assert by_target[T1].known_neighbor_count == 0
    assert by_target[T1].reason == "no_known_labels"


def test_probability_is_the_laplace_smoothed_rate_per_target() -> None:
    a, b, c = (str(uuid4()) for _ in range(3))
    labels = [
        _label(a, T2, "true", BEFORE_SEAL),
        _label(b, T2, "false", BEFORE_SEAL),
        _label(c, T2, "true", BEFORE_SEAL),
    ]
    results = neighbor_outcomes(
        neighbor_family_ids=(a, b, c),
        neighbor_arrivals=(
            (a, BEFORE_TARGET),
            (b, BEFORE_TARGET),
            (c, BEFORE_TARGET),
        ),
        target_corpus_arrival_at=TARGET_ARRIVAL,
        labels=tuple(labels),
        as_of=AS_OF,
    )
    by_target = {value.target_id: value for value in results}
    assert by_target[T2].known_neighbor_count == 3
    assert by_target[T2].positive_neighbor_count == 2
    assert by_target[T2].probability == pytest.approx((2 + 1) / (3 + 2))
    assert [value.target_id for value in results] == [T1, T2, T3]
