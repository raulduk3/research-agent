from __future__ import annotations

from uuid import uuid4

import pytest

from research_agent.contracts import ProducerVersion, RecordMeta, sha256_hex
from research_agent.contracts.cards import AvailabilityValue
from research_agent.contracts.graph import GraphEdge, GraphManifest
from research_agent.contracts.learning import AutomaticLabel, CountBounds, LabelCounts
from research_agent.contracts.primitives import ContractValidationError
from research_agent.papers.diagnostics import (
    CitationDiagnostic,
    build_citation_diagnostic,
)

PRODUCER = ProducerVersion("1" * 64, "2" * 40, 1)
CONFIG_HASH = "3" * 64
CREATED_AT = "2026-09-23T00:00:00.000000Z"
FAMILY = str(uuid4())
CITER_ONE = str(uuid4())
CITER_TWO = str(uuid4())
CITED_ONE = str(uuid4())
_BOUNDS = CountBounds(0, None)
_COUNTS = LabelCounts(_BOUNDS, _BOUNDS, _BOUNDS, _BOUNDS)


def _meta() -> RecordMeta:
    return RecordMeta(1, (), PRODUCER, CONFIG_HASH, CREATED_AT)


def _edge(source: str, target: str, evidence_hash: str) -> GraphEdge:
    return GraphEdge(
        source_family_id=source,
        target_family_id=target,
        sources=("openalex_capture",),
        evidence_hashes=(evidence_hash,),
        available_ats=(CREATED_AT,),
    )


def _manifest(edges: tuple[GraphEdge, ...]) -> GraphManifest:
    ordered = tuple(
        sorted(edges, key=lambda edge: (edge.source_family_id, edge.target_family_id))
    )
    return GraphManifest(
        schema_version=1,
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash=CONFIG_HASH,
        created_at=CREATED_AT,
        graph_version=str(uuid4()),
        edges=ordered,
        unmatched_count=0,
        prior_manifest_hash=None,
    )


def _label() -> AutomaticLabel:
    return AutomaticLabel(
        schema_version=1,
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash=CONFIG_HASH,
        created_at=CREATED_AT,
        paper_family_id=FAMILY,
        target_id="citation_reach_365d",
        target_definition_hash="d" * 64,
        state="unknown",
        reason="immature",
        observation_hash="e" * 64,
        counts=_COUNTS,
        witness_family_ids=(),
        witness_subfield_ids=(),
        completion_page_hashes=(),
        maturity_at=CREATED_AT,
        resolved_at=CREATED_AT,
        supersedes_label_hash=None,
        correction_hash=None,
    )


def test_diagnostic_reports_incoming_and_outgoing_counts_with_availability() -> None:
    manifest = _manifest(
        (
            _edge(CITER_ONE, FAMILY, "a" * 64),
            _edge(CITER_TWO, FAMILY, "b" * 64),
            _edge(FAMILY, CITED_ONE, "c" * 64),
        )
    )
    diagnostic = build_citation_diagnostic(
        manifest, family_id=FAMILY, captured_at=CREATED_AT
    )
    assert diagnostic.artifact_role == "card_diagnostic"
    assert diagnostic.incoming_count == AvailabilityValue.available(2)
    assert diagnostic.outgoing_count == AvailabilityValue.available(1)
    assert diagnostic.graph_manifest_hash == sha256_hex(manifest.to_canonical_json())


def test_diagnostic_artifact_role_is_distinct_from_a_label_observation() -> None:
    manifest = _manifest(())
    diagnostic = build_citation_diagnostic(
        manifest, family_id=FAMILY, captured_at=CREATED_AT
    )
    label = _label()
    assert diagnostic.artifact_role != "label_observation"
    assert not isinstance(diagnostic, type(label))
    assert not isinstance(label, CitationDiagnostic)


def test_changing_a_current_graph_count_does_not_touch_preserved_label_bytes() -> None:
    """A diagnostic is descriptive only: recomputing it from manifests with
    different current counts never reads or changes an already-resolved
    label's preserved bytes (EN-17, TDD-3.1.18)."""

    label = _label()
    before = label.to_canonical_json()

    small = _manifest((_edge(CITER_ONE, FAMILY, "a" * 64),))
    large = _manifest(
        (_edge(CITER_ONE, FAMILY, "a" * 64), _edge(CITER_TWO, FAMILY, "b" * 64))
    )
    first = build_citation_diagnostic(small, family_id=FAMILY, captured_at=CREATED_AT)
    second = build_citation_diagnostic(large, family_id=FAMILY, captured_at=CREATED_AT)

    assert first.incoming_count != second.incoming_count
    assert label.to_canonical_json() == before


def test_citation_diagnostic_requires_available_value_counts() -> None:
    with pytest.raises(ContractValidationError):
        CitationDiagnostic(
            artifact_role="card_diagnostic",
            family_id=FAMILY,
            graph_manifest_hash="a" * 64,
            captured_at=CREATED_AT,
            incoming_count=3,  # type: ignore[arg-type]
            outgoing_count=AvailabilityValue.available(0),
        )


def test_citation_diagnostic_rejects_a_foreign_artifact_role() -> None:
    with pytest.raises(ContractValidationError):
        CitationDiagnostic(
            artifact_role="label_observation",
            family_id=FAMILY,
            graph_manifest_hash="a" * 64,
            captured_at=CREATED_AT,
            incoming_count=AvailabilityValue.available(0),
            outgoing_count=AvailabilityValue.available(0),
        )
