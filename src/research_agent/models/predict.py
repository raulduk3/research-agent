"""Three named prediction-head outputs from one pinned bundle (SDD RD-08).

Evaluates each qualified head of a :class:`~research_agent.models.registry.ServingHandle`
in registry order, over the caller's already-assembled ``[2d+m]`` head-input
vector (:func:`research_agent.learning.features.apply_head_input`). A request
naming a representation namespace other than the pinned bundle's is refused
before any head is evaluated, rather than silently mixing representations.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from research_agent.contracts import (
    canonical_json,
    canonical_loads,
    sha256_hex,
    validate_finite,
    validate_probability,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.contracts.learning import (
    EMBEDDING_FEATURE_DIMENSION,
    METADATA_DIMENSION,
    PRIMARY_CATEGORY_IDS,
    TARGET_IDS,
    TargetDefinition,
)
from research_agent.learning.features import apply_head_input
from research_agent.models.registry import PublishedHead, ServingHandle

_PRIMARY_CATEGORY_OFFSET = 2


class PredictError(ValueError):
    """A prediction request or artifact is not admissible."""


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _primary_category(metadata_block: tuple[float, ...]) -> str | None:
    """The paper's primary category, read from the metadata block's one-hot.

    The closed block order (#149 Appendix B) puts the one-hot after the
    author count and the listed-category count; calibration reads the same
    columns, so serving picks the calibrator fitted for the paper's own
    category. ``None`` means a category outside the four calibrated ones.
    """

    one_hot = metadata_block[
        _PRIMARY_CATEGORY_OFFSET : _PRIMARY_CATEGORY_OFFSET + len(PRIMARY_CATEGORY_IDS)
    ]
    if any(value not in (0.0, 1.0) for value in one_hot) or sum(one_hot) > 1.0:
        raise PredictError("metadata block primary category is not a one-hot")
    return PRIMARY_CATEGORY_IDS[one_hot.index(1.0)] if 1.0 in one_hot else None


@dataclass(frozen=True, slots=True)
class PredictionArtifact:
    """One target's full served prediction, raw logit and all (SDD TDD-1.1.22).

    Persisted in full so lineage is auditable; only :meth:`public` -- never
    this record itself -- may reach a paper card or an agent/rater
    projection (SDD RD-08 Limits: "no raw vector coordinates or composite
    quality score go to the agent").
    """

    target_id: str
    target_definition_hash: str
    question: str
    original_version_id: str
    bundle_hash: str
    representation_hash: str
    status: str
    reason: str | None
    raw_logit: float | None
    probability: float | None
    input_hash: str
    computed_at: str
    available_at: str

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise PredictError("prediction artifact names an unregistered target")
        validate_sha256(self.target_definition_hash)
        if not self.question:
            raise PredictError(
                "prediction artifact requires its plain-language question"
            )
        validate_uuid4(self.original_version_id)
        validate_sha256(self.bundle_hash)
        validate_sha256(self.representation_hash)
        validate_sha256(self.input_hash)
        validate_utc_instant(self.computed_at)
        if validate_utc_instant(self.available_at) < self.computed_at:
            raise PredictError("prediction artifact availability precedes computation")
        if self.status == "available":
            if (
                self.raw_logit is None
                or self.probability is None
                or self.reason is not None
            ):
                raise PredictError(
                    "an available prediction carries a probability and no reason"
                )
            validate_finite(self.raw_logit)
            validate_probability(self.probability)
        elif self.status == "unavailable":
            if (
                self.raw_logit is not None
                or self.probability is not None
                or not self.reason
            ):
                raise PredictError(
                    "an unavailable prediction carries a reason and no probability"
                )
        else:
            raise PredictError("prediction artifact status is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_definition_hash": self.target_definition_hash,
            "question": self.question,
            "original_version_id": self.original_version_id,
            "bundle_hash": self.bundle_hash,
            "representation_hash": self.representation_hash,
            "status": self.status,
            "reason": self.reason,
            "raw_logit": self.raw_logit,
            "probability": self.probability,
            "input_hash": self.input_hash,
            "computed_at": self.computed_at,
            "available_at": self.available_at,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "PredictionArtifact":
        value = canonical_loads(raw)
        fields = {
            "target_id",
            "target_definition_hash",
            "question",
            "original_version_id",
            "bundle_hash",
            "representation_hash",
            "status",
            "reason",
            "raw_logit",
            "probability",
            "input_hash",
            "computed_at",
            "available_at",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise PredictError("prediction artifact fields do not match schema")
        return cls(**cast(dict[str, Any], value))

    def public(self) -> "PublicPrediction":
        """The only projection a paper card or agent/rater surface may read."""

        return PublicPrediction(
            target_id=self.target_id,
            target_definition_hash=self.target_definition_hash,
            question=self.question,
            status=self.status,
            reason=self.reason,
            probability=self.probability,
            bundle_hash=self.bundle_hash,
        )


@dataclass(frozen=True, slots=True)
class PublicPrediction:
    """The paper-card contract: never a raw logit, never a composite score."""

    target_id: str
    target_definition_hash: str
    question: str
    status: str
    reason: str | None
    probability: float | None
    bundle_hash: str


def predict_targets(
    handle: ServingHandle,
    heads: Mapping[str, PublishedHead],
    definitions: tuple[TargetDefinition, TargetDefinition, TargetDefinition],
    *,
    original_version_id: str,
    requested_bundle_hash: str,
    representation_hash: str,
    embedding_block: tuple[float, ...],
    metadata_block: tuple[float, ...],
    computed_at: str,
    available_at: str,
) -> tuple[PredictionArtifact, PredictionArtifact, PredictionArtifact]:
    """Evaluate each qualified head of the pinned bundle, in registry order.

    Refuses before evaluating any head when the caller's pinned bundle id or
    representation namespace disagrees with the resolved serving handle
    (SDD #185 acceptance: "a request against a mismatched namespace is
    refused"). Dimension mismatches are rejected before any multiplication
    (SDD RD-08). Each head applies the calibrator of the paper's primary
    category; a category that head has no calibrator for leaves that one
    target unavailable (RD-08 Limits: "calibration is per primary
    category").
    """

    if requested_bundle_hash != handle.bundle_hash:
        raise PredictError(
            "pinned bundle id does not match the currently resolved serving handle"
        )
    if representation_hash != handle.manifest.representation_hash:
        raise PredictError(
            "prediction request representation namespace does not match the bundle"
        )
    if tuple(item.target_id for item in definitions) != TARGET_IDS:
        raise PredictError("target definitions must cover the registry in order")
    if (
        not isinstance(embedding_block, tuple)
        or len(embedding_block) != EMBEDDING_FEATURE_DIMENSION
    ):
        raise PredictError("embedding block dimension mismatch")
    if (
        not isinstance(metadata_block, tuple)
        or len(metadata_block) != METADATA_DIMENSION
    ):
        raise PredictError("metadata block dimension mismatch")
    for value in (*embedding_block, *metadata_block):
        validate_finite(value)
    primary_category = _primary_category(metadata_block)
    validate_uuid4(original_version_id)
    validate_utc_instant(computed_at)
    if validate_utc_instant(available_at) < computed_at:
        raise PredictError("prediction availability precedes computation")

    input_hash = sha256_hex(
        canonical_json(
            {
                "embedding_block": list(embedding_block),
                "metadata_block": list(metadata_block),
            }
        )
    )

    records: list[PredictionArtifact] = []
    for definition in definitions:
        entry = handle.manifest.entry_for(definition.target_id)
        definition_hash = sha256_hex(definition.to_canonical_json())
        if definition_hash != entry.target_definition_hash:
            raise PredictError(
                "target definition does not match the bundle's bound registry"
            )
        head = heads.get(definition.target_id)
        if entry.status != "qualified" or head is None:
            reason = (
                entry.reason if entry.status == "unavailable" else "head_not_loaded"
            )
            records.append(
                PredictionArtifact(
                    target_id=definition.target_id,
                    target_definition_hash=definition_hash,
                    question=definition.question,
                    original_version_id=original_version_id,
                    bundle_hash=handle.bundle_hash,
                    representation_hash=representation_hash,
                    status="unavailable",
                    reason=reason,
                    raw_logit=None,
                    probability=None,
                    input_hash=input_hash,
                    computed_at=computed_at,
                    available_at=available_at,
                )
            )
            continue
        calibrator = (
            None if primary_category is None else head.calibrator_for(primary_category)
        )
        if calibrator is None or calibrator.a is None or calibrator.b is None:
            reason = (
                "primary category is not a calibrated category"
                if calibrator is None
                else f"{primary_category} not calibrated: {calibrator.reason}"
            )
            records.append(
                PredictionArtifact(
                    target_id=definition.target_id,
                    target_definition_hash=definition_hash,
                    question=definition.question,
                    original_version_id=original_version_id,
                    bundle_hash=handle.bundle_hash,
                    representation_hash=representation_hash,
                    status="unavailable",
                    reason=reason,
                    raw_logit=None,
                    probability=None,
                    input_hash=input_hash,
                    computed_at=computed_at,
                    available_at=available_at,
                )
            )
            continue
        standardized = apply_head_input(
            embedding_block, metadata_block, head.standardization
        )
        raw_logit = (
            math.fsum(
                weight * value
                for weight, value in zip(head.weights, standardized, strict=True)
            )
            + head.intercept
        )
        probability = _sigmoid(calibrator.a * raw_logit + calibrator.b)
        records.append(
            PredictionArtifact(
                target_id=definition.target_id,
                target_definition_hash=definition_hash,
                question=definition.question,
                original_version_id=original_version_id,
                bundle_hash=handle.bundle_hash,
                representation_hash=representation_hash,
                status="available",
                reason=None,
                raw_logit=float(raw_logit),
                probability=float(probability),
                input_hash=input_hash,
                computed_at=computed_at,
                available_at=available_at,
            )
        )
    return cast(
        "tuple[PredictionArtifact, PredictionArtifact, PredictionArtifact]",
        tuple(records),
    )
