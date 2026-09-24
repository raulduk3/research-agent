"""The owner's cost read: settled spend against the profile's caps (#251)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient


from tests.storage.test_exclusions import PRODUCER, World, identity, world  # noqa: E402
from tests.storage.test_http import Jobs, _tls_material  # noqa: E402
from tests.storage.test_settlements import backdate, repository, settle  # noqa: E402
from tests.web.api_contract import check, check_refusal  # noqa: E402

from research_agent.artifacts import ArtifactStore
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient
from research_agent.storage.database import Database
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.owners import OwnerRepository
from research_agent.storage.queries import InspectorQueries
from research_agent.web.actions.app import (
    JEV_DAILY_SUBLIMIT_MICROS,
    ActionsAppConfig,
    CostCaps,
    create_app,
)
from research_agent.web.auth import OwnerDirectory, hash_credential

pytestmark = pytest.mark.integration

__all__ = ["world"]

# Not the operator the shared storage fixture already provisions.
OWNER_ID = UUID("abababab-abab-4bab-8bab-abababababab")
CREDENTIAL = "owner-credential-for-tests"
OWNER_SCOPES = frozenset({"owner:read"})
CAPS = CostCaps(daily_cap_usd="8", monthly_cap_usd="200", paid_execution_enabled=False)
SETTINGS = {
    "producer": PRODUCER,
    "config_hash": "c" * 64,
    "retention_policy_hash": "d" * 64,
}


@pytest.fixture
def owner_app(
    world: World, artifact_root: Path, tmp_path: Path
) -> Iterator[tuple[TestClient, OwnerDirectory, StorageClient]]:
    database, store = Database(world.dsn), ArtifactStore(artifact_root)
    owners = OwnerRepository(database, store, **SETTINGS)
    salt, credential_hash = hash_credential(CREDENTIAL)
    owners.execute(
        "provision",
        identity=identity(),
        payload={
            "owner_id": str(OWNER_ID),
            "salt": salt,
            "credential_hash": credential_hash,
        },
    )
    server_context, _client, fingerprint, _wrong, _other, _none = _tls_material(
        tmp_path
    )
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {fingerprint: ServiceCapability(uuid4(), "owner", OWNER_SCOPES)},
        tls_context=server_context,
        authorization=StorageAuthorization(database),
        settlements=repository(world, artifact_root),
        queries=InspectorQueries(database, store),
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    host, port = httpd.server_address[:2]
    storage = StorageClient(
        connect_host=str(host),
        port=int(port),
        server_hostname="localhost",
        ca_file=tmp_path / "ca.pem",
        client_cert_file=tmp_path / "client.pem",
        client_key_file=tmp_path / "client.key",
        scopes=OWNER_SCOPES,
        timeout_seconds=10,
    )
    directory = OwnerDirectory(owners)
    app = create_app(
        ActionsAppConfig(
            actions=storage,
            directory=directory,
            budget_funded=True,
            cost_caps=CAPS,
        )
    )
    try:
        yield TestClient(app, base_url="https://testserver"), directory, storage
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def sign_in(client: TestClient) -> None:
    response = client.post("/api/v1/login", json={"credential": CREDENTIAL})
    assert response.status_code == 200, response.text


def test_the_read_totals_equal_the_days_settlements_and_the_caps_are_the_profiles(
    world: World,
    artifact_root: Path,
    owner_app: tuple[TestClient, OwnerDirectory, StorageClient],
) -> None:
    client, _, _ = owner_app
    settlements = repository(world, artifact_root)
    priced, unpriced = world.run(uuid4(), "p1"), world.run(uuid4(), "p2")
    settle(settlements, priced, input_tokens=900, output_tokens=90)
    settle(settlements, unpriced, input_tokens=1200, output_tokens=300)
    now = datetime.now(timezone.utc)
    backdate(world.dsn, priced, now.isoformat(), 4200)
    sign_in(client)

    data = check(
        client.get(f"/api/v1/costs?day={now.date().isoformat()}"),
        "actions",
        "GET",
        "/api/v1/costs",
    )

    assert data["source"] == "settlements"
    assert data["caps"] == {
        "daily_cap_micros": 8_000_000,
        "monthly_cap_micros": 200_000_000,
        "jev_daily_sublimit_micros": JEV_DAILY_SUBLIMIT_MICROS,
        "jev_daily_sublimit_source": "profile_constant",
        "funded": True,
        "paid_execution_enabled": False,
    }
    assert data["today"] == {
        "priced_micros": 4200,
        "priced_runs": 1,
        "unpriced_runs": 1,
        "unpriced_input_tokens": 1200,
        "unpriced_output_tokens": 300,
    }
    assert data["month_to_date"] == data["today"]
    assert [row["island"] for row in data["by_island"]["items"]] == [None]
    assert len(data["by_configuration"]["items"]) == 2
    # Without a day the read is today's.
    assert client.get("/api/v1/costs").json()["data"]["today"] == data["today"]


def test_the_days_read_sums_each_days_settlements_and_refuses_a_malformed_day(
    world: World,
    artifact_root: Path,
    owner_app: tuple[TestClient, OwnerDirectory, StorageClient],
) -> None:
    client, _, _ = owner_app
    settlements = repository(world, artifact_root)
    priced, unpriced = world.run(uuid4(), "p1"), world.run(uuid4(), "p2")
    settle(settlements, priced, input_tokens=900, output_tokens=90)
    settle(settlements, unpriced, input_tokens=1200, output_tokens=300)
    now = datetime.now(timezone.utc)
    backdate(world.dsn, priced, now.isoformat(), 4200)
    check_refusal(client.get("/api/v1/costs/days"), 401, "unauthenticated")
    sign_in(client)

    data = check(
        client.get(f"/api/v1/costs/days?day={now.date().isoformat()}"),
        "actions",
        "GET",
        "/api/v1/costs/days",
    )

    assert data["day"] == now.date().isoformat()
    assert data["days"]["items"] == [
        {
            "day": now.date().isoformat(),
            "island": None,
            "priced_micros": 4200,
            "priced_runs": 1,
            "unpriced_runs": 1,
            "unpriced_input_tokens": 1200,
            "unpriced_output_tokens": 300,
        }
    ]
    error = check_refusal(
        client.get("/api/v1/costs/days?day=20260923"), 422, "invalid_request"
    )
    assert error["field"] == "day"


def test_only_an_owner_session_reads_costs(
    owner_app: tuple[TestClient, OwnerDirectory, StorageClient],
) -> None:
    client, _, _ = owner_app
    check_refusal(client.get("/api/v1/costs"), 401, "unauthenticated")
    refused = client.post("/api/v1/login", json={"credential": "a-rater-credential"})
    check_refusal(refused, 401, "unauthenticated")
    check_refusal(client.get("/api/v1/costs"), 401, "unauthenticated")


def test_a_malformed_day_is_refused_naming_the_field(
    owner_app: tuple[TestClient, OwnerDirectory, StorageClient],
) -> None:
    client, _, _ = owner_app
    sign_in(client)
    error = check_refusal(
        client.get("/api/v1/costs?day=20260923"), 422, "invalid_request"
    )
    assert error["field"] == "day"


def test_without_the_profile_caps_the_read_is_unavailable(
    owner_app: tuple[TestClient, OwnerDirectory, StorageClient],
) -> None:
    _, directory, storage = owner_app
    unwired = TestClient(
        create_app(ActionsAppConfig(actions=storage, directory=directory)),
        base_url="https://testserver",
    )
    sign_in(unwired)
    check_refusal(unwired.get("/api/v1/costs"), 503, "unavailable")


def test_a_cap_that_is_not_whole_microdollars_is_refused_at_composition() -> None:
    with pytest.raises(ValueError):
        CostCaps(
            daily_cap_usd="8.0000001",
            monthly_cap_usd="200",
            paid_execution_enabled=False,
        )
    with pytest.raises(ValueError):
        CostCaps(
            daily_cap_usd="eight", monthly_cap_usd="200", paid_execution_enabled=False
        )
