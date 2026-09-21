"""Masked, deterministic logistic fitting for the fixed three-head representation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize  # type: ignore[import-untyped]

from research_agent.contracts.learning import TARGET_IDS, TargetDefinition
from research_agent.contracts import canonical_json
from research_agent.contracts.primitives import validate_sha256, validate_uuid4
from research_agent.learning.tensors import decode_tensor, encode_tensor

LAMBDAS = (0.0001, 0.001, 0.01, 0.1, 1.0)
DIMENSION = 2048


class FitError(ValueError):
    """A materialized numerical input or candidate is not admissible."""


@dataclass(frozen=True, slots=True)
class MaterializedPartition:
    features: NDArray[np.float32]
    labels: NDArray[np.uint8]
    known_mask: NDArray[np.uint8]
    family_ids: tuple[str, ...]
    partition: str
    corpus_release_hash: str
    split_hash: str
    target_registry_hash: str
    representation_hash: str
    solver_runtime_hash: str
    target_definition_hashes: tuple[str, str, str]

    def __post_init__(self) -> None:
        if self.partition not in {"fit", "development", "calibration"}:
            raise FitError("partition is not admitted for numerical fitting")
        if (
            self.features.ndim != 2
            or self.features.shape[1] != DIMENSION
            or self.features.dtype != np.float32
        ):
            raise FitError("features must be float32 [N,2048]")
        if self.features.shape[0] == 0:
            raise FitError("materialized partition has insufficient support")
        if not np.isfinite(self.features).all():
            raise FitError("features are nonfinite")
        norms = np.linalg.norm(self.features.astype(np.float64), axis=1)
        if not np.all(np.abs(norms - 1.0) <= 1e-5):
            raise FitError("features must be unit-normalized combined vectors")
        if (
            self.labels.shape != (self.features.shape[0], 3)
            or self.known_mask.shape != self.labels.shape
        ):
            raise FitError("label arrays must be [N,3]")
        if self.labels.dtype != np.uint8 or self.known_mask.dtype != np.uint8:
            raise FitError("labels and mask must be uint8")
        if (
            not np.isin(self.labels, (0, 1)).all()
            or not np.isin(self.known_mask, (0, 1)).all()
        ):
            raise FitError("labels and mask must be binary")
        if np.any(self.labels[self.known_mask == 0] != 0):
            raise FitError("unknown labels must use the zero serialization placeholder")
        if len(self.family_ids) != self.features.shape[0] or len(
            set(self.family_ids)
        ) != len(self.family_ids):
            raise FitError("family ids must be unique and match rows")
        if not isinstance(self.family_ids, tuple) or not isinstance(
            self.target_definition_hashes, tuple
        ):
            raise FitError("partition identities must be immutable tuples")
        if (
            len(self.target_definition_hashes) != 3
            or len(set(self.target_definition_hashes)) != 3
        ):
            raise FitError("partition requires three distinct target definitions")
        try:
            for family_id in self.family_ids:
                validate_uuid4(family_id)
            for value in (
                self.corpus_release_hash,
                self.split_hash,
                self.target_registry_hash,
                self.representation_hash,
                self.solver_runtime_hash,
                *self.target_definition_hashes,
            ):
                validate_sha256(value)
        except ValueError as error:
            raise FitError("partition identity is invalid") from error
        feature_ref, feature_bytes = encode_tensor(self.features)
        label_ref, label_bytes = encode_tensor(self.labels)
        mask_ref, mask_bytes = encode_tensor(self.known_mask)
        features = cast(NDArray[np.float32], decode_tensor(feature_ref, feature_bytes))
        labels = cast(NDArray[np.uint8], decode_tensor(label_ref, label_bytes))
        mask = cast(NDArray[np.uint8], decode_tensor(mask_ref, mask_bytes))
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "known_mask", mask)


@dataclass(frozen=True, slots=True)
class CandidateDiagnostics:
    regularization: float
    objective: float
    iterations: int
    gradient_inf_norm: float
    converged: bool
    positive_count: int
    negative_count: int
    development_brier: float | None
    failure: str | None
    solver: str
    solver_runtime_hash: str


@dataclass(frozen=True, slots=True)
class FitResult:
    target_id: str
    target_definition_hash: str
    weights: NDArray[np.float64]
    intercept: float
    selected_lambda: float
    diagnostics: tuple[CandidateDiagnostics, ...]
    development_brier: float
    fit_family_ids: tuple[str, ...]
    development_family_ids: tuple[str, ...]
    partition_family_ids: tuple[str, ...]
    corpus_release_hash: str
    split_hash: str
    target_registry_hash: str
    representation_hash: str
    solver_runtime_hash: str
    fit_row_ids_hash: str
    development_row_ids_hash: str

    def __post_init__(self) -> None:
        if (
            self.target_id not in TARGET_IDS
            or self.weights.shape != (DIMENSION,)
            or self.weights.dtype != np.float64
            or not np.isfinite(self.weights).all()
            or not np.isfinite(self.intercept)
            or self.selected_lambda not in LAMBDAS
            or not np.isfinite(self.development_brier)
        ):
            raise FitError("fitted head coefficients are invalid")
        for value in (
            self.target_definition_hash,
            self.corpus_release_hash,
            self.split_hash,
            self.target_registry_hash,
            self.representation_hash,
            self.solver_runtime_hash,
            self.fit_row_ids_hash,
            self.development_row_ids_hash,
        ):
            validate_sha256(value)
        if (
            len(self.diagnostics) != len(LAMBDAS)
            or tuple(item.regularization for item in self.diagnostics) != LAMBDAS
            or any(
                item.solver != "L-BFGS"
                or item.solver_runtime_hash != self.solver_runtime_hash
                or not np.isfinite(item.objective)
                or not np.isfinite(item.gradient_inf_norm)
                for item in self.diagnostics
            )
        ):
            raise FitError("fitted head diagnostics are invalid")
        for values in (
            self.fit_family_ids,
            self.development_family_ids,
            self.partition_family_ids,
        ):
            if not isinstance(values, tuple):
                raise FitError("fitted head row identities must be immutable tuples")
            if len(set(values)) != len(values):
                raise FitError("fitted head row identities repeat")
            for family_id in values:
                validate_uuid4(family_id)
        if (
            not set(self.fit_family_ids).issubset(self.partition_family_ids)
            or not set(self.development_family_ids).issubset(self.partition_family_ids)
            or self.fit_row_ids_hash != _row_ids_hash(self.fit_family_ids)
            or self.development_row_ids_hash
            != _row_ids_hash(self.development_family_ids)
        ):
            raise FitError("fitted head row lineage is invalid")
        weight_ref, weight_bytes = encode_tensor(self.weights)
        weights = cast(NDArray[np.float64], decode_tensor(weight_ref, weight_bytes))
        object.__setattr__(self, "weights", weights)


def _sigmoid(values: NDArray[np.float64]) -> NDArray[np.float64]:
    return cast(NDArray[np.float64], np.exp(-np.logaddexp(0.0, -values)))


def logistic_objective_gradient(
    parameters: NDArray[np.float64],
    features: NDArray[np.float64],
    labels: NDArray[np.float64],
    regularization: float,
) -> tuple[float, NDArray[np.float64]]:
    weights, intercept = parameters[:-1], parameters[-1]
    logits = features @ weights + intercept
    loss = float(
        np.mean(np.logaddexp(0.0, logits) - labels * logits)
        + regularization * np.dot(weights, weights) / 2
    )
    residual = _sigmoid(logits) - labels
    gradient = np.empty_like(parameters)
    gradient[:-1] = features.T @ residual / features.shape[0] + regularization * weights
    gradient[-1] = np.mean(residual)
    return loss, gradient


def _target_data(
    partition: MaterializedPartition, index: int
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    known = partition.known_mask[:, index].astype(bool)
    indices = np.flatnonzero(known)
    order = sorted(indices, key=lambda row: partition.family_ids[int(row)])
    return partition.features[order].astype(np.float64), partition.labels[
        order, index
    ].astype(np.float64)


def _fit_candidate(
    fit_x: NDArray[np.float64],
    fit_y: NDArray[np.float64],
    development_x: NDArray[np.float64],
    development_y: NDArray[np.float64],
    regularization: float,
    solver_runtime_hash: str,
    *,
    maximum_iterations: int = 2000,
) -> tuple[CandidateDiagnostics, NDArray[np.float64], float]:
    """Run one real fixed-objective candidate; tests may lower only its budget."""

    if type(maximum_iterations) is not int or maximum_iterations <= 0:
        raise FitError("candidate iteration budget must be a positive integer")
    initial = np.zeros(DIMENSION + 1, dtype=np.float64)
    result = minimize(
        logistic_objective_gradient,
        initial,
        args=(fit_x, fit_y, regularization),
        jac=True,
        method="L-BFGS-B",
        options={"gtol": 1e-6, "ftol": 0.0, "maxiter": maximum_iterations},
    )
    objective, gradient = logistic_objective_gradient(
        result.x, fit_x, fit_y, regularization
    )
    norm = float(np.abs(gradient).max())
    converged = bool(result.success and norm <= 1e-6 and np.isfinite(objective))
    brier: float | None = None
    if converged:
        probability = _sigmoid(development_x @ result.x[:-1] + result.x[-1])
        brier = float(np.mean((probability - development_y) ** 2))
    diagnostic = CandidateDiagnostics(
        regularization,
        objective,
        int(result.nit),
        norm,
        converged,
        int(fit_y.sum()),
        int(fit_y.size - fit_y.sum()),
        brier,
        None if converged else "nonconvergence",
        "L-BFGS",
        solver_runtime_hash,
    )
    return diagnostic, result.x.copy(), brier if brier is not None else float("inf")


def _select_candidate(
    records: list[tuple[CandidateDiagnostics, NDArray[np.float64], float]],
) -> tuple[CandidateDiagnostics, NDArray[np.float64], float]:
    viable = [record for record in records if record[0].converged]
    if not viable:
        raise FitError("all candidates failed convergence")
    return min(viable, key=lambda record: (record[2], -record[0].regularization))


def fit_head(
    target: TargetDefinition,
    fit: MaterializedPartition,
    development: MaterializedPartition,
) -> FitResult:
    if fit.partition != "fit" or development.partition != "development":
        raise FitError("fit and development partition identities are required")
    if set(fit.family_ids) & set(development.family_ids):
        raise FitError("fit and development families overlap")
    if (
        fit.corpus_release_hash,
        fit.split_hash,
        fit.target_registry_hash,
        fit.representation_hash,
        fit.solver_runtime_hash,
        fit.target_definition_hashes,
    ) != (
        development.corpus_release_hash,
        development.split_hash,
        development.target_registry_hash,
        development.representation_hash,
        development.solver_runtime_hash,
        development.target_definition_hashes,
    ):
        raise FitError("fit and development partition identities differ")
    index = TARGET_IDS.index(target.target_id)
    target_hash = sha256(target.to_canonical_json()).hexdigest()
    if target_hash != fit.target_definition_hashes[index]:
        raise FitError("target definition is not a member of the bound registry")
    fit_x, fit_y = _target_data(fit, index)
    dev_x, dev_y = _target_data(development, index)
    fit_known = fit.known_mask[:, index].astype(bool)
    dev_known = development.known_mask[:, index].astype(bool)
    fit_ids = tuple(
        family_id
        for family_id, include in zip(fit.family_ids, fit_known, strict=True)
        if include
    )
    dev_ids = tuple(
        family_id
        for family_id, include in zip(development.family_ids, dev_known, strict=True)
        if include
    )
    positives, negatives = int(fit_y.sum()), int(fit_y.size - fit_y.sum())
    if positives < 100 or negatives < 100:
        raise FitError("insufficient fit classes")
    if int(dev_y.sum()) < 25 or int(dev_y.size - dev_y.sum()) < 25:
        raise FitError("insufficient development classes")
    records: list[tuple[CandidateDiagnostics, NDArray[np.float64], float]] = []
    for regularization in LAMBDAS:
        records.append(
            _fit_candidate(
                fit_x,
                fit_y,
                dev_x,
                dev_y,
                regularization,
                fit.solver_runtime_hash,
            )
        )
    selected = _select_candidate(records)
    return FitResult(
        target.target_id,
        target_hash,
        selected[1][:-1].copy(),
        float(selected[1][-1]),
        selected[0].regularization,
        tuple(record[0] for record in records),
        selected[2],
        fit_ids,
        dev_ids,
        fit.family_ids + development.family_ids,
        fit.corpus_release_hash,
        fit.split_hash,
        fit.target_registry_hash,
        fit.representation_hash,
        fit.solver_runtime_hash,
        _row_ids_hash(fit_ids),
        _row_ids_hash(dev_ids),
    )


def _row_ids_hash(values: tuple[str, ...]) -> str:
    return sha256(canonical_json(list(values))).hexdigest()
