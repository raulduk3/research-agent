"""Seeded control-paper sampling from the residual eligible pool (EN-33)."""

from __future__ import annotations

from collections.abc import Sequence, Set
from dataclasses import dataclass
from hashlib import sha256

from research_agent.contracts.canonical import canonical_json, sha256_hex

CONTROL_LIMIT = 3


@dataclass(frozen=True, slots=True)
class ControlDraw:
    """The island's random-control entries for one digest build (EN-33)."""

    candidate_pool_hash: str
    selected: tuple[str, ...]
    inclusion_probability: float | None
    shortfall: int


def sample_controls(
    eligible_family_ids: Sequence[str],
    *,
    population_family_ids: Set[str],
    batch_hash: str,
    island: str,
    control_rubric_version: str,
) -> ControlDraw:
    """Sample up to three controls by SHA-256 rank, tied broken by family id.

    The candidate pool is the island's eligible daily families minus whatever
    the population allocation already selected, deduplicated and canonically
    ordered before ranking. Ranking depends only on ``batch_hash``,
    ``island``, ``control_rubric_version`` and each family id, never on a
    prediction-head score, so replaying the same inputs reproduces the same
    draw (TDD-3.1.32).
    """

    pool = sorted(set(eligible_family_ids) - set(population_family_ids))
    ranked = sorted(
        pool,
        key=lambda family_id: (
            _rank_key(batch_hash, island, control_rubric_version, family_id),
            family_id,
        ),
    )
    selected = tuple(ranked[:CONTROL_LIMIT])
    total = len(pool)
    inclusion_probability = min(CONTROL_LIMIT, total) / total if total > 0 else None
    return ControlDraw(
        candidate_pool_hash=sha256_hex(canonical_json(pool)),
        selected=selected,
        inclusion_probability=inclusion_probability,
        shortfall=CONTROL_LIMIT - len(selected),
    )


def _rank_key(
    batch_hash: str, island: str, control_rubric_version: str, family_id: str
) -> str:
    return sha256(
        f"{batch_hash}:{island}:{control_rubric_version}:{family_id}".encode()
    ).hexdigest()
