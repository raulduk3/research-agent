"""Explicit Linux-container worker-image probe; skipped outside an admitted runtime."""

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
def test_built_image_and_declared_mounts_admit_the_weight_free_policy() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        (
            sys.executable,
            str(root / "bin" / "check-collection-linux"),
            "--worker-image",
        ),
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Collection worker image probe passed" in result.stdout, result.stdout
