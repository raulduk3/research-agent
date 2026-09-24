"""The run specification and snapshot membership, read from storage (#287).

The shared tool service holds no run state of its own (PL-20). For each
call it reads the run's stored specification once through storage's
``GET /v1/runs/{id}/specification`` and answers the call against exactly
that record: :class:`SpecificationLookup` is the :class:`RunLookup` of one
run and refuses to speak for any other. :class:`StorageSnapshotMembership`
answers whether a sealed snapshot pins a family through storage's family
read, so nothing is inferred from what the call claims.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..contracts.primitives import ContractValidationError
from ..storage.client import QueryResult, RunSpecificationRecord, StorageClientError

__all__ = [
    "FamilyReads",
    "SpecificationLookup",
    "StorageSnapshotMembership",
]


class SpecificationLookup:
    """The :class:`~research_agent.tools.snapshot.RunLookup` of one stored run."""

    def __init__(self, specification: RunSpecificationRecord) -> None:
        self._specification = specification

    @property
    def active(self) -> bool:
        return self._specification.active

    def _own(self, run_id: str) -> RunSpecificationRecord:
        if run_id != str(self._specification.run_id):
            raise ContractValidationError("call names a run other than its own")
        return self._specification

    def snapshot_hash_for(self, run_id: str) -> str:
        return self._own(run_id).snapshot_hash

    def allowed_tools_for(self, run_id: str) -> frozenset[str]:
        return self._own(run_id).allowed_tools

    def paper_id_for(self, run_id: str) -> str:
        return self._own(run_id).paper_id

    def issued_question_ids_for(self, run_id: str) -> frozenset[str]:
        return self._own(run_id).issued_question_ids


class FamilyReads(Protocol):
    def snapshot_family(
        self, snapshot_hash: str, *, family_id: UUID
    ) -> QueryResult: ...


class StorageSnapshotMembership:
    """Whether a sealed snapshot pins a family, as storage answers it."""

    def __init__(self, storage: FamilyReads) -> None:
        self._storage = storage

    def holds_family(self, snapshot_hash: str, family_id: str) -> bool:
        """True when the snapshot pins exactly one version of *family_id*.

        Storage refuses a family it does not pin and one pinned under two
        versions with the same code. Only the first is an absent family; the
        second is a defect in the snapshot and raises rather than recording
        a request for a paper the snapshot holds.
        """

        try:
            self._storage.snapshot_family(snapshot_hash, family_id=UUID(family_id))
        except StorageClientError as error:
            if error.code == "unavailable_input" and "not pinned" in str(error):
                return False
            raise
        return True
