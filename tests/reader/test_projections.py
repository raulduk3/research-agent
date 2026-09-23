from typing import Any
from uuid import uuid4

import pytest

from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.cards import (
    AvailabilityValue,
    CardBuildInput,
    CardOverview,
    HeadCardValue,
    JevCardAssessment,
    JevCardUnavailable,
)
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.passages import SourceLocator
from research_agent.contracts.primitives import ContractValidationError
from research_agent.reader.cards import assemble_card
from research_agent.reader.projections import (
    AgentCardProjection,
    RaterCardProjection,
    strip_discovery_origin,
)

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


def test_strip_discovery_origin_passes_a_clean_payload_through() -> None:
    payload = {"title": "A title", "paper_family_id": "x"}
    assert strip_discovery_origin(payload) is payload


@pytest.mark.parametrize(
    "key",
    ["service_rank", "discovery_rank", "nomination_flag", "genome_hash", "origin"],
)
def test_strip_discovery_origin_rejects_a_withheld_field(key: str) -> None:
    payload = {"title": "A title", key: "leaked"}
    with pytest.raises(ContractValidationError):
        strip_discovery_origin(payload)


def test_agent_card_projection_carries_the_allowlisted_signals() -> None:
    card = assemble_card(_base_input())
    projection = AgentCardProjection.from_card(card)
    assert projection.paper_family_id == card.paper_family_id
    assert projection.title == "A title"
    assert projection.abstract == "An abstract."
    assert projection.head_predictions == card.head_predictions
    assert projection.graph == card.graph


def test_agent_card_projection_round_trips_through_canonical_json() -> None:
    card = assemble_card(_base_input())
    projection = AgentCardProjection.from_card(card)
    restored = AgentCardProjection.from_json(projection.to_canonical_json())
    assert restored == projection


def test_agent_card_projection_rejects_an_extra_field_at_deserialization() -> None:
    card = assemble_card(_base_input())
    projection = AgentCardProjection.from_card(card)
    payload = projection.to_dict()
    payload["embedding_vector"] = [0.1, 0.2, 0.3]

    with pytest.raises(ContractValidationError):
        AgentCardProjection.from_json(canonical_json(payload))


def test_agent_card_projection_rejects_a_leaked_discovery_field() -> None:
    card = assemble_card(_base_input())
    payload = AgentCardProjection.from_card(card).to_dict()
    payload["service_rank"] = 3

    with pytest.raises(ContractValidationError):
        AgentCardProjection.from_json(canonical_json(payload))


def test_rater_card_projection_carries_no_model_judgement() -> None:
    card = assemble_card(_base_input())
    projection = RaterCardProjection.from_card(card)
    assert projection.title == "A title"
    assert not hasattr(projection, "head_predictions")
    assert not hasattr(projection, "graph")
    assert not hasattr(projection, "jev")
    assert not hasattr(projection, "neighbors")


def test_rater_card_projection_round_trips_through_canonical_json() -> None:
    card = assemble_card(_base_input())
    projection = RaterCardProjection.from_card(card)
    restored = RaterCardProjection.from_json(projection.to_canonical_json())
    assert restored == projection


def test_identical_papers_with_a_hidden_service_rank_produce_identical_projections() -> (
    None
):
    build_input_one = _base_input()
    build_input_two = _base_input(
        paper_family_id=build_input_one.paper_family_id,
        paper_version_id=build_input_one.paper_version_id,
    )
    card_one = assemble_card(build_input_one)
    card_two = assemble_card(build_input_two)

    projection_one = AgentCardProjection.from_card(card_one)
    projection_two = AgentCardProjection.from_card(card_two)
    assert projection_one == projection_two

    for projection in (projection_one, projection_two):
        assert not (
            set(projection.to_dict()) & {"service_rank", "origin", "genome_hash"}
        )
