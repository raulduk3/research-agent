"""Merge parsed and captured citation edges into a published graph snapshot
(MD-08). Kept separate from outcomes' observation/capture-completion
protocol (Appendix B: Learning protocol): a live graph count here never
settles a target label, and settling a label never reads this module.
"""

from __future__ import annotations

from collections.abc import Callable

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.graph import GraphEdge, GraphManifest, merge_edges
from research_agent.contracts.primitives import RecordMeta, validate_non_negative_int


def merge_graph_observation(
    *,
    parsed_edges: tuple[GraphEdge, ...],
    parsed_unmatched_count: int,
    captured_edges: tuple[GraphEdge, ...],
    prior_manifest: GraphManifest | None,
    graph_version: str,
    meta: RecordMeta,
    store: Callable[[GraphManifest], None],
) -> GraphManifest:
    """Publish a new immutable graph manifest merging both edge sources.

    Duplicate observations of the same ``(source_family_id,
    target_family_id)`` pair -- whether both from this call's own
    ``parsed_edges``/``captured_edges`` or repeated across them -- merge
    into one edge rather than appearing twice. An empty ``captured_edges``
    (the remote capture is unavailable) still publishes the source-parsed
    edges; it never collapses the manifest to an invented empty-complete
    graph. ``prior_manifest``, when given, is never mutated: this always
    returns a new manifest and records the prior one's hash for lineage.
    """

    validate_non_negative_int(parsed_unmatched_count)
    merged: dict[tuple[str, str], GraphEdge] = {}
    for edge in (*parsed_edges, *captured_edges):
        key = (edge.source_family_id, edge.target_family_id)
        merged[key] = edge if key not in merged else merge_edges(merged[key], edge)
    edges = tuple(merged[key] for key in sorted(merged))

    manifest = GraphManifest(
        schema_version=meta.schema_version,
        input_hashes=meta.input_hashes,
        producer_version=meta.producer_version,
        config_hash=meta.config_hash,
        created_at=meta.created_at,
        graph_version=graph_version,
        edges=edges,
        unmatched_count=parsed_unmatched_count,
        prior_manifest_hash=(
            None
            if prior_manifest is None
            else sha256_hex(prior_manifest.to_canonical_json())
        ),
    )
    store(manifest)
    return manifest
