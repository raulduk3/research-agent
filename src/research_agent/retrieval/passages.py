"""Passage building, search and publication (SDD RD-25 to RD-28, Appendix C).

``build_passages`` is the public entry point named by TDD-1.1.25; it chunks
one extraction to the fixed passage policy through the private
``reader.chunk.chunk_passages`` helper (TDD's implementation interface map).
``publish_index`` is TDD-1.1.28's owner: it atomically publishes one paper
version's overview and passage vectors into a representation namespace
directory, reusing unchanged artifacts and never mixing model, chunk-policy
or platform identities (Appendix C: Failure, caching and snapshots).
``search_passages`` and ``attach_evidence`` have no shipped implementation
anywhere in the codebase yet: they raise until their owning slices land.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from ..contracts.canonical import canonical_json, sha256_hex
from ..contracts.passages import CHUNK_POLICY, ExtractionRecord, PassageRecord
from ..contracts.primitives import (
    ContractValidationError,
    validate_finite,
    validate_non_empty_string,
    validate_sha256,
)
from ..reader.chunk import SectionTokenizer, chunk_passages

__all__ = [
    "build_passages",
    "search_passages",
    "attach_evidence",
    "PublishedPassage",
    "IndexEntry",
    "IndexPublicationResult",
    "publish_index",
]


def build_passages(
    extraction: ExtractionRecord,
    canonical_text: str,
    extraction_hash: str,
    tokenizer: SectionTokenizer,
) -> tuple[PassageRecord, ...]:
    """Chunk one extraction's included text into ordered, source-linked passages."""

    return chunk_passages(extraction, canonical_text, extraction_hash, tokenizer)


def search_passages(*args: object, **kwargs: object) -> NoReturn:
    """RD-26 passage search. No implementation exists; #70 owns it."""

    raise NotImplementedError("search_passages has no owning slice yet; see #70")


def attach_evidence(*args: object, **kwargs: object) -> NoReturn:
    """RD-27 query-attached evidence on a paper card. #116 owns it."""

    raise NotImplementedError("attach_evidence has no owning slice yet; see #116")


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
    another's file, so prior snapshot membership is preserved. A different
    entry already published under the same paper version id is refused
    rather than silently replaced: changed extraction, chunking or model
    output publishes under a new namespace instead (Appendix A).
    """

    namespace_dir.mkdir(parents=True, exist_ok=True)
    final_path = namespace_dir / f"{entry.paper_version_id}.json"
    payload = entry.to_canonical_json()
    entry_hash = sha256_hex(payload)

    if final_path.exists():
        if sha256_hex(final_path.read_bytes()) == entry_hash:
            return IndexPublicationResult(
                entry.paper_version_id, entry_hash, True, final_path
            )
        raise ContractValidationError(
            "a published paper version cannot be silently replaced; publish "
            "changed extraction, chunking or model output under a new namespace",
        )

    descriptor, temp_name = tempfile.mkstemp(
        dir=namespace_dir, prefix=".tmp-", suffix=".json"
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
    return IndexPublicationResult(entry.paper_version_id, entry_hash, False, final_path)
