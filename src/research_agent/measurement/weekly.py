"""The weekly island report: skill, preference credit and like rates (FT-26, TDD-4.1.80).

`island_report` only arranges records it is given: per-target skill from the
shared scorer, credit rows exactly as stored, and rated entries by origin. The
one statistic it computes is a like rate, and only to hand it to the shared
bootstrap and verdict. The skill, credit and count columns are each read from
their own record and never combined or derived from one another.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from research_agent.contracts.digests import DIGEST_ISLANDS, DIGEST_ORIGINS
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.preference import validate_iso_week
from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_sha256,
    validate_uuid4,
)
from research_agent.measurement import MeasurementError
from research_agent.measurement.bootstrap import BootstrapInterval, bootstrap_difference
from research_agent.measurement.comparisons import IntervalVerdict, interval_verdict
from research_agent.measurement.preference import RATING_SIGNS, PreferenceCredit
from research_agent.scoring.scores import TargetSkill

UNRATED_ISLAND = "q-bio"
UNRATED_REASON = (
    "The q-bio island has no rater, so none of its entries is rated and no genome "
    "of it is credited."
)
COMPARATORS: tuple[str, ...] = ("random_control", "service")
LOWER_TAIL = 2.5
UPPER_TAIL = 97.5
MINIMUM_WEEKS = 2


@dataclass(frozen=True, slots=True)
class PresentGenome:
    """A genome in the island at the freeze."""

    genome_hash: str
    founder: bool

    def __post_init__(self) -> None:
        validate_sha256(self.genome_hash)


@dataclass(frozen=True, slots=True)
class RatedEntry:
    """One rating of one entry, with the origin the rater never saw and its cluster week."""

    rating_id: str
    origin: str
    value: str
    week: str

    def __post_init__(self) -> None:
        validate_uuid4(self.rating_id)
        if self.origin not in DIGEST_ORIGINS:
            raise MeasurementError("origin is not an admitted value")
        if self.value not in RATING_SIGNS:
            raise MeasurementError("value must be like, dislike or skip")
        validate_iso_week(self.week)


@dataclass(frozen=True, slots=True)
class AdmittedMigration:
    """A genome admitted into the island from another island that week (AG-37)."""

    child_hash: str
    source_island: str
    source_hash: str

    def __post_init__(self) -> None:
        validate_sha256(self.child_hash)
        validate_sha256(self.source_hash)
        if self.source_island not in DIGEST_ISLANDS:
            raise MeasurementError("source_island is not an admitted value")


@dataclass(frozen=True, slots=True)
class SkillCell:
    """One registered target's skill for one genome, or its absence."""

    target_id: str
    skill: float | None
    support_count: int
    disposition: str


@dataclass(frozen=True, slots=True)
class GenomeRow:
    genome_hash: str
    founder: bool
    skills: tuple[SkillCell, ...]
    preference_credit: float
    credited_entries: int


@dataclass(frozen=True, slots=True)
class LikeRateComparison:
    """The rater's like rate on population entries against one comparator origin."""

    comparator: str
    population_likes: int
    population_decided: int
    comparator_likes: int
    comparator_decided: int
    population_rate: float | None
    comparator_rate: float | None
    weeks: int
    interval: BootstrapInterval
    verdict: IntervalVerdict


@dataclass(frozen=True, slots=True)
class IslandReport:
    island: str
    iso_week: str
    rows: tuple[GenomeRow, ...]
    preference_reason: str | None
    comparisons: tuple[LikeRateComparison, ...]
    migrations: tuple[AdmittedMigration, ...]

    @property
    def founder(self) -> GenomeRow | None:
        return next((row for row in self.rows if row.founder), None)


@dataclass(slots=True)
class _WeekRate:
    """One cluster week's difference between two like rates.

    Not frozen: `bootstrap.ClusteredDifference` declares its fields settable.
    """

    publication_week: str
    family_id: str
    difference: float


