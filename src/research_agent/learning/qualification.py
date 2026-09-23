"""Source and label qualification, and the release-study permutation null (SDD-FT-22).

Four gates run in order, and a failed target never borrows another target's
success: the 100-paper acquisition pilot (corpus-wide), per-target modeling
coverage and class-count floors, the locked-evaluation Brier-improvement
comparison under a Bonferroni three-head correction, and the Appendix A
permutation null that blocks a release study when too many within-month
label permutations look spuriously significant. Human semantic annotation
(Jev) is never checked here because it is not required for these targets.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.stats import binomtest  # type: ignore[import-untyped]

from research_agent.contracts import canonical_json
from research_agent.contracts.learning import TARGET_IDS, TargetDefinition
from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_int,
    validate_probability,
    validate_uuid4,
)
from research_agent.learning.calibration import CalibrationResult, fit_calibrator
from research_agent.learning.fit import (
    FitError,
    FitResult,
    MaterializedPartition,
    _sigmoid,
    _standardized_matrix,
    fit_head,
)
from research_agent.learning.promote import base_rate_baseline
from research_agent.measurement.bootstrap import (
    BOOTSTRAP_SEED,
    RESAMPLE_COUNT,
    BootstrapInterval,
    ClusteredDifference,
    bootstrap_difference,
)
from research_agent.measurement.comparisons import IntervalVerdict, interval_verdict

PILOT_INTENDED_COUNT = 100
PILOT_PASS_THRESHOLD = 70
ADEQUATE_SLICE_FAMILIES = 30
OVERALL_COVERAGE_FLOOR = 0.70
SLICE_COVERAGE_FLOOR = 0.50
HEAD_COUNT = 3
FAMILY_ERROR_BUDGET = 0.05
_TAIL_PERCENT = (FAMILY_ERROR_BUDGET / HEAD_COUNT / 2) * 100
PERMUTATION_COUNT = 100
PERMUTATION_NULL_RATE = 0.05
PERMUTATION_ALPHA = 0.01 / HEAD_COUNT
PERMUTATION_LOWER_TAIL = 2.5
PERMUTATION_UPPER_TAIL = 97.5
PERMUTATION_RESAMPLE_COUNT = 2000


class QualificationError(ValueError):
    """A qualification input is not admissible, or its own gates disagree."""


# --- 100-paper acquisition pilot (Appendix B: Bounded acquisition) ----------


@dataclass(frozen=True, slots=True)
class PilotPaper:
    """One pilot paper's source feasibility, for the acquisition-pilot gate."""

    paper_id: str
    complete_original_text: bool
    known_targets: tuple[bool, bool, bool]
    conformance_passed: bool

    def __post_init__(self) -> None:
        validate_non_empty_string(self.paper_id)
        if not isinstance(self.known_targets, tuple) or len(self.known_targets) != 3:
            raise QualificationError(
                "pilot paper known_targets must name all three registry targets"
            )

    @property
    def eligible(self) -> bool:
        return (
            self.complete_original_text
            and all(self.known_targets)
            and self.conformance_passed
        )


@dataclass(frozen=True, slots=True)
class PilotFeasibilityReport:
    """Whether at least 70 of the 100 intended papers pass source feasibility."""

    intended_count: int
    acquired_count: int
    eligible_count: int
    passed: bool

    def __post_init__(self) -> None:
        validate_positive_int(self.intended_count)
        validate_non_negative_int(self.acquired_count)
        validate_non_negative_int(self.eligible_count)
        if self.acquired_count > self.intended_count:
            raise QualificationError(
                "more acquired pilot papers than the intended count"
            )
        if self.eligible_count > self.acquired_count:
            raise QualificationError("more eligible pilot papers than were acquired")
        if self.passed != (self.eligible_count >= PILOT_PASS_THRESHOLD):
            raise QualificationError(
                "pilot feasibility disposition disagrees with its counts"
            )


