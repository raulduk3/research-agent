from __future__ import annotations

from uuid import uuid4

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.graph import GraphEdge, GraphManifest
from research_agent.ingest.graph import merge_graph_observation

PRODUCER = ProducerVersion("1" * 64, "2" * 40, 1)
CONFIG_HASH = "3" * 64
CREATED_AT = "2026-09-23T00:00:00.000000Z"
CITING = str(uuid4())
TARGET = str(uuid4())
OTHER_TARGET = str(uuid4())


def _meta() -> RecordMeta:
    return RecordMeta(1, (), PRODUCER, CONFIG_HASH, CREATED_AT)


def _edge(
    source: str,
    target: str,
    *,
    edge_source: str,
    evidence_hash: str,
    available_at: str = CREATED_AT,
) -> GraphEdge:
    return GraphEdge(
        source_family_id=source,
        target_family_id=target,
        sources=(edge_source,),
        evidence_hashes=(evidence_hash,),
        available_ats=(available_at,),
    )


def test_merges_duplicate_source_and_index_edges_once() -> None:
    """The same family pair observed by both bibliography parsing and an
    OpenAlex capture merges into one edge naming both sources
    (SDD-MD-08)."""

    published: list[GraphManifest] = []
    parsed = (
        _edge(CITING, TARGET, edge_source="bibliography_parse", evidence_hash="a" * 64),
    )
    captured = (
        _edge(CITING, TARGET, edge_source="openalex_capture", evidence_hash="b" * 64),
    )

    manifest = merge_graph_observation(
        parsed_edges=parsed,
        parsed_unmatched_count=0,
        captured_edges=captured,
        prior_manifest=None,
        graph_version=str(uuid4()),
        meta=_meta(),
        store=published.append,
    )

    assert len(manifest.edges) == 1
    edge = manifest.edges[0]
    assert edge.sources == ("bibliography_parse", "openalex_capture")
    assert edge.evidence_hashes == ("a" * 64, "b" * 64)
    assert published == [manifest]


def test_missing_remote_capture_preserves_source_parsed_edges() -> None:
    """An empty ``captured_edges`` (the remote is unavailable this run)
    still publishes the source-parsed edges rather than an invented empty
    complete graph (SDD-MD-08 on-failure)."""

    parsed = (
        _edge(CITING, TARGET, edge_source="bibliography_parse", evidence_hash="a" * 64),
    )

    manifest = merge_graph_observation(
        parsed_edges=parsed,
        parsed_unmatched_count=2,
        captured_edges=(),
        prior_manifest=None,
        graph_version=str(uuid4()),
        meta=_meta(),
        store=lambda _manifest: None,
    )

    assert manifest.edges == parsed
    assert manifest.unmatched_count == 2


def test_a_later_capture_cannot_change_an_old_snapshot() -> None:
    """Publishing again never mutates the prior manifest; it produces a new
    one and records the prior one's hash for lineage (SDD-MD-08)."""

    first_edges = (
        _edge(CITING, TARGET, edge_source="bibliography_parse", evidence_hash="a" * 64),
    )
    first = merge_graph_observation(
        parsed_edges=first_edges,
        parsed_unmatched_count=0,
        captured_edges=(),
        prior_manifest=None,
        graph_version=str(uuid4()),
        meta=_meta(),
        store=lambda _manifest: None,
    )
    original_edges = first.edges

    second_edges = (
        _edge(
            CITING, OTHER_TARGET, edge_source="openalex_capture", evidence_hash="c" * 64
        ),
    )
    second = merge_graph_observation(
        parsed_edges=(),
        parsed_unmatched_count=0,
        captured_edges=second_edges,
        prior_manifest=first,
        graph_version=str(uuid4()),
        meta=_meta(),
        store=lambda _manifest: None,
    )

    assert first.edges == original_edges
    assert second.graph_version != first.graph_version
    assert second.prior_manifest_hash is not None
    assert second.edges != first.edges


def test_edges_are_ordered_by_source_then_target_family_id() -> None:
    lower, higher = sorted((TARGET, OTHER_TARGET))
    parsed = (
        _edge(CITING, higher, edge_source="bibliography_parse", evidence_hash="a" * 64),
        _edge(CITING, lower, edge_source="bibliography_parse", evidence_hash="b" * 64),
    )
    manifest = merge_graph_observation(
        parsed_edges=parsed,
        parsed_unmatched_count=0,
        captured_edges=(),
        prior_manifest=None,
        graph_version=str(uuid4()),
        meta=_meta(),
        store=lambda _manifest: None,
    )
    assert [edge.target_family_id for edge in manifest.edges] == [lower, higher]
