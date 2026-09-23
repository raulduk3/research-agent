"""Prospective vs retrospective prediction-head evaluation (SDD IN-38).

Prospective results require a persisted probability from a qualified
bundle, sealed before its label's outcome window ends, excluding every
family used to fit, tune or calibrate that bundle. Retrospective results
carry looser timing but the same training exclusion and are reported
under a separate denominator, never mixed into the prospective one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.primitives import (
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.models.predict import PredictionArtifact

EVALUATION_KINDS = frozenset({"prospective", "retrospective"})
_BIN_COUNT = 10


class EvaluationError(ValueError):
    """A matched prediction or evaluation report is not admissible."""


@dataclass(frozen=True, slots=True)
class MatchedPrediction:
    """One prediction joined to its resolved label and training membership.

    ``training_family`` marks a family used to fit, tune or calibrate the
    bundle that produced ``prediction``: excluded from every report
    regardless of observation kind (SDD IN-38). Labels resolved
    ``"unknown"`` never join here at all -- a caller filters them out
    before construction, since an unknown label is neither a true nor a
    false observation.
    """

    prediction: PredictionArtifact
    family_id: str
    label_state: str
    label_maturity_at: str
    observation_kind: str
    training_family: bool

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        if self.label_state not in {"true", "false"}:
            raise EvaluationError("matched prediction label state must be resolved")
        validate_utc_instant(self.label_maturity_at)
        if self.observation_kind not in {
            "historical_reconstructed",
            "prospective_maturity",
        }:
            raise EvaluationError("matched prediction observation kind is invalid")

    @property
    def label_value(self) -> float:
        return 1.0 if self.label_state == "true" else 0.0

    def eligible(self, kind: str) -> bool:
        if self.training_family or self.prediction.status != "available":
            return False
        if kind == "prospective":
            return (
                self.observation_kind == "prospective_maturity"
                and self.prediction.available_at < self.label_maturity_at
            )
        if kind == "retrospective":
            return self.observation_kind == "historical_reconstructed"
        raise EvaluationError("evaluation kind is not admitted")


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    """One of the ten fixed equal-width probability bins, with its counts."""

    lower: float
    upper: float
    count: int
    mean_probability: float | None
    mean_outcome: float | None

    def __post_init__(self) -> None:
        if self.count < 0:
            raise EvaluationError("reliability bin count must not be negative")
        if self.count == 0:
            if self.mean_probability is not None or self.mean_outcome is not None:
                raise EvaluationError("an empty reliability bin carries no means")
        elif self.mean_probability is None or self.mean_outcome is None:
            raise EvaluationError("a nonempty reliability bin requires both means")


def _reliability_bins(
    pairs: tuple[tuple[float, float], ...],
) -> tuple[ReliabilityBin, ...]:
    bins: list[ReliabilityBin] = []
    for index in range(_BIN_COUNT):
        lower, upper = index / _BIN_COUNT, (index + 1) / _BIN_COUNT
        members = [
            (probability, outcome)
            for probability, outcome in pairs
            if (lower <= probability < upper)
            or (index == _BIN_COUNT - 1 and probability == 1.0)
        ]
        if not members:
            bins.append(ReliabilityBin(lower, upper, 0, None, None))
            continue
        bins.append(
            ReliabilityBin(
                lower,
                upper,
                len(members),
                math.fsum(p for p, _ in members) / len(members),
                math.fsum(o for _, o in members) / len(members),
            )
        )
    return tuple(bins)


def _average_precision(pairs: tuple[tuple[float, float], ...]) -> float | None:
    positives = sum(1 for _, outcome in pairs if outcome == 1.0)
    if positives == 0:
        return None
    ranked = sorted(pairs, key=lambda pair: -pair[0])
    hits = 0
    precision_sum = 0.0
    for rank, (_, outcome) in enumerate(ranked, start=1):
        if outcome == 1.0:
            hits += 1
            precision_sum += hits / rank
    return precision_sum / positives


@dataclass(frozen=True, slots=True)
class TargetEvaluation:
    """One target's evaluation of one kind: available with metrics, or why not."""

    target_id: str
    evaluation_kind: str
    status: str
    reason: str | None
    support_count: int
    brier_score: float | None
    baseline_brier: float | None
    base_rate_skill: float | None
    average_precision: float | None
    reliability_bins: tuple[ReliabilityBin, ...]
    bundle_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise EvaluationError("target evaluation names an unregistered target")
        if self.evaluation_kind not in EVALUATION_KINDS:
            raise EvaluationError("target evaluation kind is not admitted")
        if self.status not in {"available", "unavailable"}:
            raise EvaluationError("target evaluation status is invalid")
        if self.status == "unavailable":
            if self.support_count != 0 or not self.reason:
                raise EvaluationError(
                    "an unavailable evaluation carries no support and a reason"
                )
            if (
                self.brier_score is not None
                or self.baseline_brier is not None
                or self.base_rate_skill is not None
                or self.average_precision is not None
                or self.reliability_bins
                or self.bundle_hashes
            ):
                raise EvaluationError("an unavailable evaluation carries no metrics")
        else:
            if self.support_count <= 0 or self.reason is not None:
                raise EvaluationError(
                    "an available evaluation carries positive support and no reason"
                )
            if self.brier_score is None or self.baseline_brier is None:
                raise EvaluationError(
                    "an available evaluation requires its Brier scores"
                )
            if len(self.reliability_bins) != _BIN_COUNT:
                raise EvaluationError("reliability report requires ten fixed bins")
            for value in self.bundle_hashes:
                validate_sha256(value)


