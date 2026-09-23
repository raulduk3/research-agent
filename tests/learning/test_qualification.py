from __future__ import annotations

from hashlib import sha256
from typing import cast
from uuid import UUID

import numpy as np
import pytest

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import EMBEDDING_FEATURE_DIMENSION, TARGET_IDS
from research_agent.learning.calibration import fit_calibrator
from research_agent.learning.fit import (
    DIMENSION,
    MaterializedPartition,
    _sigmoid,
    _standardized_matrix,
    fit_head,
)
from research_agent.learning.qualification import (
    BrierRow,
    CoverageSlice,
    PermutationNullResult,
    PermutationTrial,
    PilotPaper,
    QualificationError,
    TargetQualificationInput,
    evaluate_head_qualification,
    evaluate_modeling_coverage,
    evaluate_pilot_feasibility,
    pairwise_label_association,
    permutation_null,
    qualify_corpus,
)
from research_agent.outcomes.targets import registry

IDENTITY = ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)


# --- acquisition pilot feasibility ------------------------------------------


def _pilot_paper(paper_id: str, *, eligible: bool) -> PilotPaper:
    return PilotPaper(paper_id, eligible, (eligible, eligible, eligible), eligible)


def test_evaluate_pilot_feasibility_passes_at_the_70_of_100_floor() -> None:
    papers = tuple(_pilot_paper(f"p{i}", eligible=i < 70) for i in range(100))
    report = evaluate_pilot_feasibility(100, papers)
    assert report.eligible_count == 70
    assert report.passed


def test_evaluate_pilot_feasibility_fails_below_the_floor() -> None:
    papers = tuple(_pilot_paper(f"p{i}", eligible=i < 69) for i in range(100))
    report = evaluate_pilot_feasibility(100, papers)
    assert not report.passed


def test_evaluate_pilot_feasibility_keeps_shortfalls_in_the_denominator() -> None:
    papers = tuple(_pilot_paper(f"p{i}", eligible=True) for i in range(65))
    report = evaluate_pilot_feasibility(100, papers)
    assert report.acquired_count == 65
    assert report.eligible_count == 65
    assert not report.passed


# --- modeling coverage -------------------------------------------------------


def test_evaluate_modeling_coverage_requires_overall_and_slice_floors() -> None:
    overall = CoverageSlice("overall", 100, 75)
    good_slice = CoverageSlice("cs.AI:2026-03", 40, 25)
    report = evaluate_modeling_coverage(TARGET_IDS[0], overall, (good_slice,))
    assert report.passed


def test_evaluate_modeling_coverage_fails_below_overall_floor() -> None:
    overall = CoverageSlice("overall", 100, 50)
    report = evaluate_modeling_coverage(TARGET_IDS[0], overall, ())
    assert not report.passed


def test_evaluate_modeling_coverage_excludes_sparse_slices_from_the_gate() -> None:
    overall = CoverageSlice("overall", 100, 80)
    sparse_slice = CoverageSlice("q-bio:2026-03", 5, 1)
    report = evaluate_modeling_coverage(TARGET_IDS[0], overall, (sparse_slice,))
    assert report.passed
    assert report.sparse_slice_ids == ("q-bio:2026-03",)


def test_coverage_slice_rejects_covered_above_intended() -> None:
    with pytest.raises(QualificationError, match="cannot exceed"):
        CoverageSlice("overall", 10, 20)


# --- Brier-improvement gate --------------------------------------------------


def _brier_rows(better: bool) -> tuple[BrierRow, ...]:
    families = tuple(
        str(UUID(bytes=sha256(f"brier-{i}".encode()).digest()[:16], version=4))
        for i in range(8)
    )
    weeks = (
        "2026-W01",
        "2026-W01",
        "2026-W01",
        "2026-W01",
        "2026-W02",
        "2026-W02",
        "2026-W02",
        "2026-W02",
    )
    labels = (1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0)
    candidate = (0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1) if better else (0.5,) * 8
    baseline = (0.5,) * 8
    return tuple(
        BrierRow(family, week, cand, base, label)
        for family, week, cand, base, label in zip(
            families, weeks, candidate, baseline, labels, strict=True
        )
    )


