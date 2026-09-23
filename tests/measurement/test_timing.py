"""SDD-IN-29: operational latency from UTC pairs, apart from accuracy."""

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.timing import LatencyPair, timing_report


def _at(seconds: int) -> str:
    return f"2026-01-01T{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}.000000Z"


def test_seconds_stage_uses_linear_quantiles() -> None:
    pairs = [LatencyPair(_at(0), _at(d)) for d in (10, 20, 30, 40, 100)]
    summary = timing_report("queue_wait", pairs)
    assert summary.unit == "seconds"
    assert summary.count == 5
    assert summary.median == 30.0
    assert summary.p95 == pytest.approx(88.0)


def test_publication_to_ingest_is_in_hours() -> None:
    summary = timing_report(
        "publication_to_ingest",
        [LatencyPair("2026-01-01T00:00:00.000000Z", "2026-01-01T03:00:00.000000Z")],
    )
    assert summary.unit == "hours" and summary.median == 3.0


def test_absent_and_invalid_endpoints_are_counted_not_imputed() -> None:
    summary = timing_report(
        "ingest_to_card",
        [
            LatencyPair(_at(0), _at(60)),
            LatencyPair(None, _at(60)),
            LatencyPair(_at(0), None),
            LatencyPair(_at(90), _at(60)),
            LatencyPair("yesterday", _at(60)),
        ],
    )
    assert (summary.count, summary.missing_count, summary.invalid_count) == (1, 2, 2)
    assert summary.median == 60.0


def test_no_valid_pair_gives_unavailable_quantiles() -> None:
    summary = timing_report("batch_to_digest", [LatencyPair(None, None)])
    assert (summary.count, summary.median, summary.p95) == (0, None, None)


def test_a_monotonic_or_mixed_clock_domain_is_rejected() -> None:
    with pytest.raises(MeasurementError):
        timing_report(
            "queue_wait", [LatencyPair(_at(0), _at(5), end_clock="monotonic")]
        )
    with pytest.raises(MeasurementError):
        timing_report("not_a_stage", [])
