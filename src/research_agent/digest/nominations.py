"""Two-stage deterministic nomination allocation for population entries (EN-41)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

POPULATION_ENTRY_LIMIT = 7


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
    shard_nominations: Mapping[str, Sequence[Sequence[str]]],
    *,
    day_ordinal: int,
) -> PopulationAllocation:
    """Round-robin merge shard nominations, then configurations, into up to seven entries.

    ``shard_nominations`` maps each of an island's active configuration ids to
    that configuration's own shard nomination lists, in shard order; a caller
    has already dropped void or quarantined submissions and any nomination
    outside the island, since those are refused at submit and never reach
    allocation. No probability, score or rationale is read here, so replaying
    the identical lists reproduces byte-identical output regardless of any
    prediction-head change (EN-41's "do not sort by citation-head
    probabilities").
    """

    configuration_lists = {
        configuration_id: _merge_round_robin(lists)
        for configuration_id, lists in shard_nominations.items()
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


def _merge_round_robin(shard_lists: Sequence[Sequence[str]]) -> tuple[str, ...]:
    """Merge one configuration's shard lists round-robin in shard order, skipping repeats."""

    seen: set[str] = set()
    merged: list[str] = []
    cursors = [0] * len(shard_lists)
    active = list(range(len(shard_lists)))
    while active:
        progressed = False
        for index in list(active):
            family_id, cursor = _next_unseen(shard_lists[index], cursors[index], seen)
            cursors[index] = cursor
            if family_id is None:
                active.remove(index)
                continue
            seen.add(family_id)
            merged.append(family_id)
            progressed = True
        if not progressed:
            break
    return tuple(merged)


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