def _cluster_map() -> dict[str, frozenset[str]]:
    families = tuple(
        str(UUID(bytes=sha256(f"brier-{i}".encode()).digest()[:16], version=4))
        for i in range(8)
    )
    return {
        "2026-W01": frozenset(families[:4]),
        "2026-W02": frozenset(families[4:]),
    }


def test_evaluate_head_qualification_passes_a_clear_improvement() -> None:
    result = evaluate_head_qualification(
        TARGET_IDS[0], _brier_rows(True), _cluster_map(), resamples=500
    )
    assert result.qualified
    assert result.verdict.verdict == "favorable"


def test_evaluate_head_qualification_fails_an_identical_baseline() -> None:
    result = evaluate_head_qualification(
        TARGET_IDS[0], _brier_rows(False), _cluster_map(), resamples=500
    )
    assert not result.qualified


def test_brier_row_rejects_a_label_outside_zero_or_one() -> None:
    family_id = str(UUID(bytes=sha256(b"brier-invalid").digest()[:16], version=4))
    with pytest.raises(QualificationError, match="0.0 or 1.0"):
        BrierRow(family_id, "2026-W01", 0.5, 0.5, 0.5)


# --- pairwise label association ---------------------------------------------


def _ids(name: str, count: int) -> tuple[str, ...]:
    return tuple(
        str(UUID(bytes=sha256(f"{name}-{index}".encode()).digest()[:16], version=4))
        for index in range(count)
    )


def _bindings() -> tuple[str, str, str, str, str, tuple[str, str, str]]:
    hashes = cast(
        tuple[str, str, str],
        tuple(
            sha256(row.to_canonical_json()).hexdigest()
            for row in registry(_meta()).definitions
        ),
    )
    return (*IDENTITY, hashes)


def _meta() -> RecordMeta:
    return RecordMeta(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        "2026-01-01T00:00:00.000000Z",
    )


def test_pairwise_label_association_reports_all_three_pairs() -> None:
    count = 20
    features = np.zeros((count, DIMENSION), dtype=np.float32)
    features[:, 0] = 1.0
    labels = np.zeros((count, 3), dtype=np.uint8)
    labels[:, 0] = (np.arange(count) % 2).astype(np.uint8)
    labels[:, 1] = labels[:, 0]
    labels[:, 2] = (np.arange(count) % 3 == 0).astype(np.uint8)
    partition = MaterializedPartition(
        features,
        labels,
        np.ones_like(labels),
        _ids("assoc", count),
        "locked_evaluation",
        *_bindings(),
    )
    associations = pairwise_label_association(partition)
    assert len(associations) == 3
    first_second = next(
        item
        for item in associations
        if (item.first_target_id, item.second_target_id)
        == (TARGET_IDS[0], TARGET_IDS[1])
    )
    assert first_second.correlation is not None
    assert first_second.correlation == pytest.approx(1.0)


# --- full-pipeline fixtures for permutation null and qualify_corpus --------


def _partition(name: str, count: int, seed: int) -> MaterializedPartition:
    rng = np.random.default_rng(seed)
    x = np.zeros((count, DIMENSION), dtype=np.float32)
    x[:, :3] = rng.normal(size=(count, 3)).astype(np.float32)
    labels = np.zeros((count, 3), dtype=np.uint8)
    for index in range(3):
        labels[:, index] = ((np.arange(count) + index) % 2).astype(np.uint8)
        x[:, index] += labels[:, index].astype(np.int8) * 2 - 1
    embedding = x[:, :EMBEDDING_FEATURE_DIMENSION]
    norms = np.linalg.norm(embedding.astype(np.float64), axis=1)
    x[:, :EMBEDDING_FEATURE_DIMENSION] = embedding / norms[:, None].astype(np.float32)
    return MaterializedPartition(
        x, labels, np.ones_like(labels), _ids(name, count), name, *_bindings()
    )


def _full_partitions() -> tuple[
    MaterializedPartition,
    MaterializedPartition,
    MaterializedPartition,
    MaterializedPartition,
]:
    return (
        _partition("fit", 220, 11),
        _partition("development", 60, 12),
        _partition("calibration", 60, 13),
        _partition("locked_evaluation", 40, 14),
    )


