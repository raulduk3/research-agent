"""Snapshot citation-graph counters and earlier-neighbor outcomes (RD-10, RD-11).

`graph_summary` reads already-captured citation-graph edges and bibliography
match observations (MD-07, MD-08); it takes no storage dependency of its own,
so a missing graph is the caller passing `None` rather than an empty tuple.
`neighbor_outcomes` reads already-selected earlier neighbors (RD-06) and their
resolved automatic labels and reports, per target, the Laplace-smoothed rate
among neighbors with a known outcome before the snapshot seal.
"""

from __future__ import annotations

from ..contracts.cards import AvailabilityValue, GraphCardValues, NeighborTargetValue
from ..contracts.learning import TARGET_IDS, AutomaticLabel
from ..contracts.primitives import ContractValidationError

__all__ = ["graph_summary", "neighbor_outcomes"]


def graph_summary(
    *,
    incoming_family_ids: tuple[str, ...] | None,
    outgoing_family_ids: tuple[str, ...] | None,
    parsed_reference_count: int,
    matched_reference_ids: tuple[str, ...],
    reference_vector_count: int,
    missing_reference_vector_count: int,
    reference_centroid_distance: AvailabilityValue,
    graph_manifest_hash: str | None,
) -> GraphCardValues:
    """Build one paper's `GraphCardValues` from captured graph observations.

    Deduplicates repeated DOI/preprint aliases before counting, so a family
    reachable through more than one alias counts once. A `None` edge list
    means the citation graph could not be read for that direction, and is
    reported as unavailable rather than a false zero (RD-10); an empty tuple
    means the graph was read and found no edges.
    """

    incoming_count = (
        None if incoming_family_ids is None else len(set(incoming_family_ids))
    )
    outgoing_count = (
        None if outgoing_family_ids is None else len(set(outgoing_family_ids))
    )
    matched_count = len(set(matched_reference_ids))
    if parsed_reference_count > 0:
        match_fraction: int | float | None = matched_count / parsed_reference_count
    else:
        match_fraction = None
    return GraphCardValues(
        incoming_family_count=incoming_count,
        outgoing_family_count=outgoing_count,
        reference_match_fraction=match_fraction,
        reference_count=parsed_reference_count,
        matched_reference_count=matched_count,
        reference_vector_count=reference_vector_count,
        missing_reference_vector_count=missing_reference_vector_count,
        reference_centroid_distance=reference_centroid_distance,
        graph_manifest_hash=graph_manifest_hash,
    )


def neighbor_outcomes(
    *,
    neighbor_family_ids: tuple[str, ...],
    neighbor_arrivals: tuple[tuple[str, str], ...],
    target_corpus_arrival_at: str,
    labels: tuple[AutomaticLabel, ...],
    as_of: str,
) -> tuple[NeighborTargetValue, NeighborTargetValue, NeighborTargetValue]:
    """Report, per target, the outcome rate among earlier neighbors (RD-11).

    `neighbor_family_ids` names the candidates already selected as nearest
    earlier neighbors (RD-06); this function re-checks corpus arrival, a
    timestamp distinct from the first-public ordering RD-06 already applied,
    and excludes any neighbor that did not in fact arrive in the corpus
    before this paper. A neighbor's outcome for a target counts as known only
    when its most recent label resolved strictly before the snapshot seal
    and settled true or false; a label resolved at or after `as_of`, or a
    label that never settled, is excluded.
    """

    arrival_by_neighbor = dict(neighbor_arrivals)
    if len(arrival_by_neighbor) != len(neighbor_arrivals):
        raise ContractValidationError("neighbor_arrivals names a neighbor twice")
    eligible: list[str] = []
    for family_id in neighbor_family_ids:
        arrival = arrival_by_neighbor.get(family_id)
        if arrival is None:
            raise ContractValidationError("a neighbor has no declared corpus arrival")
        if arrival < target_corpus_arrival_at:
            eligible.append(family_id)
    eligible_set = set(eligible)

    latest_by_pair: dict[tuple[str, str], AutomaticLabel] = {}
    for label in labels:
        if label.paper_family_id not in eligible_set:
            continue
        if label.resolved_at >= as_of:
            continue
        key = (label.paper_family_id, label.target_id)
        current = latest_by_pair.get(key)
        if current is None or label.resolved_at > current.resolved_at:
            latest_by_pair[key] = label

    results: list[NeighborTargetValue] = []
    for target_id in TARGET_IDS:
        known = 0
        positive = 0
        for family_id in eligible:
            resolved = latest_by_pair.get((family_id, target_id))
            if resolved is None or resolved.state not in {"true", "false"}:
                continue
            known += 1
            if resolved.state == "true":
                positive += 1
        results.append(NeighborTargetValue.from_counts(target_id, known, positive))
    return (results[0], results[1], results[2])
