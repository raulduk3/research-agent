"""Passage building, search and publication (SDD RD-25 to RD-28, Appendix C).

``build_passages`` is the public entry point named by TDD-1.1.25; it chunks
one extraction to the fixed passage policy through the private
``reader.chunk.chunk_passages`` helper (TDD's implementation interface map).
``publish_index`` is TDD-1.1.28's owner: it atomically publishes one paper
version's overview and passage vectors into a representation namespace
directory, reusing unchanged artifacts and never mixing model, chunk-policy
or platform identities (Appendix C: Failure, caching and snapshots).
``publish_namespace_manifest`` records what a namespace was built under,
and ``namespace_identity`` reads back the index identity a day binds (#355).

``search_passages`` (RD-26) is a pure ranking function: it never embeds a
query and never reads storage itself. Its caller resolves the snapshot's
eligible candidates and the query's already-computed vector; this module
only applies the cosine ranking, tie order, per-paper cap and greedy
non-overlap selection Appendix C fixes. ``attach_evidence`` (RD-27) then
wraps ranked results as a query-specific envelope beside an unchanged base
paper card.
"""

from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts.canonical import canonical_json, canonical_loads, sha256_hex
from ..contracts.passages import (
    CHUNK_POLICY,
    ExtractionRecord,
    PassageRecord,
    SourceLocator,
)
from ..contracts.primitives import (
    ContractValidationError,
    validate_finite,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_uuid4,
)
from ..reader.chunk import SectionTokenizer, chunk_passages

__all__ = [
    "build_passages",
    "search_passages",
    "attach_evidence",
    "SearchCandidate",
    "SearchResult",
    "QueryEvidenceEnvelope",
    "PublishedPassage",
    "IndexEntry",
    "IndexPublicationResult",
    "publish_index",
    "read_index_entry",
    "NAMESPACE_MANIFEST",
    "publish_namespace_manifest",
    "namespace_identity",
]

# Not ``*.json``: namespace readers take every ``*.json`` stem as a paper
# version id.
NAMESPACE_MANIFEST = "namespace.manifest"

# The representation manifest's fields a namespace records, less
# ``qualified``: qualification is evidence about a representation, not part
# of it, so promoting it must not change an identity a snapshot has frozen.
_REPRESENTATION_FIELDS = frozenset(
    {
        "model_id",
        "revision",
        "checkpoint_date",
        "dtype",
        "device",
        "deterministic_algorithms",
        "dimension",
        "pooling",
        "document_prefix",
        "query_prefix",
        "max_model_tokens",
        "tokenizer_hash",
        "weight_hash",
    }
)

PER_FAMILY_RESULT_LIMIT = 2


