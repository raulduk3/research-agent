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
"""

from __future__ import annotations

from dataclasses import dataclass

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
