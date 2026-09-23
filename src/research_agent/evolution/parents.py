"""Skill-ranked parent selection within an island (AG-19, FT-27).

``draw_parents`` is the cycle-gated draw AG-19 describes: before the third
weekly cycle it is disabled by profile like every other evolution
mechanism; afterward it ranks the island's eligible genomes on FT-12's mean
skill, or the island's registered proxy while skill is unavailable, gated
first by the minimum resolved-claim count and FT-27's grounding floor, and
draws the requested count from the top of that ranking.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_positive_int,
)
from research_agent.evolution.genome import Genome, GenomeStanding, rank_items
from research_agent.orchestration.selection import cycle_guard


@dataclass(frozen=True, slots=True)
class DrawResult:
    """The outcome of one parent draw within an island (AG-19)."""

    disposition: Literal["disabled_by_profile", "drawn"]
    profile_hash: str
    ranked_support: tuple[str, ...]
    drawn: tuple[Genome, ...]
    excluded: tuple[str, ...] = ()


def draw_parents(
    *,
    island: str,
    standings: Sequence[GenomeStanding],
    count: int,
    completed_weekly_cycles: int | None,
    profile_hash: str | None,
    minimum_resolved_claim_count: int = 30,
    grounding_floor: float = 0.95,
) -> DrawResult:
    """Draw up to *count* parents from *island*'s eligible, ranked genomes.

    Applies the cycle guard first: before the third weekly cycle this
    returns ``disabled_by_profile`` and draws nothing. Afterward, a genome
    below the minimum resolved-claim count or FT-27's grounding floor is
    excluded before ranking; the rest are ranked by mean skill, or the
    island's registered proxy while skill is unavailable, tied on skill per
    dollar. No agent output or cost figure enters the ranking beyond that
    recorded skill-per-dollar tie-break; a rating enters only as the
    already-computed preference-credit proxy a caller supplies.
    """

    validate_positive_int(count)
    for standing in standings:
        if standing.genome.island != island:
            raise ContractValidationError(
                "draw_parents received a standing of another island"
            )

    guard = cycle_guard(
        profile_hash=profile_hash, completed_weekly_cycles=completed_weekly_cycles
    )
    if guard.disposition == "disabled_by_profile":
        return DrawResult(
            disposition="disabled_by_profile",
            profile_hash=guard.profile_hash,
            ranked_support=(),
            drawn=(),
        )

    ranked, excluded = rank_items(
        standings,
        standing_of=lambda standing: standing,
        minimum_resolved_claim_count=minimum_resolved_claim_count,
        grounding_floor=grounding_floor,
    )
    drawn = tuple(standing.genome for standing in ranked[:count])
    return DrawResult(
        disposition="drawn",
        profile_hash=guard.profile_hash,
        ranked_support=tuple(standing.genome.configuration_hash for standing in ranked),
        drawn=drawn,
        excluded=tuple(standing.genome.configuration_hash for standing, _ in excluded),
    )