def island_report(
    *,
    island: str,
    iso_week: str,
    genomes: Sequence[PresentGenome],
    skills: Mapping[str, Sequence[TargetSkill]],
    credits: Sequence[PreferenceCredit],
    rated_entries: Sequence[RatedEntry],
    migrations: Sequence[AdmittedMigration],
) -> IslandReport:
    """Build one island's report at its weekly freeze from stored records."""

    if island not in DIGEST_ISLANDS:
        raise MeasurementError("island is not an admitted value")
    validate_iso_week(iso_week)
    hashes = [genome.genome_hash for genome in genomes]
    if len(set(hashes)) != len(hashes):
        raise MeasurementError("a genome appears once in the report")
    unrated = island == UNRATED_ISLAND
    if unrated and (credits or rated_entries):
        raise MeasurementError(f"the {UNRATED_ISLAND} island carries no preference")
    for credit in credits:
        if credit.island != island or credit.iso_week != iso_week:
            raise MeasurementError("a credit belongs to another island or week")

    summed: dict[str, float] = {}
    counted: dict[str, set[str]] = {}
    for credit in credits:
        summed[credit.genome_hash] = summed.get(credit.genome_hash, 0.0) + credit.share
        counted.setdefault(credit.genome_hash, set()).add(credit.entry_id)

    rows = tuple(
        GenomeRow(
            genome_hash=genome.genome_hash,
            founder=genome.founder,
            skills=_skill_cells(skills.get(genome.genome_hash, ())),
            preference_credit=summed.get(genome.genome_hash, 0.0),
            credited_entries=len(counted.get(genome.genome_hash, ())),
        )
        for genome in genomes
    )
    return IslandReport(
        island=island,
        iso_week=iso_week,
        rows=rows,
        preference_reason=UNRATED_REASON if unrated else None,
        comparisons=()
        if unrated
        else tuple(_comparison(name, rated_entries) for name in COMPARATORS),
        migrations=tuple(migrations),
    )


def _skill_cells(skills: Sequence[TargetSkill]) -> tuple[SkillCell, ...]:
    by_target: dict[str, TargetSkill] = {}
    for skill in skills:
        if skill.target_id in by_target:
            raise MeasurementError("a genome carries one skill record per target")
        by_target[skill.target_id] = skill
    cells: list[SkillCell] = []
    for target_id in TARGET_IDS:
        found = by_target.get(target_id)
        if found is None or found.skill is None:
            cells.append(
                SkillCell(
                    target_id,
                    None,
                    0 if found is None else found.support_count,
                    "unavailable",
                )
            )
        else:
            cells.append(
                SkillCell(
                    target_id, found.skill, found.support_count, found.disposition
                )
            )
    return tuple(cells)


def _tally(entries: Sequence[RatedEntry]) -> tuple[int, int]:
    """Likes and decided ratings; a skip is neither a like nor a dislike."""

    likes = sum(1 for entry in entries if entry.value == "like")
    decided = sum(1 for entry in entries if entry.value != "skip")
    return likes, decided


def _rate(likes: int, decided: int) -> float | None:
    return likes / decided if decided else None


def _comparison(comparator: str, rated: Sequence[RatedEntry]) -> LikeRateComparison:
    ids = [entry.rating_id for entry in rated]
    if len(set(ids)) != len(ids):
        raise MeasurementError("a rating appears once in the report")
    population = [entry for entry in rated if entry.origin == "population"]
    other = [entry for entry in rated if entry.origin == comparator]
    weeks = sorted(
        {entry.week for entry in population} & {entry.week for entry in other}
    )
    rows: list[_WeekRate] = []
    for week in weeks:
        pop_rate = _rate(*_tally([entry for entry in population if entry.week == week]))
        other_rate = _rate(*_tally([entry for entry in other if entry.week == week]))
        if pop_rate is not None and other_rate is not None:
            rows.append(_WeekRate(week, week, pop_rate - other_rate))
    # One week resamples to itself; an interval over it would claim precision
    # it does not have, so fewer than two weeks is unavailable, not narrow.
    resampled = rows if len(rows) >= MINIMUM_WEEKS else []
    interval = bootstrap_difference(
        resampled,
        {row.publication_week: frozenset({row.family_id}) for row in resampled},
        lower_tail=LOWER_TAIL,
        upper_tail=UPPER_TAIL,
    )
    pop_likes, pop_decided = _tally(population)
    other_likes, other_decided = _tally(other)
    return LikeRateComparison(
        comparator=validate_non_empty_string(comparator),
        population_likes=pop_likes,
        population_decided=pop_decided,
        comparator_likes=other_likes,
        comparator_decided=other_decided,
        population_rate=_rate(pop_likes, pop_decided),
        comparator_rate=_rate(other_likes, other_decided),
        weeks=len(rows),
        interval=interval,
        verdict=interval_verdict(
            interval.low, interval.high, favorable_direction="higher"
        ),
    )
