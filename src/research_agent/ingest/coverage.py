"""Daily acquisition coverage: what was listed, admitted, fetched and audited.

The denominator is the day's complete admitted-family manifest, decided
before any extraction runs. Four extraction legs (source, text, figure,
bibliography) are left joined against that manifest: a family absent from a
leg's status map is `missing`, not silently excluded, and an explicit
`error` status is never folded into `missing`. A day's independent
source-audit report is attached when one exists; its absence produces
`not_yet_audited` and never suppresses or reinterprets the automatic counts
next to it.
"""

from __future__ import annotations

from dataclasses import dataclass

_STATUSES = frozenset({"present", "missing", "error"})


class CoverageError(ValueError):
    """A coverage input does not match the admitted-family denominator."""


@dataclass(frozen=True, slots=True)
class LegCoverage:
    present: int
    missing: int
    error: int

    @property
    def denominator(self) -> int:
        return self.present + self.missing + self.error


def _leg(family_ids: tuple[str, ...], status: dict[str, str], name: str) -> LegCoverage:
    unknown = set(status) - set(family_ids)
    if unknown:
        raise CoverageError(f"{name} status names families outside the manifest")
    bad = {value for value in status.values() if value not in _STATUSES}
    if bad:
        raise CoverageError(f"{name} status has an inadmissible value")
    present = sum(1 for family_id in family_ids if status.get(family_id) == "present")
    error = sum(1 for family_id in family_ids if status.get(family_id) == "error")
    missing = len(family_ids) - present - error
    return LegCoverage(present, missing, error)


@dataclass(frozen=True, slots=True)
class SourceAuditReport:
    """An immutable, already-completed independent audit of a sample of days."""

    sampled_family_ids: tuple[str, ...]
    verdicts: tuple[str, ...]
    audited_at: str

    def __post_init__(self) -> None:
        if len(self.sampled_family_ids) != len(self.verdicts):
            raise CoverageError("audit verdicts must pair one-to-one with samples")
        if len(set(self.sampled_family_ids)) != len(self.sampled_family_ids):
            raise CoverageError("audit samples must not repeat a family")


@dataclass(frozen=True, slots=True)
class DailyCoverage:
    day: str
    listed: int
    admitted: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    source: LegCoverage
    text: LegCoverage
    figure: LegCoverage
    bibliography: LegCoverage
    audit_state: str
    audit: SourceAuditReport | None

    @property
    def denominator(self) -> int:
        return len(self.admitted)


def build_daily_coverage(
    *,
    day: str,
    listed: int,
    admitted_family_ids: tuple[str, ...],
    skipped: tuple[tuple[str, str], ...],
    source_status: dict[str, str],
    text_status: dict[str, str],
    figure_status: dict[str, str],
    bibliography_status: dict[str, str],
    audit: SourceAuditReport | None = None,
) -> DailyCoverage:
    """Compute the day's coverage; a zero-paper day is a valid, all-zero result.

    `admitted_family_ids` is the complete daily admission manifest (this
    issue's eligibility rule, decision 0016); `skipped` names every listed
    family excluded before admission with its one reason. A missing audit
    report never changes the automatic leg counts, only `audit_state`.
    """
    if listed < len(admitted_family_ids) + len(skipped):
        raise CoverageError("listed count is smaller than the families it explains")
    if len(set(admitted_family_ids)) != len(admitted_family_ids):
        raise CoverageError("admitted families must not repeat")
    skipped_ids = [family_id for family_id, _ in skipped]
    if len(set(skipped_ids)) != len(skipped_ids):
        raise CoverageError("skipped families must not repeat")
    if set(skipped_ids) & set(admitted_family_ids):
        raise CoverageError("a family cannot be both admitted and skipped")
    return DailyCoverage(
        day,
        listed,
        admitted_family_ids,
        skipped,
        _leg(admitted_family_ids, source_status, "source"),
        _leg(admitted_family_ids, text_status, "text"),
        _leg(admitted_family_ids, figure_status, "figure"),
        _leg(admitted_family_ids, bibliography_status, "bibliography"),
        "not_yet_audited" if audit is None else "audited",
        audit,
    )
