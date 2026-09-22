"""The three launch comparison baselines (SDD-IN-07, IN-08, IN-09).

Each baseline is a pure function over already-captured, timestamped inputs: it
never reads a clock and never reaches past a forecast batch's seal instant for
either training data or the covariates it answers with (SDD-IN-35). A question
a baseline cannot answer is reported as a gap, never a fabricated probability.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
from scipy.optimize import minimize  # type: ignore[import-untyped]

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_probability,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

GAP_REASONS: frozenset[str] = frozenset(
    {
        "late_capture",
        "missing_capture_date",
        "missing_author_count",
        "no_signal",
        "baseline_unqualified",
        "unqualified_reference_partition",
    }
)
EXCLUSION_REASONS: frozenset[str] = frozenset({"missing_capture_date", "late_capture"})


def _require_target(target_id: str) -> None:
    if target_id not in TARGET_IDS:
        raise ContractValidationError("target_id is not a registered target")


# --- shared temporal availability barrier (SDD-IN-35) ------------------------


@dataclass(frozen=True, slots=True)
class ExcludedInput:
    """An input a baseline left out, with the reason it was left out."""

    input_id: str
    reason: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.input_id)
        if self.reason not in EXCLUSION_REASONS:
            raise ContractValidationError("reason is not a recognized exclusion")


def _eligible_capture(
    *,
    input_id: str,
    captured_at: str | None,
    available_at: str | None,
    batch_sealed_at: str,
) -> ExcludedInput | None:
    """Return the exclusion for one input, or None when it is temporally eligible."""

    if captured_at is None:
        return ExcludedInput(input_id, "missing_capture_date")
    validate_utc_instant(captured_at)
    resolved_available_at = available_at if available_at is not None else captured_at
    validate_utc_instant(resolved_available_at)
    if captured_at >= batch_sealed_at or resolved_available_at >= batch_sealed_at:
        return ExcludedInput(input_id, "late_capture")
    return None


# --- shared answer/gap shape every baseline reports --------------------------


@dataclass(frozen=True, slots=True)
class BaselineAnswer:
    """One sealed probability a baseline offers for a question."""

    question_id: str
    forecast_id: str
    probability: float
    covariate_hash: str

    def __post_init__(self) -> None:
        validate_uuid4(self.question_id)
        validate_uuid4(self.forecast_id)
        validate_probability(self.probability)
        validate_sha256(self.covariate_hash)


@dataclass(frozen=True, slots=True)
class BaselineGap:
    """A question a baseline records no answer for, with why."""

    question_id: str
    reason: str

    def __post_init__(self) -> None:
        validate_uuid4(self.question_id)
        if self.reason not in GAP_REASONS:
            raise ContractValidationError("reason is not a recognized gap")


@dataclass(frozen=True, slots=True)
class BaselineAnswerSet:
    """A baseline's complete, sealed answer to one forecast batch."""

    baseline_id: str
    target_id: str
    target_definition_hash: str
    answers: tuple[BaselineAnswer, ...]
    gaps: tuple[BaselineGap, ...]
    excluded_inputs: tuple[ExcludedInput, ...]

    def __post_init__(self) -> None:
        validate_non_empty_string(self.baseline_id)
        _require_target(self.target_id)
        validate_sha256(self.target_definition_hash)
        answered = {answer.question_id for answer in self.answers}
        gapped = {gap.question_id for gap in self.gaps}
        if len(answered) != len(self.answers) or len(gapped) != len(self.gaps):
            raise ContractValidationError(
                "a question appears at most once on each side"
            )
        if answered & gapped:
            raise ContractValidationError(
                "a question cannot be both answered and gapped"
            )


def _covariate_hash(values: dict[str, float | bool | str | int | None]) -> str:
    return sha256_hex(canonical_json(values))


# --- a small shared logistic fit, private to this file ----------------------
#
# `learning.logistic.fit_binary_logistic` does not exist yet and building a
# shared owner is out of this slice's scope (src/research_agent/scoring/,
# tests/scoring/ only). Both baselines below need a tiny (1-4 feature)
# logistic fit, so this private helper is used twice rather than duplicated;
# it is not a general-purpose fitter and is not exported.


