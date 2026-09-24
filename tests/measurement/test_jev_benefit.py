"""SDD-RD-23: the paired prospective Jev comparison."""

import random
from dataclasses import replace

import pytest

from research_agent.contracts import ProducerVersion
from research_agent.evaluation.registrations import (
    ComparisonEndpoint,
    ComparisonRegistration,
)
from research_agent.measurement import MeasurementError
from research_agent.measurement.jev import (
    BENEFIT_FAMILIES,
    BENEFIT_PRIMARY_METRIC,
    BenefitFamily,
    JevBenefitStudy,
    PairedOutcome,
)

REGISTRATION_ID = "11111111-1111-4111-8111-111111111111"
WEEKS = tuple(f"2026-W{week:02d}" for week in range(1, 53))
FIRST_PUBLIC = "2026-01-05T00:00:00.000000Z"
MATURE = "2027-12-01T00:00:00.000000Z"
IMMATURE = "2027-03-01T00:00:00.000000Z"


def _uuid(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-000000000000"


def _registration(**changes: object) -> ComparisonRegistration:
    values: dict[str, object] = {
        "schema_version": 1,
        "input_hashes": (),
        "producer_version": ProducerVersion("a" * 64, "b" * 40, 1),
        "config_hash": "c" * 64,
        "created_at": "2026-09-01T00:00:00.000000Z",
        "registration_id": REGISTRATION_ID,
        "hypothesis": "with-Jev forecasts improve citation-reach Brier",
        "population_hash": "d" * 64,
        "split_hash": "e" * 64,
        "subject_configuration_hash": "f" * 64,
        "endpoints": (ComparisonEndpoint(BENEFIT_PRIMARY_METRIC, "primary", "lower"),),
        "pass_threshold": -0.01,
        "kill_threshold": 0.0,
        "minimum_effect": 0.01,
        "exclusions": (),
        "sample_size": BENEFIT_FAMILIES,
        "failure_handling": "count_as_failure",
        "stop_rule_hash": "0" * 64,
        "provenance": "runtime",
        "registered_at": "2026-09-02T00:00:00.000000Z",
        "imported_at": None,
        "signature_evidence_hash": None,
        "exploratory_of": None,
    }
    values.update(changes)
    return ComparisonRegistration(**values)  # type: ignore[arg-type]


def _families(count: int = BENEFIT_FAMILIES, weeks: int = 26) -> list[BenefitFamily]:
    return [
        BenefitFamily(_uuid(n + 1), WEEKS[n % weeks], FIRST_PUBLIC)
        for n in range(count)
    ]


def _outcomes(
    study: JevBenefitStudy,
    families: list[BenefitFamily],
    *,
    gain: float,
    noise: float = 0.02,
    failed_every: int = 0,
    missing_every: int = 0,
) -> list[PairedOutcome]:
    rng = random.Random(7)
    outcomes = []
    for n, family in enumerate(families):
        base = 0.25 + rng.uniform(-noise, noise)
        failed = failed_every and n % failed_every == 0
        missing = missing_every and n % missing_every == 0
        outcomes.append(
            PairedOutcome(
                question_id=_uuid(10_000 + n),
                family_id=family.family_id,
                assigned_first=study.arm_order(family.family_id)[0],
                exposure="unavailable" if failed else "delivered",
                unavailable_reason="provider_failure" if failed else None,
                with_run_id=None if missing else f"with-{n}",
                with_loss=None if missing else base - gain + rng.uniform(-0.01, 0.01),
                without_run_id=f"without-{n}",
                without_loss=base,
            )
        )
    return outcomes


def _study() -> JevBenefitStudy:
    return JevBenefitStudy(_registration(), seed=20260923)


def test_registration_must_freeze_the_fixed_comparison() -> None:
    for changes in (
        {"sample_size": 1999},
        {"minimum_effect": 0.02},
        {"failure_handling": "exclude"},
        {"endpoints": (ComparisonEndpoint("skill_gain", "primary", "lower"),)},
        {"exploratory_of": _uuid(9)},
    ):
        with pytest.raises(MeasurementError):
            JevBenefitStudy(_registration(**changes), seed=1)


def test_arm_order_is_seeded_reproducible_and_balanced() -> None:
    study = _study()
    first = [study.arm_order(family.family_id)[0] for family in _families()]
    assert first == [
        JevBenefitStudy(_registration(), seed=20260923).arm_order(f.family_id)[0]
        for f in _families()
    ]
    other = [
        JevBenefitStudy(_registration(), seed=1).arm_order(f.family_id)[0]
        for f in _families()
    ]
    assert first != other
    assert 0.4 < first.count("with_jev") / len(first) < 0.6
    assert set(study.arm_order(_uuid(1))) == {"with_jev", "without_jev"}


def test_allocation_takes_the_first_families_regardless_of_input_order() -> None:
    study = _study()
    families = _families(2600, weeks=52)
    shuffled = list(families)
    random.Random(3).shuffle(shuffled)
    allocation = study.allocate(shuffled)
    assert allocation == study.allocate(families)
    assert len(allocation.selected) == BENEFIT_FAMILIES
    assert allocation.selected == tuple(
        sorted(allocation.selected, key=lambda item: item.publication_week)
    )
    assert allocation.complete


def test_allocation_across_too_few_weeks_reads_incomplete() -> None:
    study = _study()
    allocation = study.allocate(_families(weeks=25))
    assert len(allocation.weeks) == 25
    assert not allocation.complete
    report = study.evaluate(allocation, [], as_of=MATURE)
    assert (report.verdict, report.reason) == ("pending", "allocation_incomplete")


def test_short_allocation_is_not_padded() -> None:
    study = _study()
    allocation = study.allocate(_families(1500))
    assert len(allocation.selected) == 1500
    assert not allocation.complete


def test_no_verdict_before_the_last_family_matures() -> None:
    study = _study()
    families = _families()
    allocation = study.allocate(families)
    report = study.evaluate(
        allocation, _outcomes(study, families, gain=0.05), as_of=IMMATURE
    )
    assert report.verdict == "pending"
    assert report.reason == "outcomes_immature"
    assert report.gain is None and report.estimate is None
    assert report.matched_support == 0.0


def test_a_clear_gain_passes() -> None:
    study = _study()
    families = _families()
    report = study.evaluate(
        study.allocate(families),
        _outcomes(study, families, gain=0.03),
        as_of=MATURE,
    )
    assert (report.verdict, report.reason) == ("passed", "criteria_met")
    assert report.gain is not None and report.gain >= 0.01
    assert report.low is not None and report.high is not None and report.high < 0
    assert report.matched_support == 1.0


def test_a_gain_below_the_minimum_fails_even_when_significant() -> None:
    study = _study()
    families = _families()
    report = study.evaluate(
        study.allocate(families),
        _outcomes(study, families, gain=0.004),
        as_of=MATURE,
    )
    assert (report.verdict, report.reason) == ("failed", "gain_below_minimum")


def test_a_worse_with_jev_arm_fails() -> None:
    study = _study()
    families = _families()
    report = study.evaluate(
        study.allocate(families),
        _outcomes(study, families, gain=-0.03),
        as_of=MATURE,
    )
    assert (report.verdict, report.reason) == ("failed", "with_jev_worse")


def test_an_interval_spanning_zero_is_inconclusive() -> None:
    study = _study()
    families = _families()
    report = study.evaluate(
        study.allocate(families),
        _outcomes(study, families, gain=0.0),
        as_of=MATURE,
    )
    assert (report.verdict, report.reason) == ("inconclusive", "interval_spans_zero")


def test_missing_pairs_below_seventy_percent_are_inconclusive_not_imputed() -> None:
    study = _study()
    families = _families()
    report = study.evaluate(
        study.allocate(families),
        _outcomes(study, families, gain=0.05, missing_every=3),
        as_of=MATURE,
    )
    assert report.matched_families < 0.7 * BENEFIT_FAMILIES
    assert (report.verdict, report.reason) == (
        "inconclusive",
        "matched_support_below_floor",
    )


def test_failed_delivery_stays_in_the_assigned_treatment_analysis() -> None:
    study = _study()
    families = _families()
    allocation = study.allocate(families)
    outcomes = _outcomes(study, families, gain=0.03, failed_every=4)
    report = study.evaluate(allocation, outcomes, as_of=MATURE)
    assert report.unavailable == BENEFIT_FAMILIES // 4
    assert report.matched_families == BENEFIT_FAMILIES
    assert report.registered_families == BENEFIT_FAMILIES
    dropped = [item for item in outcomes if item.exposure == "delivered"]
    per_protocol = study.evaluate(allocation, dropped, as_of=MATURE)
    assert per_protocol.matched_families == report.matched_families * 3 // 4
    assert per_protocol.matched_support < report.matched_support


def test_outcomes_for_an_unallocated_or_repeated_family_are_refused() -> None:
    study = _study()
    families = _families()
    allocation = study.allocate(families)
    outcomes = _outcomes(study, families, gain=0.03)
    stranger = replace(outcomes[0], family_id=_uuid(99_999))
    with pytest.raises(MeasurementError):
        study.evaluate(allocation, [stranger], as_of=MATURE)
    with pytest.raises(MeasurementError):
        study.evaluate(allocation, [outcomes[0], outcomes[0]], as_of=MATURE)


def test_an_unavailable_exposure_must_name_its_reason() -> None:
    with pytest.raises(MeasurementError):
        PairedOutcome(
            _uuid(1), _uuid(2), "with_jev", "unavailable", None, "a", 0.1, "b", 0.2
        )
    with pytest.raises(MeasurementError):
        PairedOutcome(
            _uuid(1), _uuid(2), "with_jev", "delivered", None, "a", None, "b", 0.2
        )
