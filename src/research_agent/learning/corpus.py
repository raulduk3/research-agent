"""Outcome-independent pilot selection with explicit intended denominators."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from research_agent.contracts import canonical_json, sha256_hex
from research_agent.outcomes.windows import MATURITY_SECONDS, instant, utc

SELECTION_SEED = 20260920
DEFAULT_CAP = 100
DEFAULT_PER_MONTH = 4
DEFAULT_POPULATION_RULE = (
    "100-paper acquisition pilot: four families per mature month, ranked by "
    "ascending seeded hash of the canonical arXiv id"
)
DEFAULT_CATEGORIES: tuple[str, ...] = ("cs.AI", "cs.LG", "quant-ph", "q-bio")


_ARXIV_FAMILY = re.compile(r"[0-9]{4}\.[0-9]{4,5}\Z")


@dataclass(frozen=True, slots=True)
class PilotCandidate:
    """One listed arXiv family: canonical unversioned id, v1 time and categories.

    `primary_category` defaults to the first listed category (arXiv's own
    convention) so a cross-listed family carries its primary category
    without every caller having to compute it (decision 0016).
    """

    family_id: str
    first_public_at: str
    categories: tuple[str, ...]
    primary_category: str | None = None

    def __post_init__(self) -> None:
        if _ARXIV_FAMILY.fullmatch(self.family_id) is None:
            raise ValueError("pilot candidate needs a canonical unversioned arXiv id")
        instant(self.first_public_at)
        if not self.categories or not all(
            isinstance(value, str) and value for value in self.categories
        ):
            raise ValueError("pilot candidate categories are invalid")
        if self.primary_category is None:
            object.__setattr__(self, "primary_category", self.categories[0])
        elif self.primary_category not in self.categories:
            raise ValueError("primary category must be one of the listed categories")


@dataclass(frozen=True, slots=True)
class PilotSelection:
    frozen_at: str
    publication_months: tuple[str, ...]
    selected: tuple[PilotCandidate, ...]
    month_shortfalls: tuple[tuple[str, int], ...]
    eligible_counts: tuple[tuple[str, int], ...]
    intended_count: int = 100
    seed: int = SELECTION_SEED
    population_rule: str = DEFAULT_POPULATION_RULE
    categories: tuple[str, ...] = tuple(sorted(DEFAULT_CATEGORIES))

    @property
    def shortfall_count(self) -> int:
        return sum(count for _, count in self.month_shortfalls)


def _previous_month(value: datetime) -> datetime:
    return (value.replace(day=1) - timedelta(days=1)).replace(day=1)


def mature_months(frozen_at: str) -> tuple[str, ...]:
    """Latest 25 UTC months whose last possible instant is already mature."""
    freeze = instant(frozen_at)
    candidate = freeze.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result: list[str] = []
    while len(result) < 25:
        next_month = (candidate.replace(day=28) + timedelta(days=4)).replace(day=1)
        last_instant = next_month - timedelta(microseconds=1)
        if last_instant + timedelta(seconds=MATURITY_SECONDS) < freeze:
            result.append(candidate.strftime("%Y-%m"))
        candidate = _previous_month(candidate)
    return tuple(reversed(result))


def selection_hash(family_id: str, seed: int = SELECTION_SEED) -> str:
    """Rank key over the canonical arXiv id, reproducible from arXiv's listing."""
    # Canonical encoding fixes the seed/id boundary without ambiguous concatenation.
    return sha256_hex(canonical_json({"seed": seed, "paper_family_id": family_id}))


def select_pilot(
    candidates: tuple[PilotCandidate, ...],
    *,
    frozen_at: str,
    seed: int = SELECTION_SEED,
    cap: int = DEFAULT_CAP,
    per_month: int = DEFAULT_PER_MONTH,
    population_rule: str = DEFAULT_POPULATION_RULE,
    categories: Iterable[str] = DEFAULT_CATEGORIES,
) -> PilotSelection:
    """Select eligible families without consulting outcomes or availability. A
    family is eligible when any of its categories is among `categories`
    (default: cs.AI, cs.LG, quant-ph, q-bio), including cross-lists.

    With `per_month` positive, stratifies the draw at up to `per_month`
    families per mature month (the pilot's own purpose), then truncates to
    `cap`. With `per_month` zero, draws uniformly over every eligible family
    across the whole mature window by ascending seeded hash, capped at `cap`.
    """
    if cap < 0:
        raise ValueError("cap must not be negative")
    if per_month < 0:
        raise ValueError("per_month must not be negative")
    target_categories = frozenset(categories)
    freeze = instant(frozen_at)
    months = mature_months(frozen_at)
    buckets: dict[str, dict[str, PilotCandidate]] = {month: {} for month in months}
    families: dict[str, PilotCandidate] = {}
    for candidate in candidates:
        if target_categories.isdisjoint(candidate.categories):
            continue
        prior = families.get(candidate.family_id)
        if prior is not None:
            if prior.first_public_at != candidate.first_public_at:
                raise ValueError("family has conflicting first-public times")
            continue
        families[candidate.family_id] = candidate
        month = instant(candidate.first_public_at).strftime("%Y-%m")
        if month in buckets:
            buckets[month][candidate.family_id] = candidate

    def rank(item: PilotCandidate) -> tuple[str, str]:
        return (selection_hash(item.family_id, seed), item.family_id)

    if per_month:
        selected = []
        shortages = []
        for month in months:
            ranked = sorted(buckets[month].values(), key=rank)
            selected.extend(ranked[:per_month])
            shortages.append((month, max(0, per_month - len(ranked))))
        selected = selected[:cap]
    else:
        pool = [c for month in months for c in buckets[month].values()]
        selected = sorted(pool, key=rank)[:cap]
        shortages = [(month, 0) for month in months]
    return PilotSelection(
        utc(freeze),
        months,
        tuple(selected),
        tuple(shortages),
        tuple((month, len(buckets[month])) for month in months),
        cap,
        seed,
        population_rule,
        tuple(sorted(target_categories)),
    )


def publication_week(t0: str) -> str:
    iso = instant(t0).isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


@dataclass(frozen=True, slots=True)
class WeekSplit:
    fit: tuple[str, ...]
    development: tuple[str, ...]
    calibration: tuple[str, ...]
    locked_evaluation: tuple[str, ...]


def split_weeks(weeks: tuple[str, ...]) -> WeekSplit:
    """Freeze chronological partitions before outcome inspection; never shrink gates."""
    if len(weeks) < 40 or len(set(weeks)) != len(weeks):
        raise ValueError("temporal split requires at least 40 distinct weeks")
    dates = []
    for week in weeks:
        try:
            parsed = datetime.strptime(week + "-1", "%G-W%V-%u").replace(
                tzinfo=timezone.utc
            )
        except ValueError as error:
            raise ValueError("invalid ISO publication week") from error
        if publication_week(utc(parsed)) != week:
            raise ValueError("publication week is not canonical")
        dates.append(parsed)
    if dates != sorted(dates):
        raise ValueError("publication weeks must be chronologically ordered")
    count = len(weeks)
    first, second, third = count * 60 // 100, count * 15 // 100, count * 10 // 100
    return WeekSplit(
        weeks[:first],
        weeks[first : first + second],
        weeks[first + second : first + second + third],
        weeks[first + second + third :],
    )