def _fit_logistic(
    features: np.ndarray, labels: np.ndarray, *, ridge: float = 1e-3
) -> np.ndarray:
    design = np.hstack([features, np.ones((features.shape[0], 1))])

    def negative_log_likelihood(weights: np.ndarray) -> float:
        logits = design @ weights
        loss = np.logaddexp(0.0, -logits) * labels + np.logaddexp(0.0, logits) * (
            1.0 - labels
        )
        penalty = ridge * float(np.sum(weights[:-1] ** 2))
        return float(np.sum(loss)) + penalty

    def gradient(weights: np.ndarray) -> np.ndarray:
        probabilities = 1.0 / (1.0 + np.exp(-design @ weights))
        grad = design.T @ (probabilities - labels)
        grad = grad.copy()
        grad[:-1] += 2.0 * ridge * weights[:-1]
        return cast(np.ndarray, grad)

    initial = np.zeros(design.shape[1])
    result = minimize(negative_log_likelihood, initial, jac=gradient, method="L-BFGS-B")
    return cast(np.ndarray, result.x)


def _sigmoid(value: float) -> float:
    return float(1.0 / (1.0 + math.exp(-value)))


# --- IN-07: the popularity baseline ------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorCountRow:
    """One question's logged author-citation covariate at its capture time."""

    question_id: str
    forecast_id: str
    author_counts: tuple[int, ...] | None
    captured_at: str | None

    def __post_init__(self) -> None:
        validate_uuid4(self.question_id)
        validate_uuid4(self.forecast_id)
        if self.author_counts is not None:
            for count in self.author_counts:
                validate_non_negative_int(count)
        if self.captured_at is not None:
            validate_utc_instant(self.captured_at)


@dataclass(frozen=True, slots=True)
class AuthorCountExample(AuthorCountRow):
    """A historical row with the resolved label used to fit the baseline."""

    outcome: bool = False

    def __post_init__(self) -> None:
        AuthorCountRow.__post_init__(self)
        if not isinstance(self.outcome, bool):
            raise ContractValidationError("outcome must be a boolean")


def _popularity_feature(row: AuthorCountRow) -> float | None:
    if row.author_counts is None or len(row.author_counts) == 0:
        return None
    return math.log1p(float(sum(row.author_counts)))


def popularity_baseline_answers(
    training: Sequence[AuthorCountExample],
    batch: Sequence[AuthorCountRow],
    *,
    target_id: str,
    target_definition_hash: str,
    batch_sealed_at: str,
) -> BaselineAnswerSet:
    """Answer every batch question from logged prior author-citation counts.

    Only training rows captured strictly before `batch_sealed_at`, with every
    author count present, ever enter the fit; a batch row captured at or after
    the seal, or with a missing author count, gets no answer (SDD-IN-07, IN-35).
    """

    _require_target(target_id)
    validate_sha256(target_definition_hash)
    validate_utc_instant(batch_sealed_at)

    excluded: list[ExcludedInput] = []
    fit_rows: list[tuple[float, bool]] = []
    for example in training:
        exclusion = _eligible_capture(
            input_id=example.forecast_id,
            captured_at=example.captured_at,
            available_at=example.captured_at,
            batch_sealed_at=batch_sealed_at,
        )
        if exclusion is not None:
            excluded.append(exclusion)
            continue
        feature = _popularity_feature(example)
        if feature is None:
            excluded.append(ExcludedInput(example.forecast_id, "missing_capture_date"))
            continue
        fit_rows.append((feature, example.outcome))

    qualified = (
        len(fit_rows) >= 2
        and any(outcome for _, outcome in fit_rows)
        and any(not outcome for _, outcome in fit_rows)
    )
    weights: np.ndarray | None = None
    if qualified:
        features = np.array([[value] for value, _ in fit_rows], dtype=np.float64)
        labels = np.array(
            [1.0 if outcome else 0.0 for _, outcome in fit_rows], dtype=np.float64
        )
        weights = _fit_logistic(features, labels)

    answers: list[BaselineAnswer] = []
    gaps: list[BaselineGap] = []
    for row in batch:
        if row.captured_at is None:
            gaps.append(BaselineGap(row.question_id, "missing_capture_date"))
            continue
        if row.captured_at >= batch_sealed_at:
            gaps.append(BaselineGap(row.question_id, "late_capture"))
            continue
        feature = _popularity_feature(row)
        if feature is None:
            gaps.append(BaselineGap(row.question_id, "missing_author_count"))
            continue
        if not qualified or weights is None:
            gaps.append(BaselineGap(row.question_id, "baseline_unqualified"))
            continue
        probability = _sigmoid(float(weights[0] * feature + weights[1]))
        answers.append(
            BaselineAnswer(
                question_id=row.question_id,
                forecast_id=row.forecast_id,
                probability=probability,
                covariate_hash=_covariate_hash({"log1p_author_citations": feature}),
            )
        )

    return BaselineAnswerSet(
        baseline_id="popularity_baseline_v1",
        target_id=target_id,
        target_definition_hash=target_definition_hash,
        answers=tuple(answers),
        gaps=tuple(gaps),
        excluded_inputs=tuple(excluded),
    )


