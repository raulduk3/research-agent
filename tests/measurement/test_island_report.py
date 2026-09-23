"""SDD-FT-26: the weekly island report's columns come from their own records."""

from __future__ import annotations

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.preference import PreferenceCredit
from research_agent.measurement.weekly import (
    UNRATED_REASON,
    AdmittedMigration,
    PresentGenome,
    RatedEntry,
    island_report,
)
from research_agent.scoring.scores import TargetSkill

FOUNDER = "a" * 64
SECOND = "b" * 64
IDLE = "c" * 64
WEEK = "2026-W38"


def uid(number: int) -> str:
    return f"{number:08d}-0000-4000-8000-000000000000"


def skill(target: str, value: float | None, support: int = 12) -> TargetSkill:
    if value is None:
        return TargetSkill(
            target_id=target,
            agent_producer_id="agent",
            baseline_producer_id="baseline",
            support_count=0,
            agent_mean_brier=None,
            baseline_mean_brier=None,
            skill=None,
            disposition="unavailable",
            skill_per_dollar=None,
            cost_microdollars=None,
            cost_record_ids=(),
            cost_disposition="unavailable",
        )
    return TargetSkill(
        target_id=target,
        agent_producer_id="agent",
        baseline_producer_id="baseline",
        support_count=support,
        agent_mean_brier=0.2,
        baseline_mean_brier=0.25,
        skill=value,
        disposition="available",
        skill_per_dollar=None,
        cost_microdollars=None,
        cost_record_ids=(),
        cost_disposition="unavailable",
    )


def credit(number: int, genome: str, entry: int, share: float) -> PreferenceCredit:
    return PreferenceCredit(
        rating_id=uid(number),
        genome_hash=genome,
        island="cs",
        entry_id=uid(entry),
        sealed_probability=0.5,
        share=share,
        iso_week=WEEK,
    )


GENOMES = [
    PresentGenome(FOUNDER, True),
    PresentGenome(SECOND, False),
    PresentGenome(IDLE, False),
]
SKILLS = {
    FOUNDER: [skill("citation_reach_365d", 0.1)],
    SECOND: [
        skill("citation_reach_365d", -0.05),
        skill("late_citation_activity_365d", 0.2, support=7),
    ],
}


def rated(start: int, origin: str, week: str, values: str) -> list[RatedEntry]:
    names = {"l": "like", "d": "dislike", "s": "skip"}
    return [
        RatedEntry(uid(start + offset), origin, names[letter], week)
        for offset, letter in enumerate(values)
    ]


def test_each_column_matches_its_stored_record() -> None:
    credits = [
        credit(1, FOUNDER, 101, 0.75),
        credit(2, FOUNDER, 102, -0.25),
        credit(3, SECOND, 101, 0.25),
        credit(4, SECOND, 101, 0.5),
    ]
    report = island_report(
        island="cs",
        iso_week=WEEK,
        genomes=GENOMES,
        skills=SKILLS,
        credits=credits,
        rated_entries=[],
        migrations=[],
    )
    founder, second, idle = report.rows
    assert report.founder == founder
    assert (founder.preference_credit, founder.credited_entries) == (0.5, 2)
    assert (second.preference_credit, second.credited_entries) == (0.75, 1)
    assert founder.skills[0].skill == 0.1
    assert second.skills[0].skill == -0.05
    assert second.skills[1].skill == 0.2 and second.skills[1].support_count == 7
    assert [cell.skill for cell in founder.skills[1:]] == [None, None]
    assert all(cell.disposition == "unavailable" for cell in founder.skills[1:])
    assert report.preference_reason is None


def test_a_genome_with_no_rated_entries_has_zero_credit_and_count() -> None:
    report = island_report(
        island="cs",
        iso_week=WEEK,
        genomes=GENOMES,
        skills={},
        credits=[credit(1, FOUNDER, 101, 1.0)],
        rated_entries=[],
        migrations=[],
    )
    idle = report.rows[2]
    assert idle.genome_hash == IDLE
    assert (idle.preference_credit, idle.credited_entries) == (0.0, 0)
    assert all(cell.skill is None for cell in idle.skills)


