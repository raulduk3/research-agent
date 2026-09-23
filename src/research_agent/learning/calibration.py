"""Independent constrained sigmoid calibration for a fitted numerical head."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize  # type: ignore[import-untyped]

from .fit import (
    FitError,
    FitResult,
    MaterializedPartition,
    _row_ids_hash,
    _sigmoid,
    _standardized_matrix,
)

PENALTY = 0.000001


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
    head: FitResult, calibration: MaterializedPartition
) -> CalibrationResult:
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
    index = (
        "citation_reach_365d",
        "late_citation_activity_365d",
        "cross_subfield_reach_365d",
    ).index(head.target_id)
    if calibration.target_definition_hashes[index] != head.target_definition_hash:
        raise FitError("calibration target definition differs from fitted head")
    known = calibration.known_mask[:, index].astype(bool)
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
    )
