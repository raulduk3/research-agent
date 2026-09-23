"""Explicit Linux-container secret scan probe; skipped outside an admitted runtime."""

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
def test_built_image_and_build_context_carry_no_synthetic_secret_value() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        (sys.executable, str(root / "bin" / "check-collection-linux"), "--secret-scan"),
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    for record in (
        "control_detection: caught",
        "image_history: clean",
        "rendered_compose: clean",
        "image_filesystem: clean",
        "Collection secret scan probe passed",
    ):
        assert record in result.stdout, result.stdout
