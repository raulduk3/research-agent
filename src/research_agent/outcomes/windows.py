"""Elapsed-day outcome windows with conservative provider-date intervals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from research_agent.contracts.papers import SourceInterval
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_utc_instant,
)

DAY_SECONDS = 86_400
EVENT_SECONDS = 365 * DAY_SECONDS
MATURITY_SECONDS = 455 * DAY_SECONDS
CAPTURE_ALLOWANCE_SECONDS = DAY_SECONDS
FORECAST_ALLOWANCE_SECONDS = DAY_SECONDS
IntervalMembership = Literal["definite", "possible", "outside"]


def instant(value: str) -> datetime:
    validate_utc_instant(value)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class OutcomeWindow:
    """An open-left, closed-right window relative to the exact original t0."""

    start_seconds_exclusive: int
    end_seconds_inclusive: int

    def __post_init__(self) -> None:
        validate_non_negative_int(self.start_seconds_exclusive)
        validate_non_negative_int(self.end_seconds_inclusive)
        if (
            not self.start_seconds_exclusive
            < self.end_seconds_inclusive
            <= EVENT_SECONDS
        ):
            raise ContractValidationError(
                "outcome window must lie in the first 365 elapsed days"
            )

    def bounds(self, t0: str) -> tuple[datetime, datetime]:
        origin = instant(t0)
        return (
            origin + timedelta(seconds=self.start_seconds_exclusive),
            origin + timedelta(seconds=self.end_seconds_inclusive),
        )

    def classify(self, t0: str, interval: SourceInterval | None) -> IntervalMembership:
        if interval is None:
            return "possible"
        lower, upper = self.bounds(t0)
        start, end = instant(interval.start), instant(interval.end_exclusive)
        if end <= lower or start > upper:
            return "outside"
        if start > lower and end <= upper:
            return "definite"
        return "possible"

    def classify_alternatives(
        self, t0: str, intervals: tuple[SourceInterval, ...]
    ) -> IntervalMembership:
        if not intervals:
            return "possible"
        membership = tuple(self.classify(t0, interval) for interval in intervals)
        if all(value == "definite" for value in membership):
            return "definite"
        if all(value == "outside" for value in membership):
            return "outside"
        return "possible"


FIRST_YEAR = OutcomeWindow(0, EVENT_SECONDS)
FIRST_LATE = OutcomeWindow(180 * DAY_SECONDS, 270 * DAY_SECONDS)
SECOND_LATE = OutcomeWindow(270 * DAY_SECONDS, EVENT_SECONDS)


def maturity_at(t0: str) -> str:
    return utc(instant(t0) + timedelta(seconds=MATURITY_SECONDS))


def forecast_deadline(t0: str) -> str:
    return utc(instant(t0) + timedelta(seconds=FORECAST_ALLOWANCE_SECONDS))


def capture_timing_failure(
    *, t0: str, kind: str, started_at: str, completed_at: str, as_of: str
) -> str | None:
    """Validate availability without backdating historical acquisition."""
    start, end, cutoff = instant(started_at), instant(completed_at), instant(as_of)
    if end < start:
        raise ContractValidationError("capture completion precedes start")
    if kind not in {"historical_reconstructed", "prospective_maturity"}:
        raise ContractValidationError("unknown observation kind")
    maturity = instant(maturity_at(t0))
    if cutoff < maturity or end < maturity:
        return "immature"
    if cutoff < end:
        return "invalid_source"
    if kind == "prospective_maturity" and (
        start < maturity
        or end > maturity + timedelta(seconds=CAPTURE_ALLOWANCE_SECONDS)
    ):
        return "outside_capture_window"
    return None