# --- IN-08: the base-rate baseline -------------------------------------------


@dataclass(frozen=True, slots=True)
class FittingBundle:
    """The immutable fitting-partition counts a base rate is computed from."""

    bundle_id: str
    target_id: str
    target_definition_hash: str
    positive_count: int
    known_count: int
    frozen_at: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.bundle_id)
        _require_target(self.target_id)
        validate_sha256(self.target_definition_hash)
        validate_non_negative_int(self.positive_count)
        validate_non_negative_int(self.known_count)
        if self.positive_count > self.known_count:
            raise ContractValidationError("positive_count cannot exceed known_count")
        validate_utc_instant(self.frozen_at)


@dataclass(frozen=True, slots=True)
class BaselineQuestion:
    """A question on the batch that needs an answer."""

    question_id: str
    forecast_id: str

    def __post_init__(self) -> None:
        validate_uuid4(self.question_id)
        validate_uuid4(self.forecast_id)


def base_rate_baseline_answers(
    bundle: FittingBundle,
    batch: Sequence[BaselineQuestion],
    *,
    target_id: str,
    target_definition_hash: str,
    batch_sealed_at: str,
) -> BaselineAnswerSet:
    """Answer every batch question with the bundle's frozen empirical base rate.

    The bundle must name the exact target and target version being answered,
    must have frozen strictly before the batch's seal, and must carry a nonzero
    denominator; otherwise every question on the batch is a gap (SDD-IN-08).
    """

    _require_target(target_id)
    validate_sha256(target_definition_hash)
    validate_utc_instant(batch_sealed_at)

    def all_gaps(reason: str) -> BaselineAnswerSet:
        return BaselineAnswerSet(
            baseline_id="base_rate_baseline_v1",
            target_id=target_id,
            target_definition_hash=target_definition_hash,
            answers=(),
            gaps=tuple(BaselineGap(q.question_id, reason) for q in batch),
            excluded_inputs=(),
        )

    bundle_matches = (
        bundle.target_id == target_id
        and bundle.target_definition_hash == target_definition_hash
    )
    if not bundle_matches:
        return all_gaps("unqualified_reference_partition")
    if bundle.frozen_at >= batch_sealed_at:
        return all_gaps("unqualified_reference_partition")
    if bundle.known_count == 0:
        return all_gaps("unqualified_reference_partition")

    probability = bundle.positive_count / bundle.known_count
    covariate_hash = _covariate_hash(
        {
            "bundle_id": bundle.bundle_id,
            "positive_count": bundle.positive_count,
            "known_count": bundle.known_count,
        }
    )
    answers = tuple(
        BaselineAnswer(
            question_id=question.question_id,
            forecast_id=question.forecast_id,
            probability=probability,
            covariate_hash=covariate_hash,
        )
        for question in batch
    )
    return BaselineAnswerSet(
        baseline_id="base_rate_baseline_v1",
        target_id=target_id,
        target_definition_hash=target_definition_hash,
        answers=answers,
        gaps=(),
        excluded_inputs=(),
    )


# --- IN-09: the paper-card regression baseline -------------------------------


@dataclass(frozen=True, slots=True)
class CardFeatureRow:
    """The fixed, snapshot-pinned scalar signals a paper card exposes.

    Only the target's own prediction-head logit and the original-overview
    neighbor distance ever enter this baseline: no Jev field, no raw vector and
    no paper text is a field here (SDD-IN-09).
    """

    question_id: str
    forecast_id: str
    target_logit: float | None
    neighbor_distance: float | None
    captured_at: str | None

    def __post_init__(self) -> None:
        validate_uuid4(self.question_id)
        validate_uuid4(self.forecast_id)
        if self.captured_at is not None:
            validate_utc_instant(self.captured_at)


