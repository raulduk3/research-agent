"""Discovery-service attention: descriptive overlap, and a genome's lead time.

`service_comparison` never computes a Brier loss or skill figure itself; it
only ever attaches one already produced by `research_agent.scoring.scores`,
the shared scorer (SDD-IN-40). `forecast_lead_time` never treats a source's
capture time as its unknowable first recommendation time -- it only asks
whether a genome's forecast crossed the registered threshold strictly before
that capture (SDD-IN-41).
"""

from __future__ import annotations

from collections.abc import Sequence, Set
from dataclasses import dataclass
from datetime import datetime, timezone

from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_probability,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.measurement import MeasurementError
from research_agent.scoring.scores import TargetSkill

LEAD_TIME_TARGET_ID = "citation_reach_365d"
LEAD_TIME_THRESHOLD = 0.75
LEAD_TIME_DISPOSITIONS: frozenset[str] = frozenset(
    {"crossed", "no_crossing", "unavailable_history"}
)


@dataclass(frozen=True, slots=True)
class ServiceComparison:
    """A descriptive record of one discovery service's overlap with the corpus."""

    service_id: str | None
    capture_start: str
    capture_end: str
    overlapping_family_ids: tuple[str, ...]
    rating_coverage: float | None
    forecast_skill: TargetSkill | None
    disposition: str

    def __post_init__(self) -> None:
        validate_utc_instant(self.capture_start)
        validate_utc_instant(self.capture_end)
        if self.capture_start > self.capture_end:
            raise MeasurementError("capture_start must not be after capture_end")
        if self.disposition == "disabled":
            if (
                self.service_id is not None
                or self.overlapping_family_ids
                or self.rating_coverage is not None
                or self.forecast_skill is not None
            ):
                raise MeasurementError("a disabled comparison carries no measurement")
        elif self.disposition == "available":
            if self.service_id is None:
                raise MeasurementError("an available comparison must name its service")
            validate_non_empty_string(self.service_id)
            for family_id in self.overlapping_family_ids:
                validate_uuid4(family_id)
            if self.rating_coverage is not None:
                validate_probability(self.rating_coverage)
            elif self.overlapping_family_ids:
                raise MeasurementError(
                    "an overlap with no coverage figure must carry no overlap"
                )
        else:
            raise MeasurementError("disposition is not a recognized value")


def service_comparison(
    *,
    service_id: str | None,
    capture_start: str,
    capture_end: str,
    picked_family_ids: Sequence[str],
    corpus_family_ids: Set[str],
    rated_family_ids: Set[str],
    forecast_skill: TargetSkill | None = None,
) -> ServiceComparison:
    """Build one service's descriptive overlap and rating coverage.

    Missing source identity disables the comparison outright (SDD-IN-40): no
    overlap, coverage or attached skill is reported for a service that
    cannot be named. `forecast_skill` is never computed here -- callers
    attach the shared scorer's own `TargetSkill`, or none at all.
    """

    if service_id is None:
        return ServiceComparison(
            service_id=None,
            capture_start=capture_start,
            capture_end=capture_end,
            overlapping_family_ids=(),
            rating_coverage=None,
            forecast_skill=None,
            disposition="disabled",
        )
    overlap = tuple(sorted(set(picked_family_ids) & corpus_family_ids))
    coverage = len(set(overlap) & rated_family_ids) / len(overlap) if overlap else None
    return ServiceComparison(
        service_id=service_id,
        capture_start=capture_start,
        capture_end=capture_end,
        overlapping_family_ids=overlap,
        rating_coverage=coverage,
        forecast_skill=forecast_skill,
        disposition="available",
    )


@dataclass(frozen=True, slots=True)
class SealedForecastProbability:
    """One sealed citation_reach_365d probability, ready for the lead-time draw."""

    question_id: str
    configuration_id: str
    probability: float
    sealed_at: str

    def __post_init__(self) -> None:
        validate_uuid4(self.question_id)
        validate_non_empty_string(self.configuration_id)
        validate_probability(self.probability)
        validate_utc_instant(self.sealed_at)


@dataclass(frozen=True, slots=True)
class LeadTime:
    """How many days before a service capture a genome's forecast crossed threshold."""

    source_capture_id: str
    configuration_id: str
    question_id: str | None
    threshold: float
    lead_days: float | None
    disposition: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.source_capture_id)
        validate_non_empty_string(self.configuration_id)
        if self.disposition not in LEAD_TIME_DISPOSITIONS:
            raise MeasurementError("disposition is not a recognized value")
        if self.disposition == "crossed":
            if self.question_id is None or self.lead_days is None:
                raise MeasurementError(
                    "a crossed lead time carries its question and days"
                )
            validate_uuid4(self.question_id)
            if self.lead_days < 0:
                raise MeasurementError("a crossed lead time cannot be negative")
        elif self.question_id is not None or self.lead_days is not None:
            raise MeasurementError(
                "only a crossed lead time carries a question or days"
            )


def forecast_lead_time(
    forecasts: Sequence[SealedForecastProbability],
    *,
    source_capture_id: str,
    capture_at: str,
    configuration_id: str,
) -> LeadTime:
    """Find the earliest sealed forecast that crossed threshold before capture.

    Only forecasts strictly sealed before `capture_at` are eligible, and
    equality is not earlier (SDD-IN-41): a forecast sealed at the exact
    capture instant never counts. No configuration history at all is
    `unavailable_history`; a history that never crossed the preregistered
    0.75 threshold before capture is `no_crossing` -- the two are never
    conflated.
    """

    validate_non_empty_string(source_capture_id)
    validate_non_empty_string(configuration_id)
    capture_instant = _instant(validate_utc_instant(capture_at))
    history = [
        forecast
        for forecast in forecasts
        if forecast.configuration_id == configuration_id
    ]
    if not history:
        return LeadTime(
            source_capture_id=source_capture_id,
            configuration_id=configuration_id,
            question_id=None,
            threshold=LEAD_TIME_THRESHOLD,
            lead_days=None,
            disposition="unavailable_history",
        )
    eligible = [
        forecast
        for forecast in history
        if forecast.probability > LEAD_TIME_THRESHOLD
        and _instant(forecast.sealed_at) < capture_instant
    ]
    if not eligible:
        return LeadTime(
            source_capture_id=source_capture_id,
            configuration_id=configuration_id,
            question_id=None,
            threshold=LEAD_TIME_THRESHOLD,
            lead_days=None,
            disposition="no_crossing",
        )
    earliest = min(eligible, key=lambda forecast: forecast.sealed_at)
    lead_days = (capture_instant - _instant(earliest.sealed_at)).total_seconds() / 86400
    return LeadTime(
        source_capture_id=source_capture_id,
        configuration_id=configuration_id,
        question_id=earliest.question_id,
        threshold=LEAD_TIME_THRESHOLD,
        lead_days=lead_days,
        disposition="crossed",
    )


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