def evaluate_pilot_feasibility(
    intended_count: int, papers: tuple[PilotPaper, ...]
) -> PilotFeasibilityReport:
    """Shortfalls (fewer than ``intended_count`` acquired) stay in the denominator."""

    if len(papers) > intended_count:
        raise QualificationError("more pilot papers were preserved than intended")
    eligible_count = sum(1 for paper in papers if paper.eligible)
    return PilotFeasibilityReport(
        intended_count,
        len(papers),
        eligible_count,
        eligible_count >= PILOT_PASS_THRESHOLD,
    )


# --- Modeling coverage and sparse-slice gates -------------------------------


@dataclass(frozen=True, slots=True)
class CoverageSlice:
    """One denominator slice: an overall count, or one primary-category/month slice."""

    slice_id: str
    intended_count: int
    covered_count: int

    def __post_init__(self) -> None:
        validate_non_empty_string(self.slice_id)
        validate_non_negative_int(self.intended_count)
        validate_non_negative_int(self.covered_count)
        if self.covered_count > self.intended_count:
            raise QualificationError(
                "a slice's covered count cannot exceed its intended count"
            )

    @property
    def coverage_fraction(self) -> float:
        if self.intended_count == 0:
            return 0.0
        return self.covered_count / self.intended_count

    @property
    def adequately_sampled(self) -> bool:
        return self.intended_count >= ADEQUATE_SLICE_FAMILIES


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """One target's coverage gate: >=70% overall, >=50% in every adequately sampled slice."""

    target_id: str
    overall: CoverageSlice
    slices: tuple[CoverageSlice, ...]
    passed: bool
    sparse_slice_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise QualificationError("coverage report names an unregistered target")


def evaluate_modeling_coverage(
    target_id: str, overall: CoverageSlice, slices: tuple[CoverageSlice, ...]
) -> CoverageReport:
    """Sparse slices (below the 30-family floor) are unqualified but reported, never hidden."""

    if target_id not in TARGET_IDS:
        raise QualificationError("coverage evaluation names an unregistered target")
    adequate = tuple(item for item in slices if item.adequately_sampled)
    sparse = tuple(item.slice_id for item in slices if not item.adequately_sampled)
    passed = overall.coverage_fraction >= OVERALL_COVERAGE_FLOOR and all(
        item.coverage_fraction >= SLICE_COVERAGE_FLOOR for item in adequate
    )
    return CoverageReport(target_id, overall, slices, passed, sparse)


# --- Locked-evaluation Brier-improvement gate (Bonferroni across 3 heads) --


@dataclass(frozen=True, slots=True)
class BrierRow:
    """One locked-evaluation row's candidate/baseline probabilities and outcome."""

    family_id: str
    publication_week: str
    candidate_probability: float
    baseline_probability: float
    label: float

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        validate_non_empty_string(self.publication_week)
        validate_probability(self.candidate_probability)
        validate_probability(self.baseline_probability)
        if self.label not in (0.0, 1.0):
            raise QualificationError("a Brier row's label must be exactly 0.0 or 1.0")

    @property
    def difference(self) -> float:
        return (self.candidate_probability - self.label) ** 2 - (
            self.baseline_probability - self.label
        ) ** 2


def _clustered(rows: tuple[BrierRow, ...]) -> Sequence[ClusteredDifference]:
    """``BrierRow`` is frozen and structurally matches ``ClusteredDifference``.

    mypy's Protocol variance rules require a *settable* attribute for
    ``ClusteredDifference``'s plain-typed fields, which a frozen dataclass
    can never offer; ``bootstrap_difference`` only ever reads these fields,
    so the cast is sound.
    """

    return cast("Sequence[ClusteredDifference]", rows)


@dataclass(frozen=True, slots=True)
class HeadQualificationResult:
    """Whether one target's candidate clears the Bonferroni-adjusted Brier gate."""

    target_id: str
    qualified: bool
    verdict: IntervalVerdict
    interval: BootstrapInterval

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise QualificationError("head qualification names an unregistered target")
        if self.qualified != (self.verdict.verdict == "favorable"):
            raise QualificationError(
                "head qualification disagrees with its own verdict"
            )


