"""One paper version's embedding view, derived where its vectors are published (#298).

``build_embedding_view`` reads the vectors a publish path has just written
(the ``IndexEntry``), the paper's canonical text and its passages, and the
overview vectors already published in the same representation namespace,
and returns the derived record the owner's front end renders: the overview
vector and its value histogram, each passage's position, cosine to the
overview and folded magnitudes, the passage-to-passage cosine matrix, a 2D
PCA projection over the paper's own vectors, and the nearest papers by
overview cosine. Every number is measured from those inputs and rounded to
a fixed precision, so the same inputs rebuild the same bytes and the same
artifact hash (SR-23). Raw passage vectors stay in the index.

Neighbors rank the way ``models.neighbors.earlier_neighbors`` does -- each
family's first public version, descending exact cosine, then family id --
but are not restricted to earlier papers; ``earlier`` says which are.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..contracts.canonical import canonical_json, sha256_hex
from ..contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from ..reader.chunk import SectionTokenizer
from ..retrieval.passages import IndexEntry, build_passages
from .batch import PaperText
from .neighbors import _cosine, _unit

__all__ = [
    "COMPONENT_VERSION",
    "EmbeddingViewSink",
    "NeighborCandidate",
    "PaperIdentity",
    "build_embedding_view",
    "load_candidates",
]

#: Changes whenever the builder's output for the same inputs would change.
COMPONENT_VERSION = "embedding-view-v1"
HISTOGRAM_BINS = 48
PASSAGE_BINS = 96
NEIGHBOR_COUNT = 10
EXCERPT_CHARACTERS = 120
_VECTOR_DECIMALS = 4
_DECIMALS = 3


@dataclass(frozen=True, slots=True)
class PaperIdentity:
    """What a view names a paper version by: its family, title and first public time."""

    paper_family_id: str
    title: str
    first_public_at: str | None

    def __post_init__(self) -> None:
        validate_uuid4(self.paper_family_id)
        validate_non_empty_string(self.title)
        if self.first_public_at is not None:
            validate_utc_instant(self.first_public_at)


@dataclass(frozen=True, slots=True)
class NeighborCandidate:
    """One published overview vector a view may list as a neighbor."""

    paper_version_id: str
    identity: PaperIdentity
    vector: tuple[float, ...]


class EmbeddingViewSink(Protocol):
    """Where a publish path stores the views it builds.

    ``identities`` maps paper version id to identity for every version the
    sink can name; ``store`` publishes one view derived from the stored
    ``input_hashes`` and returns its manifest hash.
    """

    def identities(self) -> Mapping[str, PaperIdentity]: ...

    def store(self, view: Mapping[str, Any], input_hashes: tuple[str, ...]) -> str: ...


def load_candidates(
    namespace_dir: Path,
    identities: Mapping[str, PaperIdentity],
    *,
    loaded: dict[str, NeighborCandidate] | None = None,
) -> tuple[NeighborCandidate, ...]:
    """Every overview vector published in ``namespace_dir`` that ``identities`` names.

    A published entry is never replaced (``publish_index``), so a caller may
    pass the ``loaded`` mapping from an earlier call and only entries not in
    it are read.
    """

    known = {} if loaded is None else loaded
    for path in sorted(namespace_dir.glob("*.json")):
        version_id = path.stem
        identity = identities.get(version_id)
        if identity is None or version_id in known:
            continue
        entry = json.loads(path.read_bytes())
        known[version_id] = NeighborCandidate(
            version_id,
            identity,
            tuple(float(value) for value in entry["overview_vector"]),
        )
    return tuple(known[version_id] for version_id in sorted(known))


def _round(value: float, decimals: int) -> float:
    # ``round`` can answer -0.0, which canonical JSON would spell differently.
    return round(float(value), decimals) + 0.0


def _histogram(vector: tuple[float, ...]) -> dict[str, Any]:
    low, high = min(vector), max(vector)
    counts = [0] * HISTOGRAM_BINS
    width = (high - low) / HISTOGRAM_BINS
    for value in vector:
        index = HISTOGRAM_BINS - 1 if width == 0 else int((value - low) / width)
        counts[min(index, HISTOGRAM_BINS - 1)] += 1
    return {
        "bins": HISTOGRAM_BINS,
        "min": _round(low, _VECTOR_DECIMALS),
        "max": _round(high, _VECTOR_DECIMALS),
        "counts": counts,
    }


def _folded(vector: tuple[float, ...]) -> list[float]:
    """Summed absolute coordinates over ``PASSAGE_BINS`` consecutive runs."""

    size = len(vector)
    return [
        _round(
            math.fsum(
                abs(value)
                for value in vector[
                    index * size // PASSAGE_BINS : (index + 1) * size // PASSAGE_BINS
                ]
            ),
            _DECIMALS,
        )
        for index in range(PASSAGE_BINS)
    ]


def _excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= EXCERPT_CHARACTERS:
        return collapsed
    return collapsed[:EXCERPT_CHARACTERS] + "…"


def _projection(
    rows: Sequence[tuple[float, ...]],
) -> tuple[list[list[float]], list[float]]:
    """Two principal coordinates per row and their explained-variance shares.

    Each component's sign is fixed so that its largest-magnitude loading is
    positive, so the same rows always project the same way round.
    """

    matrix = np.asarray(rows, dtype=np.float64)
    centered = matrix - matrix.mean(axis=0)
    _, singular, components = np.linalg.svd(centered, full_matrices=False)
    variance = singular**2
    total = float(variance.sum())
    shares = [0.0, 0.0]
    coordinates = np.zeros((len(rows), 2))
    for axis in range(min(2, components.shape[0])):
        component = components[axis]
        if component[int(np.argmax(np.abs(component)))] < 0:
            component = -component
        coordinates[:, axis] = centered @ component
        shares[axis] = 0.0 if total == 0.0 else float(variance[axis]) / total
    return (
        [[_round(x, _DECIMALS), _round(y, _DECIMALS)] for x, y in coordinates],
        [_round(share, _DECIMALS) for share in shares],
    )


def _neighbors(
    identity: PaperIdentity,
    unit: tuple[float, ...],
    candidates: Iterable[NeighborCandidate],
) -> tuple[list[dict[str, Any]], str]:
    """The nearest families by overview cosine, and the hash of what was ranked."""

    originals: dict[str, tuple[NeighborCandidate, tuple[float, ...]]] = {}
    for candidate in candidates:
        family_id = candidate.identity.paper_family_id
        candidate_unit = _unit(candidate.vector)
        if (
            family_id == identity.paper_family_id
            or candidate_unit is None
            or len(candidate_unit) != len(unit)
        ):
            continue
        current = originals.get(family_id)
        if current is not None and _version_key(current[0]) <= _version_key(candidate):
            continue
        originals[family_id] = (candidate, candidate_unit)
    ranked = sorted(
        (
            (_cosine(unit, candidate_unit), family_id, candidate)
            for family_id, (candidate, candidate_unit) in originals.items()
        ),
        key=lambda item: (-item[0], item[1]),
    )
    ranked_input = sha256_hex(
        canonical_json(
            [
                [family_id, candidate.paper_version_id, list(candidate.vector)]
                for family_id, (candidate, _) in sorted(originals.items())
            ]
        )
    )
    return [
        {
            "paper_id": family_id,
            "title": candidate.identity.title,
            "cos": _round(cosine, _DECIMALS),
            "earlier": identity.first_public_at is not None
            and candidate.identity.first_public_at is not None
            and candidate.identity.first_public_at < identity.first_public_at,
        }
        for cosine, family_id, candidate in ranked[:NEIGHBOR_COUNT]
    ], ranked_input


def _version_key(candidate: NeighborCandidate) -> tuple[bool, str, str]:
    first = candidate.identity.first_public_at
    return (first is None, first or "", candidate.paper_version_id)


def build_embedding_view(
    *,
    identity: PaperIdentity,
    text: PaperText,
    entry: IndexEntry,
    tokenizer: SectionTokenizer,
    representation_hash: str,
    candidates: Iterable[NeighborCandidate],
    overview_hash: str | None = None,
) -> dict[str, Any]:
    """The embedding view of one published paper version.

    ``entry`` is the published index entry for ``text``'s paper version;
    its passages are matched to ``build_passages`` over the same text by
    order and text hash, and a mismatch is refused rather than drawn.
    ``overview_hash`` is the overview artifact's hash where a publish path
    stores one; the overview vector itself is inside the passage index.
    """

    validate_sha256(representation_hash)
    if overview_hash is not None:
        validate_sha256(overview_hash)
    if entry.paper_version_id != text.paper_version_id:
        raise ContractValidationError("the index entry is another paper version's")
    if entry.extraction_hash != text.extraction_hash:
        raise ContractValidationError("the index entry is another extraction's")
    overview = entry.overview_vector
    unit = _unit(overview)
    if unit is None:
        raise ContractValidationError("an overview vector must be nonzero")
    records = build_passages(
        text.extraction, text.canonical_text, text.extraction_hash, tokenizer
    )
    vectors = sorted(entry.passages, key=lambda passage: passage.passage_order)
    if [(p.passage_order, p.text_hash) for p in vectors] != [
        (order, record.text_hash) for order, record in enumerate(records)
    ]:
        raise ContractValidationError("the index passages do not match the text")
    units: list[tuple[float, ...]] = []
    for passage in vectors:
        passage_unit = _unit(passage.vector)
        if passage_unit is None or len(passage_unit) != len(unit):
            raise ContractValidationError("a passage vector must match the overview")
        units.append(passage_unit)
    points, explained = _projection([overview, *(p.vector for p in vectors)])
    neighbors, ranked_input = _neighbors(identity, unit, candidates)
    stacked = np.asarray(units, dtype=np.float64).reshape(len(units), len(unit))
    similarity = np.clip(stacked @ stacked.T, -1.0, 1.0)
    return {
        "paper_id": identity.paper_family_id,
        "paper_version_id": entry.paper_version_id,
        "representation_hash": representation_hash,
        "extraction_hash": entry.extraction_hash,
        "chunk_policy": entry.chunk_policy,
        "coverage": entry.coverage,
        "dims": len(overview),
        "overview": {
            "vector": [_round(value, _VECTOR_DECIMALS) for value in overview],
            "histogram": _histogram(overview),
            "pc": points[0],
        },
        "passages": [
            {
                "order": order,
                "section_path": list(record.section_path),
                "section_order": record.section_order,
                "tokens": record.section_token_end_exclusive
                - record.section_token_start,
                "char_start": record.char_start,
                "char_end_exclusive": record.char_end_exclusive,
                "excerpt": _excerpt(
                    text.canonical_text[record.char_start : record.char_end_exclusive]
                ),
                "cos_overview": _round(_cosine(unit, units[order]), _DECIMALS),
                "bins": _folded(passage.vector),
                "pc": points[order + 1],
            }
            for order, (record, passage) in enumerate(zip(records, vectors))
        ],
        "similarity": {
            "order": "passage order",
            "rows": [[_round(value, _DECIMALS) for value in row] for row in similarity],
        },
        "projection": {"method": "pca", "explained": explained},
        "neighbors": neighbors,
        "derived_from": {
            "overview_hash": overview_hash,
            "passage_index_hash": sha256_hex(entry.to_canonical_json()),
            "neighbor_index_hash": ranked_input,
            "component_version": COMPONENT_VERSION,
        },
    }
