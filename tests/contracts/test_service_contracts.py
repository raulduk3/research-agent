import pytest

from research_agent.contracts.http import (
    InterfaceRegistry,
    ServiceContract,
    ServiceRefusal,
    ServiceRequestEnvelope,
    refuse,
)
from research_agent.contracts.primitives import ContractValidationError

REQUEST_ID = "8b6a5f2e-5c1a-4b4b-9b3d-8e2f6a7c1d90"


def _registry() -> InterfaceRegistry:
    return InterfaceRegistry(
        interfaces=(
            ServiceContract(
                caller_role="ingest",
                callee_role="storage",
                method="POST",
                route="/v1/artifacts",
                schema_version=1,
                authorization_scope="artifacts:write",
            ),
        )
    )


def test_service_interface_rejects_a_route_outside_v1() -> None:
    with pytest.raises(ContractValidationError):
        ServiceContract(
            caller_role="ingest",
            callee_role="storage",
            method="POST",
            route="/artifacts",
            schema_version=1,
            authorization_scope="artifacts:write",
        )


def test_interface_registry_rejects_a_route_declared_twice() -> None:
    interface = ServiceContract(
        caller_role="ingest",
        callee_role="storage",
        method="POST",
        route="/v1/artifacts",
        schema_version=1,
        authorization_scope="artifacts:write",
    )
    with pytest.raises(ContractValidationError):
        InterfaceRegistry(interfaces=(interface, interface))


def test_authorize_returns_the_declared_interface_for_its_own_caller() -> None:
    registry = _registry()
    interface = registry.authorize(
        caller_role="ingest", method="POST", route="/v1/artifacts"
    )
    assert interface.callee_role == "storage"


def test_authorize_refuses_the_wrong_caller_role() -> None:
    registry = _registry()
    with pytest.raises(ServiceRefusal) as excinfo:
        registry.authorize(caller_role="reader", method="POST", route="/v1/artifacts")
    assert excinfo.value.error_code == "unauthorized_role"


def test_authorize_refuses_an_undeclared_route() -> None:
    registry = _registry()
    with pytest.raises(ServiceRefusal) as excinfo:
        registry.authorize(caller_role="ingest", method="GET", route="/v1/nonexistent")
    assert excinfo.value.error_code == "unknown_route"


def test_service_request_envelope_requires_a_uuid4_and_a_positive_schema_version() -> (
    None
):
    envelope = ServiceRequestEnvelope(request_id=REQUEST_ID, schema_version=1)
    assert envelope.schema_version == 1
    with pytest.raises(ContractValidationError):
        ServiceRequestEnvelope(request_id="not-a-uuid", schema_version=1)


def test_refuse_carries_only_the_error_code_and_request_id() -> None:
    body = refuse("unknown_route", REQUEST_ID)
    assert body == {"error_code": "unknown_route", "request_id": REQUEST_ID}


def test_refuse_rejects_an_undeclared_error_code() -> None:
    with pytest.raises(ContractValidationError):
        refuse("internal_error", REQUEST_ID)
