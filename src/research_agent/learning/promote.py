"""Score calibrated heads on development monitoring support and decide promotion.

Appendix B: Learning protocol scores weekly promotion by comparing candidate
and incumbent "on the same original development monitoring support,
requiring baseline improvement and no higher Brier loss" — the reused
original development partition, not a fresh locked-evaluation draw; a locked
release evaluation set is "consumed once" for initial qualification
(FT-22), a separate concern this module does not perform. The baseline
probability is the fitting-partition positive fraction for a target, fixed
before any later partition is read (SDD-FT-11).

A head that never fit or never calibrated is refused without a numeric
comparison; the incumbent, or explicit unavailability, is what keeps
serving.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, cast

import numpy as np
from numpy.typing import NDArray

from research_agent.contracts.learning import TARGET_IDS
from research_agent.learning.fit import FitError, MaterializedPartition, _row_ids_hash
from research_agent.learning.heads import (
    CalibratedHead,
    HeadUnavailable,
    ThreeHeadCalibration,
)


def _sigmoid(values: NDArray[np.float64]) -> NDArray[np.float64]:
    return cast(NDArray[np.float64], np.exp(-np.logaddexp(0.0, -values)))


def base_rate_baseline(fit: MaterializedPartition, target_id: str) -> float:
    """The fitting-partition positive fraction for one target (SDD-FT-11)."""

    if fit.partition != "fit":
        raise FitError("base rate baseline requires the fitting partition")
    index = TARGET_IDS.index(target_id)
    known = fit.known_mask[:, index].astype(bool)
    if not known.any():
        raise FitError("fitting partition has no known labels for this target")
    return float(fit.labels[known, index].astype(np.float64).mean())


@dataclass(frozen=True, slots=True)
class HeldOutEvaluation:
    """One calibrated head's development-monitoring Brier loss against its baseline."""

    target_id: str
    baseline_probability: float
    candidate_brier: float
    baseline_brier: float
    support_count: int
    row_ids_hash: str

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise FitError("held-out evaluation names an unregistered target")
        if self.support_count <= 0:
            raise FitError("held-out evaluation requires positive support")
        for value in (
            self.baseline_probability,
            self.candidate_brier,
            self.baseline_brier,
        ):
            if not np.isfinite(value):
                raise FitError("held-out evaluation values must be finite")


def evaluate_head(
    calibrated: CalibratedHead,
    fit: MaterializedPartition,
    development: MaterializedPartition,
) -> HeldOutEvaluation:
    """Score one calibrated head's Brier loss on its own development monitoring support.

    Reads the head's and calibrator's already-fitted parameters and the exact
    family support ``fit_head`` recorded for this target; it never refits or
    adjusts either, so recomputing this against a differently labeled copy of
    the same development partition cannot change the fitted head or
    calibrator it read (SDD-FT-11). ``development`` must carry the identical
    known rows the head itself was selected against — a different or
    narrower support is refused rather than silently rescored.
    """

    head, calibrator = calibrated.head, calibrated.calibrator
    if development.partition != "development":
        raise FitError("development partition identity is required")
    if (
        development.corpus_release_hash,
        development.split_hash,
        development.target_registry_hash,
        development.representation_hash,
    ) != (
        calibrator.corpus_release_hash,
        calibrator.split_hash,
        calibrator.target_registry_hash,
        calibrator.representation_hash,
    ):
        raise FitError(
            "development partition identity differs from the calibrated head"
        )
    index = TARGET_IDS.index(head.target_id)
    known = development.known_mask[:, index].astype(bool)
    known_ids = frozenset(
        family_id
        for family_id, include in zip(development.family_ids, known, strict=True)
        if include
    )
    if known_ids != frozenset(head.development_family_ids):
        raise FitError(
            "development partition support differs from the head's own monitoring set"
        )
    logits = (
        development.features[known].astype(np.float64) @ head.weights + head.intercept
    )
    probability = _sigmoid(calibrator.a * logits + calibrator.b)
    labels = development.labels[known, index].astype(np.float64)
    baseline = base_rate_baseline(fit, head.target_id)
    return HeldOutEvaluation(
        head.target_id,
        baseline,
        float(np.mean((probability - labels) ** 2)),
        float(np.mean((baseline - labels) ** 2)),
        int(known.sum()),
        _row_ids_hash(head.development_family_ids),
    )


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Whether one target's candidate head replaces its incumbent, and why."""

    target_id: str
    promoted: bool
    reason: str
    evaluation: HeldOutEvaluation | None

    _REASONS: ClassVar[frozenset[str]] = frozenset(
        {
            "unavailable",
            "below_baseline_requirement",
            "worse_than_incumbent",
            "promoted",
        }
    )

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise FitError("promotion decision names an unregistered target")
        if self.reason not in self._REASONS:
            raise FitError("promotion decision reason is not recognized")
        if self.promoted != (self.reason == "promoted"):
            raise FitError("promotion decision disposition disagrees with its reason")
        if self.reason == "unavailable" and self.evaluation is not None:
            raise FitError("an unavailable decision carries no evaluation")
        if self.reason != "unavailable" and self.evaluation is None:
            raise FitError("a scored decision requires its evaluation")


def decide_promotion(
    evaluation: HeldOutEvaluation, incumbent: HeldOutEvaluation | None
) -> PromotionDecision:
    """Refuse promotion unless the candidate beats both the baseline and the incumbent.

    No higher Brier loss than the incumbent is the written threshold: zero
    tolerance for regression, exactly Appendix B: Learning protocol's weekly
    refresh comparison, "requiring baseline improvement and no higher Brier
    loss."
    """

    if incumbent is not None and incumbent.target_id != evaluation.target_id:
        raise FitError("incumbent evaluation targets a different head")
    if evaluation.candidate_brier >= evaluation.baseline_brier:
        return PromotionDecision(
            evaluation.target_id, False, "below_baseline_requirement", evaluation
        )
    if incumbent is not None and evaluation.candidate_brier > incumbent.candidate_brier:
        return PromotionDecision(
            evaluation.target_id, False, "worse_than_incumbent", evaluation
        )
    return PromotionDecision(evaluation.target_id, True, "promoted", evaluation)


def promote_three_heads(
    calibration: ThreeHeadCalibration,
    fit: MaterializedPartition,
    development: MaterializedPartition,
    incumbents: tuple[
        HeldOutEvaluation | None, HeldOutEvaluation | None, HeldOutEvaluation | None
    ] = (None, None, None),
) -> tuple[PromotionDecision, ...]:
    """Evaluate and decide promotion for all three registry targets, in order.

    A target that never fit or never calibrated is refused without ever being
    scored; the bundle keeps whatever incumbent it already had for that
    target, or stays explicitly unavailable (SDD-FT-08, FT-11).
    """

    if len(incumbents) != 3:
        raise FitError("incumbent evaluations must cover the registry in order")
    decisions: list[PromotionDecision] = []
    for item, prior in zip(calibration.calibrated, incumbents, strict=True):
        if isinstance(item, HeadUnavailable):
            decisions.append(
                PromotionDecision(item.target_id, False, "unavailable", None)
            )
            continue
        decisions.append(decide_promotion(evaluate_head(item, fit, development), prior))
    return tuple(decisions)
