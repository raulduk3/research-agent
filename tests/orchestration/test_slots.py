from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.orchestration.slots import Slot, build_slot

BATCH_ID = "a" * 64
CONFIGURATION_ID = "123e4567-e89b-42d3-a456-426614174000"


def test_build_slot_returns_the_four_part_identity() -> None:
    slot = build_slot(BATCH_ID, "0000", CONFIGURATION_ID)
    assert slot == Slot(BATCH_ID, "0000", CONFIGURATION_ID, 0)
    assert slot.to_dict() == {
        "batch_id": BATCH_ID,
        "shard_id": "0000",
        "configuration_id": CONFIGURATION_ID,
        "attempt": 0,
    }


def test_build_slot_accepts_an_explicit_attempt() -> None:
    slot = build_slot(BATCH_ID, "0000", CONFIGURATION_ID, attempt=2)
    assert slot.attempt == 2


def test_build_slot_rejects_a_non_sha256_batch_id() -> None:
    with pytest.raises(ContractValidationError):
        build_slot("not-a-hash", "0000", CONFIGURATION_ID)


def test_build_slot_rejects_an_empty_shard_id() -> None:
    with pytest.raises(ContractValidationError):
        build_slot(BATCH_ID, "", CONFIGURATION_ID)


def test_build_slot_rejects_a_shard_id_with_a_nul_byte() -> None:
    with pytest.raises(ContractValidationError):
        build_slot(BATCH_ID, "bad\x00id", CONFIGURATION_ID)


def test_build_slot_rejects_a_non_uuid4_configuration_id() -> None:
    with pytest.raises(ContractValidationError):
        build_slot(BATCH_ID, "0000", "not-a-uuid")


def test_build_slot_rejects_a_negative_attempt() -> None:
    with pytest.raises(ContractValidationError):
        build_slot(BATCH_ID, "0000", CONFIGURATION_ID, attempt=-1)
