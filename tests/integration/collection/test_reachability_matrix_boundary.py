"""Explicit Linux-container reachability matrix probe; skipped outside an admitted runtime."""

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
def test_compiled_reachability_policy_holds_for_a_declared_and_an_undeclared_role() -> (
    None
):
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        (
            sys.executable,
            str(root / "bin" / "check-collection-linux"),
            "--reachability-matrix",
        ),
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    for record in (
        "storage_to_postgres: reachable (declared edge holds)",
        "bystander_to_postgres: denied (no compiled edge)",
        "Collection reachability matrix probe passed",
    ):
        assert record in result.stdout, result.stdout
