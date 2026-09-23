import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.inventory import (
    BatchRecord,
    ComponentInventory,
    ComponentRecord,
    ObservedComponent,
)

DIGEST = "a" * 64
PROJECT = "research-agent"


def _component(**overrides: object) -> ComponentRecord:
    values: dict[str, object] = {
        "component_id": "storage",
        "role": "storage",
        "layers": frozenset({"infrastructure"}),
        "image_digest": DIGEST,
        "interface_ids": ("storage-v1",),
        "mode_membership": frozenset({"collection", "engineering", "study"}),
    }
    values.update(overrides)
    return ComponentRecord(**values)  # type: ignore[arg-type]


def _inventory() -> ComponentInventory:
    return ComponentInventory(
        components=(
            _component(),
            _component(
                component_id="ingest",
                role="ingest",
                layers=frozenset({"environment"}),
                interface_ids=("ingest-v1",),
            ),
        )
    )


def test_component_record_rejects_zero_layers() -> None:
    with pytest.raises(ContractValidationError):
        _component(layers=frozenset())


def test_component_record_rejects_two_layers() -> None:
    with pytest.raises(ContractValidationError):
        _component(layers=frozenset({"infrastructure", "environment"}))


def test_component_record_rejects_a_layer_that_does_not_match_its_role() -> None:
    with pytest.raises(ContractValidationError):
        _component(layers=frozenset({"models"}))


def test_batch_record_carries_input_and_output_layers_instead_of_one() -> None:
    batch = BatchRecord(
        component_id="fit_prediction_heads",
        input_layer="reader",
        output_layer="models",
        image_digest=DIGEST,
        interface_ids=(),
        mode_membership=frozenset({"engineering", "study"}),
    )
    assert batch.role == "batch"


def test_batch_record_rejects_identical_input_and_output_layers() -> None:
    with pytest.raises(ContractValidationError):
        BatchRecord(
            component_id="fit_prediction_heads",
            input_layer="reader",
            output_layer="reader",
            image_digest=DIGEST,
            interface_ids=(),
            mode_membership=frozenset({"study"}),
        )


def test_component_inventory_rejects_duplicate_component_ids() -> None:
    with pytest.raises(ContractValidationError):
        ComponentInventory(components=(_component(), _component()))


def test_component_inventory_hash_is_stable_for_identical_inventories() -> None:
    assert _inventory().compute_hash() == _inventory().compute_hash()


def test_reconcile_passes_when_every_mode_eligible_component_is_observed_once() -> None:
    inventory = _inventory()
    observed = (
        ObservedComponent("storage", PROJECT),
        ObservedComponent("ingest", PROJECT),
    )
    result = inventory.reconcile(observed, project=PROJECT, mode="collection")
    assert result.ok


def test_reconcile_reports_a_missing_component() -> None:
    inventory = _inventory()
    observed = (ObservedComponent("storage", PROJECT),)
    result = inventory.reconcile(observed, project=PROJECT, mode="collection")
    assert result.missing == ("ingest",)
    assert not result.ok


def test_reconcile_reports_a_duplicate_component() -> None:
    inventory = _inventory()
    observed = (
        ObservedComponent("storage", PROJECT),
        ObservedComponent("storage", PROJECT),
        ObservedComponent("ingest", PROJECT),
    )
    result = inventory.reconcile(observed, project=PROJECT, mode="collection")
    assert result.duplicate == ("storage",)


def test_reconcile_reports_an_undeclared_extra_component() -> None:
    inventory = _inventory()
    observed = (
        ObservedComponent("storage", PROJECT),
        ObservedComponent("ingest", PROJECT),
        ObservedComponent("intruder", PROJECT),
    )
    result = inventory.reconcile(observed, project=PROJECT, mode="collection")
    assert result.extra == ("intruder",)


def test_reconcile_ignores_an_unrelated_host_project() -> None:
    inventory = _inventory()
    observed = (
        ObservedComponent("storage", PROJECT),
        ObservedComponent("ingest", PROJECT),
        ObservedComponent("some-other-app", "unrelated-project"),
    )
    result = inventory.reconcile(observed, project=PROJECT, mode="collection")
    assert result.ok
