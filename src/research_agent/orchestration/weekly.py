"""The weekly stage: refresh, evaluate and activate, in order (SDD FT-16).

One freeze watermark and one weekly id make the stage idempotent: fitting
and calibration are pure functions of already-frozen partitions
(:mod:`research_agent.learning.heads`), scoring and selection reuse the
existing promotion comparison (:mod:`research_agent.learning.promote`), and
activation is the same atomic pointer swap every other promotion uses
(:mod:`research_agent.models.registry`). A candidate that fails scoring, or
a target with insufficient labels, is not a stage failure: its bundle entry
carries the incumbent's qualified artifact forward unchanged, and scoring
and reporting still run against it (SDD FT-16: "allow scoring and reporting
with the incumbent"). Only a corrupt source artifact or a ledger-integrity
failure stops the stage -- surfaced by letting the underlying storage
exception propagate, never swallowed into a partial disposition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

from research_agent.contracts import (
    ProducerVersion,
    canonical_json,
    sha256_hex,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.contracts.learning import TARGET_IDS, TargetDefinition
from research_agent.learning.fit import MaterializedPartition
from research_agent.learning.heads import (
    CalibratedHead,
    HeadUnavailable,
    ThreeHeadCalibration,
)
from research_agent.learning.promote import (
    HeldOutEvaluation,
    PromotionDecision,
    promote_three_heads,
)
from research_agent.measurement.heads import (
    EvaluationReport,
    MatchedPrediction,
    evaluate_predictions,
)
from research_agent.models.registry import (
    ActivationResult,
    BundleManifest,
    BundleTargetEntry,
    PublishedHead,
    ServingHandle,
    activate_bundle,
    publish_head,
)
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database

_MAXIMUM_DISPOSITION_BYTES = 1024 * 1024
_RETENTION_POLICY = (
    b"Weekly disposition records are retained privately for this research "
    b"and are not redistributed."
)
_RETENTION_POLICY_HASH = sha256_hex(_RETENTION_POLICY)

IncumbentEvaluations = tuple[
    HeldOutEvaluation | None, HeldOutEvaluation | None, HeldOutEvaluation | None
]


class WeeklyStageError(ValueError):
    """A weekly stage's inputs or resulting disposition are not admissible."""


def _decision_dict(decision: PromotionDecision) -> dict[str, Any]:
    evaluation = decision.evaluation
    return {
        "target_id": decision.target_id,
        "promoted": decision.promoted,
        "reason": decision.reason,
        "candidate_brier": None if evaluation is None else evaluation.candidate_brier,
        "baseline_brier": None if evaluation is None else evaluation.baseline_brier,
        "support_count": None if evaluation is None else evaluation.support_count,
    }


@dataclass(frozen=True, slots=True)
class WeeklyDisposition:
    """The one record a weekly stage run leaves: per-target decision plus outcome."""

    weekly_id: str
    freeze_watermark: str
    decisions: tuple[PromotionDecision, PromotionDecision, PromotionDecision]
    bundle_hash: str
    bundle_generation: int
    evaluation_report_hash: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.weekly_id)
        validate_utc_instant(self.freeze_watermark)
        if tuple(item.target_id for item in self.decisions) != TARGET_IDS:
            raise WeeklyStageError(
                "weekly disposition must cover the registry in order"
            )
        validate_sha256(self.bundle_hash)
        validate_sha256(self.evaluation_report_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "weekly_id": self.weekly_id,
            "freeze_watermark": self.freeze_watermark,
            "decisions": [_decision_dict(item) for item in self.decisions],
            "bundle_hash": self.bundle_hash,
            "bundle_generation": self.bundle_generation,
            "evaluation_report_hash": self.evaluation_report_hash,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())


def _entry_for(
    target_id: str,
    definition_hash: str,
    decision: PromotionDecision,
    calibrated: CalibratedHead | HeadUnavailable,
    incumbent: BundleManifest | None,
    *,
    artifacts: ArtifactRepository,
    producer_version: ProducerVersion,
) -> BundleTargetEntry:
    if decision.promoted:
        if not isinstance(calibrated, CalibratedHead):
            raise WeeklyStageError("a promoted decision requires its calibrated head")
        published = PublishedHead.from_calibrated(calibrated)
        artifact_hash = publish_head(
            artifacts, published, producer_version=producer_version
        )
        return BundleTargetEntry(
            target_id, definition_hash, "qualified", artifact_hash, None
        )
    if incumbent is not None:
        prior = incumbent.entry_for(target_id)
        if prior.status == "qualified":
            return prior
    return BundleTargetEntry(
        target_id, definition_hash, "unavailable", None, decision.reason
    )


