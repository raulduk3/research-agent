"""Operational latency summaries, kept apart from forecast accuracy (SDD-IN-29).

Every duration comes from a pair of UTC instants. A monotonic reading is never
converted into one, and an absent or invalid endpoint is counted, not imputed.
These figures are not a measure of how well timing is predicted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_utc_instant,
)
from research_agent.measurement import MeasurementError

UTC_CLOCK = "utc"
STAGE_UNITS: dict[str, str] = {
    "publication_to_ingest": "hours",
    "ingest_to_card": "seconds",
    "queue_wait": "seconds",
    "first_model_call_to_submit": "seconds",
    "batch_to_digest": "seconds",
}
_SECONDS_PER_UNIT = {"hours": 3600.0, "seconds": 1.0}


@dataclass(frozen=True, slots=True)
class LatencyPair:
    """The two endpoints of one stage; either may be absent."""

    start: str | None
    end: str | None
    start_clock: str = UTC_CLOCK
    end_clock: str = UTC_CLOCK


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Count, missing/invalid count and quantiles of one stage's durations."""

    stage: str
    unit: str
    count: int
    missing_count: int
    invalid_count: int
    median: float | None
    p95: float | None


def _instant(value: str) -> datetime:
    validate_utc_instant(value)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


def timing_report(stage: str, pairs: Sequence[LatencyPair]) -> LatencySummary:
    """Summarize one stage's durations with linear-interpolated median and p95."""

    unit = STAGE_UNITS.get(stage)
    if unit is None:
        raise MeasurementError("stage is not a recognized latency stage")
    durations: list[float] = []
    missing = 0
    invalid = 0
    for pair in pairs:
        if pair.start_clock != UTC_CLOCK or pair.end_clock != UTC_CLOCK:
            raise MeasurementError("latency endpoints must both be UTC instants")
        if pair.start is None or pair.end is None:
            missing += 1
            continue
        try:
            elapsed = (_instant(pair.end) - _instant(pair.start)).total_seconds()
        except ContractValidationError:
            invalid += 1
            continue
        if elapsed < 0:
            invalid += 1
            continue
        durations.append(elapsed / _SECONDS_PER_UNIT[unit])
    values = np.asarray(durations, dtype=np.float64)
    return LatencySummary(
        stage=stage,
        unit=unit,
        count=len(durations),
        missing_count=missing,
        invalid_count=invalid,
        median=float(np.quantile(values, 0.5, method="linear")) if durations else None,
        p95=float(np.quantile(values, 0.95, method="linear")) if durations else None,
    )
