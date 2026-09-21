"""Exercise the installed administration entry point against real storage."""

import os
import subprocess
import sys

import pytest

from research_agent.platform.storage_service import _capabilities


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


def test_collection_readiness_requires_explicit_evidence(tmp_path) -> None:
    config = tmp_path / "storage.json"
    config.write_text("{}\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_agent",
            "collection-readiness",
            "--storage-config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "host_enforced_isolation_evidence" in result.stderr


def test_storage_capabilities_reject_duplicate_principals() -> None:
    principal = "123e4567-e89b-42d3-a456-426614174000"
    row = {
        "principal_id": principal,
        "role": "reader",
        "scopes": [],
        "job_kinds": [],
        "producer_version": {
            "image_digest": "c" * 64,
            "source_commit": "d" * 40,
            "contract_version": 1,
        },
        "config_hash": "e" * 64,
        "retention_policy_hash": "f" * 64,
    }
    with pytest.raises(ValueError, match="principal_id must be unique"):
        _capabilities(
            {"a" * 64: row, "b" * 64: row},
        )


def test_storage_capabilities_require_worker_deployment_binding() -> None:
    with pytest.raises(ValueError, match="producer_version"):
        _capabilities(
            {
                "a" * 64: {
                    "principal_id": "123e4567-e89b-42d3-a456-426614174000",
                    "role": "reader",
                    "scopes": [],
                    "job_kinds": [],
                    "config_hash": "e" * 64,
                    "retention_policy_hash": "f" * 64,
                }
            }
        )


@pytest.mark.integration
def test_cli_refuses_absent_schema_then_migrates(unmigrated_postgres_dsn: str) -> None:
    absent = invoke("check-schema", unmigrated_postgres_dsn)
    assert absent.returncode == 1
    assert unmigrated_postgres_dsn not in absent.stderr
    assert invoke("migrate", unmigrated_postgres_dsn).returncode == 0
    assert invoke("migrate", unmigrated_postgres_dsn).returncode == 0
    assert invoke("check-schema", unmigrated_postgres_dsn).returncode == 0
