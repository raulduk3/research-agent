"""``GET /api/v1/health`` on the owner actions app serves the health monitor (#254)."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient
from web.test_owner_actions_app import (  # noqa: F401
    CREDENTIAL,
    PRODUCER,
    build_owner_app,
    storage_service,
)

from research_agent.artifacts import ArtifactStore
from research_agent.platform.health import HealthMonitor, HealthPoll, initial_health
from research_agent.storage.database import Database
from research_agent.storage.owners import OwnerRepository
from research_agent.web.actions.app import ActionsAppConfig, create_app
from research_agent.web.auth import OwnerDirectory

pytestmark = pytest.mark.integration

STARTED_AT = "2026-09-23T00:00:00.000000Z"
CHECKED_AT = "2026-09-23T00:01:00.000000Z"


def _report() -> dict[str, object]:
    monitor = HealthMonitor()
    ready = monitor.apply_poll(
        initial_health("storage", started_at=STARTED_AT),
        HealthPoll(ready=True, polled_at="2026-09-23T00:00:30.000000Z"),
    )
    loading = initial_health("models", started_at=STARTED_AT)
    return monitor.report([ready, loading], checked_at=CHECKED_AT)


def _client(postgres_dsn: str, artifact_root: Path, *, serve: bool) -> TestClient:
    # build_owner_app provisions the owner and starts the storage service;
    # this app is the same wiring plus the health provider under test.
    provisioned = build_owner_app(postgres_dsn, artifact_root, members=0)
    owners = OwnerRepository(
        Database(postgres_dsn),
        ArtifactStore(artifact_root),
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    app = create_app(
        ActionsAppConfig(
            actions=provisioned.actions,
            directory=OwnerDirectory(owners),
            health=_report if serve else None,
        )
    )
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_the_owner_reads_the_monitor_report(
    postgres_dsn: str, artifact_root: Path
) -> None:
    client = _client(postgres_dsn, artifact_root, serve=True)
    assert client.post("/login", data={"credential": CREDENTIAL}).status_code == 303
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "state": "waiting",
        "checked_at": CHECKED_AT,
        "checks": [
            {"name": "storage", "state": "healthy", "detail": "ready"},
            {
                "name": "models",
                "state": "waiting",
                "detail": f"not yet ready since {STARTED_AT}; 0 failed polls",
            },
        ],
    }


def test_no_session_and_a_wrong_credential_get_no_report(
    postgres_dsn: str, artifact_root: Path
) -> None:
    client = _client(postgres_dsn, artifact_root, serve=True)
    assert client.get("/api/v1/health").status_code == 401
    refused = client.post("/login", data={"credential": "not-the-credential"})
    assert refused.status_code == 401
    assert client.get("/api/v1/health").status_code == 401


def test_an_unwired_monitor_is_unavailable_not_a_made_up_state(
    postgres_dsn: str, artifact_root: Path
) -> None:
    client = _client(postgres_dsn, artifact_root, serve=False)
    assert client.post("/login", data={"credential": CREDENTIAL}).status_code == 303
    assert client.get("/api/v1/health").status_code == 503
