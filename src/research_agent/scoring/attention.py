"""Selection disagreement with the discovery services' picks (SDD-IN-04).

The non-overlap term is one minus the share of a batch's deduplicated nominations
that a permitted service also captured on the same batch. It is a descriptive
diagnostic with no fitness output: a missing comparator or an empty nomination
set yields no value with a reason, never one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_uuid4,
)


@dataclass(frozen=True, slots=True)
class PickNonOverlap:
    """One configuration's pick-set non-overlap on one batch."""

    source_id: str
    value: float | None
    reason: str | None
    nomination_hash: str
    capture_hash: str


def _family_set(ids: Iterable[str]) -> frozenset[str]:
    unique = frozenset(ids)
    for family_id in unique:
        validate_uuid4(family_id)
    return unique


def _set_hash(ids: frozenset[str]) -> str:
    return sha256_hex(canonical_json(sorted(ids)))


def pick_nonoverlap(
    nominated_family_ids: Iterable[str],
    captured_family_ids: Iterable[str],
    *,
    source_id: str,
) -> PickNonOverlap:
    """Return `1 - |nominated & captured| / |nominated|` over deduplicated sets."""

    validate_non_empty_string(source_id)
    nominated = _family_set(nominated_family_ids)
    captured = _family_set(captured_family_ids)
    value: float | None = None
    reason: str | None = None
    if not nominated:
        reason = "no_nominations"
    elif not captured:
        reason = "no_source_captures"
    else:
        value = 1.0 - len(nominated & captured) / len(nominated)
    return PickNonOverlap(
        source_id=source_id,
        value=value,
        reason=reason,
        nomination_hash=_set_hash(nominated),
        capture_hash=_set_hash(captured),
    )
