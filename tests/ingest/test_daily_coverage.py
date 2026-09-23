"""Daily acquisition coverage over the admitted-family manifest."""

from __future__ import annotations

import pytest

from research_agent.ingest.coverage import (
    CoverageError,
    SourceAuditReport,
    build_daily_coverage,
)


def _coverage(**overrides: object) -> object:
    base: dict[str, object] = {
        "day": "2026-01-05",
        "listed": 3,
        "admitted_family_ids": ("a", "b"),
        "skipped": (("c", "category_excluded"),),
        "source_status": {"a": "present", "b": "missing"},
        "text_status": {},
        "figure_status": {},
        "bibliography_status": {},
    }
    base.update(overrides)
    return build_daily_coverage(**base)  # type: ignore[arg-type]


def test_zero_paper_day_is_a_valid_all_zero_result() -> None:
    coverage = build_daily_coverage(
        day="2026-01-05",
        listed=0,
        admitted_family_ids=(),
        skipped=(),
        source_status={},
        text_status={},
        figure_status={},
        bibliography_status={},
    )
    assert coverage.denominator == 0
    assert coverage.source == coverage.text == coverage.figure == coverage.bibliography


def test_every_combination_of_present_missing_and_error_is_counted() -> None:
    coverage = build_daily_coverage(
        day="2026-01-05",
        listed=3,
        admitted_family_ids=("a", "b", "c"),
        skipped=(),
        source_status={"a": "present", "b": "missing", "c": "error"},
        text_status={"a": "present"},
        figure_status={},
        bibliography_status={"c": "error"},
    )
    assert coverage.source.present == 1
    assert coverage.source.missing == 1
    assert coverage.source.error == 1
    # A family absent from a leg's status map is missing, not excluded.
    assert coverage.text.present == 1
    assert coverage.text.missing == 2
    assert coverage.text.error == 0
    assert coverage.figure.missing == 3
    assert coverage.bibliography.error == 1
    assert coverage.bibliography.missing == 2


def test_a_withheld_audit_report_does_not_suppress_daily_counts() -> None:
    coverage = _coverage()
    assert coverage.audit_state == "not_yet_audited"
    assert coverage.audit is None
    assert coverage.source.present == 1


def test_an_attached_audit_report_is_recorded_without_describing_unaudited_rows() -> (
    None
):
    audit = SourceAuditReport(
        sampled_family_ids=("a",),
        verdicts=("confirmed",),
        audited_at="2026-01-06T00:00:00.000000Z",
    )
    coverage = _coverage(audit=audit)
    assert coverage.audit_state == "audited"
    assert coverage.audit is audit
    # The automatic counts are unchanged by the audit's presence.
    assert coverage.source.present == 1


def test_audit_verdicts_must_pair_one_to_one_with_samples() -> None:
    with pytest.raises(CoverageError):
        SourceAuditReport(
            sampled_family_ids=("a", "b"),
            verdicts=("confirmed",),
            audited_at="2026-01-06T00:00:00.000000Z",
        )


def test_status_naming_a_family_outside_the_manifest_is_refused() -> None:
    with pytest.raises(CoverageError):
        _coverage(source_status={"z": "present"})


def test_an_inadmissible_status_value_is_refused() -> None:
    with pytest.raises(CoverageError):
        _coverage(source_status={"a": "hand_verified"})


def test_admitted_and_skipped_families_cannot_overlap() -> None:
    with pytest.raises(CoverageError):
        _coverage(admitted_family_ids=("a", "b"), skipped=(("a", "category_excluded"),))


def test_listed_count_must_cover_every_admitted_and_skipped_family() -> None:
    with pytest.raises(CoverageError):
        _coverage(listed=1)
