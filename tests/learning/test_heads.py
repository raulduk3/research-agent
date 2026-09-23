from __future__ import annotations

from hashlib import sha256
from typing import cast
from uuid import UUID

import numpy as np
import pytest

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import EMBEDDING_FEATURE_DIMENSION, TARGET_IDS
from research_agent.learning.fit import (
    DIMENSION,
    FitError,
    FitResult,
    MaterializedPartition,
)
from research_agent.learning.heads import (
    CalibratedHead,
    HeadUnavailable,
    ThreeHeadCalibration,
    ThreeHeadFit,
    calibrate_three_heads,
    fit_three_heads,
)
from research_agent.learning.promote import (
    HeldOutEvaluation,
    PromotionDecision,
    base_rate_baseline,
    decide_promotion,
    evaluate_head,
    promote_three_heads,
)
from research_agent.outcomes.targets import registry

IDENTITY = ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)


def _meta() -> RecordMeta:
    return RecordMeta(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        "2026-01-01T00:00:00.000000Z",
    )


def _registry_definitions() -> tuple:
    return registry(_meta()).definitions


def _bindings() -> tuple[str, str, str, str, str, tuple[str, str, str]]:
    hashes = cast(
        tuple[str, str, str],
        tuple(
            sha256(row.to_canonical_json()).hexdigest()
            for row in _registry_definitions()
        ),
    )
    return (*IDENTITY, hashes)


def _ids(name: str, count: int) -> tuple[str, ...]:
    return tuple(
        str(UUID(bytes=sha256(f"{name}-{index}".encode()).digest()[:16], version=4))
        for index in range(count)
    )


def _partition(name: str, count: int, seed: int) -> MaterializedPartition:
    """Build a partition whose three label columns are independently informative.

    Each target's positive class is driven by its own feature dimension, so
    the three labels are genuinely distinct signals, not copies of one
    another (SDD-FT-08's co-occurring, independent events).
    """

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


def _partitions(
    seed_offset: int = 0,
) -> tuple[MaterializedPartition, MaterializedPartition, MaterializedPartition]:
    return (
        _partition("fit", 220, 1 + seed_offset),
        _partition("development", 60, 2 + seed_offset),
        _partition("calibration", 60, 3 + seed_offset),
    )


# --- fit_three_heads (SDD-FT-08) --------------------------------------------


def test_fit_three_heads_fits_all_three_in_registry_order() -> None:
    fit, development, _ = _partitions()
    result = fit_three_heads(registry(_meta()), fit, development)
    assert isinstance(result, ThreeHeadFit)
    assert tuple(item.target_id for item in result.fitted) == TARGET_IDS
    assert all(isinstance(item, FitResult) for item in result.fitted)


def test_fitting_one_target_is_invariant_to_the_labels_of_the_other_two() -> None:
    """The three events can co-occur: each head reads only its own label column."""

    fit_a, development_a, _ = _partitions(seed_offset=10)
    flipped_labels = fit_a.labels.copy()
    flipped_labels[:, 1] = 1 - flipped_labels[:, 1]
    flipped_labels[:, 2] = 1 - flipped_labels[:, 2]
    fit_b = MaterializedPartition(
        fit_a.features,
        flipped_labels,
        fit_a.known_mask,
        fit_a.family_ids,
        "fit",
        *_bindings(),
    )
    reg = registry(_meta())
    result_a = fit_three_heads(reg, fit_a, development_a)
    result_b = fit_three_heads(reg, fit_b, development_a)
    head_a = cast(FitResult, result_a.fitted[0])
    head_b = cast(FitResult, result_b.fitted[0])
    assert np.array_equal(head_a.weights, head_b.weights)
    assert head_a.intercept == head_b.intercept
    assert head_a.selected_lambda == head_b.selected_lambda


def test_a_failed_target_does_not_block_the_other_two() -> None:
    fit, development, _ = _partitions(seed_offset=20)
    zeroed_labels = fit.labels.copy()
    zeroed_labels[:, 0] = 0
    broken_fit = MaterializedPartition(
        fit.features, zeroed_labels, fit.known_mask, fit.family_ids, "fit", *_bindings()
    )
    result = fit_three_heads(registry(_meta()), broken_fit, development)
    assert isinstance(result.fitted[0], HeadUnavailable)
    assert result.fitted[0].target_id == "citation_reach_365d"
    assert "insufficient fit" in result.fitted[0].reason
    assert isinstance(result.fitted[1], FitResult)
    assert isinstance(result.fitted[2], FitResult)


