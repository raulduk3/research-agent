"""Typed citation diagnostics, kept separate from label observations
(EN-17 to EN-23).

``CitationDiagnostic`` reports a family's current graph-derived counts;
``disabled_diagnostic`` reports the fixed unavailable view for the six
launch-disabled social/provider adapters. Both carry the ``card_diagnostic``
artifact role, distinct from ``label_observation`` (contracts.learning), so
a caller that mistakes one for the other is rejected by type rather than
by a runtime string comparison the caller could skip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.cards import AvailabilityValue
from research_agent.contracts.graph import GraphManifest
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

ARTIFACT_ROLE = "card_diagnostic"

# The reserved provenance shape of each launch-disabled diagnostic (EN-18 to
# EN-23): documented field names only. No adapter reads or backfills them;
# enabling one requires its own source-capability and retention review
# under IN-25, not a flag flip here.
DISABLED_DIAGNOSTIC_KINDS: dict[str, tuple[str, ...]] = {
    "citation_intent": (
        "provider_method",
        "annotation_availability",
        "source_evidence",
    ),
    "repository_forks": (
        "repository_attribution",
        "fork_count",
        "captured_at",
    ),
    "linked_artifact": (
        "paper_declared_link",
        "artifact_identity",
        "source_text_locator",
    ),
    "artifact_upvotes": (
        "source_page_identity",
        "observed_count",
        "captured_at",
    ),
    "repository_stars": (
        "repository_attribution",
        "count_or_event_series",
        "captured_at",
    ),
    "discussion_mentions": (
        "matched_item_ids",
        "dates",
        "paper_link_attribution",
    ),
}


@dataclass(frozen=True, slots=True)
class CitationDiagnostic:
    """A paper family's current graph-derived citation counts (EN-17, TDD-3.1.18).

    Descriptive only: a current count here cannot settle a time-windowed
    outcome label. Only the frozen observation protocol in Appendix B does
    that.
    """

    artifact_role: str
    family_id: str
    graph_manifest_hash: str
    captured_at: str
    incoming_count: AvailabilityValue
    outgoing_count: AvailabilityValue

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "artifact_role",
            "family_id",
            "graph_manifest_hash",
            "captured_at",
            "incoming_count",
            "outgoing_count",
        }
    )

    def __post_init__(self) -> None:
        if self.artifact_role != ARTIFACT_ROLE:
            raise ContractValidationError("citation diagnostic artifact role is fixed")
        validate_uuid4(self.family_id)
        validate_sha256(self.graph_manifest_hash)
        validate_utc_instant(self.captured_at)
        for count in (self.incoming_count, self.outgoing_count):
            if not isinstance(count, AvailabilityValue):
                raise ContractValidationError(
                    "citation counts must be AvailabilityValue"
                )
            if count.status == "available" and (
                not isinstance(count.value, int) or count.value < 0
            ):
                raise ContractValidationError(
                    "an available citation count must be a non-negative integer"
                )


def build_citation_diagnostic(
    manifest: GraphManifest, *, family_id: str, captured_at: str
) -> CitationDiagnostic:
    """Compute one family's current incoming/outgoing counts from a graph manifest.

    A published manifest never repeats a ``(source, target)`` pair, but a
    caller that assembled edges from more than one manifest could hand
    this duplicate citing or cited ids; resolve those duplicates to unique
    families before computing the descriptive totals (TDD-3.1.18).
    """

    validate_uuid4(family_id)
    incoming = {
        edge.source_family_id
        for edge in manifest.edges
        if edge.target_family_id == family_id
    }
    outgoing = {
        edge.target_family_id
        for edge in manifest.edges
        if edge.source_family_id == family_id
    }
    return CitationDiagnostic(
        artifact_role=ARTIFACT_ROLE,
        family_id=family_id,
        graph_manifest_hash=sha256_hex(manifest.to_canonical_json()),
        captured_at=captured_at,
        incoming_count=AvailabilityValue.available(len(incoming)),
        outgoing_count=AvailabilityValue.available(len(outgoing)),
    )


@dataclass(frozen=True, slots=True)
class DisabledDiagnostic:
    """The fixed unavailable view for a launch-disabled diagnostic adapter
    (EN-18 to EN-23, TDD-3.1.19 to TDD-3.1.24).
    """

    artifact_role: str
    kind: str
    status: str
    reason: str
    reserved_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.artifact_role != ARTIFACT_ROLE:
            raise ContractValidationError("disabled diagnostic artifact role is fixed")
        if self.kind not in DISABLED_DIAGNOSTIC_KINDS:
            raise ContractValidationError("diagnostic kind is not admitted")
        if self.status != "unavailable" or self.reason != "disabled_by_profile":
            raise ContractValidationError(
                "a disabled diagnostic must be unavailable by profile"
            )
        if self.reserved_fields != DISABLED_DIAGNOSTIC_KINDS[self.kind]:
            raise ContractValidationError(
                "reserved provenance fields disagree with the diagnostic kind"
            )


def disabled_diagnostic(kind: str) -> DisabledDiagnostic:
    """Return the fixed unavailable view for one launch-disabled diagnostic.

    The launch adapter registry has no enabled job for any of these six
    kinds, so this refuses the same way for every call naming an admitted
    kind: no network client runs, no historical backfill runs and no zero
    is substituted for the missing count.
    """

    if kind not in DISABLED_DIAGNOSTIC_KINDS:
        raise ContractValidationError("diagnostic kind is not admitted")
    return DisabledDiagnostic(
        artifact_role=ARTIFACT_ROLE,
        kind=kind,
        status="unavailable",
        reason="disabled_by_profile",
        reserved_fields=DISABLED_DIAGNOSTIC_KINDS[kind],
    )
