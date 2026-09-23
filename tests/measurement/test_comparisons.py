"""SDD-IN-14, SDD-IN-16: the forecast as the unit of analysis, and its verdict."""

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.comparisons import (
    ForecastObservation,
    interval_verdict,
    paired_forecast_rows,
    pooled_mean_difference,
)

FAMILY_A = "11111111-1111-4111-8111-111111111111"
FAMILY_B = "22222222-2222-4222-8222-222222222222"
WEEK = "2026-W10"


def _question(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-000000000000"


def _observation(
    n: int, *, run_id: str, family_id: str, loss: float
) -> ForecastObservation:
    return ForecastObservation(
        question_id=_question(n),
        run_id=run_id,
        family_id=family_id,
        publication_week=WEEK,
        loss=loss,
    )


def test_pooled_forecast_difference_disagrees_with_average_run_difference() -> None:
    # Run "heavy" contributes three forecasts all favoring the candidate by a
    # little; run "light" contributes one forecast favoring the baseline by a
    # lot. Pooling by forecast is dragged toward "heavy"; averaging per-run
    # differences first would weight both runs equally and land elsewhere.
    candidate = [
        _observation(1, run_id="heavy", family_id=FAMILY_A, loss=0.10),
        _observation(2, run_id="heavy", family_id=FAMILY_A, loss=0.10),
        _observation(3, run_id="heavy", family_id=FAMILY_A, loss=0.10),
        _observation(4, run_id="light", family_id=FAMILY_B, loss=0.90),
    ]
    baseline = [
        _observation(1, run_id="ref", family_id=FAMILY_A, loss=0.20),
        _observation(2, run_id="ref", family_id=FAMILY_A, loss=0.20),
        _observation(3, run_id="ref", family_id=FAMILY_A, loss=0.20),
        _observation(4, run_id="ref", family_id=FAMILY_B, loss=0.10),
    ]
    row_set = paired_forecast_rows(candidate, baseline)
    assert row_set.matched_count == 4
    pooled = pooled_mean_difference(row_set.rows)
    heavy_mean = (
        sum(r.difference for r in row_set.rows if r.candidate_run_id == "heavy") / 3
    )
    light_mean = (
        sum(r.difference for r in row_set.rows if r.candidate_run_id == "light") / 1
    )
    average_of_run_means = (heavy_mean + light_mean) / 2
    assert pooled != pytest.approx(average_of_run_means)
    assert pooled == pytest.approx(sum(r.difference for r in row_set.rows) / 4)


def test_omitted_support_is_counted_and_named() -> None:
    candidate = [_observation(1, run_id="a", family_id=FAMILY_A, loss=0.1)]
    baseline = [
        _observation(1, run_id="ref", family_id=FAMILY_A, loss=0.2),
        _observation(2, run_id="ref", family_id=FAMILY_A, loss=0.3),
    ]
    row_set = paired_forecast_rows(candidate, baseline)
    assert row_set.candidate_count == 1
    assert row_set.baseline_count == 2
    assert row_set.matched_count == 1
    assert row_set.candidate_only_question_ids == ()
    assert row_set.baseline_only_question_ids == (_question(2),)


def test_a_side_cannot_repeat_a_question_id() -> None:
    duplicate = [
        _observation(1, run_id="a", family_id=FAMILY_A, loss=0.1),
        _observation(1, run_id="a", family_id=FAMILY_A, loss=0.2),
    ]
    with pytest.raises(MeasurementError):
        paired_forecast_rows(duplicate, [])


def test_matched_question_must_agree_on_family_and_week() -> None:
    candidate = [_observation(1, run_id="a", family_id=FAMILY_A, loss=0.1)]
    baseline = [
        ForecastObservation(
            question_id=_question(1),
            run_id="ref",
            family_id=FAMILY_B,
            publication_week=WEEK,
            loss=0.2,
        )
    ]
    with pytest.raises(MeasurementError):
        paired_forecast_rows(candidate, baseline)


def test_no_rows_pool_to_no_difference() -> None:
    assert pooled_mean_difference(()) is None


def test_interval_touching_zero_is_inconclusive() -> None:
    verdict = interval_verdict(0.0, 0.05, favorable_direction="lower")
    assert verdict.verdict == "inconclusive"
    verdict = interval_verdict(-0.05, 0.0, favorable_direction="higher")
    assert verdict.verdict == "inconclusive"


def test_wide_interval_around_large_estimate_crossing_zero_is_inconclusive() -> None:
    verdict = interval_verdict(-1000.0, 2000.0, favorable_direction="lower")
    assert verdict.verdict == "inconclusive"


def test_reversed_bounds_are_refused() -> None:
    with pytest.raises(MeasurementError):
        interval_verdict(0.5, -0.5, favorable_direction="lower")


def test_missing_bounds_are_unavailable() -> None:
    verdict = interval_verdict(None, None, favorable_direction="lower")
    assert verdict.verdict == "unavailable"


def test_favorable_direction_lower_needs_a_negative_interval() -> None:
    verdict = interval_verdict(-0.2, -0.05, favorable_direction="lower")
    assert verdict.verdict == "favorable"
    verdict = interval_verdict(0.05, 0.2, favorable_direction="lower")
    assert verdict.verdict == "unfavorable"


def test_favorable_direction_higher_needs_a_positive_interval() -> None:
    verdict = interval_verdict(0.05, 0.2, favorable_direction="higher")
    assert verdict.verdict == "favorable"
    verdict = interval_verdict(-0.2, -0.05, favorable_direction="higher")
    assert verdict.verdict == "unfavorable"


def test_minimum_effect_pass_requires_clearing_the_registered_margin() -> None:
    small = interval_verdict(
        -0.02, -0.01, favorable_direction="lower", minimum_effect=0.05
    )
    assert small.verdict == "favorable"
    assert small.minimum_effect_pass is False

    large = interval_verdict(
        -0.2, -0.1, favorable_direction="lower", minimum_effect=0.05
    )
    assert large.verdict == "favorable"
    assert large.minimum_effect_pass is True


def test_no_equivalence_verdict_without_a_registered_margin() -> None:
    verdict = interval_verdict(-0.01, 0.01, favorable_direction="lower")
    assert verdict.verdict == "inconclusive"
    assert verdict.minimum_effect_pass is None