def test_overview_only_feature_width_is_refused_before_fitting() -> None:
    x = np.zeros((4, 768), dtype=np.float32)
    x[:, 0] = 1
    labels = np.zeros((4, 3), dtype=np.uint8)
    with pytest.raises(FitError, match=r"\[N,1553\]"):
        MaterializedPartition(
            x, labels, np.ones_like(labels), _ids("fit", 4), "fit", *_bindings()
        )


# --- calibrate_three_heads (SDD-FT-11) --------------------------------------


def test_calibrate_three_heads_calibrates_every_fitted_head() -> None:
    fit, development, calibration = _partitions(seed_offset=30)
    fitted = fit_three_heads(registry(_meta()), fit, development)
    result = calibrate_three_heads(fitted, calibration)
    assert isinstance(result, ThreeHeadCalibration)
    assert tuple(item.target_id for item in result.calibrated) == TARGET_IDS
    for item in result.calibrated:
        assert isinstance(item, CalibratedHead)
        assert item.calibrator.a >= 0
        assert item.calibrator.converged


def test_a_target_that_never_fit_stays_unavailable_after_calibration() -> None:
    fit, development, calibration = _partitions(seed_offset=40)
    zeroed_labels = fit.labels.copy()
    zeroed_labels[:, 1] = 0
    broken_fit = MaterializedPartition(
        fit.features, zeroed_labels, fit.known_mask, fit.family_ids, "fit", *_bindings()
    )
    fitted = fit_three_heads(registry(_meta()), broken_fit, development)
    result = calibrate_three_heads(fitted, calibration)
    assert isinstance(result.calibrated[1], HeadUnavailable)
    assert result.calibrated[1].target_id == "late_citation_activity_365d"


def test_a_target_whose_calibration_families_overlap_is_demoted_unavailable() -> None:
    fit, development, _ = _partitions(seed_offset=50)
    fitted = fit_three_heads(registry(_meta()), fit, development)
    overlapping = MaterializedPartition(
        fit.features[:60],
        fit.labels[:60],
        fit.known_mask[:60],
        fit.family_ids[:60],
        "calibration",
        *_bindings(),
    )
    result = calibrate_three_heads(fitted, overlapping)
    assert all(isinstance(item, HeadUnavailable) for item in result.calibrated)


# --- promote.py: base_rate_baseline and evaluate_head (SDD-FT-11) ----------


def test_base_rate_baseline_is_the_fitting_partition_positive_fraction() -> None:
    fit, _, _ = _partitions(seed_offset=60)
    assert base_rate_baseline(fit, "citation_reach_365d") == pytest.approx(0.5)


def test_base_rate_baseline_requires_the_fitting_partition() -> None:
    _, development, _ = _partitions(seed_offset=61)
    with pytest.raises(FitError, match="fitting partition"):
        base_rate_baseline(development, "citation_reach_365d")


def test_evaluate_head_scores_the_heads_own_development_support() -> None:
    fit, development, calibration = _partitions(seed_offset=70)
    fitted = fit_three_heads(registry(_meta()), fit, development)
    calibrated = calibrate_three_heads(fitted, calibration)
    head = cast(CalibratedHead, calibrated.calibrated[0])
    evaluation = evaluate_head(head, fit, development)
    assert isinstance(evaluation, HeldOutEvaluation)
    assert evaluation.target_id == "citation_reach_365d"
    assert evaluation.support_count == len(head.head.development_family_ids)
    assert 0.0 <= evaluation.candidate_brier <= 1.0
    assert evaluation.baseline_probability == pytest.approx(0.5)


def test_evaluate_head_never_mutates_the_head_or_calibrator_it_reads() -> None:
    fit, development, calibration = _partitions(seed_offset=71)
    fitted = fit_three_heads(registry(_meta()), fit, development)
    calibrated = calibrate_three_heads(fitted, calibration)
    head = cast(CalibratedHead, calibrated.calibrated[0])
    before_weights = head.head.weights.copy()
    before_a, before_b = head.calibrator.a, head.calibrator.b
    relabeled = development.labels.copy()
    relabeled[:, 0] = 1 - relabeled[:, 0]
    changed = MaterializedPartition(
        development.features,
        relabeled,
        development.known_mask,
        development.family_ids,
        "development",
        *_bindings(),
    )
    evaluate_head(head, fit, changed)
    assert np.array_equal(head.head.weights, before_weights)
    assert (head.calibrator.a, head.calibrator.b) == (before_a, before_b)


