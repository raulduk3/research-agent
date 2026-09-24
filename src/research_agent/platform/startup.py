"""Declarative mode startup (SDD-PL-03).

`start_mode` is the operator entrypoint's decision function: it validates
the selected profile's readiness (`platform.profile.LaunchProfile.readiness`),
the host floor (`platform.preflight.HostFloorReport`) and the Compose
project's actual component inventory (`platform.inventory.ComponentInventory.reconcile`)
before ever claiming a mode started. A readiness failure leaves cycle
scheduling disabled and reports every failed gate; because each mode
re-evaluates its own gates from the same profile and the same reconciliation
scope, a successful `collection` outcome never implies `study` is ready.

`WorkerSpec` and `launch_worker` are the operator-owned host launcher's own
narrow rule: it starts only a predeclared immutable specification from
authenticated orchestration, and a worker never carries the Docker socket,
which `platform.workers.WorkerImagePolicy` separately verifies against a
real container's actual mounts.

`launch_role` is the operator entry point's start command for every role
beyond storage (#315): each reads one configuration through
`platform.services.config.load_launch_config`, which refuses a mismatched
profile or a missing secret before the role opens anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_uuid4,
)
from research_agent.platform.inventory import (
    ComponentInventory,
    MODES,
    ObservedComponent,
)
from research_agent.platform.preflight import HostFloorReport
from research_agent.platform.profile import LaunchProfile


@dataclass(frozen=True, slots=True)
class StartupOutcome:
    """Whether one requested mode actually started, and every gate that blocked it."""

    mode: str
    profile_hash: str
    failed_gates: tuple[str, ...]

    @property
    def started(self) -> bool:
        return not self.failed_gates

    @property
    def cycle_scheduling_enabled(self) -> bool:
        return self.started


def start_mode(
    *,
    mode: str,
    profile: LaunchProfile,
    floor_report: HostFloorReport,
    inventory: ComponentInventory,
    observed: tuple[ObservedComponent, ...],
    compose_project: str,
) -> StartupOutcome:
    """Validate profile readiness, the host floor and the component inventory for *mode*."""

    if mode not in MODES:
        raise ContractValidationError("mode must be one of MODES")

    failed_gates: list[str] = [f"profile:{gate}" for gate in profile.readiness(mode)]
    failed_gates.extend(f"host_floor:{gate}" for gate in floor_report.shortfalls)

    reconciliation = inventory.reconcile(observed, project=compose_project, mode=mode)
    if reconciliation.missing:
        failed_gates.append("inventory_missing:" + ",".join(reconciliation.missing))
    if reconciliation.duplicate:
        failed_gates.append("inventory_duplicate:" + ",".join(reconciliation.duplicate))
    if reconciliation.extra:
        failed_gates.append("inventory_extra:" + ",".join(reconciliation.extra))

    return StartupOutcome(
        mode=mode, profile_hash=profile.compute_hash(), failed_gates=tuple(failed_gates)
    )


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    """One predeclared, immutable worker specification the host launcher may start."""

    run_id: str
    image_digest: str
    orchestration_token: str
    docker_socket_mounted: bool = False

    def __post_init__(self) -> None:
        validate_uuid4(self.run_id)
        validate_sha256(self.image_digest)
        validate_non_empty_string(self.orchestration_token)
        if self.docker_socket_mounted:
            raise ContractValidationError(
                "a worker specification must never mount the Docker socket"
            )


def launch_worker(spec: WorkerSpec, *, authenticated: bool) -> WorkerSpec:
    """Admit *spec* only from authenticated orchestration; the specification is unchanged."""

    if not authenticated:
        raise ContractValidationError(
            "the host launcher accepts a worker specification only from authenticated "
            "orchestration"
        )
    return spec


#: The role commands `launch_role` starts, in the operator entry point's order.
ROLE_COMMANDS = (
    "serve-models",
    "serve-owner",
    "serve-rating",
    "serve-ingest",
    "provision-launch-roles",
)


def launch_role(command: str, config_path: Path, *, once: bool = False) -> None:
    """Start the role *command* names from the configuration at *config_path*.

    ``once`` runs a single day pass for ``serve-ingest``; the other roles
    serve until stopped. Imports are deferred so a command loads only its
    own role's dependencies.
    """

    if command == "serve-models":
        from research_agent.platform.services.models import serve_models

        serve_models(config_path)
    elif command == "serve-owner":
        from research_agent.platform.services.web import serve_owner

        serve_owner(config_path)
    elif command == "serve-rating":
        from research_agent.platform.services.web import serve_rating

        serve_rating(config_path)
    elif command == "serve-ingest":
        from research_agent.platform.services.ingest import serve_ingest

        serve_ingest(config_path, once=once)
    elif command == "provision-launch-roles":
        from research_agent.platform.services.roles import provision_launch_roles

        roles = provision_launch_roles(config_path)
        print(
            f"Provisioned runtime role {roles.application} "
            f"and migrator role {roles.migrator}."
        )
    else:
        raise ContractValidationError(f"unknown role command {command!r}")
