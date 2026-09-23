"""Earlier overview neighbors and the two card distances (RD-06, RD-07, RD-13).

Every function here reads one snapshot's original overview vectors, already
loaded by the caller, and computes exactly: float64 dot products over the
stored coordinates, no approximate index. Ties break by canonical family id,
so the same vectors always give the same neighbors in the same order. Only
ids, similarities and distances leave this module, never a vector.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..contracts.cards import AvailabilityValue, NeighborCardSummary
from ..contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

__all__ = [
    "NEIGHBOR_LIMIT",
    "OverviewVector",
    "NeighborSelection",
    "ReferenceCentroid",
    "earlier_neighbors",
    "neighbor_distance",
    "reference_centroid_distance",
]

NEIGHBOR_LIMIT = 5


def _unit(vector: tuple[float, ...]) -> tuple[float, ...] | None:
    """`vector` scaled to unit length in float64, or None when it has none."""

    if not vector or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in vector
    ):
        return None
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if norm == 0.0 or not math.isfinite(norm):
        return None
    return tuple(float(value) / norm for value in vector)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """The cosine of two unit vectors, clamped to [-1, 1] against rounding."""

    dot = math.fsum(a * b for a, b in zip(left, right, strict=True))
    return min(1.0, max(-1.0, dot))


@dataclass(frozen=True, slots=True)
class OverviewVector:
    """One paper's original overview vector as a snapshot holds it.

    `first_public_at` is the verified first public time, or None when it is
    uncertain; `available_at` is when the vector was committed, which decides
    whether a snapshot can see it.
    """

    paper_family_id: str
    paper_version_id: str
    title: str
    card_id: str
    first_public_at: str | None
    corpus_arrival_at: str
    available_at: str
    representation_hash: str
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        validate_uuid4(self.paper_family_id)
        validate_uuid4(self.paper_version_id)
        validate_non_empty_string(self.title)
        validate_sha256(self.card_id)
        if self.first_public_at is not None:
            validate_utc_instant(self.first_public_at)
        validate_utc_instant(self.corpus_arrival_at)
        validate_utc_instant(self.available_at)
        validate_sha256(self.representation_hash)
        if _unit(self.vector) is None:
            raise ContractValidationError(
                "an overview vector must be nonzero with finite coordinates"
            )


@dataclass(frozen=True, slots=True)
class NeighborSelection:
    """The selected earlier neighbors, nearest first, or why none were sought.

    `arrivals` pairs each neighbor's family id with its corpus arrival, the
    form RD-11's outcome projection reads.
    """

    representation_hash: str | None
    neighbors: tuple[NeighborCardSummary, ...]
    arrivals: tuple[tuple[str, str], ...]
    reason: str | None


@dataclass(frozen=True, slots=True)
class ReferenceCentroid:
    """The reference-centroid distance with the cited families it covers."""

    distance: AvailabilityValue
    vector_count: int
    missing_vector_count: int


def _visible_originals(
    candidates: tuple[OverviewVector, ...],
    *,
    representation_hash: str,
    dimension: int,
    as_of: str,
) -> dict[str, tuple[OverviewVector, tuple[float, ...]]]:
    """Each family's original overview vector the snapshot can see.

    A vector committed at or after `as_of`, or under another representation
    or dimension, is invisible. Of several versions of one family, the first
    public one is the original; an uncertain time ranks after every known
    one, and version id breaks what remains.
    """

    visible: dict[str, tuple[OverviewVector, tuple[float, ...]]] = {}
    for candidate in candidates:
        if (
            candidate.available_at >= as_of
            or candidate.representation_hash != representation_hash
            or len(candidate.vector) != dimension
        ):
            continue
        current = visible.get(candidate.paper_family_id)
        if current is not None and _version_key(current[0]) <= _version_key(candidate):
            continue
        unit = _unit(candidate.vector)
        assert unit is not None  # OverviewVector refuses a vector with no unit
        visible[candidate.paper_family_id] = (candidate, unit)
    return visible


def _version_key(candidate: OverviewVector) -> tuple[bool, str, str]:
    return (
        candidate.first_public_at is None,
        candidate.first_public_at or "",
        candidate.paper_version_id,
    )


def earlier_neighbors(
    *,
    paper_family_id: str,
    first_public_at: str | None,
    as_of: str,
    representation_hash: str | None,
    vector: tuple[float, ...] | None,
    candidates: tuple[OverviewVector, ...],
    limit: int = NEIGHBOR_LIMIT,
) -> NeighborSelection:
    """The paper's nearest strictly earlier overview neighbors (RD-06).

    Candidates are the snapshot-visible originals under the paper's own
    representation whose verified first public time is strictly before the
    paper's, excluding the paper's own family. They rank by descending exact
    cosine, then ascending family id, and the first `limit` are kept.
    """

    if representation_hash is None:
        return NeighborSelection(None, (), (), "incompatible_representation")
    unit = None if vector is None else _unit(vector)
    if unit is None:
        return NeighborSelection(representation_hash, (), (), "missing_vector")
    if first_public_at is None:
        return NeighborSelection(representation_hash, (), (), "missing_source")
    ranked: list[tuple[float, str, OverviewVector]] = []
    for family_id, (candidate, candidate_unit) in _visible_originals(
        candidates,
        representation_hash=representation_hash,
        dimension=len(unit),
        as_of=as_of,
    ).items():
        if (
            family_id == paper_family_id
            or candidate.first_public_at is None
            or candidate.first_public_at >= first_public_at
        ):
            continue
        ranked.append((_cosine(unit, candidate_unit), family_id, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = ranked[:limit]
    return NeighborSelection(
        representation_hash,
        tuple(
            NeighborCardSummary(
                candidate.paper_family_id,
                candidate.paper_version_id,
                candidate.title,
                similarity,
                candidate.card_id,
            )
            for similarity, _, candidate in selected
        ),
        tuple(
            (candidate.paper_family_id, candidate.corpus_arrival_at)
            for _, _, candidate in selected
        ),
        None,
    )


def neighbor_distance(selection: NeighborSelection) -> AvailabilityValue:
    """The embedding distance: mean one-minus-cosine over `selection` (RD-07).

    It reads the exact neighbors RD-06 selected, in their order, and runs no
    second search. A selection that was never made, or that found no
    neighbor, leaves the distance unavailable. The number describes distance
    only; it is not a novelty or anomaly probability.
    """

    if selection.reason is not None:
        return AvailabilityValue.unavailable(selection.reason)
    if not selection.neighbors:
        return AvailabilityValue.unavailable("no_neighbors")
    assert selection.representation_hash is not None
    distance = math.fsum(
        1.0 - neighbor.similarity for neighbor in selection.neighbors
    ) / len(selection.neighbors)
    return AvailabilityValue.available(
        distance, evidence_hashes=(selection.representation_hash,)
    )


def reference_centroid_distance(
    *,
    as_of: str,
    representation_hash: str | None,
    vector: tuple[float, ...] | None,
    reference_family_ids: tuple[str, ...] | None,
    candidates: tuple[OverviewVector, ...],
) -> ReferenceCentroid:
    """The distance from the paper to the centroid of what it cites (RD-13).

    The cited families are deduplicated, so an alias reached twice counts
    once. Each one's snapshot-visible original vector under the paper's
    representation is normalized, summed in family-id order, divided by
    the present count and normalized again; the distance is one minus the
    cosine to that centroid. A family with no such vector is counted as
    missing. No cited family, none with a vector, or a centroid that cancels
    to zero leaves the distance unavailable. A `None` reference list means
    the citation graph could not be read.
    """

    families = sorted(set(reference_family_ids or ()))

    def unavailable(reason: str, present: int = 0) -> ReferenceCentroid:
        return ReferenceCentroid(
            AvailabilityValue.unavailable(reason), present, len(families) - present
        )

    if representation_hash is None:
        return unavailable("incompatible_representation")
    unit = None if vector is None else _unit(vector)
    if unit is None:
        return unavailable("missing_vector")
    if not families:
        return unavailable("missing_source")
    visible = _visible_originals(
        candidates,
        representation_hash=representation_hash,
        dimension=len(unit),
        as_of=as_of,
    )
    present = [visible[family][1] for family in families if family in visible]
    if not present:
        return unavailable("missing_vector")
    mean = tuple(
        math.fsum(column) / len(present) for column in zip(*present, strict=True)
    )
    centroid = _unit(mean)
    if centroid is None:
        return unavailable("zero_centroid", len(present))
    return ReferenceCentroid(
        AvailabilityValue.available(
            1.0 - _cosine(unit, centroid), evidence_hashes=(representation_hash,)
        ),
        len(present),
        len(families) - len(present),
    )
