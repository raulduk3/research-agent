"""Weight-free worker images and mounts (SDD-PL-09).

An agent run loads no model weights of its own: its image carries the model
HTTP client, the strict tool loop and contract code only, and admission
checks the actual image contents and attached volumes rather than trusting a
filename convention. The host-acceptance probe feeds real `docker inspect`
and image-layer listings through `WorkerImagePolicy.evaluate`; this module
carries no Docker dependency itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

_DEFAULT_DENIED_PATH_PREFIXES: frozenset[str] = frozenset(
    {
        "/root/.cache/huggingface",
        "/home/app/.cache/huggingface",
        "/app/models",
        "/var/lib/research-agent/models",
        "/var/lib/research-agent/artifacts",
    }
)

_DEFAULT_DENIED_MOUNT_DESTINATIONS: frozenset[str] = frozenset(
    {
        "/var/lib/research-agent/artifacts",
        "/var/lib/research-agent/models",
        "/var/lib/postgresql/data",
        "/var/run/docker.sock",
    }
)

_DEFAULT_DENIED_ENVIRONMENT_KEYS: frozenset[str] = frozenset(
    {"HF_HOME", "TRANSFORMERS_CACHE", "HUGGINGFACE_HUB_CACHE"}
)


@dataclass(frozen=True, slots=True)
class VolumeMount:
    """One mount attached to a worker container, as `docker inspect` reports it."""

    destination: str
    read_only: bool


@dataclass(frozen=True, slots=True)
class WorkerImagePolicy:
    """The denylist an admitted worker image and its mounts must satisfy."""

    denied_path_prefixes: frozenset[str] = field(
        default_factory=lambda: _DEFAULT_DENIED_PATH_PREFIXES
    )
    denied_mount_destinations: frozenset[str] = field(
        default_factory=lambda: _DEFAULT_DENIED_MOUNT_DESTINATIONS
    )
    denied_environment_keys: frozenset[str] = field(
        default_factory=lambda: _DEFAULT_DENIED_ENVIRONMENT_KEYS
    )

    def evaluate(
        self,
        *,
        image_paths: Iterable[str],
        mounts: Iterable[VolumeMount],
        environment: Iterable[str],
    ) -> tuple[str, ...]:
        """Return every violation found; an empty result means admission passes."""

        violations: list[str] = []
        for path in image_paths:
            for prefix in self.denied_path_prefixes:
                if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
                    violations.append(f"image_path:{path}")
                    break
        for mount in mounts:
            if mount.destination in self.denied_mount_destinations:
                violations.append(f"mount:{mount.destination}")
        for entry in environment:
            key = entry.split("=", 1)[0]
            if key in self.denied_environment_keys:
                violations.append(f"environment:{key}")
        return tuple(violations)
