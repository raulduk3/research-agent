"""Outcome-independent pilot selection with explicit intended denominators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from research_agent.contracts import canonical_json, sha256_hex
from research_agent.contracts.papers import PaperVersionRecord
from research_agent.outcomes.windows import MATURITY_SECONDS, instant, utc

SELECTION_SEED = 20260920


@dataclass(frozen=True, slots=True)
class PilotSelection:
    frozen_at: str
    publication_months: tuple[str, ...]
    selected: tuple[PaperVersionRecord, ...]
    month_shortfalls: tuple[tuple[str, int], ...]
    intended_count: int = 100

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


def selection_hash(family_id: str) -> str:
    # Canonical encoding fixes the seed/id boundary without ambiguous concatenation.
    return sha256_hex(
        canonical_json({"seed": SELECTION_SEED, "paper_family_id": family_id})
    )


def select_pilot(
    candidates: tuple[PaperVersionRecord, ...], *, frozen_at: str
) -> PilotSelection:
    """Select four originals per month without consulting outcomes or availability."""
    freeze = instant(frozen_at)
    months = mature_months(frozen_at)
    buckets: dict[str, dict[str, PaperVersionRecord]] = {month: {} for month in months}
    families: dict[str, PaperVersionRecord] = {}
    for paper in candidates:
        if (
            not paper.is_first_public_version
            or paper.first_public_at is None
            or paper.primary_source_subfield not in {"cs.AI", "cs.LG"}
            or not any(
                identifier.scheme == "arxiv" for identifier in paper.external_ids
            )
        ):
            continue
        if instant(paper.created_at) > freeze:
            raise ValueError("candidate was recorded after selection freeze")
        prior = families.get(paper.family_id)
        if prior is not None:
            if prior != paper:
                raise ValueError("family has conflicting original selection records")
            continue
        families[paper.family_id] = paper
        month = instant(paper.first_public_at).strftime("%Y-%m")
        if month in buckets:
            buckets[month][paper.family_id] = paper
    selected = []
    shortages = []
    for month in months:
        ranked = sorted(
            buckets[month].values(),
            key=lambda paper: (selection_hash(paper.family_id), paper.family_id),
        )
        selected.extend(ranked[:4])
        shortages.append((month, max(0, 4 - len(ranked))))
    return PilotSelection(utc(freeze), months, tuple(selected), tuple(shortages))


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
