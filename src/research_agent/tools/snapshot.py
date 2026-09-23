"""Bind every tool call to the run's own frozen snapshot, never a newer one.

A snapshot is frozen when its batch is issued (PL-21); the shared tool
service answers every call a run makes from exactly the snapshot named in
that run's own immutable specification, even after a newer snapshot
exists (AG-10). ``authorize_snapshot`` resolves that bound snapshot hash
from the run's own capability -- never from a caller-supplied field --
and compares it to what the call claims before any read runs, so a client
cannot select a newer snapshot by changing the request.

A ``deep_read`` or ``graph`` naming a family that bound snapshot does not
hold is answered by ``answer_outside_snapshot`` (decision 0025): it records
a paper request through storage and answers ``not_in_snapshot`` with the
receipt. The call still reads nothing outside the run's own snapshot; the
request is a row the acquisition side fulfils for a later snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID, uuid4

from ..contracts.primitives import ContractValidationError
from ..contracts.tools import PAPER_REQUEST_TOOLS, not_in_snapshot_answer

__all__ = [
    "PaperRequests",
    "RunLookup",
    "SnapshotMembership",
    "answer_outside_snapshot",
    "authorize_snapshot",
]


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


class SnapshotMembership(Protocol):
    """Whether a sealed snapshot holds a paper family."""

    def holds_family(self, snapshot_hash: str, family_id: str) -> bool:
        """True when *snapshot_hash* pins some version of *family_id*."""


class _RecordedRequest(Protocol):
    @property
    def data(self) -> Mapping[str, Any]: ...


class PaperRequests(Protocol):
    """Storage's paper-request command, as ``StorageClient`` exposes it."""

    def record_paper_request(
        self,
        *,
        run_id: UUID,
        family_id: UUID,
        snapshot_hash: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> _RecordedRequest: ...


def answer_outside_snapshot(
    *,
    tool: str,
    arguments: Mapping[str, Any],
    run_id: str,
    snapshot_hash: str,
    membership: SnapshotMembership,
    requests: PaperRequests,
) -> dict[str, Any] | None:
    """Record a request for a family *snapshot_hash* lacks, or return ``None``.

    Only ``deep_read`` and ``graph`` request papers. When the run's own
    snapshot holds the named family this returns ``None`` and the tool's
    handler answers as usual. Otherwise storage decides the outcome --
    ``requested``, ``already_requested`` or ``request_budget_exhausted``
    against the per-run cap -- and the answer is ``not_in_snapshot``
    carrying that receipt.
    """

    if tool not in PAPER_REQUEST_TOOLS:
        return None
    family_id = arguments["paper_id"]
    if membership.holds_family(snapshot_hash, family_id):
        return None
    result = requests.record_paper_request(
        run_id=UUID(run_id),
        family_id=UUID(family_id),
        snapshot_hash=snapshot_hash,
        command_id=uuid4(),
        request_id=uuid4(),
        idempotency_key=uuid4(),
    )
    return not_in_snapshot_answer(result.data)
