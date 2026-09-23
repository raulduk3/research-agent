"""Vector-free, discovery-blind tool projections of one paper card (RD-05, RD-14).

`AgentCardProjection` is the allowlisted view an agent tool response may
carry: scalar signals, identities, locators and text drawn from an already
assembled `PaperCardBody`. It is its own closed type, built field by field
rather than by copying the card wholesale, so a vector array, feature pool or
model coefficient the card's schema never had cannot silently start reaching
a run just because a future field is added to it elsewhere.

`RaterCardProjection` is the narrower view for a human rating a paper: its
own identity and readable text only, with no model judgement (prediction
heads, neighbors, graph diagnostics, Jev) and, as for the agent projection,
no discovery-service ranking or recommendation, no genome and no origin
(RD-14; the digest-level blinding of SR-21/SR-22 is a separate, already
implemented concern this projection does not repeat).

`strip_discovery_origin` is the belt-and-suspenders guard both projections
run before they read a raw payload: a paper card's closed schema (RD-01)
never carries a discovery service's rank or a selection origin, so this
function exists to fail loudly if one ever appears on an input rather than
to routinely remove one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar, cast

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
from ..contracts.canonical import canonical_json, canonical_loads
from ..contracts.passages import SourceLocator
from ..contracts.primitives import ContractValidationError

T = TypeVar("T")

__all__ = ["AgentCardProjection", "RaterCardProjection", "strip_discovery_origin"]

# A discovery service's rank or recommendation, and a digest selection's
# genome or origin, are never part of a paper card's own closed schema
# (RD-01). These names exist only so a payload that somehow carries one is
# rejected rather than silently admitted into a projection.
_DISCOVERY_ORIGIN_KEYS = frozenset(
    {
        "service_rank",
        "discovery_rank",
        "discovery_score",
        "nomination_flag",
        "source_origin",
        "origin",
        "genome_hash",
        "genome_id",
    }
)


def strip_discovery_origin(payload: dict[str, Any]) -> dict[str, Any]:
    """Return `payload` unchanged, or raise if it carries a withheld field (RD-14)."""

    leaked = _DISCOVERY_ORIGIN_KEYS & set(payload)
    if leaked:
        raise ContractValidationError(
            f"payload carries a withheld discovery/origin field: {sorted(leaked)}"
        )
    return payload


def _closed(raw: bytes, fields: frozenset[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return cast(dict[str, Any], value)


def _construct(cls: type[T], values: dict[str, Any], name: str) -> T:
    try:
        return cls(**values)
    except ContractValidationError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise ContractValidationError(f"{name} field types are invalid") from error


@dataclass(frozen=True, slots=True)
class AgentCardProjection:
    """The positive list of fields an agent tool response may carry for a paper.

    Every field here is a scalar, an identity, a locator or text; none is a
    raw vector, a feature pool or a model coefficient (RD-05).
    """

    paper_family_id: str
    paper_version_id: str
    as_of: str
    title: str
    abstract: str | None
    original_source: SourceLocator
    overview_available: bool
    passage_coverage: str
    passage_count: int
    head_predictions: tuple[HeadCardValue, ...]
    neighbors: tuple[NeighborCardSummary, ...]
    neighbor_embedding_distance: AvailabilityValue
    neighbor_outcomes: tuple[NeighborTargetValue, ...]
    graph: GraphCardValues
    author_citations: tuple[AuthorCitationValue, ...]
    jev: JevCardAssessment
    card_token_count: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "paper_family_id",
            "paper_version_id",
            "as_of",
            "title",
            "abstract",
            "original_source",
            "overview_available",
            "passage_coverage",
            "passage_count",
            "head_predictions",
            "neighbors",
            "neighbor_embedding_distance",
            "neighbor_outcomes",
            "graph",
            "author_citations",
            "jev",
            "card_token_count",
        }
    )

    @classmethod
    def from_card(cls, card: PaperCardBody) -> "AgentCardProjection":
        strip_discovery_origin(card.to_dict())
        return cls(
            paper_family_id=card.paper_family_id,
            paper_version_id=card.paper_version_id,
            as_of=card.as_of,
            title=card.overview.title,
            abstract=card.overview.abstract,
            original_source=card.original_source,
            overview_available=card.overview_available,
            passage_coverage=card.passage_coverage,
            passage_count=card.passage_count,
            head_predictions=card.head_predictions,
            neighbors=card.neighbors,
            neighbor_embedding_distance=card.neighbor_embedding_distance,
            neighbor_outcomes=card.neighbor_outcomes,
            graph=card.graph,
            author_citations=card.author_citations,
            jev=card.jev,
            card_token_count=card.card_token_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_family_id": self.paper_family_id,
            "paper_version_id": self.paper_version_id,
            "as_of": self.as_of,
            "title": self.title,
            "abstract": self.abstract,
            "original_source": self.original_source.to_dict(),
            "overview_available": self.overview_available,
            "passage_coverage": self.passage_coverage,
            "passage_count": self.passage_count,
            "head_predictions": [item.to_dict() for item in self.head_predictions],
            "neighbors": [item.to_dict() for item in self.neighbors],
            "neighbor_embedding_distance": self.neighbor_embedding_distance.to_dict(),
            "neighbor_outcomes": [item.to_dict() for item in self.neighbor_outcomes],
            "graph": self.graph.to_dict(),
            "author_citations": [item.to_dict() for item in self.author_citations],
            "jev": self.jev.to_dict(),
            "card_token_count": self.card_token_count,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(strip_discovery_origin(self.to_dict()))

    @classmethod
    def from_json(cls, raw: bytes) -> "AgentCardProjection":
        values = _closed(raw, cls._FIELDS, "AgentCardProjection")
        strip_discovery_origin(values)
        values["original_source"] = SourceLocator.from_json(
            canonical_json(values["original_source"])
        )
        values["head_predictions"] = tuple(
            HeadCardValue.from_json(canonical_json(item))
            for item in values["head_predictions"]
        )
        values["neighbors"] = tuple(
            NeighborCardSummary.from_json(canonical_json(item))
            for item in values["neighbors"]
        )
        values["neighbor_embedding_distance"] = AvailabilityValue.from_json(
            canonical_json(values["neighbor_embedding_distance"])
        )
        values["neighbor_outcomes"] = tuple(
            NeighborTargetValue.from_json(canonical_json(item))
            for item in values["neighbor_outcomes"]
        )
        values["graph"] = GraphCardValues.from_json(canonical_json(values["graph"]))
        values["author_citations"] = tuple(
            AuthorCitationValue.from_json(canonical_json(item))
            for item in values["author_citations"]
        )
        values["jev"] = _construct(
            JevCardAssessment, values["jev"], "JevCardAssessment"
        )
        return _construct(cls, values, "AgentCardProjection")


@dataclass(frozen=True, slots=True)
class RaterCardProjection:
    """The positive list of fields a rater's paper view may carry.

    No prediction, neighbor, graph or Jev field is present here: a rater
    judges the paper itself, not a model's opinion of it, and none of these
    fields is needed to keep the projection free of genome or origin
    (RD-14) since none of them ever carried one in the first place; the
    absence is a narrower, purpose-built allowlist for a different reader,
    not a defense against a specific leak.
    """

    paper_family_id: str
    paper_version_id: str
    title: str
    abstract: str | None
    original_source: SourceLocator
    passage_coverage: str
    card_token_count: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "paper_family_id",
            "paper_version_id",
            "title",
            "abstract",
            "original_source",
            "passage_coverage",
            "card_token_count",
        }
    )

    @classmethod
    def from_card(cls, card: PaperCardBody) -> "RaterCardProjection":
        strip_discovery_origin(card.to_dict())
        return cls(
            paper_family_id=card.paper_family_id,
            paper_version_id=card.paper_version_id,
            title=card.overview.title,
            abstract=card.overview.abstract,
            original_source=card.original_source,
            passage_coverage=card.passage_coverage,
            card_token_count=card.card_token_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_family_id": self.paper_family_id,
            "paper_version_id": self.paper_version_id,
            "title": self.title,
            "abstract": self.abstract,
            "original_source": self.original_source.to_dict(),
            "passage_coverage": self.passage_coverage,
            "card_token_count": self.card_token_count,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(strip_discovery_origin(self.to_dict()))

    @classmethod
    def from_json(cls, raw: bytes) -> "RaterCardProjection":
        values = _closed(raw, cls._FIELDS, "RaterCardProjection")
        strip_discovery_origin(values)
        values["original_source"] = SourceLocator.from_json(
            canonical_json(values["original_source"])
        )
        return _construct(cls, values, "RaterCardProjection")
