"""``graph``: a paper's pinned citation graph in the run's own snapshot.

The named family resolves to the one version the run's snapshot pins, and
its graph is exactly the graph artifact that snapshot pinned for it. A
family the snapshot lacks never reaches this handler: the dispatcher
answers it with a paper request (decision 0025). A pinned paper with no
pinned graph is ``graph_unavailable``, never a graph from elsewhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol
from uuid import UUID

from ..storage.client import QueryResult, StorageClientError
from .answers import CallContext, ToolAnswer, ToolError
from .query_cards import pinned_family

__all__ = ["GraphHandler", "GraphReads"]


class GraphReads(Protocol):
    def snapshot_family(
        self, snapshot_hash: str, *, family_id: UUID
    ) -> QueryResult: ...

    def snapshot_graph(
        self,
        snapshot_hash: str,
        *,
        paper_id: UUID,
        direction: Literal["references", "citations"] = "references",
        limit: int = 20,
    ) -> QueryResult: ...


class GraphHandler:
    """Answer ``graph`` from the graph the run's own snapshot pinned."""

    def __init__(self, *, storage: GraphReads) -> None:
        self._storage = storage

    def __call__(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer:
        member = pinned_family(
            self._storage, context.snapshot_hash, arguments["paper_id"]
        )
        try:
            graph = self._storage.snapshot_graph(
                context.snapshot_hash,
                paper_id=UUID(str(member["paper_version_id"])),
                direction=arguments["direction"],
                limit=arguments["limit"],
            ).data
        except StorageClientError as error:
            if error.status_code == 422:
                raise ToolError("graph_unavailable", str(error)) from error
            raise
        return ToolAnswer(
            {
                "kind": "graph",
                "paper_id": arguments["paper_id"],
                "direction": graph["direction"],
                "graph": graph["graph"],
            },
            retrieved_ids=(str(member["graph_hash"]),),
        )
