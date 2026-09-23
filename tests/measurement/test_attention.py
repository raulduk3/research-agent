"""SDD-IN-40, SDD-IN-41: descriptive service attention, kept apart from skill."""

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.attention import (
    LEAD_TIME_THRESHOLD,
    SealedForecastProbability,
    forecast_lead_time,
    service_comparison,
)
from research_agent.scoring.scores import TargetSkill

FAMILY_A = "11111111-1111-4111-8111-111111111111"
FAMILY_B = "22222222-2222-4222-8222-222222222222"
QUESTION_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
QUESTION_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CAPTURE_START = "2026-02-01T00:00:00.000000Z"
CAPTURE_END = "2026-02-07T00:00:00.000000Z"


def test_service_picks_without_probabilities_get_coverage_but_no_skill() -> None:
    result = service_comparison(
        service_id="hf-daily-papers",
        capture_start=CAPTURE_START,
        capture_end=CAPTURE_END,
        picked_family_ids=[FAMILY_A, FAMILY_B],
        corpus_family_ids={FAMILY_A, FAMILY_B},
        rated_family_ids={FAMILY_A},
    )
    assert result.disposition == "available"
    assert result.overlapping_family_ids == (FAMILY_A, FAMILY_B)
    assert result.rating_coverage == pytest.approx(0.5)
    assert result.forecast_skill is None


def test_missing_source_identity_disables_the_comparison() -> None:
    result = service_comparison(
        service_id=None,
        capture_start=CAPTURE_START,
        capture_end=CAPTURE_END,
        picked_family_ids=[FAMILY_A],
        corpus_family_ids={FAMILY_A},
        rated_family_ids=set(),
    )
    assert result.disposition == "disabled"
    assert result.service_id is None
    assert result.overlapping_family_ids == ()
    assert result.rating_coverage is None
    assert result.forecast_skill is None


def test_no_overlap_leaves_coverage_unavailable_not_zero() -> None:
    result = service_comparison(
        service_id="hf-daily-papers",
        capture_start=CAPTURE_START,
        capture_end=CAPTURE_END,
        picked_family_ids=[FAMILY_A],
        corpus_family_ids={FAMILY_B},
        rated_family_ids=set(),
    )
    assert result.overlapping_family_ids == ()
    assert result.rating_coverage is None


def test_forecast_skill_attaches_only_the_shared_scorers_own_record() -> None:
    skill = TargetSkill(
        target_id="citation_reach_365d",
        agent_producer_id="genome-1",
        baseline_producer_id="base-rate",
        support_count=0,
        agent_mean_brier=None,
        baseline_mean_brier=None,
        skill=None,
        disposition="unavailable",
        skill_per_dollar=None,
        cost_microdollars=None,
        cost_record_ids=(),
        cost_disposition="unavailable",
    )
    result = service_comparison(
        service_id="hf-daily-papers",
        capture_start=CAPTURE_START,
        capture_end=CAPTURE_END,
        picked_family_ids=[FAMILY_A],
        corpus_family_ids={FAMILY_A},
        rated_family_ids=set(),
        forecast_skill=skill,
    )
    assert result.forecast_skill is skill


def test_capture_start_must_not_be_after_capture_end() -> None:
    with pytest.raises(MeasurementError):
        service_comparison(
            service_id="hf-daily-papers",
            capture_start=CAPTURE_END,
            capture_end=CAPTURE_START,
            picked_family_ids=[],
            corpus_family_ids=set(),
            rated_family_ids=set(),
        )


def _forecast(
    probability: float, sealed_at: str, question_id: str = QUESTION_A
) -> SealedForecastProbability:
    return SealedForecastProbability(
        question_id=question_id,
        configuration_id="genome-1",
        probability=probability,
        sealed_at=sealed_at,
    )


def test_threshold_boundary_at_p_0_75_does_not_cross() -> None:
    forecasts = [_forecast(LEAD_TIME_THRESHOLD, "2026-01-01T00:00:00.000000Z")]
    result = forecast_lead_time(
        forecasts,
        source_capture_id="capture-1",
        capture_at="2026-01-05T00:00:00.000000Z",
        configuration_id="genome-1",
    )
    assert result.disposition == "no_crossing"


def test_probability_above_threshold_crosses() -> None:
    forecasts = [_forecast(0.76, "2026-01-01T00:00:00.000000Z")]
    result = forecast_lead_time(
        forecasts,
        source_capture_id="capture-1",
        capture_at="2026-01-05T00:00:00.000000Z",
        configuration_id="genome-1",
    )
    assert result.disposition == "crossed"
    assert result.lead_days == pytest.approx(4.0)
    assert result.question_id == QUESTION_A


def test_sealed_at_equal_to_capture_at_does_not_count() -> None:
    same_instant = "2026-01-05T00:00:00.000000Z"
    forecasts = [_forecast(0.9, same_instant)]
    result = forecast_lead_time(
        forecasts,
        source_capture_id="capture-1",
        capture_at=same_instant,
        configuration_id="genome-1",
    )
    assert result.disposition == "no_crossing"


def test_a_later_favorable_forecast_is_never_counted() -> None:
    forecasts = [_forecast(0.9, "2026-01-10T00:00:00.000000Z")]
    result = forecast_lead_time(
        forecasts,
        source_capture_id="capture-1",
        capture_at="2026-01-05T00:00:00.000000Z",
        configuration_id="genome-1",
    )
    assert result.disposition == "no_crossing"


def test_earliest_crossing_forecast_is_selected() -> None:
    forecasts = [
        _forecast(0.80, "2026-01-03T00:00:00.000000Z", question_id=QUESTION_A),
        _forecast(0.90, "2026-01-01T00:00:00.000000Z", question_id=QUESTION_B),
    ]
    result = forecast_lead_time(
        forecasts,
        source_capture_id="capture-1",
        capture_at="2026-01-05T00:00:00.000000Z",
        configuration_id="genome-1",
    )
    assert result.question_id == QUESTION_B
    assert result.lead_days == pytest.approx(4.0)


def test_no_history_for_the_configuration_is_unavailable() -> None:
    result = forecast_lead_time(
        [],
        source_capture_id="capture-1",
        capture_at="2026-01-05T00:00:00.000000Z",
        configuration_id="genome-1",
    )
    assert result.disposition == "unavailable_history"


def test_history_for_a_different_configuration_is_unavailable_not_no_crossing() -> None:
    forecasts = [_forecast(0.9, "2026-01-01T00:00:00.000000Z")]
    result = forecast_lead_time(
        forecasts,
        source_capture_id="capture-1",
        capture_at="2026-01-05T00:00:00.000000Z",
        configuration_id="a-different-genome",
    )
    assert result.disposition == "unavailable_history"
