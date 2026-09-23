from __future__ import annotations

from hashlib import sha256
from uuid import UUID

import numpy as np
import pytest

from research_agent.contracts.learning import (
    EMBEDDING_FEATURE_DIMENSION,
    METADATA_DIMENSION,
    PRIMARY_CATEGORY_IDS,
)
from research_agent.learning.calibration import (
    CalibrationUnavailable,
    calibration_objective_gradient,
    fit_calibrator,
    fit_calibrators_by_category,
)
from research_agent.learning.features import Standardization
from research_agent.learning.fit import (
    DIMENSION,
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
    features = np.zeros((60, DIMENSION), dtype=np.float32)
    features[:, :2] = rng.normal(size=(60, 2)).astype(np.float32)
    labels = np.zeros((60, 3), dtype=np.uint8)
    labels[:, 0] = (np.arange(60) % 2).astype(np.uint8)
    features[:, 0] += labels[:, 0].astype(np.int8) * 2 - 1
    embedding = features[:, :EMBEDDING_FEATURE_DIMENSION]
    norms = np.linalg.norm(embedding.astype(np.float64), axis=1)
    features[:, :EMBEDDING_FEATURE_DIMENSION] = embedding / norms[:, None].astype(
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
        np.r_[np.array((1.0, 0.4)), np.zeros(DIMENSION - 2)],
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
        Standardization((0.0,) * METADATA_DIMENSION, (1.0,) * METADATA_DIMENSION),
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


def _categorized_partition(counts: dict[str, int]) -> MaterializedPartition:
    """60 rows split across categories by ``counts``; each category's split is
    balanced 50/50 so a category can pass or fail the 25-per-class floor."""

    rng = np.random.default_rng(7)
    total = sum(counts.values())
    features = np.zeros((total, DIMENSION), dtype=np.float32)
    features[:, :2] = rng.normal(size=(total, 2)).astype(np.float32)
    labels = np.zeros((total, 3), dtype=np.uint8)
    offset = EMBEDDING_FEATURE_DIMENSION + 2
    row = 0
    for category, count in counts.items():
        index = PRIMARY_CATEGORY_IDS.index(category)
        features[row : row + count, offset + index] = 1.0
        labels[row : row + count, 0] = (np.arange(count) % 2).astype(np.uint8)
        features[row : row + count, 0] += (
            labels[row : row + count, 0].astype(np.int8) * 2 - 1
        )
        row += count
    embedding = features[:, :EMBEDDING_FEATURE_DIMENSION]
    norms = np.linalg.norm(embedding.astype(np.float64), axis=1)
    features[:, :EMBEDDING_FEATURE_DIMENSION] = embedding / norms[:, None].astype(
        np.float32
    )
    return MaterializedPartition(
        features,
        labels,
        np.ones_like(labels),
        tuple(
            str(UUID(bytes=sha256(f"category-{i}".encode()).digest()[:16], version=4))
            for i in range(total)
        ),
        "calibration",
        *IDENTITY,
        TARGET_DEFINITIONS,
    )


def test_fit_calibrator_restricts_to_one_primary_category() -> None:
    partition = _categorized_partition({"cs.AI": 60, "cs.LG": 60})
    result = fit_calibrator(_head(), partition, "cs.AI")
    assert result.primary_category == "cs.AI"
    assert (result.positive_count, result.negative_count) == (30, 30)


def test_fit_calibrator_rejects_an_unadmitted_category() -> None:
    partition = _categorized_partition({"cs.AI": 60})
    with pytest.raises(ValueError, match="not admitted"):
        fit_calibrator(_head(), partition, "not-a-category")


def test_fit_calibrators_by_category_reports_each_category_independently() -> None:
    partition = _categorized_partition({"cs.AI": 60, "cs.LG": 10})
    results = fit_calibrators_by_category(_head(), partition)
    by_category = {
        item.primary_category: item
        for item in results
        if item.primary_category in ("cs.AI", "cs.LG")
    }
    assert by_category["cs.AI"].primary_category == "cs.AI"
    assert not hasattr(by_category["cs.AI"], "reason")
    assert isinstance(by_category["cs.LG"], CalibrationUnavailable)
    assert "insufficient" in by_category["cs.LG"].reason
    unsampled = {item.primary_category for item in results} - {"cs.AI", "cs.LG"}
    assert unsampled == {"quant-ph", "q-bio"}
    for category in unsampled:
        entry = next(item for item in results if item.primary_category == category)
        assert isinstance(entry, CalibrationUnavailable)
