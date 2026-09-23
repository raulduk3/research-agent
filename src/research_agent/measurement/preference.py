"""A rating's credit to the genomes that nominated the rated paper (IN-43, TDD-4.1.79).

`credit_ratings` is a pure function of already-read rating events and the
nominations sealed for their entries. It never reads a score, a resolver input
or a ledger outcome, and nothing it returns flows back into them: the credit
is the island's weekly selection proxy and nothing else.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from research_agent.contracts.digests import DIGEST_ISLANDS, DIGEST_ORIGINS
from research_agent.contracts.preference import validate_iso_week
from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_probability,
    validate_sha256,
    validate_uuid4,
)
from research_agent.measurement import MeasurementError

RATING_SIGNS: dict[str, int] = {"like": 1, "dislike": -1, "skip": 0}

GAP_UNREADABLE = "the nominating submissions could not be read"
GAP_OTHER_ISLAND = "no nominating genome belongs to the rated island"
GAP_ZERO_PROBABILITY = "the nominating genomes sealed no probability above zero"


@dataclass(frozen=True, slots=True)
class SealedNomination:
    """One genome's accepted nomination of a paper with the probability it sealed."""

    genome_hash: str
    island: str
    sealed_probability: float

    def __post_init__(self) -> None:
        validate_sha256(self.genome_hash)
        if self.island not in DIGEST_ISLANDS:
            raise MeasurementError("island is not an admitted value")
        validate_probability(self.sealed_probability)


@dataclass(frozen=True, slots=True)
class RatingEvent:
    """One rating of a digest entry with its origin and, for a population entry, nominators.

    ``nominations`` is ``None`` when the nominating submissions could not be
    read, which is not the same as an entry nobody nominated.
    """

    rating_id: str
    entry_id: str
    island: str
    iso_week: str
    value: str
    origin: str
    nominations: tuple[SealedNomination, ...] | None

    def __post_init__(self) -> None:
        validate_uuid4(self.rating_id)
        validate_uuid4(self.entry_id)
        if self.island not in DIGEST_ISLANDS:
            raise MeasurementError("island is not an admitted value")
        validate_iso_week(self.iso_week)
        if self.value not in RATING_SIGNS:
            raise MeasurementError("value must be like, dislike or skip")
        if self.origin not in DIGEST_ORIGINS:
            raise MeasurementError("origin is not an admitted value")
        if self.nominations is not None:
            hashes = [nomination.genome_hash for nomination in self.nominations]
            if len(set(hashes)) != len(hashes):
                raise MeasurementError("a genome nominates an entry once")

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> RatingEvent:
        """Build an event from one row of `PreferenceRepository.read_rating_events`."""

        nominations = record["nominations"]
        return cls(
            rating_id=record["rating_id"],
            entry_id=record["entry_id"],
            island=record["island"],
            iso_week=record["iso_week"],
            value=record["value"],
            origin=record["origin"],
            nominations=None
            if nominations is None
            else tuple(SealedNomination(**item) for item in nominations),
        )


@dataclass(frozen=True, slots=True)
class PreferenceCredit:
    """One rating's signed share for one nominating genome."""

    rating_id: str
    genome_hash: str
    island: str
    entry_id: str
    sealed_probability: float
    share: float
    iso_week: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rating_id": self.rating_id,
            "genome_hash": self.genome_hash,
            "island": self.island,
            "entry_id": self.entry_id,
            "sealed_probability": self.sealed_probability,
            "share": self.share,
            "iso_week": self.iso_week,
        }


@dataclass(frozen=True, slots=True)
class CreditGap:
    """A population rating that could not be credited, and why."""

    rating_id: str
    iso_week: str
    reason: str

    def __post_init__(self) -> None:
        validate_uuid4(self.rating_id)
        validate_iso_week(self.iso_week)
        validate_non_empty_string(self.reason)


@dataclass(frozen=True, slots=True)
class CreditOutcome:
    credits: tuple[PreferenceCredit, ...]
    gaps: tuple[CreditGap, ...]


def credit_ratings(ratings: Sequence[RatingEvent]) -> CreditOutcome:
    """Divide each population rating among the genomes that nominated its paper.

    A like counts plus one and a dislike minus one; each nominating genome
    of the rated island receives the sign times its sealed probability over
    the nominating genomes' summed probabilities, so a rating's shares sum
    to its sign. A skip, a random control and a service pick credit nothing
    and record no row. A population rating whose nominators cannot be read,
    or none of whom belongs to the island, or whose probabilities sum to
    zero, is a gap: nothing is imputed for it.
    """

    ids = [rating.rating_id for rating in ratings]
    if len(set(ids)) != len(ids):
        raise MeasurementError("a rating event appears once")
    credits: list[PreferenceCredit] = []
    gaps: list[CreditGap] = []
    for rating in ratings:
        sign = RATING_SIGNS[rating.value]
        if rating.origin != "population" or sign == 0:
            continue
        if rating.nominations is None:
            gaps.append(CreditGap(rating.rating_id, rating.iso_week, GAP_UNREADABLE))
            continue
        nominators = [
            nomination
            for nomination in rating.nominations
            if nomination.island == rating.island
        ]
        if not nominators:
            gaps.append(
                CreditGap(
                    rating.rating_id,
                    rating.iso_week,
                    GAP_UNREADABLE if not rating.nominations else GAP_OTHER_ISLAND,
                )
            )
            continue
        total = sum(nomination.sealed_probability for nomination in nominators)
        if total <= 0:
            gaps.append(
                CreditGap(rating.rating_id, rating.iso_week, GAP_ZERO_PROBABILITY)
            )
            continue
        for nomination in sorted(nominators, key=lambda item: item.genome_hash):
            credits.append(
                PreferenceCredit(
                    rating_id=rating.rating_id,
                    genome_hash=nomination.genome_hash,
                    island=rating.island,
                    entry_id=rating.entry_id,
                    sealed_probability=nomination.sealed_probability,
                    share=sign * nomination.sealed_probability / total,
                    iso_week=rating.iso_week,
                )
            )
    return CreditOutcome(credits=tuple(credits), gaps=tuple(gaps))