def build_passages(
    extraction: ExtractionRecord,
    canonical_text: str,
    extraction_hash: str,
    tokenizer: SectionTokenizer,
) -> tuple[PassageRecord, ...]:
    """Chunk one extraction's included text into ordered, source-linked passages."""

    return chunk_passages(extraction, canonical_text, extraction_hash, tokenizer)


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    """One vector eligible for RD-26 ranking: an overview or a single passage.

    The caller has already bound this to one snapshot-visible paper
    version -- never a newer artifact and never a mix of versions -- so
    this module has no snapshot or version-selection logic of its own.
    """

    paper_family_id: str
    paper_version_id: str
    section_order: int
    section_path: tuple[str, ...]
    char_start: int
    char_end_exclusive: int
    text: str
    text_hash: str
    source_locators: tuple[SourceLocator, ...]
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        validate_uuid4(self.paper_family_id)
        validate_uuid4(self.paper_version_id)
        validate_non_negative_int(self.section_order)
        if not all(isinstance(part, str) and part for part in self.section_path):
            raise ContractValidationError("section_path must be nonempty strings")
        validate_non_negative_int(self.char_start)
        validate_positive_int(self.char_end_exclusive)
        if self.char_end_exclusive <= self.char_start:
            raise ContractValidationError("a candidate must be a nonempty span")
        validate_non_empty_string(self.text)
        validate_sha256(self.text_hash)
        if not all(isinstance(item, SourceLocator) for item in self.source_locators):
            raise ContractValidationError(
                "source_locators must be SourceLocator values"
            )
        if not self.vector:
            raise ContractValidationError("a candidate requires a vector")
        for coordinate in self.vector:
            validate_finite(coordinate)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One selected candidate and the cosine similarity that ranked it."""

    candidate: SearchCandidate
    similarity: float


def _cosine(query: tuple[float, ...], candidate: tuple[float, ...]) -> float:
    if len(query) != len(candidate):
        raise ContractValidationError(
            "query and candidate vectors must share dimension"
        )
    dot = math.fsum(float(a) * float(b) for a, b in zip(query, candidate))
    query_norm = math.sqrt(math.fsum(float(a) * float(a) for a in query))
    candidate_norm = math.sqrt(math.fsum(float(b) * float(b) for b in candidate))
    if query_norm == 0.0 or candidate_norm == 0.0:
        raise ContractValidationError("a zero vector has no cosine similarity")
    return dot / (query_norm * candidate_norm)


def _overlaps(candidate: SearchCandidate, spans: list[tuple[int, int]]) -> bool:
    return any(
        candidate.char_start < end and start < candidate.char_end_exclusive
        for start, end in spans
    )


def search_passages(
    *,
    candidates: Sequence[SearchCandidate],
    query_vector: tuple[float, ...],
    paper_filter: str | None,
    limit: int,
) -> tuple[SearchResult, ...]:
    """Rank *candidates* against *query_vector* under RD-26's bounded ranking.

    Ranking is exact float64 cosine, descending similarity, ties broken by
    paper-family id, paper-version id, section order and passage start
    offset (Appendix C: Retrieval protocol). Without ``paper_filter`` the
    *limit* counts distinct paper families and returns at most
    :data:`PER_FAMILY_RESULT_LIMIT` non-overlapping candidates per family;
    with ``paper_filter`` the *limit* counts non-overlapping candidates
    from that one family. Selection is greedy in rank order, skipping any
    candidate whose character span overlaps one already selected from the
    same paper version. Fewer eligible candidates than *limit* returns
    fewer results -- nothing is fabricated to fill it.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
        raise ContractValidationError("limit must be an integer from 1 to 5")
    if paper_filter is not None:
        validate_uuid4(paper_filter)
    pool = [
        candidate
        for candidate in candidates
        if paper_filter is None or candidate.paper_family_id == paper_filter
    ]
    scored = sorted(
        ((_cosine(query_vector, candidate.vector), candidate) for candidate in pool),
        key=lambda item: (
            -item[0],
            item[1].paper_family_id,
            item[1].paper_version_id,
            item[1].section_order,
            item[1].char_start,
        ),
    )
    selected: list[SearchResult] = []
    spans_by_version: dict[str, list[tuple[int, int]]] = {}
    family_counts: dict[str, int] = {}
    for similarity, candidate in scored:
        if (
            paper_filter is None
            and family_counts.get(candidate.paper_family_id, 0)
            >= PER_FAMILY_RESULT_LIMIT
        ):
            continue
        spans = spans_by_version.setdefault(candidate.paper_version_id, [])
        if _overlaps(candidate, spans):
            continue
        if paper_filter is None:
            already_counted = candidate.paper_family_id in family_counts
            if not already_counted and len(family_counts) >= limit:
                continue
        elif len(selected) >= limit:
            break
        selected.append(SearchResult(candidate, similarity))
        spans.append((candidate.char_start, candidate.char_end_exclusive))
        family_counts[candidate.paper_family_id] = (
            family_counts.get(candidate.paper_family_id, 0) + 1
        )
    return tuple(selected)


