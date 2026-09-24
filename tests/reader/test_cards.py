from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from research_agent.contracts.cards import (
    CARD_SECTION_LIMIT,
    AuthorCitationCapture,
    AvailabilityValue,
    CardBuildInput,
    CardOverview,
    CardSection,
    HeadCardValue,
    JevCardAssessment,
    JevCardUnavailable,
    NeighborCardSummary,
)
from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.learning import (
    TARGET_IDS,
    AutomaticLabel,
    CountBounds,
    LabelCounts,
)
from research_agent.contracts.passages import (
    CHUNK_POLICY,
    PassageRecord,
    SourceLocator,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
)
from research_agent.models.neighbors import OverviewVector
from research_agent.reader.cards import CardVectors, assemble_card

AS_OF = "2026-06-01T00:00:00.000000Z"
ARRIVAL = "2026-05-01T00:00:00.000000Z"
BEFORE_ARRIVAL = "2026-04-01T00:00:00.000000Z"
BEFORE_SEAL = "2026-05-20T00:00:00.000000Z"
AFTER_AS_OF = "2026-06-15T00:00:00.000000Z"
LATER_AFTER_AS_OF = "2026-07-01T00:00:00.000000Z"

_META = RecordMeta(
    1, ("1" * 64,), ProducerVersion("2" * 64, "3" * 40, 1), "4" * 64, BEFORE_SEAL
)
_BOUNDS = CountBounds(0, None)
_COUNTS = LabelCounts(_BOUNDS, _BOUNDS, _BOUNDS, _BOUNDS)


def _locator() -> SourceLocator:
    return SourceLocator("a" * 64, "latex", None, None, None, None)


def _overview() -> CardOverview:
    return CardOverview("complete", "A title", "An abstract.", ())


