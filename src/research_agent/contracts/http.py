"""Versioned authenticated service contracts (SDD-PL-02).

`InterfaceRegistry` is the declared side of PL-02: a component reaches
another only through an interface named here, by its caller role, method and
route, and any other attempted route is refused before it reaches a handler.
`authorize` is the exact check a real service's request middleware would
apply; the container-level half, that a denied caller cannot instead open
another component's files or database port, is a disposable-host acceptance
test outside this module's reach.

`refuse` builds the stable, credential-free error body PL-02 requires: an
error code from a closed set and the caller's own request id, never a stack
trace, a file path or a secret value.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_positive_int,
    validate_uuid4,
)

HTTP_METHODS: frozenset[str] = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

ERROR_CODES: frozenset[str] = frozenset(
    {
        "unauthorized_role",
        "unknown_route",
        "invalid_schema_version",
        "validation_failed",
    }
)


class ServiceRefusal(Exception):
    """Raised by `InterfaceRegistry.authorize` with a stable, closed error code."""

    def __init__(self, error_code: str) -> None:
        if error_code not in ERROR_CODES:
            raise ContractValidationError("error_code must be one of ERROR_CODES")
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class ServiceContract:
    """One declared interface: who may call it, and how."""

    caller_role: str
    callee_role: str
    method: str
    route: str
    schema_version: int
    authorization_scope: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.caller_role)
        validate_non_empty_string(self.callee_role)
        if self.method not in HTTP_METHODS:
            raise ContractValidationError("method must be a declared HTTP/JSON verb")
        if not self.route.startswith("/v1/"):
            raise ContractValidationError("route must be a versioned /v1 path")
        validate_positive_int(self.schema_version)
        validate_non_empty_string(self.authorization_scope)


@dataclass(frozen=True, slots=True)
class InterfaceRegistry:
    """The closed list of interfaces components may call; nothing else is reachable."""

    interfaces: tuple[ServiceContract, ...]

    def __post_init__(self) -> None:
        routes = [(interface.method, interface.route) for interface in self.interfaces]
        if len(set(routes)) != len(routes):
            raise ContractValidationError("each method and route must be declared once")

    def resolve(self, method: str, route: str) -> ServiceContract | None:
        for interface in self.interfaces:
            if interface.method == method and interface.route == route:
                return interface
        return None

    def authorize(
        self, *, caller_role: str, method: str, route: str
    ) -> ServiceContract:
        """Return the matching interface, or raise the exact refusal a caller gets."""

        interface = self.resolve(method, route)
        if interface is None:
            raise ServiceRefusal("unknown_route")
        if interface.caller_role != caller_role:
            raise ServiceRefusal("unauthorized_role")
        return interface


@dataclass(frozen=True, slots=True)
class ServiceRequestEnvelope:
    """The two fields every request must carry: its schema version and its id."""

    request_id: str
    schema_version: int

    def __post_init__(self) -> None:
        validate_uuid4(self.request_id)
        validate_positive_int(self.schema_version)


def refuse(error_code: str, request_id: str) -> dict[str, str]:
    """Build the stable, credential-free error body a refused request receives."""

    if error_code not in ERROR_CODES:
        raise ContractValidationError("error_code must be one of ERROR_CODES")
    validate_uuid4(request_id)
    return {"error_code": error_code, "request_id": request_id}