@dataclass(frozen=True, slots=True)
class QueryEvidenceEnvelope:
    """RD-27's query-specific attachment: identity, exact text and its score.

    This is never a mutation of the stored paper card: two distinct
    queries over the same card produce distinct envelopes while the base
    card, and its hash, stay exactly as sealed.
    """

    query_hash: str
    snapshot_id: str
    mode: str
    manifest_ids: tuple[str, ...]
    paper_family_id: str
    paper_version_id: str
    text: str
    section_path: tuple[str, ...]
    source_locators: tuple[SourceLocator, ...]
    similarity: float
    coverage: str

    def __post_init__(self) -> None:
        validate_sha256(self.query_hash)
        validate_sha256(self.snapshot_id)
        if self.mode not in {"overview", "passages"}:
            raise ContractValidationError("mode is not an admitted value")
        for manifest_id in self.manifest_ids:
            validate_sha256(manifest_id)
        validate_uuid4(self.paper_family_id)
        validate_uuid4(self.paper_version_id)
        validate_non_empty_string(self.text)
        if not all(isinstance(part, str) and part for part in self.section_path):
            raise ContractValidationError("section_path must be nonempty strings")
        if not all(isinstance(item, SourceLocator) for item in self.source_locators):
            raise ContractValidationError(
                "source_locators must be SourceLocator values"
            )
        similarity = validate_finite(self.similarity)
        if not -1 <= similarity <= 1:
            raise ContractValidationError("similarity must be in [-1, 1]")
        if self.coverage not in {"complete", "partial"}:
            raise ContractValidationError("coverage is not an admitted value")

    def to_dict(self) -> dict[str, object]:
        return {
            "query_hash": self.query_hash,
            "snapshot_id": self.snapshot_id,
            "mode": self.mode,
            "manifest_ids": list(self.manifest_ids),
            "paper_family_id": self.paper_family_id,
            "paper_version_id": self.paper_version_id,
            "text": self.text,
            "section_path": list(self.section_path),
            "source_locators": [item.to_dict() for item in self.source_locators],
            "similarity": self.similarity,
            "coverage": self.coverage,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())


def attach_evidence(
    *,
    base_card_hash: str,
    query_hash: str,
    snapshot_id: str,
    mode: str,
    manifest_ids: tuple[str, ...],
    coverage_by_version: Mapping[str, str],
    results: Sequence[SearchResult],
) -> tuple[str, tuple[QueryEvidenceEnvelope, ...]]:
    """Attach RD-27 query-evidence envelopes beside an unchanged base paper card.

    Returns ``base_card_hash`` unchanged alongside one envelope per entry
    in *results*, ordered as ranked. Deep reading the surrounding source
    is a separate tool call; this only carries the exact matched text,
    its score and its source location -- never vector coordinates.
    """

    validate_sha256(base_card_hash)
    envelopes = tuple(
        QueryEvidenceEnvelope(
            query_hash=query_hash,
            snapshot_id=snapshot_id,
            mode=mode,
            manifest_ids=manifest_ids,
            paper_family_id=result.candidate.paper_family_id,
            paper_version_id=result.candidate.paper_version_id,
            text=result.candidate.text,
            section_path=result.candidate.section_path,
            source_locators=result.candidate.source_locators,
            similarity=result.similarity,
            coverage=coverage_by_version[result.candidate.paper_version_id],
        )
        for result in results
    )
    return base_card_hash, envelopes


