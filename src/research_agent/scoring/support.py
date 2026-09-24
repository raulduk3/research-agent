"""Unresolved-outcome masking: which sealed forecasts may enter a loss (SDD-IN-03).

Only an eligible row that carries an explicit true or false resolution for the
exact target definition being scored is selected. Every other eligible row is
counted as unresolved and every ineligible row as excluded, so they grow the
coverage denominator without ever contributing a squared error.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
)
from research_agent.scoring.schemas import ScoringRow


@dataclass(frozen=True, slots=True)
class ResolvedSupport:
    """The rows that may enter loss, and the coverage counters for the rest."""

    resolved: tuple[ScoringRow, ...]
    unresolved_count: int
    excluded_count: int

    @property
    def intended_count(self) -> int:
        return len(self.resolved) + self.unresolved_count + self.excluded_count


def resolved_support(
    rows: Sequence[ScoringRow],
    *,
    target_id: str,
    target_definition_hash: str,
) -> ResolvedSupport:
    """Select the resolved eligible rows of one target definition, in input order.

    A row for a different target or target version is a caller error, not a
    mask: it would otherwise silently shrink the denominator. A resolution
    dated before its forecast sealed is a malformed temporal record and fails
    the whole selection.
    """

    validate_sha256(target_definition_hash)
    resolved: list[ScoringRow] = []
    unresolved = 0
    excluded = 0
    for row in rows:
        if row.target_id != target_id or (
            row.target_definition_hash != target_definition_hash
        ):
            raise ContractValidationError(
                "resolved_support selects exactly one target definition",
            )
        if row.resolution is not None and row.resolution.resolved_at < row.sealed_at:
            raise ContractValidationError("a resolution predates its forecast's seal")
        if not row.eligible:
            excluded += 1
        elif row.resolution is None:
            unresolved += 1
        else:
            resolved.append(row)
    return ResolvedSupport(tuple(resolved), unresolved, excluded)
