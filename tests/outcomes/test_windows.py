from datetime import timedelta

import pytest

from research_agent.contracts.papers import SourceInterval
from research_agent.outcomes.windows import (
    FIRST_YEAR,
    FIRST_LATE,
    SECOND_LATE,
    OutcomeWindow,
    instant,
    utc,
    maturity_at,
    forecast_deadline,
    capture_timing_failure,
)

T0 = "2020-01-01T12:00:00.000000Z"


def interval(start_day: float, end_day: float) -> SourceInterval:
    return SourceInterval(
        utc(instant(T0) + timedelta(days=start_day)),
        utc(instant(T0) + timedelta(days=end_day)),
    )


def test_provider_dates_conservatively_straddle_exact_boundaries() -> None:
    assert FIRST_YEAR.classify(T0, interval(-1, 0)) == "outside"
    assert FIRST_YEAR.classify(T0, interval(0, 1)) == "possible"
    assert FIRST_YEAR.classify(T0, interval(1, 2)) == "definite"
    assert FIRST_YEAR.classify(T0, interval(364, 365)) == "definite"
    assert FIRST_YEAR.classify(T0, interval(365, 366)) == "possible"
    assert FIRST_YEAR.classify(T0, interval(366, 367)) == "outside"
    assert FIRST_LATE.classify(T0, interval(179, 180)) == "outside"
    assert FIRST_LATE.classify(T0, interval(180, 181)) == "possible"
    assert FIRST_LATE.classify(T0, interval(269, 270)) == "definite"
    assert SECOND_LATE.classify(T0, interval(269, 270)) == "outside"
    assert FIRST_LATE.classify(T0, interval(270, 271)) == "possible"
    assert SECOND_LATE.classify(T0, interval(270, 271)) == "possible"
    assert SECOND_LATE.classify(T0, interval(271, 272)) == "definite"


def test_conflicting_aliases_cannot_choose_favorable_date() -> None:
    alternatives = (interval(200, 201), interval(300, 301))
    assert FIRST_LATE.classify_alternatives(T0, alternatives) == "possible"
    assert SECOND_LATE.classify_alternatives(T0, alternatives) == "possible"
    assert FIRST_YEAR.classify_alternatives(T0, alternatives) == "definite"
    assert FIRST_YEAR.classify(T0, None) == "possible"
    assert FIRST_YEAR.classify_alternatives(T0, ()) == "possible"


def test_maturity_and_prospective_capture_are_exact_elapsed_days() -> None:
    maturity = maturity_at(T0)
    deadline = utc(instant(maturity) + timedelta(days=1))
    assert instant(maturity) - instant(T0) == timedelta(days=455)
    assert instant(forecast_deadline(T0)) - instant(T0) == timedelta(hours=24)
    assert (
        capture_timing_failure(
            t0=T0,
            kind="prospective_maturity",
            started_at=maturity,
            completed_at=deadline,
            as_of=deadline,
        )
        is None
    )
    late = utc(instant(deadline) + timedelta(microseconds=1))
    assert (
        capture_timing_failure(
            t0=T0,
            kind="prospective_maturity",
            started_at=maturity,
            completed_at=late,
            as_of=late,
        )
        == "outside_capture_window"
    )
    assert (
        capture_timing_failure(
            t0=T0,
            kind="historical_reconstructed",
            started_at=late,
            completed_at=late,
            as_of=late,
        )
        is None
    )
    assert (
        capture_timing_failure(
            t0=T0,
            kind="historical_reconstructed",
            started_at=T0,
            completed_at=T0,
            as_of=maturity,
        )
        == "immature"
    )
    assert (
        capture_timing_failure(
            t0=T0,
            kind="historical_reconstructed",
            started_at=maturity,
            completed_at=deadline,
            as_of=maturity,
        )
        == "invalid_source"
    )


@pytest.mark.parametrize(
    "lower,upper", [(True, 10), (0, False), (1.5, 10), (0, 366 * 86400), (10, 10)]
)
def test_noncontract_windows_are_rejected(lower: object, upper: object) -> None:
    with pytest.raises(ValueError):
        OutcomeWindow(lower, upper)  # type: ignore[arg-type]
