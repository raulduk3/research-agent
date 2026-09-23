"""Applied cgroup resource ceilings (SDD-PL-04).

`ROLE_LIMITS` is Appendix A's per-role vCPU/GiB-RAM/accelerator table,
embedded as a fixed constant the way `evaluation.accuracy.CADENCE_BY_COMPONENT`
embeds its own Appendix A table, rather than threaded through a generic
profile value: PL-04's Limits bullet fixes these numbers directly. `models`
is the one role that declares the host's graphics device; `ResourcePolicy`
refuses to derive a nonzero accelerator count for any other role.
`ResourcePolicy.verify_applied` is the readiness-time comparison against
what a real container's cgroup actually reports, mirroring
`platform.preflight.evaluate_floor`'s measured-versus-declared shape.

`ResourcePolicy.can_lease` and the batch pause/resume thresholds carry
PL-04's "two workers and one heavy batch" concurrency ceiling and the 48/40
GiB foreground-memory checkpoint rule; both act on caller-supplied state,
since the transactional storage lease itself is a separate, not-yet-built
owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from research_agent.contracts.primitives import ContractValidationError

_BYTES_PER_GIB = 1024**3
_CPU_PERIOD_US = 100_000

MAX_CONCURRENT_WORKERS: int = 2
MAX_CONCURRENT_BATCH_JOBS: int = 1
BATCH_PAUSE_THRESHOLD_GIB: float = 48.0
BATCH_RESUME_THRESHOLD_GIB: float = 40.0

_ACCELERATED_ROLE: str = "models"


@dataclass(frozen=True, slots=True)
class ResourceLimit:
    """One role's declared ceiling: vCPU, memory in GiB and accelerator count."""

    vcpu: float
    memory_gib: float
    accelerator_count: int

    def __post_init__(self) -> None:
        if self.vcpu <= 0:
            raise ContractValidationError("vcpu must be positive")
        if self.memory_gib <= 0:
            raise ContractValidationError("memory_gib must be positive")
        if self.accelerator_count < 0:
            raise ContractValidationError("accelerator_count must not be negative")


# Appendix A: Launch profile, container hard limits (vCPU / GiB RAM / host
# graphics devices).
ROLE_LIMITS: dict[str, ResourceLimit] = {
    "postgres": ResourceLimit(2, 8, 0),
    "storage": ResourceLimit(1, 2, 0),
    "ingest": ResourceLimit(2, 4, 0),
    "reader": ResourceLimit(2, 4, 0),
    "models": ResourceLimit(4, 12, 1),
    "tools": ResourceLimit(1, 2, 0),
    "scorer": ResourceLimit(1, 2, 0),
    "orchestrator": ResourceLimit(0.5, 1, 0),
    "app": ResourceLimit(0.5, 1, 0),
    "worker": ResourceLimit(1, 1, 0),
    "batch": ResourceLimit(4, 16, 0),
}


@dataclass(frozen=True, slots=True)
class CgroupSettings:
    """The cgroup values PL-04 requires the platform to apply for one role."""

    cpu_quota_us: int
    period_us: int
    memory_max_bytes: int
    accelerator_device_mounted: bool


@dataclass(frozen=True, slots=True)
class AppliedCgroup:
    """What a real container's cgroup and device mounts actually report."""

    cpu_quota_us: int | None
    period_us: int | None
    memory_max_bytes: int | None
    accelerator_device_mounted: bool


@dataclass(frozen=True, slots=True)
class LeaseState:
    """The currently active worker and batch leases a scheduler holds."""

    active_worker_ids: frozenset[str] = frozenset()
    active_batch_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    """PL-04's per-role ceiling table, plus the checks and gates derived from it."""

    role_limits: Mapping[str, ResourceLimit] = field(
        default_factory=lambda: dict(ROLE_LIMITS)
    )
    max_concurrent_workers: int = MAX_CONCURRENT_WORKERS
    max_concurrent_batch_jobs: int = MAX_CONCURRENT_BATCH_JOBS
    batch_pause_threshold_gib: float = BATCH_PAUSE_THRESHOLD_GIB
    batch_resume_threshold_gib: float = BATCH_RESUME_THRESHOLD_GIB

    def cgroup_settings(self, role: str) -> CgroupSettings:
        """Derive the declared cgroup settings for *role* from `role_limits`."""

        if role not in self.role_limits:
            raise ContractValidationError("role has no declared resource limit")
        limit = self.role_limits[role]
        if role != _ACCELERATED_ROLE and limit.accelerator_count != 0:
            raise ContractValidationError(
                f"role '{role}' must declare zero accelerator devices"
            )
        return CgroupSettings(
            cpu_quota_us=round(limit.vcpu * _CPU_PERIOD_US),
            period_us=_CPU_PERIOD_US,
            memory_max_bytes=round(limit.memory_gib * _BYTES_PER_GIB),
            accelerator_device_mounted=limit.accelerator_count > 0,
        )

    def verify_applied(self, role: str, applied: AppliedCgroup) -> tuple[str, ...]:
        """Return every dimension where *applied* diverges from the declared ceiling."""

        declared = self.cgroup_settings(role)
        mismatches: list[str] = []
        if applied.cpu_quota_us != declared.cpu_quota_us:
            mismatches.append("cpu_quota")
        if applied.period_us != declared.period_us:
            mismatches.append("cpu_period")
        if applied.memory_max_bytes != declared.memory_max_bytes:
            mismatches.append("memory_max")
        if applied.accelerator_device_mounted != declared.accelerator_device_mounted:
            mismatches.append("accelerator_mount")
        return tuple(mismatches)

    def can_lease(self, state: LeaseState, role: str) -> bool:
        """Whether one more lease of *role* fits under the concurrency ceiling."""

        if role == "worker":
            return len(state.active_worker_ids) < self.max_concurrent_workers
        if role == "batch":
            return len(state.active_batch_ids) < self.max_concurrent_batch_jobs
        raise ContractValidationError("only the worker and batch roles are leased")

    def batch_should_pause(self, foreground_resident_gib: float) -> bool:
        """Whether measured foreground memory demands a batch checkpoint-and-pause."""

        return foreground_resident_gib > self.batch_pause_threshold_gib

    def batch_should_resume(self, foreground_resident_gib: float) -> bool:
        """Whether measured foreground memory has fallen enough to resume a batch."""

        return foreground_resident_gib < self.batch_resume_threshold_gib
