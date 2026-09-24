"""Report sections: every issued run accounted for (SDD-IN-18, TDD-4.1.22) and agent calibration (SDD-IN-30).

`run_accounting` left-joins a frozen watermark's run specifications against
whatever results storage produced, so a run that never completed still
appears -- scheduled, void, failed or quarantined -- instead of the report
silently narrowing to successful submissions. `calibration_section` attaches
one configuration and target's own reliability table to the report, never a pooled
diagram and never a prediction head's calibration.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_non_negative_int,
    validate_uuid4,
)
from research_agent.measurement import MeasurementError
from research_agent.scoring.calibration import AgentReliabilityBin

RUN_STATES: frozenset[str] = frozenset(
    {"scheduled", "running", "void", "failed", "quarantined", "completed"}
)


@dataclass(frozen=True, slots=True)
class RunSpecification:
    """One run issued a specification as of the report's frozen watermark."""

    run_id: str

    def __post_init__(self) -> None:
        validate_uuid4(self.run_id)


@dataclass(frozen=True, slots=True)
class RunResult:
    """What storage recorded for one issued run, if anything did."""

    run_id: str
    state: str
    missing_result_reason: str | None

    def __post_init__(self) -> None:
        validate_uuid4(self.run_id)
        if self.state not in RUN_STATES:
            raise MeasurementError("state is not a recognized run disposition")
        if self.missing_result_reason is not None:
            validate_non_empty_string(self.missing_result_reason)


@dataclass(frozen=True, slots=True)
class RunAccountingRow:
    """One issued run's reported disposition."""

    run_id: str
    state: str
    missing_result_reason: str | None


@dataclass(frozen=True, slots=True)
class RunAccountingReport:
    """The watermark-frozen accounting of every run specification issued."""

    watermark: int
    rows: tuple[RunAccountingRow, ...]


def run_accounting(
    specifications: Sequence[RunSpecification],
    results: Sequence[RunResult],
    *,
    watermark: int,
) -> RunAccountingReport:
    """Left-join frozen run specifications with results; refuse an incomplete join.

    Every specification appears exactly once, with a missing result reported
    as `scheduled` and an explicit reason rather than omitted. A result
    naming a run id outside the frozen specifications, or the resulting
    run-id count disagreeing with the specifications, means the report
    cannot be committed (SDD-IN-18).
    """

    validate_non_negative_int(watermark)
    spec_ids = [specification.run_id for specification in specifications]
    if len(set(spec_ids)) != len(spec_ids):
        raise MeasurementError("run specifications must not repeat a run id")
    spec_id_set = set(spec_ids)

    results_by_id: dict[str, RunResult] = {}
    for result in results:
        if result.run_id in results_by_id:
            raise MeasurementError("run results must not repeat a run id")
        results_by_id[result.run_id] = result
        if result.run_id not in spec_id_set:
            raise MeasurementError(
                "a result names a run id outside the frozen specifications"
            )

    rows = tuple(
        _row(specification, results_by_id.get(specification.run_id))
        for specification in specifications
    )
    if len({row.run_id for row in rows}) != len(specifications):
        raise MeasurementError(
            "the report's run-id count disagrees with the frozen specifications"
        )
    return RunAccountingReport(watermark=watermark, rows=rows)


def _row(specification: RunSpecification, result: RunResult | None) -> RunAccountingRow:
    if result is None:
        return RunAccountingRow(
            run_id=specification.run_id,
            state="scheduled",
            missing_result_reason="no result recorded",
        )
    return RunAccountingRow(
        run_id=specification.run_id,
        state=result.state,
        missing_result_reason=result.missing_result_reason,
    )


@dataclass(frozen=True, slots=True)
class CalibrationSection:
    """One configuration and target's reliability table at a report watermark."""

    configuration_id: str
    target_definition_hash: str
    watermark: int
    resolved_count: int
    unresolved_count: int
    bins: tuple[AgentReliabilityBin, ...]
    disposition: str


def calibration_section(
    *,
    configuration_id: str,
    target_definition_hash: str,
    watermark: int,
    table: Sequence[AgentReliabilityBin],
    unresolved_count: int,
) -> CalibrationSection:
    """Attach a reliability table with its resolved and unresolved counts.

    The resolved count is the table's own support; a table with none renders as
    unavailable rather than as an empty diagram.
    """

    validate_non_empty_string(configuration_id)
    validate_non_empty_string(target_definition_hash)
    validate_non_negative_int(watermark)
    validate_non_negative_int(unresolved_count)
    resolved = sum(bin_.count for bin_ in table)
    return CalibrationSection(
        configuration_id=configuration_id,
        target_definition_hash=target_definition_hash,
        watermark=watermark,
        resolved_count=resolved,
        unresolved_count=unresolved_count,
        bins=tuple(table),
        disposition="available" if resolved else "unavailable",
    )
