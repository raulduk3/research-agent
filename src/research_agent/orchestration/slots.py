"""Immutable run-slot identity: daily batch, shard, configuration and attempt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_sha256,
    validate_uuid4,
)


def _shard_id(value: str) -> str:
    if not 1 <= len(value) <= 128 or "\x00" in value:
        raise ContractValidationError(
            "shard_id must be 1 to 128 characters without NUL"
        )
    return value


@dataclass(frozen=True, slots=True)
class Slot:
    """The unique identity of one run attempt.

    Fields match ``contracts.runs``' ``RunSlot`` exactly, so a built slot is
    always acceptable to the run-record ``create`` command: ``batch_id`` is
    the sealed daily sheet's content hash (EN-10), ``shard_id`` names one
    disjoint partition of that sheet's papers, and one ``configuration_id``
    runs it at a given ``attempt`` (AG-17).
    """

    batch_id: str
    shard_id: str
    configuration_id: str
    attempt: int = 0

    def __post_init__(self) -> None:
        validate_sha256(self.batch_id)
        _shard_id(self.shard_id)
        validate_uuid4(self.configuration_id)
        validate_non_negative_int(self.attempt)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "shard_id": self.shard_id,
            "configuration_id": self.configuration_id,
            "attempt": self.attempt,
        }


def build_slot(
    batch_id: str, shard_id: str, configuration_id: str, *, attempt: int = 0
) -> Slot:
    """Construct one run attempt's immutable slot tuple (AG-17).

    Raises ``ContractValidationError`` for any part that the run-record
    contract storing it would also refuse, so a rejected slot never reaches
    a run specification.
    """

    return Slot(batch_id, shard_id, configuration_id, attempt)
