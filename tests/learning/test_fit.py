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
    _fit_candidate,
    _select_candidate,
    _target_data,
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
    x = np.zeros((count, 1536), dtype=np.float32)
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
    feature = np.zeros((1, 1536), dtype=np.float32)
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
    with pytest.raises(FitError, match="insufficient support"):
        MaterializedPartition(
            np.empty((0, 1536), dtype=np.float32),
            np.empty((0, 3), dtype=np.uint8),
            np.empty((0, 3), dtype=np.uint8),
            (),
            "fit",
            *_bindings(),
        )
    bindings = _bindings()
    with pytest.raises(FitError, match="three distinct"):
        MaterializedPartition(
            partition.features,
            partition.labels,
            partition.known_mask,
            partition.family_ids,
            "fit",
            *bindings[:-1],
            ("a" * 64, "a" * 64, "b" * 64),
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
    assert np.array_equal(result.weights, np.zeros(1536))


def test_fit_is_stable_under_real_row_permutations() -> None:
    fit, development = _partition("fit", 220, 51), _partition("development", 60, 52)
    fit_order = np.random.default_rng(53).permutation(220)
    dev_order = np.random.default_rng(54).permutation(60)
    permuted_fit = MaterializedPartition(
        fit.features[fit_order],
        fit.labels[fit_order],
        fit.known_mask[fit_order],
        tuple(fit.family_ids[int(index)] for index in fit_order),
        "fit",
        *_bindings(),
    )
    permuted_development = MaterializedPartition(
        development.features[dev_order],
        development.labels[dev_order],
        development.known_mask[dev_order],
        tuple(development.family_ids[int(index)] for index in dev_order),
        "development",
        *_bindings(),
    )
    first = fit_head(_target(), fit, development)
    second = fit_head(_target(), permuted_fit, permuted_development)
    assert first.selected_lambda == second.selected_lambda
    assert first.development_brier == second.development_brier
    assert np.array_equal(first.weights, second.weights)
    assert first.intercept == second.intercept


def test_real_iteration_exhaustion_is_classified_and_all_failed_refuses_fit() -> None:
    fit, development = _partition("fit", 220, 61), _partition("development", 60, 62)
    fit_x, fit_y = _target_data(fit, 0)
    dev_x, dev_y = _target_data(development, 0)
    failed = [
        _fit_candidate(
            fit_x,
            fit_y,
            dev_x,
            dev_y,
            regularization,
            IDENTITY[4],
            maximum_iterations=1,
        )
        for regularization in (0.0001, 0.001, 0.01, 0.1, 1.0)
    ]
    assert all(not row[0].converged for row in failed)
    assert all(row[0].failure == "nonconvergence" for row in failed)
    assert all(row[0].iterations == 1 for row in failed)
    with pytest.raises(FitError, match="all candidates failed convergence"):
        _select_candidate(failed)
    converged = _fit_candidate(fit_x, fit_y, dev_x, dev_y, 1.0, IDENTITY[4])
    mixed = [*failed, converged]
    assert _select_candidate(mixed) is converged
    assert tuple(row[0].failure for row in mixed[:-1]) == ("nonconvergence",) * 5


def test_extreme_logits_produce_finite_saturated_probabilities() -> None:
    from research_agent.learning.fit import _sigmoid

    actual = _sigmoid(np.array([-1e300, 0.0, 1e300], dtype=np.float64))
    assert np.array_equal(actual, np.array([0.0, 0.5, 1.0]))


@pytest.mark.parametrize("width", [768, 2048])
def test_features_from_another_representation_width_are_refused(width: int) -> None:
    # 2048 was the previous representation's feature width; 768 is one embedding.
    x = np.zeros((4, width), dtype=np.float32)
    x[:, 0] = 1
    labels = np.zeros((4, 3), dtype=np.uint8)
    with pytest.raises(FitError, match=r"\[N,1536\]"):
        MaterializedPartition(
            x, labels, np.ones_like(labels), _ids("fit", 4), "fit", *_bindings()
        )
