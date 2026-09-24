"""``neighbors``: a paper's nearest papers in the run's own snapshot (RD-06).

The named family's pinned overview vector is ranked against every other
paper the same snapshot pins under the same representation, by exact
float64 cosine, descending, ties by family id, and the top ones are
answered by family id and similarity with their pinned titles. The index
behind it is the snapshot's own (PL-21): a paper added in a newer snapshot
is never a neighbor here. Vectors never leave the service.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from .answers import CallContext, ToolAnswer, ToolError
from .snapshots import SnapshotIndex, SnapshotReads

__all__ = ["NeighborsHandler"]


class NeighborsHandler:
    """Answer ``neighbors`` from the run's own snapshot index."""

    def __init__(self, *, storage: SnapshotReads, index: SnapshotIndex) -> None:
        self._storage = storage
        self._index = index

    def __call__(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer:
        handle = self._index.handle(context.snapshot_hash)
        paper_id: str = arguments["paper_id"]
        member = handle.member(paper_id)
        if member is None:
            raise ToolError("not_in_snapshot", "paper family is not in this snapshot")
        if (
            member.overview is None
            or member.representation_hash != handle.representation_hash
        ):
            raise ToolError(
                "index_unavailable", "the paper has no pinned overview vector"
            )
        ranked = handle.rank(
            member.overview, limit=arguments["limit"], exclude=paper_id
        )
        cards = (
            self._storage.snapshot_cards(
                context.snapshot_hash,
                paper_ids=tuple(UUID(neighbor.version_id) for neighbor, _ in ranked),
            ).data["cards"]
            if ranked
            else []
        )
        return ToolAnswer(
            {
                "kind": "neighbors",
                "paper_id": paper_id,
                "neighbors": [
                    {
                        "paper_id": neighbor.family_id,
                        "similarity": similarity,
                        "title": _title(card),
                    }
                    for (neighbor, similarity), card in zip(ranked, cards, strict=True)
                ],
            },
            retrieved_ids=tuple(neighbor.card_hash for neighbor, _ in ranked),
        )


def _title(card: Mapping[str, Any]) -> str | None:
    overview = card.get("overview")
    title = overview.get("title") if isinstance(overview, Mapping) else None
    return title if isinstance(title, str) else None