@dataclass(frozen=True, slots=True)
class CardFeatureExample(CardFeatureRow):
    """A historical row with the resolved label used to fit the baseline."""

    outcome: bool = False

    def __post_init__(self) -> None:
        CardFeatureRow.__post_init__(self)
        if not isinstance(self.outcome, bool):
            raise ContractValidationError("outcome must be a boolean")


def _card_features(row: CardFeatureRow) -> tuple[float, float, float, float] | None:
    target_logit = row.target_logit
    neighbor_distance = row.neighbor_distance
    if target_logit is None and neighbor_distance is None:
        return None
    return (
        target_logit if target_logit is not None else 0.0,
        neighbor_distance if neighbor_distance is not None else 0.0,
        1.0 if target_logit is not None else 0.0,
        1.0 if neighbor_distance is not None else 0.0,
    )


def card_regression_baseline_answers(
    training: Sequence[CardFeatureExample],
    batch: Sequence[CardFeatureRow],
    *,
    target_id: str,
    target_definition_hash: str,
    batch_sealed_at: str,
) -> BaselineAnswerSet:
    """Answer every batch question from the fixed paper-card scalar signals.

    Fits on time-valid logged covariates and resolved outcomes only; a row with
    no target-head logit and no neighbor distance never receives an answer
    (SDD-IN-09, IN-35).
    """

    _require_target(target_id)
    validate_sha256(target_definition_hash)
    validate_utc_instant(batch_sealed_at)

    excluded: list[ExcludedInput] = []
    fit_rows: list[tuple[tuple[float, float, float, float], bool]] = []
    for example in training:
        exclusion = _eligible_capture(
            input_id=example.forecast_id,
            captured_at=example.captured_at,
            available_at=example.captured_at,
            batch_sealed_at=batch_sealed_at,
        )
        if exclusion is not None:
            excluded.append(exclusion)
            continue
        features = _card_features(example)
        if features is None:
            excluded.append(ExcludedInput(example.forecast_id, "missing_capture_date"))
            continue
        fit_rows.append((features, example.outcome))

    qualified = (
        len(fit_rows) >= 2
        and any(outcome for _, outcome in fit_rows)
        and any(not outcome for _, outcome in fit_rows)
    )
    weights: np.ndarray | None = None
    if qualified:
        features_matrix = np.array([row for row, _ in fit_rows], dtype=np.float64)
        labels = np.array(
            [1.0 if outcome else 0.0 for _, outcome in fit_rows], dtype=np.float64
        )
        weights = _fit_logistic(features_matrix, labels)

    answers: list[BaselineAnswer] = []
    gaps: list[BaselineGap] = []
    for row in batch:
        if row.captured_at is None:
            gaps.append(BaselineGap(row.question_id, "missing_capture_date"))
            continue
        if row.captured_at >= batch_sealed_at:
            gaps.append(BaselineGap(row.question_id, "late_capture"))
            continue
        features = _card_features(row)
        if features is None:
            gaps.append(BaselineGap(row.question_id, "no_signal"))
            continue
        if not qualified or weights is None:
            gaps.append(BaselineGap(row.question_id, "baseline_unqualified"))
            continue
        logit = sum(w * x for w, x in zip(weights[:-1], features)) + weights[-1]
        probability = _sigmoid(float(logit))
        answers.append(
            BaselineAnswer(
                question_id=row.question_id,
                forecast_id=row.forecast_id,
                probability=probability,
                covariate_hash=_covariate_hash(
                    {
                        "target_logit": features[0],
                        "neighbor_distance": features[1],
                        "head_available": bool(features[2]),
                        "distance_available": bool(features[3]),
                    }
                ),
            )
        )

    return BaselineAnswerSet(
        baseline_id="card_regression_baseline_v1",
        target_id=target_id,
        target_definition_hash=target_definition_hash,
        answers=tuple(answers),
        gaps=tuple(gaps),
        excluded_inputs=tuple(excluded),
    )
