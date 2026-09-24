"""Executable component inventory (SDD-SR-01).

`ComponentInventory` is the stored, versioned list SR-01 requires: every
running component assigned to exactly one of the five ordered layers,
infrastructure, environment, agents, reader and models, or, for a batch job
that connects layers rather than sitting in one, the pair of layers it
connects. `reconcile` is the readiness-time comparison against what a Compose
project and container inspection actually report, scoped to that project so
an unrelated host container never counts as missing or extra.

`ROLE_IDS` is the same closed container-role vocabulary `platform.compose`
declares; a test that both modules agree on identical role sets is what
proves the component inventory and the compose file describe one system, not
two that can drift apart.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
)

# The five ordered layers SR-01 fixes, outermost to innermost.
LAYER_ORDER: tuple[str, ...] = (
    "infrastructure",
    "environment",
    "agents",
    "reader",
    "models",
)

# The closed container-role vocabulary. "worker" and "batch" are the
# dynamic, per-run and per-job instances PL-01 also names; they are never
# static Compose services, so `platform.compose` excludes them from the
# roles a Compose definition must declare. "app" is the raters' app and
# "owner" the owner's actions and inspection app; "ingress" is the one reverse
# proxy the owner surfaces are published through (decision 0030).
ROLE_IDS: tuple[str, ...] = (
    "postgres",
    "storage",
    "ingest",
    "reader",
    "models",
    "tools",
    "scorer",
    "orchestrator",
    "app",
    "owner",
    "ingress",
    "worker",
    "batch",
)

DYNAMIC_ROLE_IDS: frozenset[str] = frozenset({"worker", "batch"})

# Every ordinary role's single layer, per SR-01's "runtime/observation,
# environment, agent workers, reader and shared models" assignment. "batch"
# has no single layer: a batch row instead names the two layers it connects.
ROLE_LAYER: Mapping[str, str] = {
    "postgres": "infrastructure",
    "storage": "infrastructure",
    "scorer": "infrastructure",
    "orchestrator": "infrastructure",
    "app": "infrastructure",
    "owner": "infrastructure",
    "ingress": "infrastructure",
    "ingest": "environment",
    "tools": "agents",
    "worker": "agents",
    "reader": "reader",
    "models": "models",
}

MODES: tuple[str, ...] = ("collection", "engineering", "study")


@dataclass(frozen=True, slots=True)
class ComponentRecord:
    """One ordinary component: its role, its exactly-one layer and its modes."""

    component_id: str
    role: str
    layers: frozenset[str]
    image_digest: str
    interface_ids: tuple[str, ...]
    mode_membership: frozenset[str]

    def __post_init__(self) -> None:
        validate_non_empty_string(self.component_id)
        if self.role == "batch" or self.role not in ROLE_LAYER:
            raise ContractValidationError(
                "an ordinary component must use a role with exactly one layer"
            )
        if len(self.layers) != 1:
            raise ContractValidationError(
                "an ordinary component must be assigned to exactly one layer"
            )
        if self.layers != frozenset({ROLE_LAYER[self.role]}):
            raise ContractValidationError("layer assignment does not match the role")
        validate_sha256(self.image_digest)
        if len(set(self.interface_ids)) != len(self.interface_ids):
            raise ContractValidationError("interface_ids must not repeat")
        for interface_id in self.interface_ids:
            validate_non_empty_string(interface_id)
        if not self.mode_membership or not self.mode_membership <= set(MODES):
            raise ContractValidationError(
                "mode_membership must be a nonempty subset of MODES"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "role": self.role,
            "layers": sorted(self.layers),
            "image_digest": self.image_digest,
            "interface_ids": list(self.interface_ids),
            "mode_membership": sorted(self.mode_membership),
        }


@dataclass(frozen=True, slots=True)
class BatchRecord:
    """One batch job: the two layers it connects, rather than one it sits in."""

    component_id: str
    input_layer: str
    output_layer: str
    image_digest: str
    interface_ids: tuple[str, ...]
    mode_membership: frozenset[str]
    role: str = "batch"

    def __post_init__(self) -> None:
        validate_non_empty_string(self.component_id)
        if self.role != "batch":
            raise ContractValidationError("a batch row must use the batch role")
        if self.input_layer not in LAYER_ORDER or self.output_layer not in LAYER_ORDER:
            raise ContractValidationError(
                "input_layer and output_layer must be named layers"
            )
        if self.input_layer == self.output_layer:
            raise ContractValidationError(
                "a batch job must connect two distinct layers"
            )
        validate_sha256(self.image_digest)
        if len(set(self.interface_ids)) != len(self.interface_ids):
            raise ContractValidationError("interface_ids must not repeat")
        for interface_id in self.interface_ids:
            validate_non_empty_string(interface_id)
        if not self.mode_membership or not self.mode_membership <= set(MODES):
            raise ContractValidationError(
                "mode_membership must be a nonempty subset of MODES"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "role": self.role,
            "input_layer": self.input_layer,
            "output_layer": self.output_layer,
            "image_digest": self.image_digest,
            "interface_ids": list(self.interface_ids),
            "mode_membership": sorted(self.mode_membership),
        }


@dataclass(frozen=True, slots=True)
class ObservedComponent:
    """One component id a Compose project's labels/container inspection reports."""

    component_id: str
    project: str


@dataclass(frozen=True, slots=True)
class ComponentReconciliation:
    """The result of comparing declared, mode-eligible components with what runs."""

    missing: tuple[str, ...]
    duplicate: tuple[str, ...]
    extra: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.duplicate or self.extra)


@dataclass(frozen=True, slots=True)
class ComponentInventory:
    """The complete, hashable component and batch-job inventory SR-01 stores."""

    components: tuple[ComponentRecord, ...]
    batches: tuple[BatchRecord, ...] = ()

    def _all_items(self) -> tuple[ComponentRecord | BatchRecord, ...]:
        return (*self.components, *self.batches)

    def __post_init__(self) -> None:
        ids = [item.component_id for item in self._all_items()]
        if len(set(ids)) != len(ids):
            raise ContractValidationError(
                "component_id must be unique across the inventory"
            )

    @property
    def role_ids(self) -> frozenset[str]:
        return frozenset(item.role for item in self._all_items())

    def to_dict(self) -> dict[str, object]:
        return {
            "components": [item.to_dict() for item in self.components],
            "batches": [item.to_dict() for item in self.batches],
        }

    def compute_hash(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))

    def reconcile(
        self,
        observed: Iterable[ObservedComponent],
        *,
        project: str,
        mode: str,
    ) -> ComponentReconciliation:
        """Compare this project's observed containers with mode-eligible components.

        An observed component from a different Compose project is ignored, so
        an unrelated host container is never counted as extra.
        """

        if mode not in MODES:
            raise ContractValidationError("mode must be one of MODES")
        expected = {
            item.component_id
            for item in self._all_items()
            if mode in item.mode_membership
        }
        seen_in_project = [
            item.component_id for item in observed if item.project == project
        ]
        seen_counts: dict[str, int] = {}
        for component_id in seen_in_project:
            seen_counts[component_id] = seen_counts.get(component_id, 0) + 1
        duplicate = tuple(
            sorted(cid for cid, count in seen_counts.items() if count > 1)
        )
        missing = tuple(sorted(expected - seen_counts.keys()))
        extra = tuple(sorted(seen_counts.keys() - expected))
        return ComponentReconciliation(
            missing=missing, duplicate=duplicate, extra=extra
        )
