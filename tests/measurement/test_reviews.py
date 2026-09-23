"""SDD-IN-11: a frozen, hand-picked-proof spot-check sample of sealed forecasts."""

import random

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.reviews import (
    SAMPLE_LIMIT,
    SealedForecast,
    record_verdict,
    sample_forecasts,
)

ISLANDS = ("cs", "quant-ph", "q-bio")


def _forecast(n: int) -> SealedForecast:
    return SealedForecast(
        forecast_id=f"{n:08x}-0000-4000-8000-000000000000",
        island=ISLANDS[n % len(ISLANDS)],
    )


def test_sample_membership_is_independent_of_input_order() -> None:
    forecasts = [_forecast(n) for n in range(20)]
    forward = sample_forecasts(forecasts, profile_id="rater-1", iso_week="2026-W10")
    shuffled = forecasts[:]
    random.Random(3).shuffle(shuffled)
    reordered = sample_forecasts(shuffled, profile_id="rater-1", iso_week="2026-W10")
    assert set(f.forecast_id for f in forward.selected) == set(
        f.forecast_id for f in reordered.selected
    )
    assert forward.selected == reordered.selected


def test_sample_is_seeded_by_profile_and_week() -> None:
    forecasts = [_forecast(n) for n in range(20)]
    one_profile = sample_forecasts(forecasts, profile_id="rater-1", iso_week="2026-W10")
    other_profile = sample_forecasts(
        forecasts, profile_id="rater-2", iso_week="2026-W10"
    )
    other_week = sample_forecasts(forecasts, profile_id="rater-1", iso_week="2026-W11")
    assert one_profile.selected != other_profile.selected
    assert one_profile.selected != other_week.selected


def test_sample_takes_first_five_or_fewer() -> None:
    forecasts = [_forecast(n) for n in range(20)]
    sample = sample_forecasts(forecasts, profile_id="rater-1", iso_week="2026-W10")
    assert len(sample.selected) == SAMPLE_LIMIT
    assert sample.shortfall == 0

    short_pool = [_forecast(n) for n in range(3)]
    short_sample = sample_forecasts(
        short_pool, profile_id="rater-1", iso_week="2026-W10"
    )
    assert len(short_sample.selected) == 3
    assert short_sample.shortfall == SAMPLE_LIMIT - 3


def test_sample_spans_all_islands_without_favoring_one() -> None:
    forecasts = [_forecast(n) for n in range(20)]
    sample = sample_forecasts(forecasts, profile_id="rater-1", iso_week="2026-W10")
    assert {member.island for member in sample.selected} <= set(ISLANDS)


def test_no_replacement_after_an_unassessable_or_unanswered_review() -> None:
    # sample_forecasts never reads a verdict, so recomputing the sample from
    # the same pool always reproduces the identical membership regardless of
    # what any member's review outcome was.
    forecasts = [_forecast(n) for n in range(20)]
    first = sample_forecasts(forecasts, profile_id="rater-1", iso_week="2026-W10")
    unassessable = record_verdict(
        first.selected[0].forecast_id,
        reviewer_id="reviewer-1",
        verdict="unassessable",
        evidence_references=("evidence-1",),
    )
    assert unassessable.forecast_id == first.selected[0].forecast_id
    second = sample_forecasts(forecasts, profile_id="rater-1", iso_week="2026-W10")
    assert first.selected == second.selected


def test_duplicate_forecast_ids_are_refused() -> None:
    duplicate = [_forecast(0), _forecast(0)]
    with pytest.raises(MeasurementError):
        sample_forecasts(duplicate, profile_id="rater-1", iso_week="2026-W10")


def test_verdict_requires_a_recognized_value() -> None:
    with pytest.raises(MeasurementError):
        record_verdict(
            _forecast(0).forecast_id,
            reviewer_id="reviewer-1",
            verdict="maybe",
            evidence_references=("evidence-1",),
        )


def test_verdict_requires_at_least_one_evidence_reference() -> None:
    with pytest.raises(MeasurementError):
        record_verdict(
            _forecast(0).forecast_id,
            reviewer_id="reviewer-1",
            verdict="supported",
            evidence_references=(),
        )
