"""Fail-closed collection-mode startup evidence checks."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CollectionReadiness:
    ready: bool
    missing: tuple[str, ...]


def check_collection_readiness(
    *, compose_file: Path, storage_config: Path, isolation_evidence: Path | None
) -> CollectionReadiness:
    missing: list[str] = []
    if platform.system() != "Linux":
        missing.append("linux_host")
    for label, path in (
        ("compose_definition", compose_file),
        ("storage_config", storage_config),
    ):
        if not path.is_file():
            missing.append(label)
    # Compose networks do not establish the required host firewall policy.
    if isolation_evidence is None or not isolation_evidence.is_file():
        missing.append("host_enforced_isolation_evidence")
    else:
        missing.append("host_enforced_isolation_unverified")
    return CollectionReadiness(not missing, tuple(missing))
