"""SDD-IN-05 and IN-06: probability concentration and the reliability table."""

from uuid import uuid4

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.scoring.calibration import (
    ResolvedProbability,
    SealedProbability,
    concentration_flag,
    probability_bin,
    reliability_table,
)

HASH = "a" * 64
OTHER_HASH = "b" * 64


def _series(
    probabilities: list[float], *, configuration: str = "c1", target: str = HASH
) -> list[SealedProbability]:
    return [
        SealedProbability(configuration, target, index + 1, probability)
        for index, probability in enumerate(probabilities)
    ]


def _report(probabilities: list[float], **kwargs: str):  # type: ignore[no-untyped-def]
    (report,) = concentration_flag(_series(probabilities, **kwargs), profile_id="p1")
    return report


def test_180_of_200_in_one_bin_flags_and_179_does_not() -> None:
    assert _report([0.55] * 180 + [0.05] * 20).flagged
    assert not _report([0.55] * 179 + [0.05] * 21).flagged
    assert _report([0.55] * 180 + [0.05] * 20).bin_counts[5] == 180


def test_probability_one_falls_in_the_last_bin() -> None:
    assert probability_bin(1.0) == 9
    assert probability_bin(0.0) == 0
    assert _report([1.0] * 200).bin_counts[9] == 200


def test_fewer_than_200_reports_insufficient_support_never_a_flag() -> None:
    report = _report([0.5] * 199)
    assert report.disposition == "insufficient_support"
    assert not report.flagged


def test_only_the_latest_200_by_seal_sequence_count() -> None:
    early = [0.05] * 300
    late = [0.95] * 200
    report = _report(early + late)
    assert report.flagged and report.observation_count == 200
    shuffled = list(reversed(_series(early + late)))
    (again,) = concentration_flag(shuffled, profile_id="p1")
    assert again.support_hash == report.support_hash


def test_configurations_and_targets_are_partitioned() -> None:
    rows = (
        _series([0.5] * 200, configuration="c1")
        + _series(
            [0.1, 0.9] * 100,
            configuration="c2",
        )
        + _series([0.5] * 200, configuration="c1", target=OTHER_HASH)
    )
    reports = {
        (r.configuration_id, r.target_definition_hash): r
        for r in concentration_flag(rows, profile_id="p1")
    }
    assert reports[("c1", HASH)].flagged
    assert reports[("c1", OTHER_HASH)].flagged
    assert not reports[("c2", HASH)].flagged


def test_a_repeated_seal_sequence_is_refused() -> None:
    rows = _series([0.5] * 3) + [SealedProbability("c1", HASH, 1, 0.5)]
    with pytest.raises(ContractValidationError):
        concentration_flag(rows, profile_id="p1")


def _resolved(probability: float, outcome: bool) -> ResolvedProbability:
    return ResolvedProbability(str(uuid4()), probability, outcome)


def test_reliability_bins_carry_means_not_centers_and_ignore_unknowns() -> None:
    rows = [
        _resolved(0.91, True),
        _resolved(0.99, False),
        _resolved(1.0, True),
        _resolved(0.12, False),
    ]
    table = reliability_table(rows)
    assert len(table) == 10
    top = table[9]
    assert top.count == 3
    assert top.mean_probability == pytest.approx((0.91 + 0.99 + 1.0) / 3)
    assert top.observed_fraction == pytest.approx(2 / 3)
    assert top.question_ids == tuple(sorted(r.question_id for r in rows[:3]))
    assert table[1].count == 1 and table[1].mean_probability == 0.12
    empty = table[4]
    assert (empty.count, empty.mean_probability, empty.observed_fraction) == (
        0,
        None,
        None,
    )
