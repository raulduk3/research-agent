"""Exercise the installed administration entry point against real storage."""

import os
import subprocess
import sys

import pytest


def invoke(command: str, dsn: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("RESEARCH_AGENT_STORAGE_DSN", None)
    if dsn is not None:
        env["RESEARCH_AGENT_STORAGE_DSN"] = dsn
    return subprocess.run(
        [sys.executable, "-m", "research_agent", command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def test_missing_dsn_refuses_administration() -> None:
    result = invoke("migrate", None)
    assert result.returncode == 2
    assert "RESEARCH_AGENT_STORAGE_DSN is required" in result.stderr


@pytest.mark.integration
def test_cli_refuses_absent_schema_then_migrates(unmigrated_postgres_dsn: str) -> None:
    absent = invoke("check-schema", unmigrated_postgres_dsn)
    assert absent.returncode == 1
    assert unmigrated_postgres_dsn not in absent.stderr
    assert invoke("migrate", unmigrated_postgres_dsn).returncode == 0
    assert invoke("migrate", unmigrated_postgres_dsn).returncode == 0
    assert invoke("check-schema", unmigrated_postgres_dsn).returncode == 0