def _unavailable_head(target_id: str) -> HeadCardValue:
    return HeadCardValue(
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


def _heads() -> tuple[HeadCardValue, ...]:
    return tuple(_unavailable_head(target_id) for target_id in TARGET_IDS)


def _qualified_head(target_id: str, training_cutoff: str) -> HeadCardValue:
    return HeadCardValue(
        target_id,
        "b" * 64,
        "Will this paper cross the threshold?",
        0.5,
        "qualified",
        None,
        "2026-12-01T00:00:00.000000Z",
        "c" * 64,
        training_cutoff,
        "d" * 64,
        "eligible",
        None,
    )


def _label(
    family_id: str, target_id: str, state: str, resolved_at: str
) -> AutomaticLabel:
    reason = {
        "true": "sufficient_positive_witnesses",
        "false": "complete_negative_evidence",
    }[state]
    return AutomaticLabel(
        schema_version=_META.schema_version,
        input_hashes=_META.input_hashes,
        producer_version=_META.producer_version,
        config_hash=_META.config_hash,
        created_at=_META.created_at,
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
        maturity_at=BEFORE_SEAL,
        resolved_at=resolved_at,
        supersedes_label_hash=None,
        correction_hash=None,
    )


def _base_input(**overrides: Any) -> CardBuildInput:
    fields: dict[str, Any] = dict(
        paper_family_id=str(uuid4()),
        paper_version_id=str(uuid4()),
        as_of=AS_OF,
        corpus_arrival_at=ARRIVAL,
        overview=_overview(),
        overview_available=True,
        first_public_at=ARRIVAL,
        original_source=_locator(),
        passage_coverage="unavailable",
        passage_count=0,
        extraction_hash=None,
        representation_hash=None,
        head_feature_eligible=False,
        head_feature_unavailable_reason="missing_source",
        head_predictions=_heads(),
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
        jev=JevCardAssessment(JevCardUnavailable("missing_input", "0" * 64, None)),
        card_token_count=42,
        author_count=3,
        categories=("cs.AI",),
        version_count=1,
        title_tokens=2,
        abstract_tokens=5,
        code_link=False,
    )
    fields.update(overrides)
    return CardBuildInput(**fields)


def test_the_inline_jev_section_round_trips_and_is_closed() -> None:
    section = JevCardAssessment(JevCardUnavailable("provider_failure", "2" * 64, None))
    assert JevCardAssessment.from_json(section.to_canonical_json()) == section
    body = section.to_dict()
    body["extra"] = 1
    with pytest.raises(ContractValidationError):
        JevCardAssessment.from_json(canonical_json(body))


def test_an_unadmitted_jev_unavailable_reason_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        JevCardUnavailable("missing_source", "2" * 64, None)


def test_a_first_paper_with_no_signals_remains_readable() -> None:
    build_input = _base_input()
    card = assemble_card(build_input)
    assert card.paper_family_id == build_input.paper_family_id
    assert card.paper_version_id == build_input.paper_version_id
    assert card.overview.title == "A title"
    assert card.overview.abstract == "An abstract."
    assert card.original_source == build_input.original_source
    assert all(head.availability == "unavailable" for head in card.head_predictions)
    assert card.graph.incoming_family_count is None
    assert card.graph.outgoing_family_count is None
    assert card.neighbors == ()
    assert all(value.reason == "no_known_labels" for value in card.neighbor_outcomes)
    assert card.author_citations == ()


def test_assembly_is_deterministic() -> None:
    build_input = _base_input()
    first = assemble_card(build_input)
    second = assemble_card(build_input)
    assert first == second
    assert first.to_canonical_json() == second.to_canonical_json()


def test_a_later_dated_capture_cannot_mutate_the_pinned_card() -> None:
    def with_capture(captured_at: str) -> CardBuildInput:
        return _base_input(
            author_ids=("alice",),
            author_captures=(AuthorCitationCapture("alice", 7, "a" * 64, captured_at),),
        )

    pinned = assemble_card(with_capture(AFTER_AS_OF))
    still_pinned = assemble_card(with_capture(LATER_AFTER_AS_OF))
    assert pinned.author_citations == still_pinned.author_citations
    assert pinned.author_citations[0].reason == "not_available_as_of"
    assert pinned.author_citations[0].count is None


def test_graph_neighbor_and_author_signals_are_computed_and_composed() -> None:
    neighbor_id = str(uuid4())
    neighbor_version_id = str(uuid4())
    build_input = _base_input(
        neighbors=(
            NeighborCardSummary(
                neighbor_id, neighbor_version_id, "A neighbor paper", 0.9, "f" * 64
            ),
        ),
        neighbor_arrivals=((neighbor_id, BEFORE_ARRIVAL),),
        neighbor_embedding_distance=AvailabilityValue.available(0.2),
        outcome_labels=(_label(neighbor_id, TARGET_IDS[0], "true", BEFORE_SEAL),),
        graph_incoming_family_ids=("g1", "g1"),
        graph_outgoing_family_ids=("g2",),
        graph_parsed_reference_count=2,
        graph_matched_reference_ids=("m1",),
        graph_reference_vector_count=1,
        graph_missing_reference_vector_count=1,
        graph_reference_centroid_distance=AvailabilityValue.available(0.3),
        graph_manifest_hash="c" * 64,
        author_ids=("alice", "bob"),
        author_captures=(AuthorCitationCapture("alice", 10, "a" * 64, BEFORE_ARRIVAL),),
    )
    card = assemble_card(build_input)

    assert card.graph.incoming_family_count == 1
    assert card.graph.outgoing_family_count == 1
    assert card.graph.matched_reference_count == 1
    assert card.graph.reference_match_fraction == 0.5

    by_target = {value.target_id: value for value in card.neighbor_outcomes}
    assert by_target[TARGET_IDS[0]].known_neighbor_count == 1
    assert by_target[TARGET_IDS[0]].positive_neighbor_count == 1
    assert by_target[TARGET_IDS[1]].known_neighbor_count == 0

    author_by_id = {value.author_id: value for value in card.author_citations}
    assert author_by_id["alice"].count == 10
    assert author_by_id["bob"].reason == "missing_source"


def test_declared_metadata_fields_pass_through_and_weekday_is_derived() -> None:
    build_input = _base_input(
        first_public_at="2026-05-01T00:00:00.000000Z",  # a Friday
        author_count=4,
        categories=("cs.LG", "cs.AI"),
        version_count=2,
        title_tokens=9,
        abstract_tokens=123,
        code_link=True,
    )
    card = assemble_card(build_input)
    assert card.author_count == 4
    assert card.categories == ("cs.LG", "cs.AI")
    assert card.version_count == 2
    assert card.title_tokens == 9
    assert card.abstract_tokens == 123
    assert card.code_link is True
    assert card.first_available_weekday == 4


def test_unknown_first_public_at_leaves_the_weekday_unknown() -> None:
    build_input = _base_input(first_public_at=None)
    card = assemble_card(build_input)
    assert card.first_available_weekday is None


def test_malformed_head_predictions_raise_instead_of_silently_publishing() -> None:
    build_input = _base_input(head_predictions=(_unavailable_head(TARGET_IDS[0]),))
    with pytest.raises(ContractValidationError):
        assemble_card(build_input)


def test_a_stale_head_stamp_is_rejected_without_suppressing_the_card() -> None:
    heads = tuple(
        _qualified_head(target_id, AFTER_AS_OF)
        if target_id == TARGET_IDS[1]
        else _qualified_head(target_id, BEFORE_SEAL)
        for target_id in TARGET_IDS
    )
    build_input = _base_input(head_predictions=heads)
    card = assemble_card(build_input)
    by_target = {head.target_id: head for head in card.head_predictions}

    stale = by_target[TARGET_IDS[1]]
    assert stale.availability == "unavailable"
    assert stale.unavailable_reason == "not_available_as_of"
    assert stale.probability is None
    assert stale.model_bundle_id == "c" * 64

    for target_id in (TARGET_IDS[0], TARGET_IDS[2]):
        archived = by_target[target_id]
        assert archived.availability == "qualified"
        assert archived.probability == 0.5
        assert archived.training_cutoff == BEFORE_SEAL


def test_a_neighbor_cannot_be_the_paper_itself() -> None:
    family_id = str(uuid4())
    build_input = _base_input(
        paper_family_id=family_id,
        neighbors=(
            NeighborCardSummary(family_id, str(uuid4()), "Itself", 1.0, "f" * 64),
        ),
        neighbor_arrivals=((family_id, BEFORE_ARRIVAL),),
    )
    with pytest.raises(ContractValidationError):
        assemble_card(build_input)


REPRESENTATION = "9" * 64


def _overview_vector(
    family_id: str,
    vector: tuple[float, ...],
    first_public_at: str,
    arrival: str = BEFORE_ARRIVAL,
) -> OverviewVector:
    return OverviewVector(
        paper_family_id=family_id,
        paper_version_id=str(uuid4()),
        title="A neighbor paper",
        card_id="f" * 64,
        first_public_at=first_public_at,
        corpus_arrival_at=arrival,
        available_at=BEFORE_ARRIVAL,
        representation_hash=REPRESENTATION,
        vector=vector,
    )


def test_vectors_give_the_card_its_neighbors_and_both_distances() -> None:
    near, far, later, cited = (str(uuid4()) for _ in range(4))
    vectors = CardVectors(
        (1.0, 0.0),
        (
            _overview_vector(near, (0.8, 0.6), BEFORE_ARRIVAL),
            _overview_vector(far, (0.0, 1.0), BEFORE_ARRIVAL),
            _overview_vector(later, (1.0, 0.0), BEFORE_SEAL, arrival=BEFORE_SEAL),
            _overview_vector(cited, (0.6, 0.8), BEFORE_ARRIVAL),
        ),
    )
    build_input = _base_input(
        representation_hash=REPRESENTATION,
        outcome_labels=(_label(near, TARGET_IDS[0], "true", BEFORE_SEAL),),
        graph_outgoing_family_ids=(cited, cited, str(uuid4())),
        graph_parsed_reference_count=3,
        graph_matched_reference_ids=("m1", "m2"),
    )
    card = assemble_card(build_input, vectors=vectors)

    assert [n.paper_family_id for n in card.neighbors] == [near, cited, far]
    assert card.neighbor_embedding_distance.value == pytest.approx(
        ((1 - 0.8) + (1 - 0.6) + 1) / 3
    )
    assert card.graph.reference_centroid_distance.value == pytest.approx(1 - 0.6)
    assert card.graph.reference_vector_count == 1
    assert card.graph.missing_reference_vector_count == 2
    by_target = {value.target_id: value for value in card.neighbor_outcomes}
    assert by_target[TARGET_IDS[0]].positive_neighbor_count == 1


def test_a_paper_without_a_vector_gets_unavailable_distances() -> None:
    card = assemble_card(
        _base_input(representation_hash=REPRESENTATION, graph_parsed_reference_count=2),
        vectors=CardVectors(None, ()),
    )
    assert card.neighbors == ()
    assert card.neighbor_embedding_distance.reason == "missing_vector"
    assert card.graph.reference_centroid_distance.reason == "missing_vector"
    assert card.graph.missing_reference_vector_count == 2


def test_vectors_and_declared_neighbor_signals_are_refused_together() -> None:
    build_input = _base_input(
        representation_hash=REPRESENTATION,
        neighbor_embedding_distance=AvailabilityValue.available(0.2),
    )
    with pytest.raises(ContractValidationError, match="vectors"):
        assemble_card(build_input, vectors=CardVectors((1.0, 0.0), ()))


def _passage(
    version_id: str, section_order: int, path: tuple[str, ...], passage_order: int
) -> PassageRecord:
    return PassageRecord(
        paper_version_id=version_id,
        extraction_hash="e" * 64,
        chunk_policy=CHUNK_POLICY,
        section_order=section_order,
        section_path=path,
        passage_order=passage_order,
        section_token_start=0,
        section_token_end_exclusive=1,
        char_start=0,
        char_end_exclusive=1,
        block_ids=("b0",),
        text_hash="d" * 64,
        source_locators=(_locator(),),
        overlap_adjusted_weight=1.0,
    )


def _sectioned_input(
    sections: list[tuple[tuple[str, ...], int]], **overrides: Any
) -> CardBuildInput:
    """A card input whose passages fill `sections`, each (path, passages)."""

    version_id = str(uuid4())
    passages = [
        _passage(version_id, section_order, path, passage_order)
        for section_order, (path, count) in enumerate(sections)
        for passage_order in range(count)
    ]
    fields: dict[str, Any] = dict(
        paper_version_id=version_id,
        passage_coverage="complete",
        passage_count=len(passages),
        passages=tuple(reversed(passages)),
    )
    fields.update(overrides)
    return _base_input(**fields)


def test_the_section_map_numbers_passages_by_top_level_section() -> None:
    card = assemble_card(
        _sectioned_input(
            [
                (("Abstract",), 1),
                (("Introduction",), 2),
                (("Introduction", "Motivation"), 1),
                (("Limitations",), 1),
                (("Future work",), 2),
            ]
        )
    )
    assert card.sections == (
        CardSection("Abstract", 1, 1, 1),
        CardSection("Introduction", 3, 2, 4),
        CardSection("Limitations", 1, 5, 5),
        CardSection("Future work", 2, 6, 7),
    )
    assert card.unlisted_section_count == 0
    assert card.to_dict()["sections"][1] == {
        "title": "Introduction",
        "passage_count": 3,
        "first_passage": 2,
        "last_passage": 4,
    }


def test_one_top_level_section_is_no_section_structure() -> None:
    card = assemble_card(_sectioned_input([(("Body",), 3)]))
    assert card.sections == ()
    assert card.unlisted_section_count == 0
    assert assemble_card(_base_input()).sections == ()


def test_the_section_map_lists_forty_sections_then_counts_the_rest() -> None:
    card = assemble_card(
        _sectioned_input([((f"Section {index}",), 1) for index in range(45)])
    )
    assert len(card.sections) == CARD_SECTION_LIMIT == 40
    assert card.sections[-1] == CardSection("Section 39", 1, 40, 40)
    assert card.unlisted_section_count == 5


def test_passages_that_are_not_the_cards_are_refused() -> None:
    build_input = _sectioned_input([(("A",), 1), (("B",), 1)])
    with pytest.raises(ContractValidationError, match="passage_count"):
        assemble_card(replace(build_input, passage_count=3))
    other = _passage(str(uuid4()), 0, ("A",), 0)
    with pytest.raises(ContractValidationError, match="version"):
        assemble_card(replace(build_input, passages=(other, build_input.passages[0])))


def test_a_section_map_that_does_not_tile_the_passages_is_refused() -> None:
    card = assemble_card(_sectioned_input([(("A",), 2), (("B",), 1)]))
    with pytest.raises(ContractValidationError, match="count"):
        CardSection("A", 2, 1, 1)
    with pytest.raises(ContractValidationError, match="tile"):
        replace(card, sections=(CardSection("B", 1, 3, 3),))
    with pytest.raises(ContractValidationError, match="more passages"):
        replace(card, passage_count=2)
    with pytest.raises(ContractValidationError, match="full section list"):
        replace(card, unlisted_section_count=1)