def run_week(
    database: Database,
    artifacts: ArtifactRepository,
    *,
    weekly_id: str,
    freeze_watermark: str,
    calibration: ThreeHeadCalibration,
    fit: MaterializedPartition,
    development: MaterializedPartition,
    definitions: tuple[TargetDefinition, TargetDefinition, TargetDefinition],
    incumbent_handle: ServingHandle | None,
    incumbent_evaluations: IncumbentEvaluations,
    matches: tuple[MatchedPrediction, ...],
    baselines: dict[str, float],
    producer_version: ProducerVersion,
    target_registry_hash: str,
    representation_hash: str,
    command_id: UUID | None = None,
) -> WeeklyDisposition:
    """Run refresh, evaluation and activation, in that order, and record one disposition.

    ``fit``/``development`` and ``calibration`` are the already-frozen
    candidate: this stage never itself draws a fresh sample from committed
    inputs (a batch job's concern), only scores what it is given against
    the incumbent and decides promotion.
    """

    validate_non_empty_string(weekly_id)
    validate_utc_instant(freeze_watermark)
    if tuple(item.target_id for item in definitions) != TARGET_IDS:
        raise WeeklyStageError("target definitions must cover the registry in order")

    decisions = promote_three_heads(
        calibration, fit, development, incumbent_evaluations
    )
    incumbent_manifest = None if incumbent_handle is None else incumbent_handle.manifest

    entries = tuple(
        _entry_for(
            definition.target_id,
            sha256_hex(definition.to_canonical_json()),
            decision,
            calibrated,
            incumbent_manifest,
            artifacts=artifacts,
            producer_version=producer_version,
        )
        for definition, decision, calibrated in zip(
            definitions, decisions, calibration.calibrated, strict=True
        )
    )
    manifest = BundleManifest(
        target_registry_hash,
        representation_hash,
        entries,
        producer_version,
        freeze_watermark,
    )

    command_id = command_id or uuid4()
    activation: ActivationResult = activate_bundle(
        database, artifacts, manifest, command_id=command_id
    )

    report: EvaluationReport = evaluate_predictions(matches, baselines)
    report_payload = canonical_json(
        {
            "evaluations": [
                {
                    "target_id": item.target_id,
                    "evaluation_kind": item.evaluation_kind,
                    "status": item.status,
                    "reason": item.reason,
                    "support_count": item.support_count,
                    "brier_score": item.brier_score,
                    "baseline_brier": item.baseline_brier,
                    "base_rate_skill": item.base_rate_skill,
                    "average_precision": item.average_precision,
                    "bundle_hashes": list(item.bundle_hashes),
                }
                for item in report.evaluations
            ]
        }
    )
    report_hash = sha256_hex(report_payload)
    artifacts.publish(
        [report_payload],
        expected_hash=report_hash,
        byte_length=len(report_payload),
        maximum_length=_MAXIMUM_DISPOSITION_BYTES,
        media_type="application/json",
        kind="manifest",
        input_hashes=(activation.bundle_hash,),
        producer_version=producer_version,
        config_hash=target_registry_hash,
        retention_policy_hash=_RETENTION_POLICY_HASH,
        command_id=command_id,
    )

    disposition = WeeklyDisposition(
        weekly_id,
        freeze_watermark,
        cast(
            "tuple[PromotionDecision, PromotionDecision, PromotionDecision]", decisions
        ),
        activation.bundle_hash,
        activation.generation,
        report_hash,
    )
    disposition_payload = disposition.to_canonical_json()
    disposition_hash = sha256_hex(disposition_payload)
    artifacts.publish(
        [disposition_payload],
        expected_hash=disposition_hash,
        byte_length=len(disposition_payload),
        maximum_length=_MAXIMUM_DISPOSITION_BYTES,
        media_type="application/json",
        kind="manifest",
        input_hashes=(activation.bundle_hash, report_hash),
        producer_version=producer_version,
        config_hash=target_registry_hash,
        retention_policy_hash=_RETENTION_POLICY_HASH,
        command_id=command_id,
    )
    return disposition
