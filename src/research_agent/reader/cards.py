"""Assemble one immutable paper card from already-committed inputs (RD-01).

`assemble_card` reads only the declared, already-resolved signals a
`CardBuildInput` carries: it computes nothing by calling out to storage or a
model, and calls no clock. Given the same input it returns a byte-identical
`PaperCardBody`; publishing that body and swapping the current-card pointer
is storage's job, not this function's.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..contracts.cards import CardBuildInput, PaperCardBody
from .counts import author_counts
from .graph import graph_summary, neighbor_outcomes

__all__ = ["assemble_card"]


def _first_available_weekday(first_public_at: str | None) -> int | None:
    """The UTC weekday of first public availability (#149), or unknown."""

    if first_public_at is None:
        return None
    return (
        datetime.fromisoformat(first_public_at.replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .weekday()
    )


def assemble_card(input: CardBuildInput) -> PaperCardBody:
    """Build the paper card `input` declares, or raise on an invalid input.

    Core identity and source text come straight from `input` and are always
    present. Graph features, earlier-neighbor outcomes and author citation
    counts are derived here from `input`'s raw observations (RD-10 to
    RD-12); every other signal (overview, head predictions, neighbor list,
    embedding distances, Jev assessment) is carried through exactly as
    `input` declares it, already in its typed available-or-unavailable form.
    """

    graph = graph_summary(
        incoming_family_ids=input.graph_incoming_family_ids,
        outgoing_family_ids=input.graph_outgoing_family_ids,
        parsed_reference_count=input.graph_parsed_reference_count,
        matched_reference_ids=input.graph_matched_reference_ids,
        reference_vector_count=input.graph_reference_vector_count,
        missing_reference_vector_count=input.graph_missing_reference_vector_count,
        reference_centroid_distance=input.graph_reference_centroid_distance,
        graph_manifest_hash=input.graph_manifest_hash,
    )
    outcomes = neighbor_outcomes(
        neighbor_family_ids=tuple(
            neighbor.paper_family_id for neighbor in input.neighbors
        ),
        neighbor_arrivals=input.neighbor_arrivals,
        target_corpus_arrival_at=input.corpus_arrival_at,
        labels=input.outcome_labels,
        as_of=input.as_of,
    )
    authors = author_counts(
        author_ids=input.author_ids,
        captures=input.author_captures,
        as_of=input.as_of,
    )
    return PaperCardBody(
        schema_version=1,
        paper_family_id=input.paper_family_id,
        paper_version_id=input.paper_version_id,
        as_of=input.as_of,
        overview=input.overview,
        first_public_at=input.first_public_at,
        original_source=input.original_source,
        overview_available=input.overview_available,
        passage_coverage=input.passage_coverage,
        passage_count=input.passage_count,
        extraction_hash=input.extraction_hash,
        representation_hash=input.representation_hash,
        head_feature_eligible=input.head_feature_eligible,
        head_feature_unavailable_reason=input.head_feature_unavailable_reason,
        head_predictions=input.head_predictions,
        neighbors=input.neighbors,
        neighbor_embedding_distance=input.neighbor_embedding_distance,
        neighbor_outcomes=outcomes,
        graph=graph,
        author_citations=authors,
        jev=input.jev,
        card_token_count=input.card_token_count,
        author_count=input.author_count,
        categories=input.categories,
        version_count=input.version_count,
        title_tokens=input.title_tokens,
        abstract_tokens=input.abstract_tokens,
        code_link=input.code_link,
        first_available_weekday=_first_available_weekday(input.first_public_at),
    )
