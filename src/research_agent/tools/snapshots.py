"""Snapshot-keyed indexes for ranking tools, with no latest fallback (PL-21).

``query_cards`` search and ``neighbors`` rank a snapshot's papers by exact
cosine over their pinned vectors (RD-06, RD-26). :class:`SnapshotIndex`
builds that index from exactly one sealed snapshot's pins -- its member
list, the cards and passage indexes it pins -- and caches it under
``(snapshot_hash, INDEX_SCHEMA_VERSION)`` (TDD-2.1.37). A call receives an
immutable :class:`SnapshotIndexHandle` for its lifetime; a call naming
another snapshot receives that snapshot's own handle, built from its own
pins, never a newer one. Nothing a run writes enters an index: it holds
only sealed snapshot content, the same for every run that names it.

Passage candidates need each paper's text, which is rebuilt from its pinned
extraction (``tools.text``); a handle rebuilds a paper's candidates the
first time a search needs them and keeps them with the snapshot's index.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from ..contracts.primitives import ContractValidationError
from ..reader.chunk import SectionTokenizer
from ..retrieval.passages import SearchCandidate, build_passages
from ..storage.client import QueryResult
from ..storage.http import MAXIMUM_OVERVIEW_READS
from .answers import ToolError
from .text import PinnedTexts

__all__ = [
    "INDEX_SCHEMA_VERSION",
    "IndexedMember",
    "SnapshotIndex",
    "SnapshotIndexHandle",
    "SnapshotReads",
]

INDEX_SCHEMA_VERSION = 1
# Snapshots whose index stays built at once; runs of a day share one.
_CACHED_SNAPSHOTS = 4
# ``GET /v1/snapshots/{id}/cards`` reads one to five cards.
_CARDS_PER_READ = 5


class SnapshotReads(Protocol):
    """Storage's snapshot reads, as ``StorageClient`` exposes them (#286, #297)."""

    def snapshot_members(
        self, snapshot_hash: str, *, cursor: str | None = None
    ) -> QueryResult: ...

    def snapshot_cards(
        self, snapshot_hash: str, *, paper_ids: tuple[UUID, ...]
    ) -> QueryResult: ...

    def snapshot_overviews(
        self, snapshot_hash: str, *, overview_hashes: tuple[str, ...]
    ) -> QueryResult: ...

    def snapshot_passage_index(
        self, snapshot_hash: str, *, passage_index_hash: str
    ) -> QueryResult: ...


@dataclass(frozen=True, slots=True)
class IndexedMember:
    """One pinned paper version as the snapshot's index holds it."""

    family_id: str
    version_id: str
    card_hash: str
    passage_index_hash: str | None
    representation_hash: str | None
    overview: tuple[float, ...] | None


def _unit(vector: Iterable[object]) -> tuple[float, ...] | None:
    values: list[float] = []
    for value in vector:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            return None
        values.append(float(value))
    norm = math.sqrt(math.fsum(value * value for value in values))
    if not values or norm == 0.0 or not math.isfinite(norm):
        return None
    return tuple(value / norm for value in values)


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Exact float64 cosine of two unit vectors, clamped against rounding."""

    if len(left) != len(right):
        raise ContractValidationError("vectors must share dimension")
    return min(1.0, max(-1.0, math.fsum(a * b for a, b in zip(left, right))))


@dataclass(slots=True)
class SnapshotIndexHandle:
    """One sealed snapshot's index, fixed for the calls that hold it."""

    snapshot_hash: str
    members: tuple[IndexedMember, ...]
    _by_family: dict[str, IndexedMember] = field(init=False)
    _passages: dict[str, tuple[SearchCandidate, ...] | None] = field(
        init=False, default_factory=dict
    )
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._by_family = {}
        for member in self.members:
            if member.family_id in self._by_family:
                # Choosing one pinned version of a family would be a guess.
                raise ToolError(
                    "snapshot_unavailable",
                    "a family is pinned under more than one version",
                )
            self._by_family[member.family_id] = member

    def member(self, family_id: str) -> IndexedMember | None:
        return self._by_family.get(family_id)

    @property
    def representation_hash(self) -> str:
        """The one representation every ranked vector of this snapshot shares."""

        found = {
            member.representation_hash
            for member in self.members
            if member.overview is not None and member.representation_hash is not None
        }
        if len(found) != 1:
            raise ToolError(
                "index_unavailable",
                "the snapshot holds no single representation to rank under",
            )
        return next(iter(found))

    def rank(
        self,
        query: tuple[float, ...],
        *,
        limit: int,
        only: str | None = None,
        exclude: str | None = None,
    ) -> tuple[tuple[IndexedMember, float], ...]:
        """Members by exact cosine to *query*, descending, ties by family id.

        Only members under the snapshot's one representation with a pinned
        overview vector are ranked (RD-06).
        """

        unit_query = _unit(query)
        if unit_query is None:
            raise ToolError("index_unavailable", "the query vector is not usable")
        representation = self.representation_hash
        scored = sorted(
            (
                (-cosine(unit_query, member.overview), member.family_id, member)
                for member in self.members
                if member.overview is not None
                and member.representation_hash == representation
                and (only is None or member.family_id == only)
                and member.family_id != exclude
            ),
            key=lambda item: (item[0], item[1]),
        )
        return tuple((member, -negative) for negative, _, member in scored[:limit])

    def passage_candidates(
        self,
        member: IndexedMember,
        *,
        storage: SnapshotReads,
        texts: PinnedTexts,
        tokenizer: SectionTokenizer,
    ) -> tuple[SearchCandidate, ...] | None:
        """*member*'s passages with their text and pinned vectors, or ``None``.

        The text is rebuilt from the pinned extraction and chunked under
        the pinned policy; every rebuilt passage must match its pinned
        index entry by text hash, or the paper has no candidates.
        """

        with self._lock:
            if member.family_id in self._passages:
                return self._passages[member.family_id]
        candidates = self._build_passages(
            member, storage=storage, texts=texts, tokenizer=tokenizer
        )
        with self._lock:
            return self._passages.setdefault(member.family_id, candidates)

    def _build_passages(
        self,
        member: IndexedMember,
        *,
        storage: SnapshotReads,
        texts: PinnedTexts,
        tokenizer: SectionTokenizer,
    ) -> tuple[SearchCandidate, ...] | None:
        if member.passage_index_hash is None:
            return None
        try:
            pinned = texts.text(self.snapshot_hash, member.family_id)
        except ToolError:
            return None
        index = storage.snapshot_passage_index(
            self.snapshot_hash, passage_index_hash=member.passage_index_hash
        ).data["passage_index"]
        vectors = {
            str(entry["text_hash"]): entry["vector"]
            for entry in index.get("passages", [])
            if isinstance(entry, dict)
        }
        if index.get("extraction_hash") != pinned.extraction_hash:
            return None
        records = build_passages(
            pinned.extraction, pinned.text, pinned.extraction_hash, tokenizer
        )
        if {record.text_hash for record in records} != set(vectors):
            return None
        candidates: list[SearchCandidate] = []
        for record in records:
            vector = _unit(vectors[record.text_hash])
            if vector is None:
                return None
            candidates.append(
                SearchCandidate(
                    paper_family_id=member.family_id,
                    paper_version_id=member.version_id,
                    section_order=record.section_order,
                    section_path=record.section_path,
                    char_start=record.char_start,
                    char_end_exclusive=record.char_end_exclusive,
                    text=pinned.text[record.char_start : record.char_end_exclusive],
                    text_hash=record.text_hash,
                    source_locators=record.source_locators,
                    vector=vector,
                )
            )
        return tuple(candidates)


