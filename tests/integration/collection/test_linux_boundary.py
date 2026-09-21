"""Explicit Linux-container acceptance probe; skipped outside an admitted runtime."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    platform.system() != "Linux"
    or not os.environ.get("RESEARCH_AGENT_CONTAINER_DOCKER"),
    reason="requires an explicitly selected disposable Linux Docker runtime",
)
def test_runtime_probe_observes_internal_network_and_named_volume() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        (
            sys.executable,
            str(root / "bin" / "check-collection-linux"),
            "--runtime-probe",
        ),
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "runtime probe passed" in result.stdout


@pytest.mark.skipif(
    platform.system() != "Linux"
    or not os.environ.get("RESEARCH_AGENT_CONTAINER_DOCKER")
    or not os.environ.get("RESEARCH_AGENT_DOCKER_CONTEXT")
    or not os.environ.get("RESEARCH_AGENT_STORAGE_IMAGE")
    or not os.environ.get("RESEARCH_AGENT_POSTGRES_CONTAINER")
    or not os.environ.get("RESEARCH_AGENT_SOURCE_COMMIT"),
    reason="requires explicitly selected disposable Linux storage fixtures",
)
def test_storage_container_enforces_mtls_and_database_roles() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        (sys.executable, str(root / "bin" / "probe-storage-mtls")),
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "cross_role_job_kind: http=403 code=forbidden" in result.stdout
    assert "storage mTLS probe passed" in result.stdout
