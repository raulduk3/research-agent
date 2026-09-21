from __future__ import annotations

from hashlib import sha256
from typing import cast
from uuid import UUID

import numpy as np
import pytest

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import TargetDefinition
from research_agent.learning.fit import (
    FitError,
    MaterializedPartition,
    fit_head,
    logistic_objective_gradient,
)
from research_agent.outcomes.targets import definitions

IDENTITY = ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)


def _ids(name: str, count: int) -> tuple[str, ...]:
    return tuple(
        str(UUID(bytes=sha256(f"{name}-{index}".encode()).digest()[:16], version=4))
        for index in range(count)
    )


def _partition(name: str, count: int, seed: int) -> MaterializedPartition:
    rng = np.random.default_rng(seed)
    x = np.zeros((count, 2048), dtype=np.float32)
    x[:, :2] = rng.normal(size=(count, 2)).astype(np.float32)
    labels = np.zeros((count, 3), dtype=np.uint8)
    labels[:, 0] = (np.arange(count) % 2).astype(np.uint8)
    x[:, 0] += labels[:, 0].astype(np.int8) * 2 - 1
    x /= np.linalg.norm(x.astype(np.float64), axis=1)[:, None].astype(np.float32)
    labels[:, 1] = labels[:, 0]
    labels[:, 2] = labels[:, 0]
    return MaterializedPartition(
        x, labels, np.ones_like(labels), _ids(name, count), name, *_bindings()
    )


def _target() -> TargetDefinition:
    meta = RecordMeta(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        "2026-01-01T00:00:00.000000Z",
    )
    return definitions(meta)[0]


def _bindings() -> tuple[str, str, str, str, str, tuple[str, str, str]]:
    target = _target()
    rows = definitions(
        RecordMeta(
            target.schema_version,
            target.input_hashes,
            target.producer_version,
            target.config_hash,
            target.created_at,
        )
    )
    hashes = cast(
        tuple[str, str, str],
        tuple(sha256(row.to_canonical_json()).hexdigest() for row in rows),
    )
    return (
        *IDENTITY,
        hashes,
    )


def test_objective_gradient_matches_finite_difference() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(9, 4)).astype(np.float64)
    y = rng.integers(0, 2, size=9).astype(np.float64)
    parameters = rng.normal(size=5).astype(np.float64)
    _, analytic = logistic_objective_gradient(parameters, x, y, 0.1)
    numerical = np.empty_like(parameters)
    for index in range(parameters.size):
        step = np.zeros_like(parameters)
        step[index] = 1e-6
        numerical[index] = (
            logistic_objective_gradient(parameters + step, x, y, 0.1)[0]
            - logistic_objective_gradient(parameters - step, x, y, 0.1)[0]
        ) / 2e-6
    assert np.allclose(analytic, numerical, atol=1e-5)


def test_fit_is_deterministic_and_valid_unknown_row_does_not_change_it() -> None:
    fit, development = _partition("fit", 220, 1), _partition("development", 60, 2)
    result = fit_head(_target(), fit, development)
    feature = np.zeros((1, 2048), dtype=np.float32)
    feature[0, 0] = 1
    labels = np.zeros((1, 3), dtype=np.uint8)
    mask = np.ones((1, 3), dtype=np.uint8)
    mask[0, 0] = 0
    extended = MaterializedPartition(
        np.concatenate((fit.features, feature)),
        np.concatenate((fit.labels, labels)),
        np.concatenate((fit.known_mask, mask)),
        fit.family_ids + _ids("unknown", 1),
        "fit",
        *_bindings(),
    )
    second = fit_head(_target(), extended, development)
    assert np.array_equal(result.weights, second.weights)
    assert result.selected_lambda == second.selected_lambda
    assert result.fit_family_ids == second.fit_family_ids


def test_partition_rejects_nonzero_unknown_label_and_nonunit_features() -> None:
    partition = _partition("fit", 220, 8)
    mask = partition.known_mask.copy()
    mask[1, 0] = 0
    with pytest.raises(FitError, match="zero serialization"):
        MaterializedPartition(
            partition.features,
            partition.labels,
            mask,
            partition.family_ids,
            "fit",
            *_bindings(),
        )
    bad = partition.features.copy()
    bad[0] = 0
    with pytest.raises(FitError, match="unit-normalized"):
        MaterializedPartition(
            bad,
            partition.labels,
            partition.known_mask,
            partition.family_ids,
            "fit",
            *_bindings(),
        )


def test_fit_rejects_insufficient_classes_overlap_and_identity_mismatch() -> None:
    fit, development = _partition("fit", 220, 1), _partition("development", 60, 2)
    bad = MaterializedPartition(
        fit.features,
        np.zeros_like(fit.labels),
        fit.known_mask,
        fit.family_ids,
        "fit",
        *_bindings(),
    )
    with pytest.raises(FitError, match="insufficient fit"):
        fit_head(_target(), bad, development)
    overlap = MaterializedPartition(
        development.features,
        development.labels,
        development.known_mask,
        fit.family_ids[:60],
        "development",
        *_bindings(),
    )
    with pytest.raises(FitError, match="overlap"):
        fit_head(_target(), fit, overlap)
    mismatched = MaterializedPartition(
        development.features,
        development.labels,
        development.known_mask,
        development.family_ids,
        "development",
        "9" * 64,
        *IDENTITY[1:],
        _bindings()[-1],
    )
    with pytest.raises(FitError, match="identities differ"):
        fit_head(_target(), fit, mismatched)


def test_one_hundred_balanced_rows_do_not_weaken_fit_class_floors() -> None:
    fit = _partition("fit", 100, 41)
    development = _partition("development", 60, 42)
    with pytest.raises(FitError, match="insufficient fit classes"):
        fit_head(_target(), fit, development)


def test_partition_and_fitted_weights_are_copied_and_frozen() -> None:
    fit, development = _partition("fit", 220, 7), _partition("development", 60, 9)
    result = fit_head(_target(), fit, development)
    with pytest.raises(ValueError):
        fit.features[0, 0] = 0
    with pytest.raises(ValueError):
        fit.features.setflags(write=True)
    with pytest.raises(ValueError):
        result.weights[0] = 0
    with pytest.raises(ValueError):
        result.weights.setflags(write=True)


def test_exact_development_tie_selects_largest_regularization() -> None:
    fit, development = _partition("fit", 220, 31), _partition("development", 60, 32)
    fit_x = np.zeros_like(fit.features)
    fit_x[:, 0] = 1
    dev_x = np.zeros_like(development.features)
    dev_x[:, 0] = 1
    fit = MaterializedPartition(
        fit_x, fit.labels, fit.known_mask, fit.family_ids, "fit", *_bindings()
    )
    development = MaterializedPartition(
        dev_x,
        development.labels,
        development.known_mask,
        development.family_ids,
        "development",
        *_bindings(),
    )
    result = fit_head(_target(), fit, development)
    assert result.selected_lambda == 1.0
    assert result.development_brier == 0.25
    assert all(candidate.converged for candidate in result.diagnostics)
    assert np.array_equal(result.weights, np.zeros(2048))


def test_extreme_logits_produce_finite_saturated_probabilities() -> None:
    from research_agent.learning.fit import _sigmoid

    actual = _sigmoid(np.array([-1e300, 0.0, 1e300], dtype=np.float64))
    assert np.array_equal(actual, np.array([0.0, 0.5, 1.0]))