def evaluate_head_qualification(
    target_id: str,
    rows: tuple[BrierRow, ...],
    cluster_map: Mapping[str, frozenset[str]],
    *,
    resamples: int = RESAMPLE_COUNT,
    seed: int = BOOTSTRAP_SEED,
) -> HeadQualificationResult:
    """Require the upper bound of a paired 98.33...% bootstrap interval below zero.

    ``_TAIL_PERCENT`` allocates the 5% family error budget across the three
    launch prediction heads (Bonferroni), giving a central interval of
    ``100 - 2 * _TAIL_PERCENT`` percent -- 98.333333% at the fixed budget.
    """

    if target_id not in TARGET_IDS:
        raise QualificationError(
            "head qualification evaluation names an unregistered target"
        )
    interval = bootstrap_difference(
        _clustered(rows),
        cluster_map,
        lower_tail=_TAIL_PERCENT,
        upper_tail=100 - _TAIL_PERCENT,
        seed=seed,
        resamples=resamples,
    )
    verdict = interval_verdict(interval.low, interval.high, favorable_direction="lower")
    return HeadQualificationResult(
        target_id, verdict.verdict == "favorable", verdict, interval
    )


# --- Pairwise label association ("different but correlated") ---------------


@dataclass(frozen=True, slots=True)
class TargetPairAssociation:
    """Pearson correlation between two targets' known labels, for the record."""

    first_target_id: str
    second_target_id: str
    support_count: int
    correlation: float | None

    def __post_init__(self) -> None:
        if (
            self.first_target_id not in TARGET_IDS
            or self.second_target_id not in TARGET_IDS
        ):
            raise QualificationError(
                "pairwise association names an unregistered target"
            )
        if TARGET_IDS.index(self.first_target_id) >= TARGET_IDS.index(
            self.second_target_id
        ):
            raise QualificationError(
                "pairwise association must name targets in registry order"
            )
        validate_non_negative_int(self.support_count)
        if (
            self.correlation is not None
            and not -1.0 - 1e-9 <= self.correlation <= 1.0 + 1e-9
        ):
            raise QualificationError("pairwise correlation must lie within [-1, 1]")


def pairwise_label_association(
    locked_evaluation: MaterializedPartition,
) -> tuple[TargetPairAssociation, ...]:
    """Report every target pair's label correlation; never fold into one score."""

    results = []
    for first_index, second_index in itertools.combinations(range(len(TARGET_IDS)), 2):
        both_known = locked_evaluation.known_mask[:, first_index].astype(
            bool
        ) & locked_evaluation.known_mask[:, second_index].astype(bool)
        support = int(both_known.sum())
        correlation: float | None = None
        if support >= 2:
            first = locked_evaluation.labels[both_known, first_index].astype(np.float64)
            second = locked_evaluation.labels[both_known, second_index].astype(
                np.float64
            )
            if first.std() > 0 and second.std() > 0:
                correlation = float(np.corrcoef(first, second)[0, 1])
        results.append(
            TargetPairAssociation(
                TARGET_IDS[first_index], TARGET_IDS[second_index], support, correlation
            )
        )
    return tuple(results)


# --- Appendix A permutation null --------------------------------------------


@dataclass(frozen=True, slots=True)
class PermutationTrial:
    """One within-month label permutation's outcome: a null-loss estimate or a failure."""

    index: int
    significant: bool
    estimate: float | None
    failure: str | None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise QualificationError("a permutation trial index must be non-negative")
        if self.failure is not None and (self.significant or self.estimate is not None):
            raise QualificationError(
                "a failed permutation trial carries no estimate or significance"
            )
        if self.failure is None and self.estimate is None:
            raise QualificationError(
                "a completed permutation trial requires its estimate"
            )


@dataclass(frozen=True, slots=True)
class PermutationNullResult:
    """One target's permutation-null verdict: does the release study proceed."""

    target_id: str
    permutations: int
    significant_count: int
    p_value: float
    passed: bool
    trials: tuple[PermutationTrial, ...]

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise QualificationError(
                "permutation null result names an unregistered target"
            )
        if self.permutations <= 0 or len(self.trials) != self.permutations:
            raise QualificationError(
                "permutation null result trial count is inconsistent"
            )
        if self.significant_count != sum(
            1 for trial in self.trials if trial.significant
        ):
            raise QualificationError(
                "permutation null significant count disagrees with its trials"
            )
        if not 0.0 <= self.p_value <= 1.0:
            raise QualificationError("permutation null p-value must lie within [0, 1]")
        if self.passed != (self.p_value >= PERMUTATION_ALPHA):
            raise QualificationError(
                "permutation null disposition disagrees with its p-value"
            )