def test_a_credit_to_a_genome_absent_at_the_freeze_adds_no_row() -> None:
    report = island_report(
        island="cs",
        iso_week=WEEK,
        genomes=[PresentGenome(FOUNDER, True)],
        skills={},
        credits=[credit(1, "d" * 64, 101, 1.0)],
        rated_entries=[],
        migrations=[],
    )
    assert [row.genome_hash for row in report.rows] == [FOUNDER]
    assert report.rows[0].preference_credit == 0.0


def test_like_rates_compare_system_picks_to_controls_and_service_picks() -> None:
    entries = (
        rated(1, "population", "2026-W36", "llld")
        + rated(11, "population", "2026-W37", "lldd")
        + rated(21, "population", "2026-W38", "lllls")
        + rated(31, "random_control", "2026-W36", "ldd")
        + rated(41, "random_control", "2026-W37", "ldds")
        + rated(51, "random_control", "2026-W38", "ddl")
        + rated(61, "service", "2026-W36", "lllll")
    )
    report = island_report(
        island="cs",
        iso_week=WEEK,
        genomes=GENOMES,
        skills={},
        credits=[],
        rated_entries=entries,
        migrations=[],
    )
    controls, service = report.comparisons
    assert controls.comparator == "random_control"
    assert (controls.population_likes, controls.population_decided) == (9, 12)
    assert (controls.comparator_likes, controls.comparator_decided) == (3, 9)
    assert controls.population_rate == pytest.approx(0.75)
    assert controls.comparator_rate == pytest.approx(1 / 3)
    week_differences = [3 / 4 - 1 / 3, 1 / 2 - 1 / 3, 1.0 - 1 / 3]
    assert controls.weeks == 3
    assert controls.interval.estimate == pytest.approx(sum(week_differences) / 3)
    assert controls.interval.low is not None and controls.interval.low > 0
    assert controls.verdict.verdict == "favorable"
    assert service.comparator == "service"
    assert service.comparator_rate == 1.0
    assert service.weeks == 1
    assert service.interval.disposition == "unavailable"
    assert service.verdict.verdict == "unavailable"


def test_a_comparison_with_no_decided_ratings_is_unavailable_not_zero() -> None:
    report = island_report(
        island="cs",
        iso_week=WEEK,
        genomes=GENOMES,
        skills={},
        credits=[],
        rated_entries=rated(1, "population", "2026-W38", "ss"),
        migrations=[],
    )
    for comparison in report.comparisons:
        assert comparison.population_rate is None
        assert comparison.comparator_rate is None
        assert comparison.verdict.verdict == "unavailable"


def test_the_qbio_report_carries_zero_preference_with_the_stated_reason() -> None:
    report = island_report(
        island="q-bio",
        iso_week=WEEK,
        genomes=[PresentGenome(FOUNDER, True), PresentGenome(SECOND, False)],
        skills=SKILLS,
        credits=[],
        rated_entries=[],
        migrations=[],
    )
    assert report.preference_reason == UNRATED_REASON
    assert report.comparisons == ()
    assert all(
        (row.preference_credit, row.credited_entries) == (0.0, 0) for row in report.rows
    )
    assert report.rows[0].skills[0].skill == 0.1


def test_a_qbio_report_refuses_any_credit_or_rating() -> None:
    with pytest.raises(MeasurementError):
        island_report(
            island="q-bio",
            iso_week=WEEK,
            genomes=GENOMES,
            skills={},
            credits=[credit(1, FOUNDER, 101, 1.0)],
            rated_entries=[],
            migrations=[],
        )


def test_the_week_and_island_of_every_credit_are_checked() -> None:
    other = PreferenceCredit(uid(1), FOUNDER, "quant-ph", uid(101), 0.5, 1.0, WEEK)
    with pytest.raises(MeasurementError):
        island_report(
            island="cs",
            iso_week=WEEK,
            genomes=GENOMES,
            skills={},
            credits=[other],
            rated_entries=[],
            migrations=[],
        )


def test_migrations_admitted_that_week_are_listed() -> None:
    migration = AdmittedMigration("d" * 64, "quant-ph", "e" * 64)
    report = island_report(
        island="cs",
        iso_week=WEEK,
        genomes=GENOMES,
        skills={},
        credits=[],
        rated_entries=[],
        migrations=[migration],
    )
    assert report.migrations == (migration,)