def _publication_months(
    partitions: tuple[MaterializedPartition, ...],
) -> dict[str, str]:
    months: dict[str, str] = {}
    for partition in partitions:
        for index, family_id in enumerate(partition.family_ids):
            months[family_id] = f"2026-{1 + (index % 3):02d}"
    return months


def _month_cluster_map(months: dict[str, str]) -> dict[str, frozenset[str]]:
    clusters: dict[str, set[str]] = {}
    for family_id, month in months.items():
        clusters.setdefault(month, set()).add(family_id)
    return {month: frozenset(families) for month, families in clusters.items()}


def test_permutation_null_runs_the_real_pipeline_and_reports_a_verdict() -> None:
    fit, development, calibration, locked_evaluation = _full_partitions()
    months = _publication_months((fit, development, calibration, locked_evaluation))
    cluster_map = _month_cluster_map(months)
    target = registry(_meta()).definitions[0]
    result = permutation_null(
        target,
        fit,
        development,
        calibration,
        locked_evaluation,
        months,
        cluster_map,
        permutations=5,
        resamples=200,
    )
    assert result.target_id == target.target_id
    assert result.permutations == 5
    assert len(result.trials) == 5
    assert result.significant_count == sum(
        1 for trial in result.trials if trial.significant
    )
    assert result.passed == (result.p_value >= 0.01 / 3)


def test_permutation_null_result_rejects_inconsistent_significant_count() -> None:
    trials = (PermutationTrial(0, True, 0.1, None),)
    with pytest.raises(QualificationError, match="disagrees with its trials"):
        PermutationNullResult(TARGET_IDS[0], 1, 0, 0.5, True, trials)


def test_qualify_corpus_is_independent_per_target() -> None:
    fit, development, calibration, locked_evaluation = _full_partitions()
    months = _publication_months((fit, development, calibration, locked_evaluation))
    cluster_map = _month_cluster_map(months)
    targets = registry(_meta()).definitions

    pilot = evaluate_pilot_feasibility(
        100, tuple(_pilot_paper(f"p{i}", eligible=True) for i in range(80))
    )

    inputs = []
    for index, target in enumerate(targets):
        overall = CoverageSlice("overall", 100, 80)
        coverage = evaluate_modeling_coverage(target.target_id, overall, ())
        if index == 1:
            inputs.append(
                TargetQualificationInput(
                    target.target_id,
                    coverage,
                    None,
                    "fit failed for this target",
                    (),
                    None,
                )
            )
            continue
        fit_result = fit_head(target, fit, development)
        calibrator_result = fit_calibrator(fit_result, calibration)
        target_index = TARGET_IDS.index(target.target_id)
        known = locked_evaluation.known_mask[:, target_index].astype(bool)
        standardized = _standardized_matrix(
            locked_evaluation.features[known].astype(np.float64),
            fit_result.standardization,
        )
        logits = standardized @ fit_result.weights + fit_result.intercept
        probabilities = _sigmoid(calibrator_result.a * logits + calibrator_result.b)
        labels = locked_evaluation.labels[known, target_index].astype(np.float64)
        family_ids = tuple(
            family_id
            for family_id, include in zip(
                locked_evaluation.family_ids, known, strict=True
            )
            if include
        )
        rows = tuple(
            BrierRow(
                family_id, months[family_id], float(probability), 0.5, float(label)
            )
            for family_id, probability, label in zip(
                family_ids, probabilities, labels, strict=True
            )
        )
        inputs.append(
            TargetQualificationInput(
                target.target_id, coverage, fit_result, None, rows, None
            )
        )

    report = qualify_corpus(
        pilot,
        cast(
            "tuple[TargetQualificationInput, TargetQualificationInput, TargetQualificationInput]",
            tuple(inputs),
        ),
        cluster_map,
        locked_evaluation,
    )
    assert report.outcomes[1].qualified is False
    assert report.outcomes[1].reason == "fit failed for this target"
    other_outcomes = (report.outcomes[0], report.outcomes[2])
    assert any(
        outcome.evaluation_report_id is not None for outcome in other_outcomes
    ) or all(outcome.reason is not None for outcome in other_outcomes)
