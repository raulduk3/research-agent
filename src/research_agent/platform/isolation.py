"""Worker capabilities and two-destination isolation (SDD-SR-12).

An agent run reaches only the shared tool service and the agent-model proxy
it was provisioned with; the platform closes every other destination,
including the shared model service and stored data outside the run's
snapshot. `WorkerIsolation` is the positive list of the two destinations one
run may reach; `is_permitted` is the check the host firewall rules mirror,
and the host-acceptance probe proves the mirrored rules actually hold from
inside a running container.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_positive_int,
    validate_sha256,
    validate_uuid4,
)

# Link-local and cloud-metadata addresses a run must never reach, even through
# an endpoint that resolves there unexpectedly.
DENIED_METADATA_ADDRESSES: frozenset[str] = frozenset(
    {"169.254.169.254", "fd00:ec2::254", "169.254.170.2"}
)


@dataclass(frozen=True, slots=True)
class NetworkDestination:
    """One address:port a container may be permitted to reach."""

    host: str
    port: int

    def __post_init__(self) -> None:
        validate_non_empty_string(self.host)
        validate_positive_int(self.port)
        if self.port > 65535:
            raise ContractValidationError("port must be at most 65535")
        if self.host in DENIED_METADATA_ADDRESSES:
            raise ContractValidationError(
                "destination must not be a link-local metadata address"
            )

    def as_tuple(self) -> tuple[str, int]:
        return (self.host, self.port)


@dataclass(frozen=True, slots=True)
class WorkerIsolation:
    """The exact, closed reach of one run: its tool service and model proxy."""

    run_id: str
    snapshot_hash: str
    tool_service: NetworkDestination
    model_proxy: NetworkDestination

    def __post_init__(self) -> None:
        validate_uuid4(self.run_id)
        validate_sha256(self.snapshot_hash)
        if self.tool_service.as_tuple() == self.model_proxy.as_tuple():
            raise ContractValidationError(
                "tool service and model proxy must be distinct destinations"
            )

    def allowed_destinations(self) -> frozenset[tuple[str, int]]:
        return frozenset({self.tool_service.as_tuple(), self.model_proxy.as_tuple()})

    def is_permitted(self, destination: NetworkDestination) -> bool:
        return destination.as_tuple() in self.allowed_destinations()
