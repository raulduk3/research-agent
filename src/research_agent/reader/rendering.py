"""Render one immutable paper card as the fixed text schema an agent reads (RD-04).

`render_card` is a pure function of a `PaperCardBody`: same card, same bytes,
every time. It renders exactly what the card already carries, in a fixed
section order, with each value's provenance and availability beside it; it
resolves nothing from storage and calls no clock. A card that cannot be
rendered this way is never stored (RD-01), so no run ever receives one.
"""

from __future__ import annotations

from ..contracts.cards import (
    AuthorCitationValue,
    AvailabilityValue,
    GraphCardValues,
    HeadCardValue,
    JevCardAssessment,
    NeighborCardSummary,
    NeighborTargetValue,
    PaperCardBody,
)

__all__ = ["render_card"]


def render_card(card: PaperCardBody) -> str:
    """Render `card` as fixed-schema text: identity, coverage, heads, Jev,
    neighbors, graph and author diagnostics, each value with its provenance
    and availability beside it."""

    sections = [
        _render_identity(card),
        _render_overview(card),
        _render_coverage(card),
        _render_heads(card.head_predictions),
        _render_jev(card.jev),
        _render_neighbors(card.neighbors, card.neighbor_embedding_distance),
        _render_neighbor_outcomes(card.neighbor_outcomes),
        _render_graph(card.graph),
        _render_authors(card.author_citations),
        _render_metadata(card),
    ]
    return "\n\n".join(sections) + "\n"


def _render_identity(card: PaperCardBody) -> str:
    return "\n".join(
        [
            f"Paper {card.paper_family_id} version {card.paper_version_id}",
            f"As of: {card.as_of}",
            f"First public at: {card.first_public_at or 'unknown'}",
        ]
    )


def _render_overview(card: PaperCardBody) -> str:
    overview = card.overview
    lines = ["# Overview", f"Title: {overview.title}"]
    if overview.kind == "complete":
        lines.append(f"Abstract: {overview.abstract}")
    else:
        lines.append("Abstract: unavailable at full length; source spans follow")
        for index, span in enumerate(overview.spans, start=1):
            lines.append(f"  Span {index} ({span.locator.source_hash}): {span.text}")
    locator = card.original_source
    lines.append(
        f"Source: {locator.source_hash} ({locator.kind})"
        + (f" page {locator.page_number}" if locator.page_number is not None else "")
    )
    return "\n".join(lines)


def _render_coverage(card: PaperCardBody) -> str:
    lines = [
        "# Coverage",
        f"Overview available: {card.overview_available}",
        f"Passage coverage: {card.passage_coverage} ({card.passage_count} passages)",
        f"Extraction hash: {card.extraction_hash or 'unavailable'}",
        f"Representation hash: {card.representation_hash or 'unavailable'}",
        "Head feature eligible: "
        + (
            "yes"
            if card.head_feature_eligible
            else f"no ({card.head_feature_unavailable_reason})"
        ),
    ]
    return "\n".join(lines)


def _render_heads(heads: tuple[HeadCardValue, ...]) -> str:
    lines = ["# Prediction heads"]
    for head in heads:
        lines.append(f"- {head.target_id} ({head.target_version}): {head.question}")
        if head.availability == "qualified":
            lines.append(
                f"  probability={head.probability} horizon_end={head.horizon_end}"
                f" bundle={head.model_bundle_id} fit={head.training_cutoff}"
                f" eval_report={head.evaluation_report_id}"
                f" eligibility={head.forecast_eligibility}"
            )
        else:
            lines.append(
                f"  unavailable ({head.unavailable_reason})"
                f" bundle={head.model_bundle_id} fit={head.training_cutoff}"
                f" eligibility={head.forecast_eligibility}"
            )
    return "\n".join(lines)


def _render_jev(jev: JevCardAssessment) -> str:
    if jev.status == "available":
        return "\n".join(
            [
                "# Jev assessment",
                f"Status: available (assessment={jev.assessment_hash})",
                f"Source: {jev.source_label}",
            ]
        )
    return "\n".join(
        [
            "# Jev assessment",
            f"Status: unavailable ({jev.reason})",
            f"Source: {jev.source_label}",
        ]
    )


def _render_neighbors(
    neighbors: tuple[NeighborCardSummary, ...],
    embedding_distance: AvailabilityValue,
) -> str:
    lines = ["# Neighbors"]
    if embedding_distance.status == "available":
        lines.append(f"Embedding distance: {embedding_distance.value}")
    else:
        lines.append(f"Embedding distance: unavailable ({embedding_distance.reason})")
    if not neighbors:
        lines.append("(none)")
    for index, neighbor in enumerate(neighbors, start=1):
        lines.append(
            f"{index}. {neighbor.title} similarity={neighbor.similarity}"
            f" card={neighbor.card_id}"
        )
    return "\n".join(lines)


def _render_neighbor_outcomes(outcomes: tuple[NeighborTargetValue, ...]) -> str:
    lines = ["# Neighbor outcomes"]
    for outcome in outcomes:
        if outcome.reason is not None:
            lines.append(f"{outcome.target_id}: unavailable ({outcome.reason})")
        else:
            lines.append(
                f"{outcome.target_id}: known={outcome.known_neighbor_count}"
                f" positive={outcome.positive_neighbor_count}"
                f" probability={outcome.probability}"
            )
    return "\n".join(lines)


def _render_graph(graph: GraphCardValues) -> str:
    centroid = graph.reference_centroid_distance
    centroid_text = (
        f"{centroid.value}"
        if centroid.status == "available"
        else f"unavailable ({centroid.reason})"
    )
    return "\n".join(
        [
            "# Graph",
            f"Incoming families: {graph.incoming_family_count if graph.incoming_family_count is not None else 'unavailable'}",
            f"Outgoing families: {graph.outgoing_family_count if graph.outgoing_family_count is not None else 'unavailable'}",
            f"References: {graph.reference_count} matched={graph.matched_reference_count}"
            f" match_fraction={graph.reference_match_fraction}",
            f"Reference vectors: {graph.reference_vector_count} missing={graph.missing_reference_vector_count}",
            f"Reference centroid distance: {centroid_text}",
            f"Graph manifest: {graph.graph_manifest_hash or 'unavailable'}",
        ]
    )


def _render_authors(authors: tuple[AuthorCitationValue, ...]) -> str:
    lines = ["# Author citations"]
    if not authors:
        lines.append("(none declared)")
    for author in authors:
        if author.count is None:
            lines.append(f"{author.author_id}: unavailable ({author.reason})")
        else:
            lines.append(f"{author.author_id}: count={author.count}")
    return "\n".join(lines)


def _render_metadata(card: PaperCardBody) -> str:
    weekday = (
        "unknown"
        if card.first_available_weekday is None
        else card.first_available_weekday
    )
    return "\n".join(
        [
            "# Metadata",
            f"Authors: {card.author_count}",
            f"Categories: {', '.join(card.categories)}",
            f"Versions: {card.version_count}",
            f"Title tokens: {card.title_tokens} Abstract tokens: {card.abstract_tokens}",
            f"Code link: {card.code_link}",
            f"First available weekday: {weekday}",
            f"Card tokens: {card.card_token_count}",
        ]
    )
