"""Bind every tool call to the run's own frozen snapshot, never a newer one.

A snapshot is frozen when its batch is issued (PL-21); the shared tool
service answers every call a run makes from exactly the snapshot named in
that run's own immutable specification, even after a newer snapshot
exists (AG-10). ``authorize_snapshot`` resolves that bound snapshot hash
from the run's own capability -- never from a caller-supplied field --
and compares it to what the call claims before any read runs, so a client
cannot select a newer snapshot by changing the request.
"""

from __future__ import annotations

from typing import Protocol

from ..contracts.primitives import ContractValidationError

__all__ = ["RunLookup", "authorize_snapshot"]


class RunLookup(Protocol):
    """Resolve a run's own immutable snapshot hash and admitted tools."""

    def snapshot_hash_for(self, run_id: str) -> str:
        """The snapshot hash pinned in this run's own specification."""

    def allowed_tools_for(self, run_id: str) -> frozenset[str]:
        """The tool names this run's own configuration admits (AG-14)."""

    def paper_id_for(self, run_id: str) -> str:
        """The one paper this run's own slot names (AG-25, AG-26)."""

    def issued_question_ids_for(self, run_id: str) -> frozenset[str]:
        """The question ids this run's own slot issued (AG-26)."""


def authorize_snapshot(
    lookup: RunLookup, run_id: str, requested_snapshot_id: str
) -> str:
    """Return the run's own snapshot hash, refusing any other (AG-10).

    Resolves the run's bound snapshot hash first, from its immutable
    capability, and only then compares it to ``requested_snapshot_id``.
    Read handlers must call this before resolving anything the call asks
    for, so a mismatch is refused before lookup rather than after.
    """

    bound_hash = lookup.snapshot_hash_for(run_id)
    if requested_snapshot_id != bound_hash:
        raise ContractValidationError(
            "tool call names a snapshot other than the run's own"
        )
    return bound_hash