def test_evaluate_head_refuses_a_development_partition_with_different_support() -> None:
    fit, development, calibration = _partitions(seed_offset=72)
    fitted = fit_three_heads(registry(_meta()), fit, development)
    calibrated = calibrate_three_heads(fitted, calibration)
    head = cast(CalibratedHead, calibrated.calibrated[0])
    narrower = MaterializedPartition(
        development.features[:10],
        development.labels[:10],
        development.known_mask[:10],
        development.family_ids[:10],
        "development",
        *_bindings(),
    )
    with pytest.raises(FitError, match="monitoring set"):
        evaluate_head(head, fit, narrower)


# --- promote.py: decide_promotion and promote_three_heads (FT-11 / #115) ---


def _evaluation(
    target_id: str, candidate: float, baseline: float = 0.25
) -> HeldOutEvaluation:
    return HeldOutEvaluation(target_id, 0.5, candidate, baseline, 30, "d" * 64)


def test_candidate_beating_baseline_with_no_incumbent_is_promoted() -> None:
    decision = decide_promotion(_evaluation("citation_reach_365d", 0.10), None)
    assert isinstance(decision, PromotionDecision)
    assert decision.promoted
    assert decision.reason == "promoted"


def test_candidate_not_beating_baseline_is_refused() -> None:
    decision = decide_promotion(_evaluation("citation_reach_365d", 0.30), None)
    assert not decision.promoted
    assert decision.reason == "below_baseline_requirement"


def test_candidate_worse_than_incumbent_is_refused_even_if_it_beats_baseline() -> None:
    incumbent = _evaluation("citation_reach_365d", 0.05)
    decision = decide_promotion(_evaluation("citation_reach_365d", 0.10), incumbent)
    assert not decision.promoted
    assert decision.reason == "worse_than_incumbent"


def test_candidate_tying_the_incumbent_is_promoted_zero_tolerance_threshold() -> None:
    incumbent = _evaluation("citation_reach_365d", 0.10)
    decision = decide_promotion(_evaluation("citation_reach_365d", 0.10), incumbent)
    assert decision.promoted
    assert decision.reason == "promoted"


def test_decide_promotion_rejects_an_incumbent_for_a_different_target() -> None:
    incumbent = _evaluation("late_citation_activity_365d", 0.05)
    with pytest.raises(FitError, match="different head"):
        decide_promotion(_evaluation("citation_reach_365d", 0.10), incumbent)


def test_promote_three_heads_refuses_an_unavailable_target_without_scoring() -> None:
    fit, development, calibration = _partitions(seed_offset=80)
    zeroed_labels = fit.labels.copy()
    zeroed_labels[:, 2] = 0
    broken_fit = MaterializedPartition(
        fit.features, zeroed_labels, fit.known_mask, fit.family_ids, "fit", *_bindings()
    )
    fitted = fit_three_heads(registry(_meta()), broken_fit, development)
    calibrated = calibrate_three_heads(fitted, calibration)
    decisions = promote_three_heads(calibrated, broken_fit, development)
    assert len(decisions) == 3
    assert decisions[2].target_id == "cross_subfield_reach_365d"
    assert decisions[2].reason == "unavailable"
    assert decisions[2].evaluation is None
    assert decisions[0].reason in {"promoted", "below_baseline_requirement"}


def test_promote_three_heads_rejects_a_mismatched_incumbent_count() -> None:
    fit, development, calibration = _partitions(seed_offset=81)
    fitted = fit_three_heads(registry(_meta()), fit, development)
    calibrated = calibrate_three_heads(fitted, calibration)
    short_incumbents = cast(
        "tuple[HeldOutEvaluation | None, HeldOutEvaluation | None, HeldOutEvaluation | None]",
        (None, None),
    )
    with pytest.raises(FitError, match="registry in order"):
        promote_three_heads(calibrated, fit, development, short_incumbents)