def _spawn_rngs(
    seed: np.random.SeedSequence, count: int
) -> tuple[np.random.Generator, ...]:
    return tuple(np.random.default_rng(child) for child in seed.spawn(count))


def _permute_labels_within_month(
    partition: MaterializedPartition,
    target_index: int,
    months: Mapping[str, str],
    rng: np.random.Generator,
) -> MaterializedPartition:
    """Shuffle one target's known labels among families sharing a publication month.

    Per-month base rates are preserved exactly; the family-to-label mapping
    is randomized, destroying any real feature/label relationship while
    leaving class counts (and so the fit/development/calibration floors)
    unchanged.
    """

    labels = partition.labels.copy()
    groups: dict[str, list[int]] = {}
    for row in np.flatnonzero(partition.known_mask[:, target_index]):
        family_id = partition.family_ids[int(row)]
        month = months.get(family_id)
        if month is None:
            raise QualificationError(
                "a materialized row has no publication month for permutation"
            )
        groups.setdefault(month, []).append(int(row))
    for rows in groups.values():
        values = labels[rows, target_index].copy()
        rng.shuffle(values)
        labels[rows, target_index] = values
    return MaterializedPartition(
        partition.features,
        labels,
        partition.known_mask,
        partition.family_ids,
        partition.partition,
        partition.corpus_release_hash,
        partition.split_hash,
        partition.target_registry_hash,
        partition.representation_hash,
        partition.solver_runtime_hash,
        partition.target_definition_hashes,
    )


def _score_partition(
    fit: FitResult, calibrator: CalibrationResult, partition: MaterializedPartition
) -> tuple[tuple[str, ...], NDArray[np.float64], NDArray[np.float64]]:
    index = TARGET_IDS.index(fit.target_id)
    known = partition.known_mask[:, index].astype(bool)
    standardized = _standardized_matrix(
        partition.features[known].astype(np.float64), fit.standardization
    )
    logits = standardized @ fit.weights + fit.intercept
    probabilities = _sigmoid(calibrator.a * logits + calibrator.b)
    labels = partition.labels[known, index].astype(np.float64)
    family_ids = tuple(
        family_id
        for family_id, include in zip(partition.family_ids, known, strict=True)
        if include
    )
    return family_ids, probabilities, labels


def _permutation_trial(
    index: int,
    target: TargetDefinition,
    fit: MaterializedPartition,
    development: MaterializedPartition,
    calibration: MaterializedPartition,
    locked_evaluation: MaterializedPartition,
    months: Mapping[str, str],
    cluster_map: Mapping[str, frozenset[str]],
    seed: np.random.SeedSequence,
    resamples: int,
) -> PermutationTrial:
    target_index = TARGET_IDS.index(target.target_id)
    fit_rng, dev_rng, cal_rng, eval_rng, interval_rng = _spawn_rngs(seed, 5)
    permuted_fit = _permute_labels_within_month(fit, target_index, months, fit_rng)
    permuted_dev = _permute_labels_within_month(
        development, target_index, months, dev_rng
    )
    permuted_cal = _permute_labels_within_month(
        calibration, target_index, months, cal_rng
    )
    permuted_eval = _permute_labels_within_month(
        locked_evaluation, target_index, months, eval_rng
    )
    try:
        fit_result = fit_head(target, permuted_fit, permuted_dev)
        calibrator = fit_calibrator(fit_result, permuted_cal)
    except FitError as error:
        return PermutationTrial(index, False, None, str(error))
    baseline = base_rate_baseline(permuted_fit, target.target_id)
    family_ids, probabilities, labels = _score_partition(
        fit_result, calibrator, permuted_eval
    )
    rows = tuple(
        BrierRow(
            family_id, months[family_id], float(probability), baseline, float(label)
        )
        for family_id, probability, label in zip(
            family_ids, probabilities, labels, strict=True
        )
    )
    interval_seed = int(interval_rng.integers(0, 2**31 - 1))
    interval = bootstrap_difference(
        _clustered(rows),
        cluster_map,
        lower_tail=PERMUTATION_LOWER_TAIL,
        upper_tail=PERMUTATION_UPPER_TAIL,
        seed=interval_seed,
        resamples=resamples,
    )
    verdict = interval_verdict(interval.low, interval.high, favorable_direction="lower")
    return PermutationTrial(
        index, verdict.verdict == "favorable", interval.estimate, None
    )


