"""``query_cards``: pinned cards by id, or ranked by a query (RD-06, RD-26).

A lookup names one to five paper families and answers their pinned cards
in the order named. A search embeds the query through the shared model
service under the snapshot's one representation (PL-08) and ranks by exact
cosine: ``overview`` mode ranks the snapshot's papers by their pinned
overview vectors, ties by family id, and answers the top cards;
``passages`` mode ranks the pinned passages of every paper whose text can
be rebuilt from its pinned extraction (RD-26's per-paper cap and
non-overlap selection) and answers the exact matched text with its source
locators. Every answer comes from the run's own snapshot (PL-21).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from ..models.service import EmbeddingResult
from ..reader.chunk import SectionTokenizer
from ..retrieval.passages import SearchCandidate, search_passages
from ..storage.client import StorageClientError
from .answers import CallContext, ToolAnswer, ToolError
from .lookup import FamilyReads
from .snapshots import IndexedMember, SnapshotIndex, SnapshotReads
from .text import PinnedTexts

__all__ = ["CardReads", "QueryEmbedder", "QueryCardsHandler", "pinned_family"]


class QueryEmbedder(Protocol):
    """The shared model service's query embedding (``models.client``)."""

    def embed_query(
        self, text: str, *, representation_hash: str
    ) -> EmbeddingResult: ...


class CardReads(SnapshotReads, FamilyReads, Protocol):
    """The snapshot reads ``query_cards`` needs."""


def pinned_family(
    storage: FamilyReads, snapshot_hash: str, family_id: str
) -> dict[str, Any]:
    """The member row of the one version the snapshot pins for *family_id*."""

    try:
        member = storage.snapshot_family(snapshot_hash, family_id=UUID(family_id)).data[
            "member"
        ]
    except StorageClientError as error:
        if error.status_code == 422:
            raise ToolError("not_in_snapshot", str(error)) from error
        raise
    return dict(member)


class QueryCardsHandler:
    """Answer ``query_cards`` from the run's own snapshot."""

    def __init__(
        self,
        *,
        storage: CardReads,
        index: SnapshotIndex,
        embedder: QueryEmbedder,
        texts: PinnedTexts,
        tokenizer: SectionTokenizer,
    ) -> None:
        self._storage = storage
        self._index = index
        self._embedder = embedder
        self._texts = texts
        self._tokenizer = tokenizer

    def __call__(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer:
        if arguments["kind"] == "lookup":
            return self._lookup(arguments["paper_ids"], context)
        if arguments["mode"] == "overview":
            return self._overview(arguments, context)
        return self._passages(arguments, context)

    def _cards(
        self, snapshot_hash: str, versions: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        if not versions:
            return []
        cards = self._storage.snapshot_cards(
            snapshot_hash, paper_ids=tuple(UUID(version) for version in versions)
        ).data["cards"]
        return [dict(card) for card in cards]

    def _lookup(self, paper_ids: tuple[str, ...], context: CallContext) -> ToolAnswer:
        members = [
            pinned_family(self._storage, context.snapshot_hash, paper_id)
            for paper_id in paper_ids
        ]
        cards = self._cards(
            context.snapshot_hash,
            tuple(str(member["paper_version_id"]) for member in members),
        )
        return ToolAnswer(
            {"kind": "cards", "cards": cards},
            retrieved_ids=tuple(str(member["card_hash"]) for member in members),
        )

    def _query_vector(self, query: str, representation_hash: str) -> tuple[float, ...]:
        result = self._embedder.embed_query(
            query, representation_hash=representation_hash
        )
        if result.representation_hash != representation_hash:
            raise ToolError(
                "index_unavailable",
                "the query was embedded under another representation",
            )
        return result.vector

    def _overview(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer:
        handle = self._index.handle(context.snapshot_hash)
        query = self._query_vector(arguments["query"], handle.representation_hash)
        ranked = handle.rank(
            query, limit=arguments["limit"], only=arguments["paper_id"]
        )
        cards = self._cards(
            context.snapshot_hash, tuple(member.version_id for member, _ in ranked)
        )
        return ToolAnswer(
            {
                "kind": "search",
                "mode": "overview",
                "results": [
                    {
                        "paper_id": member.family_id,
                        "similarity": similarity,
                        "card": card,
                    }
                    for (member, similarity), card in zip(ranked, cards, strict=True)
                ],
            },
            retrieved_ids=tuple(member.card_hash for member, _ in ranked),
        )

    def _passages(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer:
        handle = self._index.handle(context.snapshot_hash)
        paper_filter: str | None = arguments["paper_id"]
        members: tuple[IndexedMember, ...]
        if paper_filter is None:
            members = handle.members
        else:
            member = handle.member(paper_filter)
            if member is None:
                raise ToolError(
                    "not_in_snapshot", "paper family is not in this snapshot"
                )
            members = (member,)
        query = self._query_vector(arguments["query"], handle.representation_hash)
        candidates: list[SearchCandidate] = []
        unavailable = 0
        for member in members:
            if member.representation_hash != handle.representation_hash:
                unavailable += 1
                continue
            found = handle.passage_candidates(
                member,
                storage=self._storage,
                texts=self._texts,
                tokenizer=self._tokenizer,
            )
            if found is None:
                unavailable += 1
            else:
                candidates.extend(found)
        results = search_passages(
            candidates=candidates,
            query_vector=query,
            paper_filter=paper_filter,
            limit=arguments["limit"],
        )
        return ToolAnswer(
            {
                "kind": "search",
                "mode": "passages",
                "results": [
                    {
                        "paper_id": result.candidate.paper_family_id,
                        "passage_id": result.candidate.text_hash,
                        "text": result.candidate.text,
                        "section_path": list(result.candidate.section_path),
                        "source_locators": [
                            locator.to_dict()
                            for locator in result.candidate.source_locators
                        ],
                        "similarity": result.similarity,
                    }
                    for result in results
                ],
                "text_unavailable_papers": unavailable,
            },
            retrieved_ids=tuple(
                dict.fromkeys(result.candidate.text_hash for result in results)
            ),
        )
