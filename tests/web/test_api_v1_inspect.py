"""The inspector's /api/v1 twins serve the page views over real storage (#249)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient
from tests.web import test_inspect as inspect
from tests.web.api_contract import (
    WEB_DIR,
    check,
    check_refusal,
    html_fields_missing_from,
)

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_json
from research_agent.storage.database import Database

pytestmark = pytest.mark.integration

# The inspector app over real storage and the fixture that seeds it.
seed = inspect.seed
inspector_server = inspect.inspector_server
inspector_client = inspect.inspector_client

TEMPLATES = WEB_DIR / "inspect" / "templates"


@dataclass(frozen=True)
class World:
    configuration_id: UUID
    run_id: str
    manifest_hash: str


@pytest.fixture
def world(seed: tuple[inspect.Seed, Database, ArtifactStore]) -> World:
    """One genome with a run that sealed a forecast, and a manifest."""
    fixture, _, _ = seed
    sheet_hash = fixture.seal_sheet()
    snapshot_hash = fixture.seal_snapshot()
    configuration_id = uuid4()
    fixture.seed_genome(configuration_id, "hypothesis-led reading")
    run_id = fixture.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=configuration_id,
    )
    fixture.seal_forecast(sheet_hash=sheet_hash, submitter_id=UUID(run_id))
    manifest_hash = fixture.artifact(canonical_json(inspect.REPRESENTATION_MANIFEST))
    return World(configuration_id, run_id, manifest_hash)


def test_the_run_validates_and_carries_every_field_the_page_shows(
    world: World, inspector_client: TestClient
) -> None:
    path = "/api/v1/runs/{run_id}"
    data = check(
        inspector_client.get(f"/api/v1/runs/{world.run_id}"), "inspector", "GET", path
    )
    assert html_fields_missing_from(TEMPLATES / "run.html", data) == []
    assert data["run"]["run_id"] == world.run_id
    assert [item["question_id"] for item in data["submissions"]["items"]] == [
        inspect.QUESTION_A
    ]
    check_refusal(inspector_client.get(f"/api/v1/runs/{uuid4()}"), 404, "not_found")


def test_the_population_validates_and_carries_every_field_the_page_shows(
    world: World, inspector_client: TestClient
) -> None:
    data = check(
        inspector_client.get("/api/v1/agents"), "inspector", "GET", "/api/v1/agents"
    )
    assert html_fields_missing_from(TEMPLATES / "population.html", data) == []
    assert [item["configuration_id"] for item in data["configurations"]["items"]] == [
        str(world.configuration_id)
    ]
    malformed = inspector_client.get("/api/v1/agents?cursor=malformed")
    check_refusal(malformed, 422, "invalid_request")


def test_the_agent_validates_and_carries_every_field_the_page_shows(
    world: World, inspector_client: TestClient
) -> None:
    data = check(
        inspector_client.get(f"/api/v1/agents/{world.configuration_id}"),
        "inspector",
        "GET",
        "/api/v1/agents/{configuration_id}",
    )
    assert html_fields_missing_from(TEMPLATES / "agent.html", data) == []
    assert data["genome"]["island"] == "quant-ph"
    assert [run["run_id"] for run in data["runs"]["items"]] == [world.run_id]
    [forecast] = data["forecasts"]["items"]
    assert (forecast["question_id"], forecast["resolution"]) == (
        inspect.QUESTION_A,
        None,
    )


def test_an_agent_without_a_population_record_has_a_null_genome(
    inspector_client: TestClient,
) -> None:
    data = check(
        inspector_client.get(f"/api/v1/agents/{uuid4()}"),
        "inspector",
        "GET",
        "/api/v1/agents/{configuration_id}",
    )
    assert data["genome"] is None
    assert data["runs"] == {"items": [], "next_cursor": None}


def test_the_manifest_validates_and_carries_every_field_the_page_shows(
    world: World, inspector_client: TestClient
) -> None:
    data = check(
        inspector_client.get(f"/api/v1/models/{world.manifest_hash}"),
        "inspector",
        "GET",
        "/api/v1/models/{manifest_hash}",
    )
    assert html_fields_missing_from(TEMPLATES / "manifest.html", data) == []
    assert data["manifest"]["fields"]["model_id"] == "nomic-ai/modernbert-embed-base"
    unknown = inspector_client.get(f"/api/v1/models/{'0' * 64}")
    check_refusal(unknown, 404, "not_found")
