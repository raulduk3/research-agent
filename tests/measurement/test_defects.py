"""SDD-IN-13, SDD-IN-39: a traceable defect lifecycle and its audit denominators."""

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.defects import (
    DefectCase,
    confirm,
    defect_report,
    open_case,
    reject,
    start_investigation,
)

SOURCE_HASH = "a" * 64
TARGET_HASH = "b" * 64
EVIDENCE_HASH = "c" * 64


class _StubCorrectionService:
    """A minimal stand-in for outcomes.corrections.CorrectionService (IN-12)."""

    def __init__(self, correction_hash: str) -> None:
        self._correction_hash = correction_hash
        self.calls: list[DefectCase] = []

    def correct(self, *, case: DefectCase, evidence_hash: str) -> str:
        self.calls.append(case)
        return self._correction_hash


def _open(resolver_version: int = 1, case_id: str = "case-1") -> DefectCase:
    return open_case(
        case_id=case_id,
        reporter_id="reporter-1",
        source_hashes=(SOURCE_HASH,),
        target_definition_hash=TARGET_HASH,
        resolver_version=resolver_version,
    )


def test_a_preserved_malformed_date_case_reaches_correction() -> None:
    case = _open()
    case = start_investigation(case)
    service = _StubCorrectionService("d" * 64)
    confirmed = confirm(case, service, evidence_hash=EVIDENCE_HASH)
    assert confirmed.state == "confirmed"
    assert confirmed.correction_hash == "d" * 64
    assert service.calls == [case]


def test_a_preference_only_complaint_cannot_obtain_label_write_authority() -> None:
    case = _open()
    case = start_investigation(case)
    rejected = reject(case)
    assert rejected.state == "rejected"
    assert rejected.correction_hash is None
    # Rejected is a dead end: it cannot be confirmed afterward to backdoor a
    # correction.
    with pytest.raises(MeasurementError):
        confirm(rejected, _StubCorrectionService("d" * 64), evidence_hash=EVIDENCE_HASH)


def test_confirm_requires_an_investigating_case() -> None:
    case = _open()
    with pytest.raises(MeasurementError):
        confirm(case, _StubCorrectionService("d" * 64), evidence_hash=EVIDENCE_HASH)


def test_investigation_requires_an_open_case() -> None:
    case = _open()
    investigating = start_investigation(case)
    with pytest.raises(MeasurementError):
        start_investigation(investigating)


def test_confirmed_state_requires_evidence_and_correction_hash() -> None:
    with pytest.raises(MeasurementError):
        DefectCase(
            case_id="case-1",
            reporter_id="reporter-1",
            source_hashes=(SOURCE_HASH,),
            target_definition_hash=TARGET_HASH,
            resolver_version=1,
            state="confirmed",
            evidence_hash=None,
            correction_hash=None,
        )


def test_open_case_carries_no_evidence_or_correction_hash() -> None:
    with pytest.raises(MeasurementError):
        DefectCase(
            case_id="case-1",
            reporter_id="reporter-1",
            source_hashes=(SOURCE_HASH,),
            target_definition_hash=TARGET_HASH,
            resolver_version=1,
            state="open",
            evidence_hash=EVIDENCE_HASH,
            correction_hash=None,
        )


def test_defect_report_groups_by_resolver_version() -> None:
    v1_confirmed = confirm(
        start_investigation(_open(resolver_version=1, case_id="a")),
        _StubCorrectionService("d" * 64),
        evidence_hash=EVIDENCE_HASH,
    )
    v1_rejected = reject(start_investigation(_open(resolver_version=1, case_id="b")))
    v1_open = _open(resolver_version=1, case_id="c")
    v2_open = _open(resolver_version=2, case_id="d")

    reports = defect_report([v1_confirmed, v1_rejected, v1_open, v2_open])
    by_version = {report.resolver_version: report for report in reports}

    assert by_version[1].confirmed_count == 1
    assert by_version[1].investigated_count == 2
    assert by_version[1].open_count == 1
    assert by_version[1].confirmed_rate == pytest.approx(0.5)
    assert by_version[1].disposition == "available"

    assert by_version[2].investigated_count == 0
    assert by_version[2].confirmed_rate is None
    assert by_version[2].disposition == "no_investigated_cases"
    assert by_version[2].open_count == 1


def test_uninvestigated_cases_never_enter_the_denominator() -> None:
    still_investigating = start_investigation(_open(resolver_version=5, case_id="e"))
    reports = defect_report([still_investigating])
    assert reports[0].investigated_count == 0
    assert reports[0].open_count == 1
    assert reports[0].confirmed_rate is None


def test_defect_statistics_are_unchanged_by_any_support_review_verdict() -> None:
    # defect_report never accepts a reviews.ReviewVerdict at all, so nothing
    # a rationale-support reviewer decides can move these counts (SDD-IN-39).
    confirmed = confirm(
        start_investigation(_open(resolver_version=1, case_id="a")),
        _StubCorrectionService("d" * 64),
        evidence_hash=EVIDENCE_HASH,
    )
    before = defect_report([confirmed])
    after = defect_report([confirmed])
    assert before == after
