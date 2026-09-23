"""SDD-IN-15: one clustered resampling routine, shared by every comparison."""

import random
from dataclasses import dataclass
from itertools import combinations_with_replacement

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.bootstrap import (
    BOOTSTRAP_SEED,
    BootstrapInterval,
    bootstrap_difference,
)

FAMILY_A = "family-a"
FAMILY_B = "family-b"
FAMILY_C = "family-c"


@dataclass(frozen=True, slots=True)
class Row:
    publication_week: str
    family_id: str
    difference: float


def _rows() -> tuple[Row, ...]:
    return (
        Row("2026-W01", FAMILY_A, 0.10),
        Row("2026-W01", FAMILY_B, -0.05),
        Row("2026-W02", FAMILY_A, 0.20),
        Row("2026-W03", FAMILY_C, -0.30),
        Row("2026-W03", FAMILY_A, 0.05),
    )


def _cluster_map() -> dict[str, frozenset[str]]:
    return {
        "2026-W01": frozenset({FAMILY_A, FAMILY_B}),
        "2026-W02": frozenset({FAMILY_A}),
        "2026-W03": frozenset({FAMILY_A, FAMILY_C}),
    }


def test_result_is_invariant_to_row_permutation() -> None:
    rows = list(_rows())
    baseline = bootstrap_difference(
        rows, _cluster_map(), lower_tail=2.5, upper_tail=97.5
    )
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    permuted = bootstrap_difference(
        shuffled, _cluster_map(), lower_tail=2.5, upper_tail=97.5
    )
    assert permuted == baseline


def test_a_drawn_week_carries_every_family_together() -> None:
    # Week 2026-W01 has two families (sum 0.05, count 2), 2026-W02 has one
    # (sum 0.20, count 1) and 2026-W03 has two (sum -0.25, count 2). With one
    # resample of three weeks drawn with replacement, the only reachable
    # estimates are sums/counts of whole weeks combined -- never a value
    # that would require splitting a week's two families apart, such as
    # counting 2026-W01's 0.10 family alone without its -0.05 family.
    week_sum = {0: 0.05, 1: 0.20, 2: -0.25}
    week_count = {0: 2, 1: 1, 2: 2}
    reachable = set()
    for combo in combinations_with_replacement((0, 1, 2), 3):
        total = sum(week_sum[i] for i in combo)
        count = sum(week_count[i] for i in combo)
        reachable.add(round(total / count, 9))

    result = bootstrap_difference(
        _rows(), _cluster_map(), lower_tail=0.0, upper_tail=100.0, resamples=1
    )
    assert result.low == result.high
    assert result.low is not None
    assert round(result.low, 9) in reachable


def test_analytic_constant_difference_collapses_to_that_constant() -> None:
    rows = (
        Row("2026-W01", FAMILY_A, 0.42),
        Row("2026-W01", FAMILY_B, 0.42),
        Row("2026-W02", FAMILY_A, 0.42),
        Row("2026-W03", FAMILY_C, 0.42),
    )
    cluster_map = {
        "2026-W01": frozenset({FAMILY_A, FAMILY_B}),
        "2026-W02": frozenset({FAMILY_A}),
        "2026-W03": frozenset({FAMILY_C}),
    }
    result = bootstrap_difference(rows, cluster_map, lower_tail=2.5, upper_tail=97.5)
    assert result.disposition == "available"
    assert result.estimate == pytest.approx(0.42)
    assert result.low == pytest.approx(0.42)
    assert result.high == pytest.approx(0.42)


def test_empty_rows_are_unavailable() -> None:
    result = bootstrap_difference((), {}, lower_tail=2.5, upper_tail=97.5)
    assert result.disposition == "unavailable"
    assert result.estimate is None
    assert result.low is None
    assert result.high is None


def test_a_row_outside_the_cluster_map_is_refused() -> None:
    rows = (Row("2026-W99", FAMILY_A, 0.1),)
    with pytest.raises(MeasurementError):
        bootstrap_difference(rows, _cluster_map(), lower_tail=2.5, upper_tail=97.5)


def test_a_family_outside_its_weeks_cluster_is_refused() -> None:
    rows = (Row("2026-W02", FAMILY_B, 0.1),)  # W02's cluster is family A only
    with pytest.raises(MeasurementError):
        bootstrap_difference(rows, _cluster_map(), lower_tail=2.5, upper_tail=97.5)


def test_tails_must_be_ordered_within_0_to_100() -> None:
    with pytest.raises(MeasurementError):
        bootstrap_difference(_rows(), _cluster_map(), lower_tail=97.5, upper_tail=2.5)


def test_default_seed_matches_the_launch_profile() -> None:
    assert BOOTSTRAP_SEED == 20260920


def test_same_seed_reproduces_the_identical_interval() -> None:
    first = bootstrap_difference(
        _rows(), _cluster_map(), lower_tail=2.5, upper_tail=97.5
    )
    second = bootstrap_difference(
        _rows(), _cluster_map(), lower_tail=2.5, upper_tail=97.5
    )
    assert first == second


def test_available_interval_preserves_method_and_support_identity() -> None:
    result = bootstrap_difference(
        _rows(), _cluster_map(), lower_tail=2.5, upper_tail=97.5
    )
    assert isinstance(result, BootstrapInterval)
    assert result.method == "percentile_bootstrap"
    assert result.support_count == len(_rows())
    assert len(result.support_hash) == 64
