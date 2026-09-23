from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.orchestration.slots import (
    ConfigurationLaunch,
    Slot,
    build_slot,
    create_slots,
)

BATCH_ID = "a" * 64
CONFIGURATION_ID = "123e4567-e89b-42d3-a456-426614174000"
OTHER_CONFIGURATION_ID = "123e4567-e89b-42d3-a456-426614174001"
SNAPSHOT_HASH = "b" * 64
OTHER_SNAPSHOT_HASH = "c" * 64
MODEL_DEPLOYMENT = "d" * 64
LOOP_IMAGE = "e" * 64
TOOL_SCHEMA_MANIFEST = "f" * 64
BUDGETS = {"model_calls": 6, "tool_calls": 12}


def _configuration(
    configuration_id: str = CONFIGURATION_ID,
    *,
    configuration_hash: str = "1" * 64,
    seed: int = 1,
    snapshot_hash: str = SNAPSHOT_HASH,
) -> ConfigurationLaunch:
    return ConfigurationLaunch(
        configuration_id=configuration_id,
        configuration_hash=configuration_hash,
        seed=seed,
        snapshot_hash=snapshot_hash,
        model_deployment=MODEL_DEPLOYMENT,
        loop_image=LOOP_IMAGE,
        budgets=BUDGETS,
        tool_schema_manifest=TOOL_SCHEMA_MANIFEST,
    )


def test_build_slot_returns_the_four_part_identity() -> None:
    slot = build_slot(BATCH_ID, "paper-0", CONFIGURATION_ID)
    assert slot == Slot(BATCH_ID, "paper-0", CONFIGURATION_ID, 0)
    assert slot.to_dict() == {
        "batch_id": BATCH_ID,
        "paper_id": "paper-0",
        "configuration_id": CONFIGURATION_ID,
        "attempt": 0,
    }


def test_build_slot_accepts_an_explicit_attempt() -> None:
    slot = build_slot(BATCH_ID, "paper-0", CONFIGURATION_ID, attempt=2)
    assert slot.attempt == 2


def test_build_slot_rejects_a_non_sha256_batch_id() -> None:
    with pytest.raises(ContractValidationError):
        build_slot("not-a-hash", "paper-0", CONFIGURATION_ID)


def test_build_slot_rejects_an_empty_paper_id() -> None:
    with pytest.raises(ContractValidationError):
        build_slot(BATCH_ID, "", CONFIGURATION_ID)


def test_build_slot_rejects_a_paper_id_with_a_nul_byte() -> None:
    with pytest.raises(ContractValidationError):
        build_slot(BATCH_ID, "bad\x00id", CONFIGURATION_ID)


def test_build_slot_rejects_a_non_uuid4_configuration_id() -> None:
    with pytest.raises(ContractValidationError):
        build_slot(BATCH_ID, "paper-0", "not-a-uuid")


def test_build_slot_rejects_a_negative_attempt() -> None:
    with pytest.raises(ContractValidationError):
        build_slot(BATCH_ID, "paper-0", CONFIGURATION_ID, attempt=-1)


def test_create_slots_builds_one_slot_per_paper_per_configuration() -> None:
    slots = create_slots(
        BATCH_ID,
        ["paper-a", "paper-b"],
        [_configuration(CONFIGURATION_ID), _configuration(OTHER_CONFIGURATION_ID)],
    )
    assert {(item.slot.paper_id, item.slot.configuration_id) for item in slots} == {
        ("paper-a", CONFIGURATION_ID),
        ("paper-a", OTHER_CONFIGURATION_ID),
        ("paper-b", CONFIGURATION_ID),
        ("paper-b", OTHER_CONFIGURATION_ID),
    }
    assert all(item.slot.batch_id == BATCH_ID for item in slots)
    assert all(item.slot.attempt == 0 for item in slots)


def test_create_slots_shuffled_configuration_input_yields_canonical_identities() -> (
    None
):
    configurations = [
        _configuration(CONFIGURATION_ID),
        _configuration(OTHER_CONFIGURATION_ID),
    ]
    forward = create_slots(BATCH_ID, ["paper-a"], configurations)
    reversed_input = create_slots(BATCH_ID, ["paper-a"], list(reversed(configurations)))
    assert forward == reversed_input


def test_create_slots_pairwise_shared_fields_remain_equal() -> None:
    slots = create_slots(
        BATCH_ID,
        ["paper-a"],
        [_configuration(CONFIGURATION_ID), _configuration(OTHER_CONFIGURATION_ID)],
    )
    shared = {
        (
            item.snapshot_hash,
            item.model_deployment,
            item.loop_image,
            item.tool_schema_manifest,
        )
        for item in slots
    }
    assert len(shared) == 1


def test_create_slots_rejects_a_configuration_on_a_newer_snapshot() -> None:
    with pytest.raises(ContractValidationError):
        create_slots(
            BATCH_ID,
            ["paper-a"],
            [
                _configuration(CONFIGURATION_ID, snapshot_hash=SNAPSHOT_HASH),
                _configuration(
                    OTHER_CONFIGURATION_ID, snapshot_hash=OTHER_SNAPSHOT_HASH
                ),
            ],
        )


def test_create_slots_rejects_no_papers() -> None:
    with pytest.raises(ContractValidationError):
        create_slots(BATCH_ID, [], [_configuration()])


def test_create_slots_rejects_duplicate_paper_ids() -> None:
    with pytest.raises(ContractValidationError):
        create_slots(BATCH_ID, ["paper-a", "paper-a"], [_configuration()])


def test_create_slots_rejects_no_configurations() -> None:
    with pytest.raises(ContractValidationError):
        create_slots(BATCH_ID, ["paper-a"], [])


def test_create_slots_rejects_duplicate_configuration_ids() -> None:
    with pytest.raises(ContractValidationError):
        create_slots(
            BATCH_ID,
            ["paper-a"],
            [_configuration(CONFIGURATION_ID), _configuration(CONFIGURATION_ID)],
        )