def _evaluate_target(
    target_id: str, kind: str, matches: tuple[MatchedPrediction, ...], baseline: float
) -> TargetEvaluation:
    eligible = tuple(match for match in matches if match.eligible(kind))
    if not eligible:
        return TargetEvaluation(
            target_id,
            kind,
            "unavailable",
            "no_eligible_predictions",
            0,
            None,
            None,
            None,
            None,
            (),
            (),
        )
    probabilities: list[float] = []
    for match in eligible:
        if match.prediction.probability is None:
            raise EvaluationError("an eligible prediction requires its probability")
        probabilities.append(match.prediction.probability)
    pairs = tuple(
        zip(probabilities, (match.label_value for match in eligible), strict=True)
    )
    brier = math.fsum((p - y) ** 2 for p, y in pairs) / len(pairs)
    baseline_brier = math.fsum((baseline - y) ** 2 for _, y in pairs) / len(pairs)
    skill = None if baseline_brier == 0 else 1.0 - brier / baseline_brier
    bundle_hashes = tuple(sorted({match.prediction.bundle_hash for match in eligible}))
    return TargetEvaluation(
        target_id,
        kind,
        "available",
        None,
        len(pairs),
        brier,
        baseline_brier,
        skill,
        _average_precision(pairs),
        _reliability_bins(pairs),
        bundle_hashes,
    )


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """The complete report: every registry target, both evaluation kinds."""

    evaluations: tuple[TargetEvaluation, ...]

    def __post_init__(self) -> None:
        expected = {
            (target_id, kind) for target_id in TARGET_IDS for kind in EVALUATION_KINDS
        }
        found = {(item.target_id, item.evaluation_kind) for item in self.evaluations}
        if found != expected:
            raise EvaluationError(
                "evaluation report must cover every target and evaluation kind once"
            )

    def for_target(self, target_id: str, kind: str) -> TargetEvaluation:
        for item in self.evaluations:
            if item.target_id == target_id and item.evaluation_kind == kind:
                return item
        raise EvaluationError(f"no evaluation recorded for '{target_id}'/'{kind}'")


def evaluate_predictions(
    matches: tuple[MatchedPrediction, ...], baselines: dict[str, float]
) -> EvaluationReport:
    """Score every registry target's prospective and retrospective evaluation.

    ``baselines`` supplies each target's base-rate baseline probability
    (SDD-FT-11's fitting-partition positive fraction,
    :func:`research_agent.learning.promote.base_rate_baseline`), fixed
    before any evaluation partition is read.
    """

    if set(baselines) != set(TARGET_IDS):
        raise EvaluationError("baselines must cover every registry target")
    evaluations: list[TargetEvaluation] = []
    for target_id in TARGET_IDS:
        target_matches = tuple(
            match for match in matches if match.prediction.target_id == target_id
        )
        for kind in ("prospective", "retrospective"):
            evaluations.append(
                _evaluate_target(target_id, kind, target_matches, baselines[target_id])
            )
    return EvaluationReport(tuple(evaluations))
