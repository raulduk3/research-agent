"""Coverage arithmetic that retains intended denominators and per-head masks."""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts import validate_uuid4


@dataclass(frozen=True, slots=True)
class FamilySupport:
    family_id: str
    source_available: bool
    features_complete: bool
    labels_known: tuple[bool, bool, bool]

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        if (
            type(self.source_available) is not bool
            or type(self.features_complete) is not bool
        ):
            raise ValueError("coverage states must be booleans")
        if len(self.labels_known) != 3 or any(
            type(value) is not bool for value in self.labels_known
        ):
            raise ValueError("coverage requires three boolean target masks")
        if self.features_complete and not self.source_available:
            raise ValueError(
                "complete original features require available original source"
            )


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    intended: int
    selected: int
    source_available: int
    features_complete: int
    known_labels: tuple[int, int, int]
    jointly_eligible: tuple[int, int, int]
    shortfall: int

    @property
    def pilot_coverage_met(self) -> bool:
        # This is arithmetic only, never a source-feasibility qualification report.
        return self.intended == 100 and all(
            value >= 70 for value in self.jointly_eligible
        )


def summarize_support(
    rows: tuple[FamilySupport, ...], *, intended: int
) -> CoverageSummary:
    if type(intended) is not int or intended <= 0:
        raise ValueError("intended population must be a positive integer")
    if len(rows) > intended or len({row.family_id for row in rows}) != len(rows):
        raise ValueError("selected families exceed the denominator or repeat")
    known = tuple(sum(row.labels_known[index] for row in rows) for index in range(3))
    eligible = tuple(
        sum(row.features_complete and row.labels_known[index] for row in rows)
        for index in range(3)
    )
    return CoverageSummary(
        intended,
        len(rows),
        sum(row.source_available for row in rows),
        sum(row.features_complete for row in rows),
        (known[0], known[1], known[2]),
        (eligible[0], eligible[1], eligible[2]),
        intended - len(rows),
    )
