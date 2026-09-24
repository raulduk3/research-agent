from dataclasses import replace
from datetime import timedelta

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.forecasts.eligibility import check_prospective
from research_agent.outcomes.targets import definitions
from research_agent.outcomes.windows import instant, utc
from tests.forecasts.conftest import META, T0, family_between

SEAL_AT = utc(instant(T0) + timedelta(hours=20))
CITATION_REACH, LATE_ACTIVITY, CROSS_SUBFIELD = definitions(META)


def test_eligible_with_no_relevant_evidence() -> None:
    result = check_prospective(CITATION_REACH, t0=T0, seal_at=SEAL_AT, families=())
    assert result.status == "eligible"
    assert result.witness_hashes == ()


def test_missed_deadline_ignores_evidence() -> None:
    late_seal = utc(instant(T0) + timedelta(hours=25))
    witnesses = tuple(family_between(index, "A", 1, 2) for index in range(1, 6))
    result = check_prospective(
        CITATION_REACH, t0=T0, seal_at=late_seal, families=witnesses
    )
    assert result.status == "missed_deadline"
    assert result.witness_hashes == ()


def test_preexisting_event_ignores_a_capture_after_sealing() -> None:
    """A citing family captured after sealing whose dated interval definitely
    predates sealing still marks the question preexisting-event (EN-02):
    capture time is never a proxy for event date."""

    late_capture_at = utc(instant(SEAL_AT) + timedelta(days=2))
    witnesses = tuple(
        replace(family_between(index, "A", 1, 2), created_at=late_capture_at)
        for index in range(1, 6)
    )
    result = check_prospective(
        CITATION_REACH, t0=T0, seal_at=SEAL_AT, families=witnesses
    )
    assert result.status == "preexisting_event"
    assert len(result.witness_hashes) == 5


def test_timing_ambiguous_when_an_interval_straddles_seal_time() -> None:
    definite = tuple(family_between(index, "A", 1, 2) for index in range(1, 5))
    straddling = family_between(5, "A", 18, 22)
    result = check_prospective(
        CITATION_REACH, t0=T0, seal_at=SEAL_AT, families=(*definite, straddling)
    )
    assert result.status == "timing_ambiguous"
    assert len(result.witness_hashes) == 5


def test_three_targets_differ_on_the_same_evidence() -> None:
    reach_witnesses = tuple(family_between(index, "A", 1, 2) for index in range(1, 6))
    subfield_witness = family_between(6, "B", 18, 22)
    families = (*reach_witnesses, subfield_witness)

    reach = check_prospective(CITATION_REACH, t0=T0, seal_at=SEAL_AT, families=families)
    late = check_prospective(LATE_ACTIVITY, t0=T0, seal_at=SEAL_AT, families=families)
    cross = check_prospective(CROSS_SUBFIELD, t0=T0, seal_at=SEAL_AT, families=families)

    assert reach.status == "preexisting_event"
    assert late.status == "eligible"
    assert cross.status == "timing_ambiguous"


def test_late_activity_cannot_be_preexisting_within_the_seal_deadline() -> None:
    """late_citation_activity_365d's windows only open at day 180 and day
    270; nothing dated within the fixed 24-hour seal deadline can ever
    land inside them."""

    witnesses = tuple(family_between(index, "A", 1, 2) for index in range(1, 6))
    result = check_prospective(
        LATE_ACTIVITY, t0=T0, seal_at=SEAL_AT, families=witnesses
    )
    assert result.status == "eligible"


def test_seal_cannot_precede_origin() -> None:
    with pytest.raises(ContractValidationError):
        check_prospective(
            CITATION_REACH,
            t0=T0,
            seal_at=utc(instant(T0) - timedelta(hours=1)),
            families=(),
        )


def test_historical_reconstructed_observations_are_refused() -> None:
    with pytest.raises(ContractValidationError):
        check_prospective(
            CITATION_REACH,
            t0=T0,
            seal_at=SEAL_AT,
            families=(),
            observation_kind="historical_reconstructed",
        )


def test_unknown_observation_kind_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        check_prospective(
            CITATION_REACH,
            t0=T0,
            seal_at=SEAL_AT,
            families=(),
            observation_kind="not_a_kind",
        )
