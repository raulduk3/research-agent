import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.compose import (
    STATIC_ROLE_IDS,
    ComposeInventory,
    ComposeService,
)
from research_agent.platform.inventory import (
    DYNAMIC_ROLE_IDS,
    ROLE_IDS,
    ROLE_LAYER,
    ComponentInventory,
    ComponentRecord,
)

DIGEST = "a" * 64


def _service(role: str, **overrides: object) -> ComposeService:
    values: dict[str, object] = {
        "service_name": role,
        "role": role,
        "image_digest": DIGEST,
        "entrypoint": (f"/usr/bin/{role}",),
        "writable_tmpfs": True,
    }
    values.update(overrides)
    return ComposeService(**values)  # type: ignore[arg-type]


def _complete_services() -> dict[str, ComposeService]:
    return {role: _service(role) for role in STATIC_ROLE_IDS}


def test_compose_inventory_accepts_one_service_per_static_role() -> None:
    inventory = ComposeInventory(services=_complete_services())
    assert inventory.role_ids == STATIC_ROLE_IDS


def test_compose_inventory_rejects_a_missing_role() -> None:
    services = _complete_services()
    del services["storage"]
    with pytest.raises(ContractValidationError):
        ComposeInventory(services=services)


def test_compose_inventory_rejects_two_containers_claiming_one_role() -> None:
    services = _complete_services()
    services["storage-2"] = _service("storage", service_name="storage-2")
    with pytest.raises(ContractValidationError):
        ComposeInventory(services=services)


def test_compose_service_rejects_a_shared_writable_environment() -> None:
    with pytest.raises(ContractValidationError):
        _service("storage", writable_tmpfs=False)


def test_compose_service_rejects_a_non_orchestrator_starting_peers() -> None:
    with pytest.raises(ContractValidationError):
        _service("app", can_start_peers=True)


def test_compose_service_permits_the_orchestrator_starting_peers() -> None:
    service = _service("orchestrator", can_start_peers=True)
    assert service.can_start_peers


def test_static_role_ids_excludes_the_dynamic_worker_and_batch_roles() -> None:
    assert STATIC_ROLE_IDS == frozenset(ROLE_IDS) - DYNAMIC_ROLE_IDS


def test_component_inventory_and_compose_file_declare_the_same_static_roles() -> None:
    inventory = ComponentInventory(
        components=tuple(
            ComponentRecord(
                component_id=role,
                role=role,
                layers=frozenset({ROLE_LAYER[role]}),
                image_digest=DIGEST,
                interface_ids=(),
                mode_membership=frozenset({"study"}),
            )
            for role in STATIC_ROLE_IDS
        )
    )
    compose = ComposeInventory(services=_complete_services())
    assert inventory.role_ids == compose.role_ids
