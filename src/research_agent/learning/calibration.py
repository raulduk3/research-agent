"""Independent constrained sigmoid calibration for a fitted numerical head.

Appendix B: Learning protocol fits "one calibrator per target and primary
category": ``fit_calibrator`` alone (``primary_category=None``) reproduces
the pre-existing whole-partition behavior every current caller relies on;
passing a ``PRIMARY_CATEGORY_IDS`` member restricts calibration to that
category's rows, as the weekly refresh and qualification paths require.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize  # type: ignore[import-untyped]

from research_agent.contracts.learning import (
    EMBEDDING_FEATURE_DIMENSION,
    PRIMARY_CATEGORY_IDS,
    TARGET_IDS,
)

from .fit import (
    FitError,
    FitResult,
    MaterializedPartition,
    _row_ids_hash,
    _sigmoid,
    _standardized_matrix,
)

PENALTY = 0.000001
# The primary-category one-hot's offset within one feature row (#149 Appendix
# B): the metadata block starts at EMBEDDING_FEATURE_DIMENSION, and its first
# two columns (author count, listed-category count) precede the one-hot.
_PRIMARY_CATEGORY_OFFSET = EMBEDDING_FEATURE_DIMENSION + 2


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    target_id: str
    a: float
    b: float
    objective: float
    iterations: int
    projected_gradient_inf_norm: float
    calibration_row_ids_hash: str
    penalty: float
    solver: str
    converged: bool
    positive_count: int
    negative_count: int
    solver_runtime_hash: str
    target_definition_hash: str
    corpus_release_hash: str
    split_hash: str
    target_registry_hash: str
    representation_hash: str
    # None means the legacy whole-partition fit (every current heads.py
    # caller); a PRIMARY_CATEGORY_IDS member names the one category this
    # calibrator was restricted to (#149 Appendix B).
    primary_category: str | None = None

    def __post_init__(self) -> None:
        if (
            self.primary_category is not None
            and self.primary_category not in PRIMARY_CATEGORY_IDS
        ):
            raise FitError("calibration result names an unadmitted primary category")


@dataclass(frozen=True, slots=True)
class CalibrationUnavailable:
    """A target/category calibration that failed, with why (#67)."""

    target_id: str
    primary_category: str
    reason: str

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise FitError("unavailable calibration names an unregistered target")
        if self.primary_category not in PRIMARY_CATEGORY_IDS:
            raise FitError(
                "unavailable calibration names an unadmitted primary category"
            )


def _primary_categories(features: NDArray[np.float32]) -> NDArray[np.str_]:
    """The one-hot-decoded primary category of every row (#149 Appendix B)."""

    block = features[
        :,
        _PRIMARY_CATEGORY_OFFSET : _PRIMARY_CATEGORY_OFFSET + len(PRIMARY_CATEGORY_IDS),
    ].astype(np.float64)
    if not np.isin(block, (0.0, 1.0)).all() or not np.all(block.sum(axis=1) == 1.0):
        raise FitError("a row's primary-category block is not a single one-hot")
    categories = np.asarray(PRIMARY_CATEGORY_IDS)
    return cast(NDArray[np.str_], categories[np.argmax(block, axis=1)])


def calibration_objective_gradient(
    parameters: NDArray[np.float64],
    logits: NDArray[np.float64],
    labels: NDArray[np.float64],
) -> tuple[float, NDArray[np.float64]]:
    a, b = parameters
    scores = a * logits + b
    probability = _sigmoid(scores)
    loss = float(
        np.mean(np.logaddexp(0.0, scores) - labels * scores)
        + PENALTY * (a * a + b * b) / 2
    )
    residual = probability - labels
    return loss, np.array(
        (np.mean(residual * logits) + PENALTY * a, np.mean(residual) + PENALTY * b),
        dtype=np.float64,
    )


def fit_calibrator(
    head: FitResult,
    calibration: MaterializedPartition,
    primary_category: str | None = None,
) -> CalibrationResult:
    """Fit one sigmoid calibrator, optionally restricted to one category.

    ``primary_category=None`` calibrates over the whole partition, the
    behavior every existing caller (:mod:`research_agent.learning.heads`)
    relies on. Passing a ``PRIMARY_CATEGORY_IDS`` member restricts fitting
    to that category's rows and requires the same 25-per-class floor within
    that narrower support, exactly as Appendix B: Learning protocol's "one
    calibrator per target and primary category" requires.
    """

    if calibration.partition != "calibration":
        raise FitError("calibration partition identity is required")
    if set(calibration.family_ids) & set(head.partition_family_ids):
        raise FitError("calibration families overlap fitting or development")
    if (
        calibration.corpus_release_hash,
        calibration.split_hash,
        calibration.target_registry_hash,
        calibration.representation_hash,
        calibration.solver_runtime_hash,
    ) != (
        head.corpus_release_hash,
        head.split_hash,
        head.target_registry_hash,
        head.representation_hash,
        head.solver_runtime_hash,
    ):
        raise FitError("calibration partition identity differs from fitted head")
    index = TARGET_IDS.index(head.target_id)
    if calibration.target_definition_hashes[index] != head.target_definition_hash:
        raise FitError("calibration target definition differs from fitted head")
    known = calibration.known_mask[:, index].astype(bool)
    if primary_category is not None:
        if primary_category not in PRIMARY_CATEGORY_IDS:
            raise FitError("primary category is not admitted")
        known = known & (_primary_categories(calibration.features) == primary_category)
    labels = calibration.labels[known, index].astype(np.float64)
    positives = int(labels.sum())
    negatives = int(labels.size - labels.sum())
    if positives < 25 or negatives < 25:
        raise FitError("insufficient calibration classes")
    standardized = _standardized_matrix(
        calibration.features[known].astype(np.float64), head.standardization
    )
    logits = standardized @ head.weights + head.intercept
    result = minimize(
        calibration_objective_gradient,
        np.array((1.0, 0.0)),
        args=(logits, labels),
        jac=True,
        method="L-BFGS-B",
        bounds=((0.0, None), (None, None)),
        options={"gtol": 1e-6, "ftol": 0.0, "maxiter": 2000},
    )
    objective, gradient = calibration_objective_gradient(result.x, logits, labels)
    projected = gradient.copy()
    if result.x[0] <= 0 and projected[0] > 0:
        projected[0] = 0
    norm = float(np.abs(projected).max())
    if not result.success or norm > 1e-6 or not np.isfinite(objective):
        raise FitError("calibration failed convergence")
    ids = tuple(
        identifier
        for identifier, include in zip(calibration.family_ids, known, strict=True)
        if include
    )
    return CalibrationResult(
        head.target_id,
        float(result.x[0]),
        float(result.x[1]),
        objective,
        int(result.nit),
        norm,
        _row_ids_hash(ids),
        PENALTY,
        "L-BFGS-B",
        True,
        positives,
        negatives,
        calibration.solver_runtime_hash,
        head.target_definition_hash,
        head.corpus_release_hash,
        head.split_hash,
        head.target_registry_hash,
        head.representation_hash,
        primary_category,
    )


def fit_calibrators_by_category(
    head: FitResult, calibration: MaterializedPartition
) -> tuple[CalibrationResult | CalibrationUnavailable, ...]:
    """Fit one calibrator per corpus primary category, in registry order.

    A category whose calibration partition is below its class floor, or
    whose calibrator fails to converge, is recorded unavailable rather than
    raised: the other categories still calibrate from the same partition,
    exactly as "a category whose calibration partition is below its floor
    leaves that target unavailable for that category while the others are
    served" (Appendix B: Learning protocol).
    """

    results: list[CalibrationResult | CalibrationUnavailable] = []
    for category in PRIMARY_CATEGORY_IDS:
        try:
            results.append(fit_calibrator(head, calibration, category))
        except FitError as error:
            results.append(CalibrationUnavailable(head.target_id, category, str(error)))
    return tuple(results)