class SnapshotIndex:
    """Build and cache each sealed snapshot's index under its own hash."""

    def __init__(self, storage: SnapshotReads) -> None:
        self._storage = storage
        self._handles: OrderedDict[tuple[str, int], SnapshotIndexHandle] = OrderedDict()
        self._lock = threading.Lock()

    def handle(self, snapshot_hash: str) -> SnapshotIndexHandle:
        """The index of exactly *snapshot_hash*, built from its own pins."""

        key = (snapshot_hash, INDEX_SCHEMA_VERSION)
        with self._lock:
            cached = self._handles.get(key)
            if cached is not None:
                self._handles.move_to_end(key)
                return cached
        built = SnapshotIndexHandle(snapshot_hash, self._members(snapshot_hash))
        with self._lock:
            handle = self._handles.setdefault(key, built)
            self._handles.move_to_end(key)
            while len(self._handles) > _CACHED_SNAPSHOTS:
                self._handles.popitem(last=False)
            return handle

    def _members(self, snapshot_hash: str) -> tuple[IndexedMember, ...]:
        pinned: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self._storage.snapshot_members(snapshot_hash, cursor=cursor).data
            pinned.extend(page["members"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        representations = self._representations(snapshot_hash, pinned)
        overviews = self._overviews(snapshot_hash, pinned)
        return tuple(
            IndexedMember(
                family_id=str(pin["paper_family_id"]),
                version_id=str(pin["paper_version_id"]),
                card_hash=str(pin["card_hash"]),
                passage_index_hash=pin["passage_index_hash"],
                representation_hash=representations.get(str(pin["paper_version_id"])),
                overview=overviews.get(str(pin["paper_version_id"])),
            )
            for pin in pinned
        )

    def _representations(
        self, snapshot_hash: str, pinned: list[dict[str, Any]]
    ) -> dict[str, str | None]:
        versions = [str(pin["paper_version_id"]) for pin in pinned]
        found: dict[str, str | None] = {}
        for start in range(0, len(versions), _CARDS_PER_READ):
            batch = versions[start : start + _CARDS_PER_READ]
            cards = self._storage.snapshot_cards(
                snapshot_hash, paper_ids=tuple(UUID(item) for item in batch)
            ).data["cards"]
            for version, card in zip(batch, cards, strict=True):
                value = card.get("representation_hash")
                found[version] = value if isinstance(value, str) else None
        return found

    def _overviews(
        self, snapshot_hash: str, pinned: list[dict[str, Any]]
    ) -> dict[str, tuple[float, ...] | None]:
        """Each version's pinned overview vector: from its own overview pin, or
        the one its pinned passage index carries (the published index entry)."""

        found: dict[str, tuple[float, ...] | None] = {}
        by_overview = {
            str(pin["overview_hash"]): str(pin["paper_version_id"])
            for pin in pinned
            if pin["overview_hash"] is not None
        }
        hashes = sorted(by_overview)
        for start in range(0, len(hashes), MAXIMUM_OVERVIEW_READS):
            batch = tuple(hashes[start : start + MAXIMUM_OVERVIEW_READS])
            read = self._storage.snapshot_overviews(
                snapshot_hash, overview_hashes=batch
            ).data["overviews"]
            for item in read:
                overview = item["overview"]
                vector = overview.get("vector") if isinstance(overview, dict) else None
                found[by_overview[item["overview_hash"]]] = (
                    _unit(vector) if isinstance(vector, list) else None
                )
        for pin in pinned:
            version = str(pin["paper_version_id"])
            if version in found or pin["passage_index_hash"] is None:
                continue
            index = self._storage.snapshot_passage_index(
                snapshot_hash, passage_index_hash=str(pin["passage_index_hash"])
            ).data["passage_index"]
            vector = index.get("overview_vector")
            found[version] = _unit(vector) if isinstance(vector, list) else None
        return found
