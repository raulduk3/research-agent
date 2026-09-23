"""Launch readiness for the Jev layer (SDD RD-24, TDD-4.1.62).

`check_assessment_readiness` reads the dated evidence records and returns a
typed record naming every unmet gate; it supplies no default for a missing
item and raises for none. Study activation needs an empty gate list. The
collection mode makes no paid model call and stays allowed regardless, so a
failed gate blocks only the layer. Immature forecast outcomes are not a gate:
the registration permits launch before the comparison matures.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts.assessments import JevProviderIdentity, JevRubric
from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.evaluation.registrations import (
    ComparisonRegistration,
    admit_execution,
)
from research_agent.measurement import MeasurementError
from research_agent.measurement.jev import (
    SmokeActivationRefused,
    SmokeReport,
    check_smoke_activation,
    validate_benefit_registration,
)

__all__ = [
    "READINESS_GATES",
    "EvidenceRef",
    "ReadinessEvidence",
    "ReadinessRecord",
    "ReadinessRefused",
    "check_assessment_readiness",
]

#: Every gate RD-24 names, in the order the record reports them.
READINESS_GATES = (
    "provider_access",
    "retention_permission",
    "identity_semantics",
    "input_limits",
    "corpus_input_coverage",
    "operating_profile",
    "rubric_pin",
    "smoke_test",
    "registration",
)


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One dated evidence record, referenced by its content hash."""

    evidence_hash: str
    recorded_at: str

    def __post_init__(self) -> None:
        validate_sha256(self.evidence_hash)
        validate_utc_instant(self.recorded_at)


@dataclass(frozen=True, slots=True)
class ReadinessEvidence:
    """Everything the record may cite; ``None`` is an item not yet evidenced.

    ``operating_profile`` is the funded profile: timeouts, retries and cost
    ceilings. ``rubric_pin`` is the rubric hash fixed at activation.
    ``registration_watermark_at`` is the storage watermark at which the RD-23
    registration was read back.
    """

    provider_access: EvidenceRef | None
    retention_permission: EvidenceRef | None
    identity_semantics: EvidenceRef | None
    input_limits: EvidenceRef | None
    corpus_input_coverage: EvidenceRef | None
    operating_profile: EvidenceRef | None
    rubric_pin: str | None
    smoke_report: SmokeReport | None
    registration: ComparisonRegistration | None
    registration_watermark_at: str | None


@dataclass(frozen=True, slots=True)
class ReadinessRecord:
    """The readiness record: failed gates, the modes they permit and its links."""

    checked_at: str
    rubric_hash: str
    provider_configuration_hash: str
    failed_gates: tuple[tuple[str, str], ...]
    evidence_hashes: tuple[tuple[str, str], ...]

    @property
    def collection_allowed(self) -> bool:
        return True

    @property
    def study_activation_allowed(self) -> bool:
        return not self.failed_gates

    def record_hash(self) -> str:
        return sha256_hex(
            canonical_json(
                {
                    "checked_at": self.checked_at,
                    "rubric_hash": self.rubric_hash,
                    "provider_configuration_hash": self.provider_configuration_hash,
                    "failed_gates": [list(item) for item in self.failed_gates],
                    "evidence_hashes": [list(item) for item in self.evidence_hashes],
                }
            )
        )

    def require_study_activation(self) -> str:
        """Return the record hash a launch may cite, or refuse naming each gate."""

        if self.failed_gates:
            raise ReadinessRefused(self.failed_gates)
        return self.record_hash()


class ReadinessRefused(Exception):
    """Study activation is refused; ``gates`` pairs each unmet gate with its reason."""

    def __init__(self, gates: tuple[tuple[str, str], ...]) -> None:
        super().__init__(
            "assessment readiness is unmet: " + ", ".join(name for name, _ in gates)
        )
        self.gates = gates


def check_assessment_readiness(
    evidence: ReadinessEvidence,
    *,
    rubric: JevRubric,
    provider_identity: JevProviderIdentity,
    checked_at: str,
) -> ReadinessRecord:
    """Check every RD-24 gate for the active rubric and provider identity.

    Evidence dated after ``checked_at`` does not count. The smoke test must
    pass for this rubric and identity with its owner review; the registration
    must be the Jev benefit study's, and must precede the storage watermark
    it was read back at, which itself must not follow ``checked_at``.
    """

    checked = validate_utc_instant(checked_at)
    failed: list[tuple[str, str]] = []
    hashes: list[tuple[str, str]] = []

    def dated(gate: str, ref: EvidenceRef | None) -> None:
        if ref is None:
            failed.append((gate, "missing"))
        elif ref.recorded_at > checked:
            failed.append((gate, "dated_after_check"))
        else:
            hashes.append((gate, ref.evidence_hash))

    dated("provider_access", evidence.provider_access)
    dated("retention_permission", evidence.retention_permission)
    dated("identity_semantics", evidence.identity_semantics)
    dated("input_limits", evidence.input_limits)
    dated("corpus_input_coverage", evidence.corpus_input_coverage)
    dated("operating_profile", evidence.operating_profile)

    if evidence.rubric_pin is None:
        failed.append(("rubric_pin", "missing"))
    elif evidence.rubric_pin != rubric.rubric_hash:
        failed.append(("rubric_pin", "rubric_changed"))
    else:
        hashes.append(("rubric_pin", evidence.rubric_pin))

    try:
        hashes.append(
            (
                "smoke_test",
                check_smoke_activation(
                    evidence.smoke_report,
                    rubric_hash=rubric.rubric_hash,
                    provider_identity=provider_identity,
                ),
            )
        )
    except SmokeActivationRefused as refused:
        failed.append(("smoke_test", ",".join(refused.reasons)))

    failed_registration = _registration_failure(evidence, checked)
    if failed_registration is not None:
        failed.append(("registration", failed_registration))
    elif evidence.registration is not None:
        hashes.append(("registration", evidence.registration.registration_id))

    return ReadinessRecord(
        checked_at=checked,
        rubric_hash=rubric.rubric_hash,
        provider_configuration_hash=provider_identity.configuration_hash,
        failed_gates=tuple(failed),
        evidence_hashes=tuple(hashes),
    )


def _registration_failure(evidence: ReadinessEvidence, checked: str) -> str | None:
    registration = evidence.registration
    watermark = evidence.registration_watermark_at
    if registration is None or watermark is None:
        return "missing"
    if validate_utc_instant(watermark) > checked:
        return "dated_after_check"
    try:
        validate_benefit_registration(registration)
    except MeasurementError:
        return "not_the_benefit_registration"
    try:
        admit_execution(registration, execution_at=watermark)
    except ContractValidationError:
        return "not_recorded_at_watermark"
    return None
