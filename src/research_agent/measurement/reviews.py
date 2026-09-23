"""The weekly frozen spot-check sample of sealed forecasts (SDD-IN-11, TDD-4.1.14).

`sample_forecasts` hash-ranks the pool the same way every week: calling it
again with an unchanged pool, even in a different input order, reproduces the
identical membership, so a forecast left unassessed is never quietly swapped
for another. Recording a verdict is a separate, independent step -- this
module never reads its own output back to decide who is in the sample.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_uuid4,
)
from research_agent.measurement import MeasurementError

SAMPLE_LIMIT = 5
VERDICTS: frozenset[str] = frozenset({"supported", "unsupported", "unassessable"})


@dataclass(frozen=True, slots=True)
class SealedForecast:
    """One sealed forecast eligible for the spot-check draw."""

    forecast_id: str
    island: str

    def __post_init__(self) -> None:
        validate_uuid4(self.forecast_id)
        validate_non_empty_string(self.island)


@dataclass(frozen=True, slots=True)
class ReviewSample:
    """The frozen spot-check draw for one ISO week, before any verdict is recorded."""

    profile_id: str
    iso_week: str
    selected: tuple[SealedForecast, ...]
    shortfall: int


def sample_forecasts(
    sealed_forecasts: Sequence[SealedForecast], *, profile_id: str, iso_week: str
) -> ReviewSample:
    """Hash-rank the sealed pool of all islands and take the first five, or fewer.

    Ranking depends only on `profile_id`, `iso_week` and each forecast id, so
    the draw is independent of `sealed_forecasts`' input order and of which
    island a forecast belongs to (SDD-IN-11: "the human does not choose which
    forecasts are sampled").
    """

    validate_non_empty_string(profile_id)
    validate_non_empty_string(iso_week)
    forecast_ids = [forecast.forecast_id for forecast in sealed_forecasts]
    if len(set(forecast_ids)) != len(forecast_ids):
        raise MeasurementError("sealed forecasts must not repeat a forecast id")
    ranked = sorted(
        sealed_forecasts,
        key=lambda forecast: (
            _rank_key(profile_id, iso_week, forecast.forecast_id),
            forecast.forecast_id,
        ),
    )
    selected = tuple(ranked[:SAMPLE_LIMIT])
    return ReviewSample(
        profile_id=profile_id,
        iso_week=iso_week,
        selected=selected,
        shortfall=SAMPLE_LIMIT - len(selected),
    )


def _rank_key(profile_id: str, iso_week: str, forecast_id: str) -> str:
    return sha256(f"{profile_id}:{iso_week}:{forecast_id}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ReviewVerdict:
    """One reviewer's disposition on whether cited evidence supports a forecast."""

    forecast_id: str
    reviewer_id: str
    verdict: str
    evidence_references: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_uuid4(self.forecast_id)
        validate_non_empty_string(self.reviewer_id)
        if self.verdict not in VERDICTS:
            raise MeasurementError("verdict is not a recognized value")
        if not self.evidence_references:
            raise MeasurementError("a verdict requires at least one evidence reference")


def record_verdict(
    forecast_id: str,
    *,
    reviewer_id: str,
    verdict: str,
    evidence_references: Sequence[str],
) -> ReviewVerdict:
    """Construct one reviewer's verdict; an absent verdict is simply never built."""

    return ReviewVerdict(
        forecast_id=forecast_id,
        reviewer_id=reviewer_id,
        verdict=verdict,
        evidence_references=tuple(evidence_references),
    )


@dataclass(frozen=True, slots=True)
class SupportReport:
    """Evidence-support figures for one frozen sample; the ratio may be absent."""

    sampled_count: int
    supported_count: int
    unsupported_count: int
    unassessable_count: int
    unchecked_count: int
    assessable_count: int
    unsupported_share: float | None


def support_report(
    sample: ReviewSample, verdicts: Sequence[ReviewVerdict]
) -> SupportReport:
    """Join a frozen sample to its verdicts and report unsupported/assessable.

    Unassessable and unchecked forecasts change coverage, never the ratio, and a
    verdict for a forecast outside the sample is refused rather than counted.
    """

    sampled = {forecast.forecast_id for forecast in sample.selected}
    by_forecast: dict[str, ReviewVerdict] = {}
    for verdict in verdicts:
        if verdict.forecast_id not in sampled:
            raise MeasurementError("a verdict names a forecast outside the sample")
        if verdict.forecast_id in by_forecast:
            raise MeasurementError("a forecast carries more than one verdict")
        by_forecast[verdict.forecast_id] = verdict
    tally = {name: 0 for name in VERDICTS}
    for verdict in by_forecast.values():
        tally[verdict.verdict] += 1
    assessable = tally["supported"] + tally["unsupported"]
    return SupportReport(
        sampled_count=len(sampled),
        supported_count=tally["supported"],
        unsupported_count=tally["unsupported"],
        unassessable_count=tally["unassessable"],
        unchecked_count=len(sampled) - len(by_forecast),
        assessable_count=assessable,
        unsupported_share=tally["unsupported"] / assessable if assessable else None,
    )
