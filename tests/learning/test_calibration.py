from __future__ import annotations

from hashlib import sha256
from uuid import UUID

import numpy as np
import pytest

from research_agent.learning.calibration import (
    calibration_objective_gradient,
    fit_calibrator,
)
from research_agent.learning.fit import (
    LAMBDAS,
    CandidateDiagnostics,
    FitResult,
    MaterializedPartition,
    _row_ids_hash,
)

IDENTITY = ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)
TARGET_DEFINITIONS = ("a" * 64, "b" * 64, "c" * 64)


def _partition() -> MaterializedPartition:
    rng = np.random.default_rng(4)
    features = np.zeros((60, 2048), dtype=np.float32)
    features[:, :2] = rng.normal(size=(60, 2)).astype(np.float32)
    labels = np.zeros((60, 3), dtype=np.uint8)
    labels[:, 0] = (np.arange(60) % 2).astype(np.uint8)
    features[:, 0] += labels[:, 0].astype(np.int8) * 2 - 1
    features /= np.linalg.norm(features.astype(np.float64), axis=1)[:, None].astype(
        np.float32
    )
    return MaterializedPartition(
        features,
        labels,
        np.ones_like(labels),
        tuple(
            str(
                UUID(bytes=sha256(f"calibration-{i}".encode()).digest()[:16], version=4)
            )
            for i in range(60)
        ),
        "calibration",
        *IDENTITY,
        TARGET_DEFINITIONS,
    )


def _head(partition_family_ids: tuple[str, ...] = ()) -> FitResult:
    diagnostics = tuple(
        CandidateDiagnostics(
            value, 0.5, 1, 0.0, True, 100, 100, 0.2, None, "L-BFGS", IDENTITY[4]
        )
        for value in LAMBDAS
    )
    return FitResult(
        "citation_reach_365d",
        "a" * 64,
        np.r_[np.array((1.0, 0.4)), np.zeros(2046)],
        0.0,
        0.1,
        diagnostics,
        0.0,
        (),
        (),
        partition_family_ids,
        *IDENTITY,
        _row_ids_hash(()),
        _row_ids_hash(()),
    )


def test_calibration_gradient_and_nonnegative_solver() -> None:
    logits = np.array((-2.0, -0.5, 0.3, 1.2), dtype=np.float64)
    labels = np.array((0.0, 0.0, 1.0, 1.0), dtype=np.float64)
    parameters = np.array((0.7, -0.1), dtype=np.float64)
    _, gradient = calibration_objective_gradient(parameters, logits, labels)
    step = np.array((1e-6, 0.0))
    numerical = (
        calibration_objective_gradient(parameters + step, logits, labels)[0]
        - calibration_objective_gradient(parameters - step, logits, labels)[0]
    ) / 2e-6
    assert abs(gradient[0] - numerical) < 1e-5
    result = fit_calibrator(_head(), _partition())
    assert result.a >= 0
    assert result.projected_gradient_inf_norm <= 1e-6
    assert (result.positive_count, result.negative_count) == (30, 30)
    assert result.solver == "L-BFGS-B" and result.converged


def test_calibration_rejects_any_partition_overlap_and_identity_mismatch() -> None:
    partition = _partition()
    with pytest.raises(ValueError, match="overlap"):
        fit_calibrator(_head((partition.family_ids[0],)), partition)
    mismatched = MaterializedPartition(
        partition.features,
        partition.labels,
        partition.known_mask,
        partition.family_ids,
        "calibration",
        "9" * 64,
        *IDENTITY[1:],
        TARGET_DEFINITIONS,
    )
    with pytest.raises(ValueError, match="identity differs"):
        fit_calibrator(_head(), mismatched)
