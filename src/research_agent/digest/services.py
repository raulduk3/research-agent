"""Bounded discovery-service pick allocation without revealing source (EN-42)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass

SERVICE_ENTRY_LIMIT = 2


@dataclass(frozen=True, slots=True)
class ServicePick:
    """One captured service reference, resolved to a corpus family or not.

    ``family_id`` is ``None`` when the reference has no matching corpus
    family or no permitted same-day capture; such a pick is recorded omitted
    rather than admitted as a second corpus.
    """

    reference: str
    family_id: str | None


@dataclass(frozen=True, slots=True)
class ServiceAllocation:
    """The island's service-pick entries for one digest build (EN-42)."""

    selected: tuple[str, ...]
    omitted: tuple[str, ...]
    shortfall: int


def allocate_service_entries(
    service_picks: Mapping[str, Sequence[ServicePick]],
    *,
    already_selected: Set[str],
) -> ServiceAllocation:
    """Round-robin lexically sorted services into up to two new entries.

    Each service's own captured order is preserved; only the service ids are
    sorted before round-robining one pick per service per round. A pick
    naming a family already selected by the population or the controls is
    skipped without consuming a slot; a pick with no matched family is
    recorded omitted (TDD-3.1.36).
    """

    selected: list[str] = []
    omitted: list[str] = []
    taken = set(already_selected)
    service_ids = sorted(service_picks)
    cursors = {service_id: 0 for service_id in service_ids}
    active = list(service_ids)
    while active and len(selected) < SERVICE_ENTRY_LIMIT:
        progressed = False
        for service_id in list(active):
            picks = service_picks[service_id]
            cursor = cursors[service_id]
            family_id = None
            while cursor < len(picks):
                pick = picks[cursor]
                cursor += 1
                if pick.family_id is None:
                    omitted.append(pick.reference)
                    continue
                if pick.family_id in taken:
                    continue
                family_id = pick.family_id
                break
            cursors[service_id] = cursor
            if family_id is None:
                active.remove(service_id)
                continue
            taken.add(family_id)
            selected.append(family_id)
            progressed = True
            if len(selected) >= SERVICE_ENTRY_LIMIT:
                break
        if not progressed:
            break

    return ServiceAllocation(
        selected=tuple(selected),
        omitted=tuple(omitted),
        shortfall=SERVICE_ENTRY_LIMIT - len(selected),
    )
