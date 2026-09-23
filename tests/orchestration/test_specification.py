from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.orchestration.slots import build_slot
from research_agent.orchestration.specifications import (
    build_run_specification,
    derive_specification_seed,
)

RUN_ID = "123e4567-e89b-42d3-a456-426614174000"
BATCH_ID = "a" * 64
CONFIGURATION_ID = "123e4567-e89b-42d3-a456-426614174001"
GENOME_HASH = "b" * 64
SNAPSHOT_HASH = "c" * 64
PROFILE_HASH = "d" * 64
MODEL_MANIFEST = "e" * 64
SERVICE_HASH = "f" * 64
DEADLINE = "2027-01-01T00:00:00.000000Z"

SLOT = build_slot(BATCH_ID, "paper-a", CONFIGURATION_ID)
BUDGETS = {"model_calls": 6, "tool_calls": 12}
SERVICE_MANIFESTS = {"reader": SERVICE_HASH}


def _build(**overrides: object) -> object:
    base: dict[str, object] = dict(
        run_id=RUN_ID,
        slot=SLOT,
        genome_hash=GENOME_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        budgets=BUDGETS,
        allowed_tools=["query_cards", "submit"],
        profile_hash=PROFILE_HASH,
        mode="study",
        model_manifest=MODEL_MANIFEST,
        service_manifests=SERVICE_MANIFESTS,
        question_seal_deadline=DEADLINE,
    )
    base.update(overrides)
    return build_run_specification(**base)  # type: ignore[arg-type]


def test_derive_specification_seed_is_deterministic_for_the_same_slot_and_profile() -> (
    None
):
    first = derive_specification_seed(SLOT, profile_hash=PROFILE_HASH)
    second = derive_specification_seed(SLOT, profile_hash=PROFILE_HASH)
    assert first == second
    assert 0 <= first < 2**64


def test_derive_specification_seed_changes_with_the_profile_hash() -> None:
    other = derive_specification_seed(SLOT, profile_hash="9" * 64)
    assert other != derive_specification_seed(SLOT, profile_hash=PROFILE_HASH)


def test_build_run_specification_returns_the_derived_seed_and_hash() -> None:
    spec = _build()
    assert spec.specification_seed == derive_specification_seed(
        SLOT, profile_hash=PROFILE_HASH
    )
    assert len(spec.specification_hash) == 64
    assert spec.arm == "population"


def test_build_run_specification_rejects_a_missing_profile_hash() -> None:
    with pytest.raises(ContractValidationError):
        _build(profile_hash=None)


def test_build_run_specification_rejects_a_malformed_profile_hash() -> None:
    with pytest.raises(ContractValidationError):
        _build(profile_hash="not-a-hash")


def test_build_run_specification_hash_changes_with_budgets() -> None:
    base = _build()
    modified = _build(budgets={"model_calls": 6, "tool_calls": 11})
    assert base.specification_hash != modified.specification_hash


def test_build_run_specification_hash_is_order_independent_for_budgets_and_tools() -> (
    None
):
    forward = _build(
        budgets={"model_calls": 6, "tool_calls": 12},
        allowed_tools=["query_cards", "submit"],
    )
    shuffled = _build(
        budgets={"tool_calls": 12, "model_calls": 6},
        allowed_tools=["submit", "query_cards"],
    )
    assert forward.specification_hash == shuffled.specification_hash


def test_build_run_specification_restart_reuses_the_same_persisted_specification() -> (
    None
):
    # A restarted scheduler rebuilding the identical specification from the
    # same durable inputs reproduces byte-identical output, so storage's
    # idempotent create sees no change to reject.
    first = _build()
    second = _build()
    assert first == second


def test_build_run_specification_rejects_an_empty_budgets_mapping() -> None:
    with pytest.raises(ContractValidationError):
        _build(budgets={})


def test_build_run_specification_rejects_duplicate_tools() -> None:
    with pytest.raises(ContractValidationError):
        _build(allowed_tools=["submit", "submit"])


def test_build_run_specification_rejects_an_unadmitted_arm() -> None:
    with pytest.raises(ContractValidationError):
        _build(arm="not-an-arm")
