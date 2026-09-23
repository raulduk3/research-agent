from typing import Any
from uuid import uuid4

from research_agent.contracts.cards import (
    AvailabilityValue,
    CardBuildInput,
    CardOverview,
    HeadCardValue,
    JevCardAssessment,
    NeighborCardSummary,
)
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.passages import SourceLocator
from research_agent.reader.cards import assemble_card
from research_agent.reader.rendering import render_card

AS_OF = "2026-06-01T00:00:00.000000Z"
ARRIVAL = "2026-05-01T00:00:00.000000Z"


def _locator() -> SourceLocator:
    return SourceLocator("a" * 64, "latex", None, None, None, None)


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


def _base_input(**overrides: Any) -> CardBuildInput:
    fields: dict[str, Any] = dict(
        paper_family_id=str(uuid4()),
        paper_version_id=str(uuid4()),
        as_of=AS_OF,
        corpus_arrival_at=ARRIVAL,
        overview=CardOverview("complete", "A title", "An abstract.", ()),
        overview_available=True,
        first_public_at=ARRIVAL,
        original_source=_locator(),
        passage_coverage="unavailable",
        passage_count=0,
        extraction_hash=None,
        representation_hash=None,
        head_feature_eligible=False,
        head_feature_unavailable_reason="missing_source",
        head_predictions=tuple(_unavailable_head(t) for t in TARGET_IDS),
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
        code_link=False,
    )
    fields.update(overrides)
    return CardBuildInput(**fields)


def test_render_card_is_deterministic() -> None:
    card = assemble_card(_base_input())
    first = render_card(card)
    second = render_card(card)
    assert first == second
    assert isinstance(first, str)


def test_render_card_carries_identity_overview_and_coverage() -> None:
    card = assemble_card(_base_input())
    text = render_card(card)
    assert card.paper_family_id in text
    assert card.paper_version_id in text
    assert "A title" in text
    assert "An abstract." in text
    assert "Passage coverage: unavailable" in text


def test_render_card_shows_each_head_with_its_availability_and_reason() -> None:
    card = assemble_card(_base_input())
    text = render_card(card)
    for target_id in TARGET_IDS:
        assert target_id in text
    assert text.count("unavailable (missing_source)") >= 3


def test_render_card_reflects_a_qualified_head_with_its_stamps() -> None:
    heads = tuple(
        HeadCardValue(
            target_id,
            "b" * 64,
            "Will this paper cross the threshold?",
            0.5,
            "qualified",
            None,
            "2026-12-01T00:00:00.000000Z",
            "c" * 64,
            "2026-05-20T00:00:00.000000Z",
            "d" * 64,
            "eligible",
            None,
        )
        if target_id == TARGET_IDS[0]
        else _unavailable_head(target_id)
        for target_id in TARGET_IDS
    )
    card = assemble_card(_base_input(head_predictions=heads))
    text = render_card(card)
    assert "probability=0.5" in text
    assert "bundle=" + "c" * 64 in text


def test_render_card_lists_neighbors_nearest_first() -> None:
    neighbor_id = str(uuid4())
    neighbor_version_id = str(uuid4())
    build_input = _base_input(
        neighbors=(
            NeighborCardSummary(
                neighbor_id, neighbor_version_id, "A neighbor paper", 0.9, "f" * 64
            ),
        ),
        neighbor_arrivals=((neighbor_id, "2026-04-01T00:00:00.000000Z"),),
        neighbor_embedding_distance=AvailabilityValue.available(0.2),
    )
    card = assemble_card(build_input)
    text = render_card(card)
    assert "1. A neighbor paper similarity=0.9" in text
    assert "Embedding distance: 0.2" in text


def test_render_card_shows_referenced_overview_spans_instead_of_the_abstract() -> None:
    from research_agent.contracts.cards import OverviewSpan

    span = OverviewSpan(_locator(), "An excerpt of the abstract.")
    build_input = _base_input(
        overview=CardOverview("referenced", "A title", None, (span,))
    )
    card = assemble_card(build_input)
    text = render_card(card)
    assert "source spans follow" in text
    assert "An excerpt of the abstract." in text
