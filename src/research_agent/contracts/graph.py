"""Closed citation-graph contracts (MD-07, MD-08): parsed and captured
edges, unmatched bibliography entries and the immutable published graph
manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar, cast

from .canonical import canonical_json, canonical_loads
from .passages import SourceLocator
from .primitives import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

T = TypeVar("T")

EDGE_SOURCES: frozenset[str] = frozenset({"bibliography_parse", "openalex_capture"})
UNMATCHED_REASONS: frozenset[str] = frozenset(
    {"no_identifier", "unresolved_identifier"}
)


def _closed(raw: bytes, fields: frozenset[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} fields do not match schema")
    return cast(dict[str, Any], value)


def _construct(cls: type[T], values: dict[str, Any], name: str) -> T:
    try:
        return cls(**values)
    except ContractValidationError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise ContractValidationError(f"{name} field types are invalid") from error


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """One merged citation edge between two paper families (MD-07, MD-08).

    ``sources`` names which capture paths observed this edge and
    ``evidence_hashes``/``available_ats`` pair one-to-one: each evidence
    artifact carries the instant it became available, never a single
    scalar standing in for every contributing source.
    """

    source_family_id: str
    target_family_id: str
    sources: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    available_ats: tuple[str, ...]

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "source_family_id",
            "target_family_id",
            "sources",
            "evidence_hashes",
            "available_ats",
        }
    )

    def __post_init__(self) -> None:
        validate_uuid4(self.source_family_id)
        validate_uuid4(self.target_family_id)
        if (
            not self.sources
            or len(set(self.sources)) != len(self.sources)
            or tuple(sorted(self.sources)) != self.sources
            or any(source not in EDGE_SOURCES for source in self.sources)
        ):
            raise ContractValidationError("edge sources are invalid")
        if not self.evidence_hashes or len(self.evidence_hashes) != len(
            self.available_ats
        ):
            raise ContractValidationError(
                "edge evidence and availability must pair one-to-one"
            )
        if len(set(self.evidence_hashes)) != len(self.evidence_hashes):
            raise ContractValidationError("edge evidence hashes are duplicated")
        for evidence_hash in self.evidence_hashes:
            validate_sha256(evidence_hash)
        for available_at in self.available_ats:
            validate_utc_instant(available_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_family_id": self.source_family_id,
            "target_family_id": self.target_family_id,
            "sources": list(self.sources),
            "evidence_hashes": list(self.evidence_hashes),
            "available_ats": list(self.available_ats),
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "GraphEdge":
        values = _closed(raw, cls._FIELDS, "GraphEdge")
        for name in ("sources", "evidence_hashes", "available_ats"):
            if not isinstance(values[name], list):
                raise ContractValidationError(f"{name} must be an array")
            values[name] = tuple(values[name])
        return _construct(cls, values, "GraphEdge")


def merge_edges(first: GraphEdge, second: GraphEdge) -> GraphEdge:
    """Combine two observations of the same family pair into one edge.

    Both must already name the same ``(source_family_id, target_family_id)``
    pair; a caller merging across differing pairs is a programming error,
    not a data condition, so it raises rather than silently reparenting an
    edge.
    """

    if (first.source_family_id, first.target_family_id) != (
        second.source_family_id,
        second.target_family_id,
    ):
        raise ContractValidationError("cannot merge edges naming different families")
    sources = tuple(sorted(set(first.sources) | set(second.sources)))
    pairs = sorted(
        set(zip(first.evidence_hashes, first.available_ats))
        | set(zip(second.evidence_hashes, second.available_ats))
    )
    return GraphEdge(
        source_family_id=first.source_family_id,
        target_family_id=first.target_family_id,
        sources=sources,
        evidence_hashes=tuple(pair[0] for pair in pairs),
        available_ats=tuple(pair[1] for pair in pairs),
    )


@dataclass(frozen=True, slots=True)
class UnmatchedReference:
    """One bibliography entry that produced no exact family edge (MD-07).

    An unidentified reference is counted and its source span preserved,
    never guessed into an edge (no fuzzy title matching).
    """

    source_family_id: str
    raw_text: str
    locator: SourceLocator
    char_start: int
    char_end_exclusive: int
    reason: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "source_family_id",
            "raw_text",
            "locator",
            "char_start",
            "char_end_exclusive",
            "reason",
        }
    )

    def __post_init__(self) -> None:
        validate_uuid4(self.source_family_id)
        validate_non_empty_string(self.raw_text)
        if not isinstance(self.locator, SourceLocator):
            raise ContractValidationError("locator must be a SourceLocator")
        start = validate_non_negative_int(self.char_start)
        end = validate_non_negative_int(self.char_end_exclusive)
        if end <= start:
            raise ContractValidationError(
                "an unmatched reference span must be nonempty"
            )
        if self.reason not in UNMATCHED_REASONS:
            raise ContractValidationError("unmatched reason is not admitted")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_family_id": self.source_family_id,
            "raw_text": self.raw_text,
            "locator": self.locator.to_dict(),
            "char_start": self.char_start,
            "char_end_exclusive": self.char_end_exclusive,
            "reason": self.reason,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "UnmatchedReference":
        values = _closed(raw, cls._FIELDS, "UnmatchedReference")
        locator = values["locator"]
        if not isinstance(locator, dict):
            raise ContractValidationError("locator must be an object")
        values["locator"] = SourceLocator.from_json(canonical_json(locator))
        return _construct(cls, values, "UnmatchedReference")


@dataclass(frozen=True, slots=True)
class GraphManifest(RecordMeta):
    """An immutable published citation-graph snapshot (MD-07, MD-08).

    Publishing never mutates an earlier manifest's membership: each call
    produces a new ``graph_version`` and, when it followed one, records
    ``prior_manifest_hash`` for lineage rather than editing it in place.
    """

    graph_version: str
    edges: tuple[GraphEdge, ...]
    unmatched_count: int
    prior_manifest_hash: str | None

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        validate_uuid4(self.graph_version)
        if not isinstance(self.edges, tuple) or not all(
            isinstance(edge, GraphEdge) for edge in self.edges
        ):
            raise ContractValidationError("graph edges must be immutable typed records")
        pairs = [(edge.source_family_id, edge.target_family_id) for edge in self.edges]
        if len(set(pairs)) != len(pairs):
            raise ContractValidationError("graph edges must not repeat a family pair")
        if pairs != sorted(pairs):
            raise ContractValidationError(
                "graph edges must be ordered by source/target family id"
            )
        validate_non_negative_int(self.unmatched_count)
        if self.prior_manifest_hash is not None:
            validate_sha256(self.prior_manifest_hash)

    def to_dict(self) -> dict[str, Any]:
        value = RecordMeta.to_dict(self)
        value.update(
            {
                "graph_version": self.graph_version,
                "edges": [edge.to_dict() for edge in self.edges],
                "unmatched_count": self.unmatched_count,
                "prior_manifest_hash": self.prior_manifest_hash,
            }
        )
        return value

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "GraphManifest":
        fields = RecordMeta._FIELDS | {
            "graph_version",
            "edges",
            "unmatched_count",
            "prior_manifest_hash",
        }
        values = _closed(raw, frozenset(fields), "GraphManifest")
        producer = values["producer_version"]
        if not isinstance(producer, dict):
            raise ContractValidationError("producer_version must be an object")
        values["producer_version"] = ProducerVersion.from_json(canonical_json(producer))
        if not isinstance(values["input_hashes"], list):
            raise ContractValidationError("input_hashes must be an array")
        values["input_hashes"] = tuple(values["input_hashes"])
        edges = values["edges"]
        if not isinstance(edges, list):
            raise ContractValidationError("edges must be an array")
        values["edges"] = tuple(
            GraphEdge.from_json(canonical_json(edge)) for edge in edges
        )
        return _construct(cls, values, "GraphManifest")