def permutation_null(
    target: TargetDefinition,
    fit: MaterializedPartition,
    development: MaterializedPartition,
    calibration: MaterializedPartition,
    locked_evaluation: MaterializedPartition,
    publication_months: Mapping[str, str],
    cluster_map: Mapping[str, frozenset[str]],
    *,
    permutations: int = PERMUTATION_COUNT,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = PERMUTATION_RESAMPLE_COUNT,
) -> PermutationNullResult:
    """Run ``permutations`` independent within-month label permutations for one target.

    Each trial refits, recalibrates and re-evaluates the whole pipeline on
    labels permuted within their publication month, with RNG streams
    separated across fit, development, calibration and evaluation so no
    trial's randomness leaks into another partition. The count of trials
    that "look significant" against real labels must be compatible with
    ``Binomial(permutations, 0.05)`` under an exact upper-tail test at
    ``0.01 / 3``; failure blocks a release study pending leakage
    investigation (Appendix A: Launch profile).
    """

    if permutations <= 0:
        raise QualificationError(
            "permutation null requires a positive permutation count"
        )
    master = np.random.SeedSequence(seed)
    trial_seeds = master.spawn(permutations)
    trials = tuple(
        _permutation_trial(
            i,
            target,
            fit,
            development,
            calibration,
            locked_evaluation,
            publication_months,
            cluster_map,
            trial_seeds[i],
            resamples,
        )
        for i in range(permutations)
    )
    significant_count = sum(1 for trial in trials if trial.significant)
    p_value = float(
        binomtest(
            significant_count,
            permutations,
            PERMUTATION_NULL_RATE,
            alternative="greater",
        ).pvalue
    )
    passed = p_value >= PERMUTATION_ALPHA
    return PermutationNullResult(
        target.target_id, permutations, significant_count, p_value, passed, trials
    )


# --- Top-level qualification report ----------------------------------------


@dataclass(frozen=True, slots=True)
class TargetQualificationInput:
    """One target's already-computed pieces, ready for the qualification gate."""

    target_id: str
    coverage: CoverageReport
    fit: FitResult | None
    fit_failure_reason: str | None
    brier_rows: tuple[BrierRow, ...]
    permutation: PermutationNullResult | None

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise QualificationError("qualification input names an unregistered target")
        if self.coverage.target_id != self.target_id:
            raise QualificationError(
                "qualification input coverage names a different target"
            )
        if (self.fit is None) == (self.fit_failure_reason is None):
            raise QualificationError(
                "a qualification input requires exactly one of a fit or its failure reason"
            )
        if (
            self.permutation is not None
            and self.permutation.target_id != self.target_id
        ):
            raise QualificationError(
                "qualification input permutation names a different target"
            )


@dataclass(frozen=True, slots=True)
class TargetQualificationOutcome:
    """One target's final qualified/unavailable disposition, and why."""

    target_id: str
    qualified: bool
    reason: str | None
    coverage: CoverageReport
    brier: HeadQualificationResult | None
    permutation: PermutationNullResult | None
    evaluation_report_id: str | None

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise QualificationError(
                "qualification outcome names an unregistered target"
            )
        if self.qualified:
            if (
                self.reason is not None
                or self.brier is None
                or not self.brier.qualified
                or self.evaluation_report_id is None
            ):
                raise QualificationError(
                    "a qualified outcome requires a passing Brier gate and its report id"
                )
        elif self.reason is None:
            raise QualificationError("an unqualified outcome requires a reason")


