"""Mutation similarity admission: refuse a child that repeats a genome (AG-21).

``admit_child`` runs after the corpus-identifier scan (AG-31) and the
q-bio migration refusal (AG-37), both owned elsewhere and both applied
before this function is ever reached. What is left here is the comparison
AG-21 itself names: a child's configuration hash against every active and
archived genome hash of its own island.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from research_agent.evolution.genome import Genome
from research_agent.orchestration.selection import cycle_guard


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    """The outcome of one child's similarity-admission check (AG-21)."""

    disposition: Literal["disabled_by_profile", "rejected", "accepted"]
    profile_hash: str
    child_hash: str
    matched_hash: str | None = None


def admit_child(
    *,
    child: Genome,
    active_genomes: Sequence[Genome],
    archived_genomes: Sequence[Genome],
    completed_weekly_cycles: int | None,
    profile_hash: str | None,
) -> AdmissionResult:
    """Refuse *child* when its hash equals an active or archived genome of its island.

    Applies the cycle guard first. Afterward, compares *child*'s
    configuration hash against every genome of its own island among
    *active_genomes* and *archived_genomes* -- genomes of other islands
    never affect this comparison -- and refuses an equal hash.
    """

    child_hash = child.configuration_hash
    guard = cycle_guard(
        profile_hash=profile_hash, completed_weekly_cycles=completed_weekly_cycles
    )
    if guard.disposition == "disabled_by_profile":
        return AdmissionResult(
            disposition="disabled_by_profile",
            profile_hash=guard.profile_hash,
            child_hash=child_hash,
        )

    for existing in (*active_genomes, *archived_genomes):
        if existing.island != child.island:
            continue
        if existing.configuration_hash == child_hash:
            return AdmissionResult(
                disposition="rejected",
                profile_hash=guard.profile_hash,
                child_hash=child_hash,
                matched_hash=existing.configuration_hash,
            )
    return AdmissionResult(
        disposition="accepted", profile_hash=guard.profile_hash, child_hash=child_hash
    )
