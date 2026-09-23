"""A reported defect's traceable lifecycle, and its resolver-version audit.

`DefectCase` never edits a label itself: a confirmed disposition only ever
reaches correction through an injected `CorrectionService` collaborator
(SDD-IN-13), matching outcomes.corrections.CorrectionService's shape (TDD-
4.1.15) without this pure package importing or touching storage. `defect_report`
groups cases by resolver version; an uninvestigated case, open or still under
investigation, never enters the confirmed-rate denominator (SDD-IN-39).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_non_negative_int,
    validate_sha256,
)
from research_agent.measurement import MeasurementError

STATES: frozenset[str] = frozenset({"open", "investigating", "confirmed", "rejected"})


@dataclass(frozen=True, slots=True)
class DefectCase:
    """One reported source or resolver defect, open through its final disposition."""

    case_id: str
    reporter_id: str
    source_hashes: tuple[str, ...]
    target_definition_hash: str
    resolver_version: int
    state: str
    evidence_hash: str | None
    correction_hash: str | None

    def __post_init__(self) -> None:
        validate_non_empty_string(self.case_id)
        validate_non_empty_string(self.reporter_id)
        if not self.source_hashes:
            raise MeasurementError("a defect case needs at least one source hash")
        for value in self.source_hashes:
            validate_sha256(value)
        validate_sha256(self.target_definition_hash)
        validate_non_negative_int(self.resolver_version)
        if self.state not in STATES:
            raise MeasurementError("state is not a recognized defect disposition")
        if self.state == "confirmed":
            if self.evidence_hash is None or self.correction_hash is None:
                raise MeasurementError(
                    "a confirmed case carries its evidence and correction hash"
                )
            validate_sha256(self.evidence_hash)
            validate_sha256(self.correction_hash)
        elif self.correction_hash is not None:
            raise MeasurementError(
                "a case never carries a correction hash before it is confirmed"
            )
        elif self.state == "rejected":
            if self.evidence_hash is not None:
                validate_sha256(self.evidence_hash)
        elif self.evidence_hash is not None:
            raise MeasurementError(
                "an open or investigating case carries no evidence hash yet"
            )


def open_case(
    *,
    case_id: str,
    reporter_id: str,
    source_hashes: Sequence[str],
    target_definition_hash: str,
    resolver_version: int,
) -> DefectCase:
    """Open a new, traceable defect case naming its source, target and resolver."""

    return DefectCase(
        case_id=case_id,
        reporter_id=reporter_id,
        source_hashes=tuple(source_hashes),
        target_definition_hash=target_definition_hash,
        resolver_version=resolver_version,
        state="open",
        evidence_hash=None,
        correction_hash=None,
    )


def start_investigation(case: DefectCase) -> DefectCase:
    if case.state != "open":
        raise MeasurementError("only an open case can start investigation")
    return replace(case, state="investigating")


def reject(case: DefectCase, *, evidence_hash: str | None = None) -> DefectCase:
    """Disposition a case as rejected: a preference-only complaint, not a defect.

    Rejecting never grants label-write authority; it carries no correction
    hash and there is no path from here back to `CorrectionService`.
    """

    if case.state != "investigating":
        raise MeasurementError("only an investigating case can be dispositioned")
    return replace(case, state="rejected", evidence_hash=evidence_hash)


class CorrectionService(Protocol):
    """The one call a confirmed case may use to correct a label (SDD-IN-12)."""

    def correct(self, *, case: DefectCase, evidence_hash: str) -> str:
        """Return the new correction record's hash for the confirmed case."""
        ...


def confirm(
    case: DefectCase,
    correction_service: CorrectionService,
    *,
    evidence_hash: str,
) -> DefectCase:
    """Confirm a reproducible defect and delegate its correction; never edit a label.

    Only an already-investigating case with reproducible evidence may be
    confirmed. The correction hash comes back from `correction_service`,
    never computed here, so this module has no way to write a label itself
    (SDD-IN-13).
    """

    if case.state != "investigating":
        raise MeasurementError("only an investigating case can be confirmed")
    validate_sha256(evidence_hash)
    correction_hash = correction_service.correct(case=case, evidence_hash=evidence_hash)
    return replace(
        case,
        state="confirmed",
        evidence_hash=evidence_hash,
        correction_hash=correction_hash,
    )


@dataclass(frozen=True, slots=True)
class DefectAudit:
    """One resolver version's investigated-case audit, a selected sample, not a rate."""

    resolver_version: int
    confirmed_count: int
    investigated_count: int
    open_count: int
    confirmed_rate: float | None
    disposition: str


def defect_report(cases: Sequence[DefectCase]) -> tuple[DefectAudit, ...]:
    """Group defect cases by resolver version into a confirmed-rate audit.

    `investigated_count` is confirmed plus rejected -- cases that reached a
    disposition. An open or still-investigating case is never in that
    denominator (SDD-IN-39: "uninvestigated cases cannot enter the
    denominator"); it is only ever counted in `open_count`.
    """

    by_version: dict[int, list[DefectCase]] = {}
    for case in cases:
        by_version.setdefault(case.resolver_version, []).append(case)

    reports = []
    for version in sorted(by_version):
        group = by_version[version]
        confirmed_count = sum(1 for case in group if case.state == "confirmed")
        rejected_count = sum(1 for case in group if case.state == "rejected")
        open_count = sum(1 for case in group if case.state in ("open", "investigating"))
        investigated_count = confirmed_count + rejected_count
        if investigated_count == 0:
            reports.append(
                DefectAudit(
                    resolver_version=version,
                    confirmed_count=confirmed_count,
                    investigated_count=investigated_count,
                    open_count=open_count,
                    confirmed_rate=None,
                    disposition="no_investigated_cases",
                )
            )
        else:
            reports.append(
                DefectAudit(
                    resolver_version=version,
                    confirmed_count=confirmed_count,
                    investigated_count=investigated_count,
                    open_count=open_count,
                    confirmed_rate=confirmed_count / investigated_count,
                    disposition="available",
                )
            )
    return tuple(reports)
