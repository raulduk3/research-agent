"""SDD-IN-18: every issued run accounted for, not only the successful ones."""

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.reports import (
    RunResult,
    RunSpecification,
    run_accounting,
)

RUN_A = "11111111-1111-4111-8111-111111111111"
RUN_B = "22222222-2222-4222-8222-222222222222"
RUN_C = "33333333-3333-4333-8333-333333333333"
RUN_D = "44444444-4444-4444-8444-444444444444"


def test_void_and_unfinished_runs_are_reported_not_only_successes() -> None:
    specifications = [
        RunSpecification(RUN_A),
        RunSpecification(RUN_B),
        RunSpecification(RUN_C),
        RunSpecification(RUN_D),
    ]
    results = [
        RunResult(RUN_A, "completed", None),
        RunResult(RUN_B, "void", "no submit before deadline"),
        # RUN_C has no result at all: still unfinished.
        RunResult(RUN_D, "quarantined", "lineage excluded"),
    ]
    report = run_accounting(specifications, results, watermark=42)
    assert len(report.rows) == len(specifications)
    states = {row.run_id: row.state for row in report.rows}
    assert states[RUN_A] == "completed"
    assert states[RUN_B] == "void"
    assert states[RUN_C] == "scheduled"
    assert states[RUN_D] == "quarantined"
    missing = next(row for row in report.rows if row.run_id == RUN_C)
    assert missing.missing_result_reason is not None


def test_report_count_matches_issued_specifications() -> None:
    specifications = [RunSpecification(RUN_A), RunSpecification(RUN_B)]
    report = run_accounting(specifications, [], watermark=1)
    assert len({row.run_id for row in report.rows}) == len(specifications)


def test_a_result_outside_the_frozen_specifications_is_refused() -> None:
    specifications = [RunSpecification(RUN_A)]
    results = [RunResult(RUN_B, "completed", None)]
    with pytest.raises(MeasurementError):
        run_accounting(specifications, results, watermark=1)


def test_duplicate_run_ids_in_specifications_are_refused() -> None:
    with pytest.raises(MeasurementError):
        run_accounting(
            [RunSpecification(RUN_A), RunSpecification(RUN_A)], [], watermark=1
        )


def test_duplicate_run_ids_in_results_are_refused() -> None:
    specifications = [RunSpecification(RUN_A)]
    results = [
        RunResult(RUN_A, "completed", None),
        RunResult(RUN_A, "failed", "duplicate report"),
    ]
    with pytest.raises(MeasurementError):
        run_accounting(specifications, results, watermark=1)


def test_run_result_state_must_be_recognized() -> None:
    with pytest.raises(MeasurementError):
        RunResult(RUN_A, "unknown_state", None)