@dataclass(frozen=True, slots=True)
class QualificationReport:
    """The registry-ordered qualification disposition for one release or refresh."""

    pilot: PilotFeasibilityReport
    outcomes: tuple[
        TargetQualificationOutcome,
        TargetQualificationOutcome,
        TargetQualificationOutcome,
    ]
    associations: tuple[TargetPairAssociation, ...]
    exclusions: tuple[str, ...]
    costs: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if tuple(item.target_id for item in self.outcomes) != TARGET_IDS:
            raise QualificationError(
                "qualification report outcomes must cover the registry in order"
            )


def _evaluation_report_id(
    target_id: str,
    brier: HeadQualificationResult,
    permutation: PermutationNullResult | None,
) -> str:
    payload = {
        "target_id": target_id,
        "brier_support_hash": brier.interval.support_hash,
        "permutation": None
        if permutation is None
        else {
            "permutations": permutation.permutations,
            "significant_count": permutation.significant_count,
        },
    }
    return sha256(canonical_json(payload)).hexdigest()


def qualify_corpus(
    pilot: PilotFeasibilityReport,
    inputs: tuple[
        TargetQualificationInput, TargetQualificationInput, TargetQualificationInput
    ],
    cluster_map: Mapping[str, frozenset[str]],
    locked_evaluation: MaterializedPartition,
    *,
    exclusions: tuple[str, ...] = (),
    costs: tuple[tuple[str, float], ...] = (),
    resamples: int = RESAMPLE_COUNT,
    seed: int = BOOTSTRAP_SEED,
) -> QualificationReport:
    """Evaluate all three registry targets' qualification gates, independently.

    Acquisition feasibility (the pilot) is corpus-wide and gates every
    target equally; from there, each target's coverage, Brier-improvement
    and permutation-null gates are evaluated on its own inputs alone, so a
    failed target never borrows another target's success (SDD-FT-22).
    """

    if tuple(item.target_id for item in inputs) != TARGET_IDS:
        raise QualificationError(
            "qualification inputs must cover the registry in order"
        )
    outcomes: list[TargetQualificationOutcome] = []
    for item in inputs:
        if not pilot.passed:
            outcomes.append(
                TargetQualificationOutcome(
                    item.target_id,
                    False,
                    "acquisition pilot failed source feasibility",
                    item.coverage,
                    None,
                    None,
                    None,
                )
            )
            continue
        if item.fit is None:
            outcomes.append(
                TargetQualificationOutcome(
                    item.target_id,
                    False,
                    item.fit_failure_reason or "fit unavailable",
                    item.coverage,
                    None,
                    None,
                    None,
                )
            )
            continue
        if not item.coverage.passed:
            outcomes.append(
                TargetQualificationOutcome(
                    item.target_id,
                    False,
                    "insufficient modeling coverage",
                    item.coverage,
                    None,
                    None,
                    None,
                )
            )
            continue
        brier = evaluate_head_qualification(
            item.target_id, item.brier_rows, cluster_map, resamples=resamples, seed=seed
        )
        if not brier.qualified:
            outcomes.append(
                TargetQualificationOutcome(
                    item.target_id,
                    False,
                    "locked evaluation Brier improvement not established",
                    item.coverage,
                    brier,
                    item.permutation,
                    None,
                )
            )
            continue
        if item.permutation is not None and not item.permutation.passed:
            outcomes.append(
                TargetQualificationOutcome(
                    item.target_id,
                    False,
                    "permutation null indicates leakage",
                    item.coverage,
                    brier,
                    item.permutation,
                    None,
                )
            )
            continue
        outcomes.append(
            TargetQualificationOutcome(
                item.target_id,
                True,
                None,
                item.coverage,
                brier,
                item.permutation,
                _evaluation_report_id(item.target_id, brier, item.permutation),
            )
        )
    associations = pairwise_label_association(locked_evaluation)
    return QualificationReport(
        pilot,
        cast(
            "tuple[TargetQualificationOutcome, TargetQualificationOutcome, TargetQualificationOutcome]",
            tuple(outcomes),
        ),
        associations,
        exclusions,
        costs,
    )
