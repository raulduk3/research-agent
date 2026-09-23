"""Preference-ranked nomination allocation for population entries (EN-41).

One run maps to one paper (decision 0022), so a configuration's daily
nomination list is simply its own day of accepted, recommended nominations
ranked by preference; the round-robin merge across an island's
configurations is otherwise unchanged from decision 0015's shape.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

POPULATION_ENTRY_LIMIT = 7


@dataclass(frozen=True, slots=True)
class Nomination:
    """One run's accepted, recommended nomination (AG-26)."""

    paper_id: str
    preference: float


@dataclass(frozen=True, slots=True)
class NominationWinner:
    """One population entry and every configuration whose list named it."""

    family_id: str
    configuration_id: str
    supporting_configuration_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PopulationAllocation:
    """The island's population entries for one digest build (EN-41)."""

    rotation: tuple[str, ...]
    winners: tuple[NominationWinner, ...]
    shortfall: int


def allocate_population_entries(
    configuration_nominations: Mapping[str, Sequence[Nomination]],
    *,
    day_ordinal: int,
) -> PopulationAllocation:
    """Round-robin merge each configuration's preference-ranked list.

    ``configuration_nominations`` maps each of an island's active
    configuration ids to that configuration's day of accepted submissions
    with ``recommend=true``; a caller has already dropped void or
    quarantined submissions and any nomination outside the island, since
    those are refused at submit and never reach allocation. Each
    configuration's own list is ordered here by preference descending then
    paper id, never by any citation-head probability, so replaying the
    identical nominations reproduces byte-identical output regardless of
    any prediction-head change.
    """

    configuration_lists = {
        configuration_id: _rank_by_preference(nominations)
        for configuration_id, nominations in configuration_nominations.items()
    }
    rotation = _rotate(sorted(configuration_lists), day_ordinal)

    winners: list[NominationWinner] = []
    selected_ids: set[str] = set()
    cursors = {configuration_id: 0 for configuration_id in rotation}
    active = list(rotation)
    while active and len(winners) < POPULATION_ENTRY_LIMIT:
        progressed = False
        for configuration_id in list(active):
            family_id, cursor = _next_unseen(
                configuration_lists[configuration_id],
                cursors[configuration_id],
                selected_ids,
            )
            cursors[configuration_id] = cursor
            if family_id is None:
                active.remove(configuration_id)
                continue
            selected_ids.add(family_id)
            supporting = tuple(
                other for other in rotation if family_id in configuration_lists[other]
            )
            winners.append(
                NominationWinner(
                    family_id=family_id,
                    configuration_id=configuration_id,
                    supporting_configuration_ids=supporting,
                )
            )
            progressed = True
            if len(winners) >= POPULATION_ENTRY_LIMIT:
                break
        if not progressed:
            break

    return PopulationAllocation(
        rotation=tuple(rotation),
        winners=tuple(winners),
        shortfall=POPULATION_ENTRY_LIMIT - len(winners),
    )


def _rank_by_preference(nominations: Sequence[Nomination]) -> tuple[str, ...]:
    """One configuration's day of nominations, ranked by preference (AG-26, EN-41).

    Descending preference, ties broken by ascending paper id; a paper
    nominated more than once by the same configuration in a day is not
    expected (one run per paper per configuration), but the later
    duplicate is dropped defensively rather than winning a second entry.
    """

    ordered = sorted(nominations, key=lambda item: (-item.preference, item.paper_id))
    seen: set[str] = set()
    ranked: list[str] = []
    for nomination in ordered:
        if nomination.paper_id in seen:
            continue
        seen.add(nomination.paper_id)
        ranked.append(nomination.paper_id)
    return tuple(ranked)


def _next_unseen(
    items: Sequence[str], cursor: int, seen: set[str]
) -> tuple[str | None, int]:
    while cursor < len(items):
        if items[cursor] not in seen:
            return items[cursor], cursor + 1
        cursor += 1
    return None, cursor


def _rotate(ordered_ids: Sequence[str], day_ordinal: int) -> list[str]:
    if not ordered_ids:
        return []
    offset = day_ordinal % len(ordered_ids)
    return list(ordered_ids[offset:]) + list(ordered_ids[:offset])
