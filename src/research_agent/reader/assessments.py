"""The paper card's separated Jev section, and its versions (RD-15, RD-21).

`assessment_section` turns one committed assessment attempt into the card's
Jev section: eight named fields, or one unavailable record with its reason.
It resolves only a result committed by the card's cutoff and compatible
with the smoke report that snapshot pins; it never checks the current smoke
report to rewrite a historical card. It derives no rank, score or aggregate
from the fields, and nothing here is passed to head feature assembly,
outcome resolution or baseline inputs: the card itself carries only a
reference to the section (`contracts.cards.JevCardAssessment`).

`publish_assessment_version` commits a section as a new immutable artifact
and conditionally advances the current pointer; a snapshot keeps the
section hash it pinned. `section_for_snapshot` reads through that pin and
never falls back to the current pointer.

The reader has no provider route: this module reads stored bytes only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from research_agent.artifacts.store import ArtifactStore
from research_agent.assessments.schemas import (
    JevAttemptRecord,
    JevAvailable,
    JevFieldResult,
    fields_to_dict,
    fields_from_dict,
    result_from_json,
    result_hash,
)
from research_agent.contracts.assessments import (
    FIELD_IDS,
    JEV_SOURCE_LABEL,
    UNAVAILABLE_REASONS,
    JevProviderIdentity,
)
from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.cards import JevCardAssessment
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
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
    "card_reference",
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


@dataclass(frozen=True, slots=True)
class JevCardAvailable:
    """A stored valid result, projected without request, response or billing."""

    assessment_id: str
    fields: tuple[JevFieldResult, ...]
    paper_version_id: str
    extraction_hash: str
    rubric_hash: str
    provider_identity: JevProviderIdentity
    computed_at: str
    qualification_report_hash: str
    status: str = "available"

    def __post_init__(self) -> None:
        if self.status != "available":
            raise ContractValidationError("status must be available")
        validate_sha256(self.assessment_id)
        if tuple(item.field_id for item in self.fields) != FIELD_IDS:
            raise ContractValidationError(
                "fields must be exactly the eight rubric fields"
            )
        validate_uuid4(self.paper_version_id)
        validate_sha256(self.extraction_hash)
        validate_sha256(self.rubric_hash)
        validate_utc_instant(self.computed_at)
        validate_sha256(self.qualification_report_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "assessment_id": self.assessment_id,
            "fields": fields_to_dict(self.fields),
            "paper_version_id": self.paper_version_id,
            "extraction_hash": self.extraction_hash,
            "rubric_hash": self.rubric_hash,
            "provider_identity": self.provider_identity.to_dict(),
            "computed_at": self.computed_at,
            "qualification_report_hash": self.qualification_report_hash,
        }


@dataclass(frozen=True, slots=True)
class JevCardUnavailable:
    """An unavailable section: a reason, never fabricated categories or numbers."""

    reason: str
    rubric_hash: str
    assessment_id: str | None
    status: str = "unavailable"

    def __post_init__(self) -> None:
        if self.status != "unavailable":
            raise ContractValidationError("status must be unavailable")
        if self.reason not in UNAVAILABLE_REASONS:
            raise ContractValidationError(
                "reason is not an admitted unavailable reason"
            )
        validate_sha256(self.rubric_hash)
        if self.assessment_id is not None:
            validate_sha256(self.assessment_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "rubric_hash": self.rubric_hash,
            "assessment_id": self.assessment_id,
        }


@dataclass(frozen=True, slots=True)
class JevCardSection:
    """The card's Jev section, labeled with its source (TDD `JevCardAssessment`)."""

    assessment: JevCardAvailable | JevCardUnavailable
    source_label: str = JEV_SOURCE_LABEL

    def __post_init__(self) -> None:
        if self.source_label != JEV_SOURCE_LABEL:
            raise ContractValidationError("source_label must be the fixed label")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment": self.assessment.to_dict(),
            "source_label": self.source_label,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @property
    def section_hash(self) -> str:
        return sha256_hex(self.to_canonical_json())

    @classmethod
    def from_json(cls, raw: bytes) -> "JevCardSection":
        try:
            loaded = canonical_loads(raw)
        except CanonicalJsonError as error:
            raise ContractValidationError(str(error)) from error
        if not isinstance(loaded, dict) or set(loaded) != {
            "assessment",
            "source_label",
        }:
            raise ContractValidationError("JevCardSection keys differ")
        value: dict[str, Any] = loaded
        if not isinstance(value["assessment"], dict):
            raise ContractValidationError("assessment must be an object")
        body: dict[str, Any] = value["assessment"]
        if body.get("status") == "available":
            if set(body) != set(JevCardAvailable.__slots__):
                raise ContractValidationError("JevCardAvailable keys differ")
            assessment: JevCardAvailable | JevCardUnavailable = JevCardAvailable(
                assessment_id=body["assessment_id"],
                fields=fields_from_dict(body["fields"]),
                paper_version_id=body["paper_version_id"],
                extraction_hash=body["extraction_hash"],
                rubric_hash=body["rubric_hash"],
                provider_identity=JevProviderIdentity.from_dict(
                    body["provider_identity"]
                ),
                computed_at=body["computed_at"],
                qualification_report_hash=body["qualification_report_hash"],
            )
        else:
            if set(body) != set(JevCardUnavailable.__slots__):
                raise ContractValidationError("JevCardUnavailable keys differ")
            assessment = JevCardUnavailable(**body)
        return cls(assessment, value["source_label"])


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
            provider_identity=stored.provider_identity,
            computed_at=stored.computed_at,
            qualification_report_hash=snapshot_smoke_report_hash,
        )
    )


def card_reference(section: JevCardSection) -> JevCardAssessment:
    """The card's reference to its section: the section hash, or the reason."""

    if isinstance(section.assessment, JevCardAvailable):
        return JevCardAssessment.available(section.section_hash)
    return JevCardAssessment.unavailable(section.assessment.reason)


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
        f"Rubric: {assessment.rubric_hash}",
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
