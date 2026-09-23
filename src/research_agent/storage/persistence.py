"""Storage-owned persistence and verified restore (SDD-PL-18).

Data that must outlive a container -- the ledger, the corpus, raw responses,
checkpoints, prediction heads, snapshots and batch-job records -- lives on
volumes the deployment names, never inside a container's own file system.
`PersistentStores` names those volumes and their one owning role;
`verify_volume_readiness` is the check storage runs before declaring itself
ready. The host-acceptance probe recreates every application container
against the preserved volumes and calls `compare_snapshots` to prove the
data survived byte-for-byte; that probe is Docker-dependent and lives in
`bin/check-collection-linux`, not here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
)


@dataclass(frozen=True, slots=True)
class VolumeBinding:
    """One named volume, its mount point and the single role that owns it."""

    name: str
    mount_path: str
    owner_role: str
    read_only: bool

    def __post_init__(self) -> None:
        validate_non_empty_string(self.name)
        validate_non_empty_string(self.mount_path)
        validate_non_empty_string(self.owner_role)


@dataclass(frozen=True, slots=True)
class PersistentStores:
    """The volumes a deployment declares; only their owner role may write them."""

    bindings: tuple[VolumeBinding, ...]

    def __post_init__(self) -> None:
        seen_names: set[str] = set()
        seen_paths: dict[tuple[str, str], str] = {}
        for binding in self.bindings:
            if binding.name in seen_names:
                raise ContractValidationError(f"volume '{binding.name}' is duplicated")
            seen_names.add(binding.name)
            key = (binding.owner_role, binding.mount_path)
            if key in seen_paths:
                raise ContractValidationError(
                    f"mount path '{binding.mount_path}' is reused by role "
                    f"'{binding.owner_role}'"
                )
            seen_paths[key] = binding.name

    def owned_by(self, role: str) -> tuple[VolumeBinding, ...]:
        return tuple(binding for binding in self.bindings if binding.owner_role == role)


def verify_readonly_roots(
    *, roles: Mapping[str, bool], owning_roles: frozenset[str]
) -> tuple[str, ...]:
    """Return every role whose root filesystem is writable without owning a volume.

    ``roles`` maps a running container's role to whether its root filesystem
    is read-only, as observed from the platform (``docker inspect``); every
    role outside ``owning_roles`` must report ``True``.
    """

    return tuple(
        role
        for role, read_only in roles.items()
        if role not in owning_roles and not read_only
    )


def verify_volume_readiness(
    bindings: tuple[VolumeBinding, ...],
    *,
    exists: Callable[[Path], bool],
    is_writable: Callable[[Path], bool],
    free_bytes: Callable[[Path], int],
    min_free_bytes: Mapping[str, int],
) -> tuple[str, ...]:
    """Check identity, permissions and free space for every declared volume."""

    violations: list[str] = []
    for binding in bindings:
        path = Path(binding.mount_path)
        if not exists(path):
            violations.append(f"{binding.name}: mount path is absent")
            continue
        if not binding.read_only and not is_writable(path):
            violations.append(f"{binding.name}: mount path is not writable")
        minimum = min_free_bytes.get(binding.name, 0)
        if minimum and free_bytes(path) < minimum:
            violations.append(f"{binding.name}: free space below required minimum")
    return tuple(violations)


def compare_snapshots(
    before: Mapping[str, bytes], after: Mapping[str, bytes]
) -> tuple[str, ...]:
    """Return every key whose bytes differ, appeared or vanished after replacement."""

    mismatches: list[str] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            mismatches.append(key)
    return tuple(mismatches)
