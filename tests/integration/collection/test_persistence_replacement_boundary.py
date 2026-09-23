"""Explicit Linux-container persistence replacement probe; skipped outside an admitted runtime."""

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
def test_recreated_containers_preserve_the_ledger_and_artifacts_byte_for_byte() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        (
            sys.executable,
            str(root / "bin" / "check-collection-linux"),
            "--persistence-replacement",
        ),
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "artifact_marker: preserved" in result.stdout, result.stdout
    assert "ledger_record: preserved" in result.stdout, result.stdout
    assert "Collection persistence replacement probe passed" in result.stdout, (
        result.stdout
    )
