"""The owner actions app's /api/v1 read twins over real storage (#249, #255)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient
from tests.web import test_health as health
from tests.web import test_inspect as inspect
from tests.web import test_owner_inspection as inspection
from tests.web.api_contract import (
    WEB_DIR,
    check,
    check_refusal,
    html_fields_missing_from,
)

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_json
from research_agent.storage.database import Database
from research_agent.web.actions.app import ActionsAppConfig, create_app

pytestmark = pytest.mark.integration

# The owner actions app with its inspector client, a digest the owner's rater
# identity rated one entry of, and the inspector fixture that seeds runs.
owner = inspection.owner
seed = inspect.seed

ACTIONS = WEB_DIR / "actions" / "templates"
INSPECTOR = WEB_DIR / "inspect" / "templates"
#: Everything an unrated entry may not carry besides its id, paper and position.
PROVENANCE = {
    "origin",
    "service_source",
    "candidate_pool_hash",
    "inclusion_probability",
    "nominations",
}


def sign_in(client: TestClient) -> str:
    response = client.post("/api/v1/login", json={"credential": inspection.CREDENTIAL})
    data = check(response, "actions", "POST", "/api/v1/login")
    assert "owner_session" in response.cookies
    token = data["csrf_token"]
    assert isinstance(token, str)
    return token


def test_every_read_refuses_a_visitor_without_a_session(
    owner: inspection.Owner,
) -> None:
    for path in (
        "/api/v1/retrospective",
        "/api/v1/health",
        "/api/v1/agents",
        f"/api/v1/agents/{owner.configuration_id}",
        f"/api/v1/runs/{uuid4()}",
        f"/api/v1/runs/{uuid4()}/record",
        f"/api/v1/models/{'a' * 64}",
        f"/api/v1/digests/{owner.digest_hash}",
        "/api/v1/seed",
    ):
        check_refusal(owner.client.get(path), 401, "unauthenticated")


def test_the_login_view_and_a_refused_credential(owner: inspection.Owner) -> None:
    data = check(owner.client.get("/api/v1/login"), "actions", "GET", "/api/v1/login")
    assert html_fields_missing_from(ACTIONS / "login.html", data) == []
    refused = owner.client.post("/api/v1/login", json={"credential": "not-it"})
    check_refusal(refused, 401, "unauthenticated")
    assert "owner_session" not in refused.cookies


def test_the_retrospective_validates_and_carries_every_field_the_page_shows(
    owner: inspection.Owner,
) -> None:
    token = sign_in(owner.client)
    data = check(
        owner.client.get("/api/v1/retrospective"),
        "actions",
        "GET",
        "/api/v1/retrospective",
    )
    assert html_fields_missing_from(ACTIONS / "retrospective.html", data) == []
    assert data["csrf_token"] == token


def test_the_health_report_is_served_in_the_envelope(owner: inspection.Owner) -> None:
    app = create_app(
        ActionsAppConfig(
            actions=owner.connect("client", inspection.OWNER_SCOPES),
            directory=owner.directory,
            health=health._report,
        )
    )
    client = TestClient(app, base_url="https://testserver")
    sign_in(client)
    data = check(client.get("/api/v1/health"), "actions", "GET", "/api/v1/health")
    assert data["state"] == "waiting"
    unwired = TestClient(
        create_app(
            ActionsAppConfig(
                actions=owner.connect("client", inspection.OWNER_SCOPES),
                directory=owner.directory,
            )
        ),
        base_url="https://testserver",
    )
    sign_in(unwired)
    check_refusal(unwired.get("/api/v1/health"), 503, "unavailable")


def test_the_inspector_reads_validate_and_carry_every_field_their_pages_show(
    owner: inspection.Owner, seed: tuple[inspect.Seed, Database, ArtifactStore]
) -> None:
    fixture, _, _ = seed
    sheet_hash = fixture.seal_sheet()
    run_id = fixture.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=fixture.seal_snapshot(),
        configuration_id=owner.configuration_id,
    )
    fixture.seal_forecast(sheet_hash=sheet_hash, submitter_id=UUID(run_id))
    manifest_hash = fixture.artifact(canonical_json(inspect.REPRESENTATION_MANIFEST))
    sign_in(owner.client)

    population = check(
        owner.client.get("/api/v1/agents"), "actions", "GET", "/api/v1/agents"
    )
    assert html_fields_missing_from(INSPECTOR / "population.html", population) == []
    run = check(
        owner.client.get(f"/api/v1/runs/{run_id}"),
        "actions",
        "GET",
        "/api/v1/runs/{run_id}",
    )
    assert html_fields_missing_from(INSPECTOR / "run.html", run) == []
    manifest = check(
        owner.client.get(f"/api/v1/models/{manifest_hash}"),
        "actions",
        "GET",
        "/api/v1/models/{manifest_hash}",
    )
    assert html_fields_missing_from(INSPECTOR / "manifest.html", manifest) == []

    agent = check(
        owner.client.get(f"/api/v1/agents/{owner.configuration_id}"),
        "actions",
        "GET",
        "/api/v1/agents/{configuration_id}",
    )
    assert html_fields_missing_from(ACTIONS / "agent.html", agent) == []
    assert [item["run_id"] for item in agent["inspected"]["runs"]["items"]] == [run_id]
    assert len(agent["inspected"]["forecasts"]["items"]) == 1

    record = check(
        owner.client.get(f"/api/v1/runs/{run_id}/record"),
        "actions",
        "GET",
        "/api/v1/runs/{run_id}/record",
    )
    assert (record["run_id"], record["island"], record["ending"]) == (
        run_id,
        "cs",
        None,
    )
    assert record["calls"] == {"items": [], "next_cursor": None}
    assert record["nominations"] == {"items": [], "next_cursor": None}
    for missing in (uuid4(), "not-a-uuid"):
        check_refusal(
            owner.client.get(f"/api/v1/runs/{missing}/record"), 404, "not_found"
        )

    check_refusal(owner.client.get(f"/api/v1/runs/{uuid4()}"), 404, "not_found")
    check_refusal(owner.client.get(f"/api/v1/models/{'0' * 64}"), 404, "not_found")
    check_refusal(
        owner.client.get("/api/v1/agents?cursor=malformed"), 422, "invalid_request"
    )


def test_without_the_inspector_client_the_agent_has_no_inspected_field(
    owner: inspection.Owner,
) -> None:
    bare = TestClient(
        create_app(
            ActionsAppConfig(
                actions=owner.connect("client", inspection.OWNER_SCOPES),
                directory=owner.directory,
            )
        ),
        base_url="https://testserver",
    )
    sign_in(bare)
    data = check(
        bare.get(f"/api/v1/agents/{owner.configuration_id}"),
        "actions",
        "GET",
        "/api/v1/agents/{configuration_id}",
    )
    assert "inspected" not in data
    check_refusal(bare.get("/api/v1/agents"), 503, "unavailable")
    check_refusal(bare.get(f"/api/v1/agents/{uuid4()}"), 404, "not_found")


def test_an_unrated_digest_entry_carries_no_provenance_in_the_json(
    owner: inspection.Owner,
) -> None:
    sign_in(owner.client)
    data = check(
        owner.client.get(f"/api/v1/digests/{owner.digest_hash}"),
        "actions",
        "GET",
        "/api/v1/digests/{digest_hash}",
    )
    entries = {entry["entry_id"]: entry for entry in data["entries"]}
    rated, unrated = entries[str(owner.rated_entry)], entries[str(owner.unrated_entry)]
    assert rated["rated"] is True and rated["origin"] == "population"
    # another rater's rating does not unlock it for the owner
    assert unrated["rated"] is False
    assert not PROVENANCE & set(unrated)
    check_refusal(owner.client.get(f"/api/v1/digests/{'a' * 64}"), 404, "not_found")


def test_the_seed_form_validates_blank_and_copied(owner: inspection.Owner) -> None:
    sign_in(owner.client)
    blank = check(owner.client.get("/api/v1/seed"), "actions", "GET", "/api/v1/seed")
    assert blank["copied"] is None
    copied = check(
        owner.client.get(f"/api/v1/seed?template={owner.configuration_id}"),
        "actions",
        "GET",
        "/api/v1/seed",
    )
    assert html_fields_missing_from(ACTIONS / "seed.html", copied) == []
    assert copied["copied"]["configuration_id"] == str(owner.configuration_id)
    check_refusal(
        owner.client.get(f"/api/v1/seed?template={uuid4()}"), 404, "not_found"
    )
