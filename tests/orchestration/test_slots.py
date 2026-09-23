from __future__ import annotations

import pytest

from research_agent.contracts import ProducerVersion
from research_agent.contracts.primitives import ContractValidationError
from research_agent.evaluation.registrations import (
    ComparisonEndpoint,
    ComparisonRegistration,
)
from research_agent.measurement import MeasurementError
from research_agent.orchestration.slots import (
    ConfigurationLaunch,
    PopulationSlot,
    Slot,
    build_slot,
    create_comparison_slots,
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


CREATED_AT = "2026-09-03T00:00:00.000000Z"


def _benefit_registration(**changes: object) -> ComparisonRegistration:
    values: dict[str, object] = {
        "schema_version": 1,
        "input_hashes": (),
        "producer_version": ProducerVersion("a" * 64, "b" * 40, 1),
        "config_hash": "c" * 64,
        "created_at": "2026-09-01T00:00:00.000000Z",
        "registration_id": "11111111-1111-4111-8111-111111111111",
        "hypothesis": "with-Jev forecasts improve citation-reach Brier",
        "population_hash": "d" * 64,
        "split_hash": "e" * 64,
        "subject_configuration_hash": "f" * 64,
        "endpoints": (
            ComparisonEndpoint("citation_reach_365d_brier", "primary", "lower"),
        ),
        "pass_threshold": -0.01,
        "kill_threshold": 0.0,
        "minimum_effect": 0.01,
        "exclusions": (),
        "sample_size": 2000,
        "failure_handling": "count_as_failure",
        "stop_rule_hash": "0" * 64,
        "provenance": "runtime",
        "registered_at": "2026-09-02T00:00:00.000000Z",
        "imported_at": None,
        "signature_evidence_hash": None,
        "exploratory_of": None,
    }
    values.update(changes)
    return ComparisonRegistration(**values)  # type: ignore[arg-type]


def test_comparison_slots_need_a_recorded_registration() -> None:
    with pytest.raises(ContractValidationError):
        create_comparison_slots(
            None, BATCH_ID, ["p1"], _configuration(), created_at=CREATED_AT
        )


def test_comparison_slots_wait_for_the_registration_to_be_available() -> None:
    with pytest.raises(ContractValidationError):
        create_comparison_slots(
            _benefit_registration(registered_at="2026-09-10T00:00:00.000000Z"),
            BATCH_ID,
            ["p1"],
            _configuration(),
            created_at=CREATED_AT,
        )


def test_comparison_slots_refuse_another_comparisons_registration() -> None:
    other = _benefit_registration(
        endpoints=(ComparisonEndpoint("skill_gain", "primary", "higher"),),
        pass_threshold=0.05,
    )
    with pytest.raises(MeasurementError):
        create_comparison_slots(
            other, BATCH_ID, ["p1"], _configuration(), created_at=CREATED_AT
        )


def test_each_paper_gets_two_arm_slots_that_differ_only_by_arm() -> None:
    slots = create_comparison_slots(
        _benefit_registration(),
        BATCH_ID,
        ["p2", "p1"],
        _configuration(),
        created_at=CREATED_AT,
    )
    assert [(s.slot.paper_id, s.arm) for s in slots] == [
        ("p1", "with_jev"),
        ("p1", "without_jev"),
        ("p2", "with_jev"),
        ("p2", "without_jev"),
    ]
    with_arm, without_arm = slots[0], slots[1]
    assert with_arm.slot.configuration_id != without_arm.slot.configuration_id
    for field in (
        "configuration_hash",
        "seed",
        "snapshot_hash",
        "model_deployment",
        "loop_image",
        "budgets",
        "tool_schema_manifest",
    ):
        assert getattr(with_arm, field) == getattr(without_arm, field)
    assert not any(slot.nominates for slot in slots)


def test_comparison_slots_never_collide_with_population_slots() -> None:
    configuration = _configuration()
    comparison = create_comparison_slots(
        _benefit_registration(),
        BATCH_ID,
        ["p1"],
        configuration,
        created_at=CREATED_AT,
    )
    population = create_slots(BATCH_ID, ["p1"], [configuration])
    assert {item.slot for item in population}.isdisjoint(
        {item.slot for item in comparison}
    )
    assert not any(isinstance(item, PopulationSlot) for item in comparison)


def test_comparison_slot_identity_is_stable_and_study_specific() -> None:
    def build(registration: ComparisonRegistration) -> set[Slot]:
        return {
            item.slot
            for item in create_comparison_slots(
                registration,
                BATCH_ID,
                ["p1"],
                _configuration(),
                created_at=CREATED_AT,
            )
        }

    first = build(_benefit_registration())
    assert first == build(_benefit_registration())
    other = _benefit_registration(
        registration_id="22222222-2222-4222-8222-222222222222"
    )
    assert first.isdisjoint(build(other))
