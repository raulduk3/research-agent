"""The paper card's separated Jev section, and its versions (RD-15, RD-21).

`assessment_section` turns one committed assessment attempt into the card's
Jev section: eight named fields, or one unavailable record with its reason.
It resolves only a result committed by the card's cutoff and compatible
with the smoke report that snapshot pins; it never checks the current smoke
report to rewrite a historical card. It derives no rank, score or aggregate
from the fields, and nothing here is passed to head feature assembly,
outcome resolution or baseline inputs: the card itself carries only a
section inline (`contracts.cards.JevCardAssessment`), and the fields stay
separate from every derived input.

`publish_assessment_version` commits a section as a new immutable artifact
and conditionally advances the current pointer; a snapshot keeps the
section hash it pinned. `section_for_snapshot` reads through that pin and
never falls back to the current pointer.

The reader has no provider route: this module reads stored bytes only.
"""

from __future__ import annotations

from typing import Protocol

from research_agent.artifacts.store import ArtifactStore
from research_agent.assessments.schemas import (
    JevAttemptRecord,
    JevAvailable,
    result_from_json,
    result_hash,
)
from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.cards import (
    JevCardAssessment,
    JevCardAvailable,
    JevCardUnavailable,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_utc_instant,
)

__all__ = [
    "UNQUALIFIED_NOTE",
    "LaterAssessment",
    "StaleCurrentPointer",
    "JevCardAvailable",
    "JevCardUnavailable",
    "JevCardSection",
    "AssessmentPointers",
    "assessment_section",
    "render_section",
    "publish_assessment_version",
    "section_for_snapshot",
]

#: RD-15 and RD-22: every Jev field is shown as unqualified.
UNQUALIFIED_NOTE = "Unqualified: not measured against human labels."
_MAX_SECTION_BYTES = 1024 * 1024


class LaterAssessment(Exception):
    """A result committed after the card's cutoff cannot enter that snapshot."""


class StaleCurrentPointer(Exception):
    """The current section pointer moved; the caller re-reads and retries."""


#: The card carries the section inline (TDD `JevCardAssessment`).
JevCardSection = JevCardAssessment


def assessment_section(
    *,
    manifest: bytes | None,
    result: bytes | None,
    available_at: str | None,
    paper_version_id: str,
    extraction_hash: str,
    as_of: str,
    snapshot_smoke_report_hash: str | None,
    rubric_hash: str,
) -> JevCardSection:
    """Resolve the Jev section for a card at `as_of` (TDD-4.1.53).

    `manifest`, `result` and `available_at` are the committed attempt, its
    result artifact and storage's commit time; all three are `None` when
    nothing was committed for the card's paper. A result committed after
    `as_of`, or for another paper version or extraction, is refused. An
    available result enters the card only when the snapshot pins a smoke
    report and the result was produced under that same report; otherwise
    the section says `smoke_test_required`.
    """

    validate_utc_instant(as_of)
    if manifest is None:
        return JevCardSection(JevCardUnavailable("missing_input", rubric_hash, None))
    if result is None or available_at is None:
        raise ContractValidationError("a committed attempt needs its result and time")
    validate_utc_instant(available_at)
    if available_at > as_of:
        raise LaterAssessment("assessment committed after the card's cutoff")
    record = JevAttemptRecord.from_json(manifest)
    stored = result_from_json(result)
    if result_hash(stored) != record.result_artifact_hash:
        raise ContractValidationError("result bytes do not match their manifest")
    if (
        record.input.paper_version_id != paper_version_id
        or record.input.extraction_hash != extraction_hash
    ):
        raise ContractValidationError(
            "assessment belongs to another paper or extraction"
        )
    assessment_id = record.result_artifact_hash
    if not isinstance(stored, JevAvailable):
        return JevCardSection(
            JevCardUnavailable(stored.reason, stored.rubric_hash, assessment_id)
        )
    if (
        snapshot_smoke_report_hash is None
        or stored.smoke_report_hash != snapshot_smoke_report_hash
    ):
        return JevCardSection(
            JevCardUnavailable("smoke_test_required", stored.rubric_hash, assessment_id)
        )
    return JevCardSection(
        JevCardAvailable(
            assessment_id=assessment_id,
            fields=stored.fields,
            paper_version_id=paper_version_id,
            extraction_hash=extraction_hash,
            rubric_hash=stored.rubric_hash,
            rubric_version=record.rubric_version,
            provider_identity=stored.provider_identity,
            computed_at=stored.computed_at,
            qualification_report_hash=snapshot_smoke_report_hash,
        )
    )


def render_section(section: JevCardSection) -> str:
    """Fixed text for the section: source, provenance, fields, unqualified note."""

    lines = [f"Source: {section.source_label}", UNQUALIFIED_NOTE]
    assessment = section.assessment
    if isinstance(assessment, JevCardUnavailable):
        lines.append(f"Status: unavailable ({assessment.reason})")
        lines.append(f"Rubric: {assessment.rubric_hash}")
        return "\n".join(lines)
    identity = assessment.provider_identity
    lines += [
        "Status: available",
        f"Rubric: {assessment.rubric_version} ({assessment.rubric_hash})",
        f"Model: {identity.returned_model_identity or identity.configured_model_alias}"
        f" ({identity.identity_kind})",
        f"Computed: {assessment.computed_at}",
        f"Smoke report: {assessment.qualification_report_hash}",
    ]
    for item in assessment.fields:
        distribution = ", ".join(
            f"{entry.category_id}={entry.probability:.3f}"
            for entry in item.distribution
        )
        confidence = (
            "not returned"
            if item.provider_confidence is None
            else f"{item.provider_confidence:.3f}"
        )
        lines.append(
            f"{item.field_id}: {item.selected_category} "
            f"[{distribution}] confidence {confidence}"
        )
    return "\n".join(lines)


class AssessmentPointers(Protocol):
    """Storage's current-section pointer and snapshot pins for one paper version."""

    def current(self, paper_version_id: str) -> str | None: ...

    def compare_and_swap(
        self, paper_version_id: str, expected: str | None, new: str
    ) -> bool: ...

    def snapshot_pin(self, snapshot_id: str, paper_version_id: str) -> str | None: ...


def publish_assessment_version(
    artifacts: ArtifactStore,
    pointers: AssessmentPointers,
    *,
    paper_version_id: str,
    section: JevCardSection,
    expected_current: str | None,
) -> str:
    """Commit `section` immutably, then advance the current pointer (TDD-4.1.59).

    The artifact is content-addressed, so a referenced section's bytes can
    never be replaced; the pointer moves only from `expected_current`, and
    snapshots keep whichever hash they already pinned.
    """

    raw = section.to_canonical_json()
    section_hash = sha256_hex(raw)
    artifacts.commit(
        (raw,),
        expected_hash=section_hash,
        expected_length=len(raw),
        maximum_length=_MAX_SECTION_BYTES,
    )
    if not pointers.compare_and_swap(paper_version_id, expected_current, section_hash):
        raise StaleCurrentPointer(paper_version_id)
    return section_hash


def section_for_snapshot(
    artifacts: ArtifactStore,
    pointers: AssessmentPointers,
    *,
    snapshot_id: str,
    paper_version_id: str,
) -> JevCardSection:
    """The section the snapshot pinned; never the current or latest one."""

    pinned = pointers.snapshot_pin(snapshot_id, paper_version_id)
    if pinned is None:
        raise LookupError("the snapshot pins no Jev section for this paper")
    with artifacts.open_verified(pinned) as stream:
        return JevCardSection.from_json(stream.read())