@dataclass(frozen=True, slots=True)
class PublishedPassage:
    """One passage's identity and vector as published to an index (Appendix C)."""

    passage_order: int
    text_hash: str
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.passage_order < 0:
            raise ContractValidationError("passage_order must not be negative")
        validate_sha256(self.text_hash)
        if not self.vector:
            raise ContractValidationError("a published passage requires a vector")
        for coordinate in self.vector:
            validate_finite(coordinate)

    def to_dict(self) -> dict[str, object]:
        return {
            "passage_order": self.passage_order,
            "text_hash": self.text_hash,
            "vector": list(self.vector),
        }


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """One paper version's overview and passage vectors, ready to publish.

    ``index_kind`` is always ``"engineering"``: RD-28 keeps engineering
    indexes distinguishable from a study-qualified index; the shared
    retrieval qualification in Appendix A is separate, later work no
    publication here performs.
    """

    paper_version_id: str
    extraction_hash: str
    chunk_policy: str
    coverage: str
    coverage_reasons: tuple[str, ...]
    overview_vector: tuple[float, ...]
    passages: tuple[PublishedPassage, ...]
    platform: Mapping[str, object]
    equivalence: Mapping[str, object] | None
    index_kind: str = "engineering"

    def __post_init__(self) -> None:
        validate_non_empty_string(self.paper_version_id)
        validate_sha256(self.extraction_hash)
        if self.chunk_policy != CHUNK_POLICY:
            raise ContractValidationError("chunk_policy must be the pinned policy")
        validate_non_empty_string(self.coverage)
        for reason in self.coverage_reasons:
            validate_non_empty_string(reason)
        if not self.overview_vector:
            raise ContractValidationError("an index entry requires an overview vector")
        for coordinate in self.overview_vector:
            validate_finite(coordinate)
        if not all(isinstance(passage, PublishedPassage) for passage in self.passages):
            raise ContractValidationError("passages must be PublishedPassage values")
        orders = [passage.passage_order for passage in self.passages]
        if len(set(orders)) != len(orders):
            raise ContractValidationError("passage_order must not repeat")
        if not self.platform:
            raise ContractValidationError(
                "an index entry requires its platform identity"
            )
        if self.index_kind != "engineering":
            raise ContractValidationError("index_kind must be engineering")

    def to_dict(self) -> dict[str, object]:
        return {
            "paper_version_id": self.paper_version_id,
            "extraction_hash": self.extraction_hash,
            "chunk_policy": self.chunk_policy,
            "coverage": self.coverage,
            "coverage_reasons": list(self.coverage_reasons),
            "overview_vector": list(self.overview_vector),
            "passages": [passage.to_dict() for passage in self.passages],
            "platform": dict(self.platform),
            "equivalence": dict(self.equivalence)
            if self.equivalence is not None
            else None,
            "index_kind": self.index_kind,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    def identity_json(self) -> bytes:
        """The entry's canonical bytes without its equivalence report (#361).

        The report describes the import run that admitted the vectors, not
        the vectors: two imports of the same batch sample differently, and
        neither changes what is published.
        """
        record = self.to_dict()
        del record["equivalence"]
        return canonical_json(record)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> IndexEntry:
        return cls(
            paper_version_id=value["paper_version_id"],
            extraction_hash=value["extraction_hash"],
            chunk_policy=value["chunk_policy"],
            coverage=value["coverage"],
            coverage_reasons=tuple(value["coverage_reasons"]),
            overview_vector=tuple(float(x) for x in value["overview_vector"]),
            passages=tuple(
                PublishedPassage(
                    passage["passage_order"],
                    passage["text_hash"],
                    tuple(float(x) for x in passage["vector"]),
                )
                for passage in value["passages"]
            ),
            platform=value["platform"],
            equivalence=value["equivalence"],
            index_kind=value["index_kind"],
        )


def read_index_entry(namespace_dir: Path, paper_version_id: str) -> IndexEntry | None:
    """The entry published for ``paper_version_id``, or None when there is none."""

    path = namespace_dir / f"{paper_version_id}.json"
    if not path.exists():
        return None
    value = canonical_loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ContractValidationError(f"{path.name} is not a published index entry")
    return IndexEntry.from_dict(value)


@dataclass(frozen=True, slots=True)
class IndexPublicationResult:
    """What ``publish_index`` actually did with one paper version's entry."""

    paper_version_id: str
    entry_hash: str
    reused: bool
    path: Path


def publish_index(namespace_dir: Path, entry: IndexEntry) -> IndexPublicationResult:
    """Atomically publish one paper version's vectors into a representation namespace.

    RD-28 / Appendix C: publication is atomic per paper version, so a reader
    never observes a partially written entry (write-temp, fsync, atomic
    rename); an entry already published with this exact content is reused
    rather than rewritten, and publishing one paper version never touches
    another's file, so prior snapshot membership is preserved. Content is
    compared without the equivalence report, which describes the import run
    rather than the vectors, so a second import of the same batch reuses the
    first's entry as published (#361). A different entry already published
    under the same paper version id is refused rather than silently
    replaced: changed extraction, chunking or model output publishes under a
    new namespace instead (Appendix A).
    """

    namespace_dir.mkdir(parents=True, exist_ok=True)
    final_path = namespace_dir / f"{entry.paper_version_id}.json"
    payload = entry.to_canonical_json()

    published = read_index_entry(namespace_dir, entry.paper_version_id)
    if published is not None:
        if published.identity_json() == entry.identity_json():
            return IndexPublicationResult(
                entry.paper_version_id,
                sha256_hex(final_path.read_bytes()),
                True,
                final_path,
            )
        raise ContractValidationError(
            "a published paper version cannot be silently replaced; publish "
            "changed extraction, chunking or model output under a new namespace",
        )

    _write_atomically(final_path, payload)
    return IndexPublicationResult(
        entry.paper_version_id, sha256_hex(payload), False, final_path
    )


def _write_atomically(final_path: Path, payload: bytes) -> None:
    descriptor, temp_name = tempfile.mkstemp(
        dir=final_path.parent, prefix=".tmp-", suffix=".json"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, final_path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _namespace_record(
    representation: Mapping[str, object], chunk_policy: object
) -> dict[str, object]:
    if set(representation) != _REPRESENTATION_FIELDS:
        raise ContractValidationError(
            "a namespace manifest must name exactly the representation fields "
            + ", ".join(sorted(_REPRESENTATION_FIELDS))
        )
    for name in ("model_id", "revision", "dtype", "device", "pooling"):
        validate_non_empty_string(representation[name])
    validate_sha256(representation["tokenizer_hash"])
    validate_sha256(representation["weight_hash"])
    validate_positive_int(representation["dimension"])
    validate_positive_int(representation["max_model_tokens"])
    validate_non_empty_string(chunk_policy)
    return {"chunk_policy": chunk_policy, "representation": dict(representation)}


def publish_namespace_manifest(
    namespace_dir: Path, representation: Mapping[str, object], chunk_policy: str
) -> str:
    """Record what a representation namespace was built under; return its identity.

    ``representation`` is the representation manifest's record less
    ``qualified`` (``RepresentationManifest.to_dict``). The manifest is
    written once, atomically; the same manifest again is reused, and a
    different one is refused, the rule ``publish_index`` applies to an
    entry: vectors from another model, revision, dtype, device, pooling or
    chunk policy belong to another namespace (Appendix A).
    """

    record = _namespace_record(representation, chunk_policy)
    payload = canonical_json(record)
    namespace_dir.mkdir(parents=True, exist_ok=True)
    final_path = namespace_dir / NAMESPACE_MANIFEST
    if final_path.exists():
        if namespace_identity(namespace_dir) == sha256_hex(payload):
            return sha256_hex(payload)
        raise ContractValidationError(
            "a namespace's manifest cannot be replaced; publish vectors from "
            "another representation or chunk policy under a new namespace",
        )
    _write_atomically(final_path, payload)
    return sha256_hex(payload)


def namespace_identity(namespace_dir: Path) -> str:
    """The index identity of a published representation namespace (#355).

    Two namespaces are interchangeable exactly when their representation
    manifests (model id, revision, dtype, device, pooling, prefixes, token
    budget, tokenizer and weight hashes) and chunk policy agree, so the
    identity is the canonical SHA-256 of that record, never of the vectors:
    the same pinned embedder under the same chunk policy has the same
    identity however often its entries are republished, and any change to
    the record has another. A namespace with no manifest, or one missing a
    field, has no identity and is refused.
    """

    path = namespace_dir / NAMESPACE_MANIFEST
    if not path.is_file():
        raise ContractValidationError(f"{namespace_dir} has no namespace manifest")
    value = canonical_loads(path.read_bytes())
    if not isinstance(value, Mapping) or set(value) != {
        "chunk_policy",
        "representation",
    }:
        raise ContractValidationError(
            "a namespace manifest holds exactly chunk_policy and representation"
        )
    representation = value["representation"]
    if not isinstance(representation, Mapping):
        raise ContractValidationError("a namespace representation must be an object")
    return sha256_hex(
        canonical_json(_namespace_record(representation, value["chunk_policy"]))
    )
