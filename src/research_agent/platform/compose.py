"""One role per container (SDD-PL-01).

`ComposeInventory` is the declared side of PL-01: exactly one role and one
entrypoint per container, a private writable temporary filesystem instead of
a shared writable environment, and peer-starting authority reserved to the
orchestrator role alone. It shares `platform.inventory.ROLE_IDS`, the same
closed role vocabulary the component inventory uses, so a test can compare
the two role sets directly instead of trusting that two independently
maintained lists happen to agree.

The rendered Compose file this module's data corresponds to lives under
`deploy/`; this module is what a test evaluates, not a YAML parser, matching
how `platform.isolation` and `platform.network` represent their own policies
as plain dataclasses rather than reading Docker state directly.
"""

from __future__ import annotations

from collections.abc import Mapping

from dataclasses import dataclass

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
)
from research_agent.platform.inventory import DYNAMIC_ROLE_IDS, ROLE_IDS

# The roles a static Compose definition must declare. "worker" and "batch"
# are predeclared immutable specifications the operator-owned host launcher
# starts dynamically (PL-03); they are never static Compose services.
STATIC_ROLE_IDS: frozenset[str] = frozenset(ROLE_IDS) - DYNAMIC_ROLE_IDS


@dataclass(frozen=True, slots=True)
class ComposeService:
    """One container's declared role, image and isolation posture."""

    service_name: str
    role: str
    image_digest: str
    entrypoint: tuple[str, ...]
    writable_tmpfs: bool
    can_start_peers: bool = False

    def __post_init__(self) -> None:
        validate_non_empty_string(self.service_name)
        if self.role not in ROLE_IDS:
            raise ContractValidationError("role must be a declared platform role")
        validate_sha256(self.image_digest)
        if not self.entrypoint:
            raise ContractValidationError(
                "entrypoint must name at least one command part"
            )
        for part in self.entrypoint:
            validate_non_empty_string(part)
        if not self.writable_tmpfs:
            raise ContractValidationError(
                "a container must have its own private writable temporary filesystem, "
                "never a shared writable environment"
            )
        if self.can_start_peers and self.role != "orchestrator":
            raise ContractValidationError(
                "only the orchestrator role may start peer containers"
            )


@dataclass(frozen=True, slots=True)
class ComposeInventory:
    """The complete set of containers one Compose project declares."""

    services: Mapping[str, ComposeService]

    def __post_init__(self) -> None:
        roles_seen: dict[str, str] = {}
        for name, service in self.services.items():
            if name != service.service_name:
                raise ContractValidationError(
                    "service map key must equal its service_name"
                )
            if service.role in roles_seen:
                raise ContractValidationError(
                    f"role '{service.role}' is assigned to more than one container: "
                    f"{roles_seen[service.role]!r} and {name!r}"
                )
            roles_seen[service.role] = name
        missing = STATIC_ROLE_IDS - roles_seen.keys()
        if missing:
            raise ContractValidationError(
                f"compose definition is missing required roles: {sorted(missing)}"
            )
        extra = roles_seen.keys() - STATIC_ROLE_IDS
        if extra:
            raise ContractValidationError(
                f"compose definition declares roles outside the static set: {sorted(extra)}"
            )

    @property
    def role_ids(self) -> frozenset[str]:
        return frozenset(service.role for service in self.services.values())

    def for_role(self, role: str) -> ComposeService | None:
        for service in self.services.values():
            if service.role == role:
                return service
        return None
