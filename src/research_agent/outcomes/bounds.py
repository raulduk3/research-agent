"""Conservative family and subfield bounds from immutable citation records."""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts.learning import (
    CitationFamilyRecord,
    CountBounds,
    LabelCounts,
)
from research_agent.storage.errors import IntegrityFailure
from research_agent.outcomes.windows import (
    FIRST_YEAR,
    FIRST_LATE,
    SECOND_LATE,
    OutcomeWindow,
)


@dataclass(frozen=True, slots=True)
class BoundEvidence:
    counts: LabelCounts
    year_witnesses: tuple[str, ...]
    first_late_witnesses: tuple[str, ...]
    second_late_witnesses: tuple[str, ...]
    subfield_witnesses: tuple[tuple[str, str], ...]


def _membership(record: CitationFamilyRecord, t0: str, window: OutcomeWindow) -> str:
    if record.is_target_family_self_link:
        return "outside"
    if record.date_state == "missing":
        return "possible"
    intervals = record.alternative_publication_intervals
    if record.publication_interval is not None:
        intervals = (record.publication_interval, *intervals)
    return window.classify_alternatives(t0, intervals)


def _components(
    records: tuple[CitationFamilyRecord, ...], *, possible: bool
) -> list[list[int]]:
    parents = list(range(len(records)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    tokens: dict[tuple[str, str], int] = {}
    for index, record in enumerate(records):
        identifiers = [("family", record.canonical_family_id)]
        identifiers.extend(("provider", value) for value in record.provider_work_ids)
        identifiers.extend((value.scheme, value.value) for value in record.external_ids)
        if possible and record.possible_identity_cluster is not None:
            identifiers.append(("possible", record.possible_identity_cluster))
        for token in identifiers:
            if token in tokens:
                parents[root(index)] = root(tokens[token])
            else:
                tokens[token] = index
    groups: dict[int, list[int]] = {}
    for index in range(len(records)):
        groups.setdefault(root(index), []).append(index)
    return list(groups.values())


def _maximum_subfields(choices: list[set[str]]) -> int:
    """Each possible family can introduce at most one distinct subfield."""
    owners: dict[str, int] = {}

    for initial in range(len(choices)):
        # Iterative augmenting paths avoid Python recursion limits on large captures.
        queue = [initial]
        predecessor: dict[int, tuple[int, str]] = {}
        seen_families = {initial}
        seen_fields: set[str] = set()
        matched = False
        for index in queue:
            for field in sorted(choices[index]):
                if field in seen_fields:
                    continue
                seen_fields.add(field)
                owner = owners.get(field)
                if owner is None:
                    owners[field] = index
                    while index != initial:
                        parent, prior_field = predecessor[index]
                        owners[prior_field] = parent
                        index = parent
                    matched = True
                    break
                if owner not in seen_families:
                    seen_families.add(owner)
                    predecessor[owner] = (index, field)
                    queue.append(owner)
            if matched:
                break
    return len(owners)


def citation_bounds(
    records: tuple[CitationFamilyRecord, ...],
    *,
    t0: str,
    target_subfield: str | None,
    complete: bool,
) -> BoundEvidence:
    if type(complete) is not bool:
        raise ValueError("capture completeness must be boolean")
    exact = _components(records, possible=False)
    for group in exact:
        if len({records[index].is_target_family_self_link for index in group}) > 1:
            raise IntegrityFailure(
                "exact aliases disagree on target-family self linkage"
            )
    possible = _components(records, possible=True)
    windows = (FIRST_YEAR, FIRST_LATE, SECOND_LATE)
    membership = [
        [_membership(record, t0, window) for window in windows] for record in records
    ]
    witnesses: list[tuple[str, ...]] = []
    counters: list[CountBounds] = []
    for window in range(3):
        lower_ids = tuple(
            sorted(
                min(records[index].canonical_family_id for index in group)
                for group in possible
                if all(membership[index][window] == "definite" for index in group)
            )
        )
        upper = sum(
            any(membership[index][window] != "outside" for index in group)
            and not any(records[index].is_target_family_self_link for index in group)
            for group in exact
        )
        witnesses.append(lower_ids)
        counters.append(CountBounds(len(lower_ids), upper if complete else None))
    lower_fields: dict[str, str] = {}
    for group in possible:
        if not all(
            membership[index][0] == "definite"
            and records[index].subfield_state == "known"
            for index in group
        ):
            continue
        fields = {records[index].primary_subfield_id for index in group}
        if len(fields) != 1:
            continue
        field = next(iter(fields))
        if field is None or field == target_subfield or target_subfield is None:
            continue
        family = min(records[index].canonical_family_id for index in group)
        lower_fields[field] = min(lower_fields.get(field, family), family)
    choices: list[set[str]] = []
    for number, group in enumerate(exact):
        if any(records[index].is_target_family_self_link for index in group):
            continue
        fields_for_family: set[str] = set()
        for index in group:
            record = records[index]
            if membership[index][0] == "outside":
                continue
            if record.primary_subfield_id is not None:
                fields_for_family.add(record.primary_subfield_id)
            fields_for_family.update(record.alternative_subfield_ids)
            if record.subfield_state == "missing":
                # A unique opaque candidate realizes the maximal unknown taxonomy case.
                fields_for_family.add(f"\x00unknown:{number}")
        if target_subfield is not None:
            fields_for_family.discard(target_subfield)
        choices.append(fields_for_family)
    upper_fields = _maximum_subfields(choices)
    counters.append(CountBounds(len(lower_fields), upper_fields if complete else None))
    return BoundEvidence(
        LabelCounts(*counters),
        witnesses[0],
        witnesses[1],
        witnesses[2],
        tuple(sorted(lower_fields.items())),
    )
