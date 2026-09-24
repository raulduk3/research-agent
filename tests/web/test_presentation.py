"""The rater and inspector pages carry the design mock's structural landmarks."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from research_agent.artifacts import ArtifactStore
from research_agent.storage.database import Database
from tests.web.test_inspect import Seed, inspector_client, inspector_server, seed  # noqa: F401
from tests.web.test_private_rater_access import _login


@pytest.mark.integration
def test_the_login_page_is_the_mock_form(rating_app_client: TestClient) -> None:
    page = rating_app_client.get("/login").text

    assert '<link rel="stylesheet" href="/static/atoll.css">' in page
    assert '<a class="brand" href="/">' in page
    assert '<form method="post" action="/login" class="box login-box"' in page
    assert 'name="csrf_token"' in page
    assert '<input type="submit" value="sign in">' in page
    assert '<div class="lab"' in page


@pytest.mark.integration
def test_the_mock_sheet_is_served_from_static(rating_app_client: TestClient) -> None:
    response = rating_app_client.get("/static/atoll.css")

    assert response.status_code == 200
    assert response.text.startswith("/*! tailwindcss v4")
    assert ".feed{" in response.text


@pytest.mark.integration
def test_the_digest_is_the_mock_card_list_with_accept_and_pass_only(
    rating_app_client: TestClient,
) -> None:
    _login(rating_app_client)
    page = rating_app_client.get("/").text

    assert '<ol class="cards" role="list">' in page
    assert page.count('<article class="feed"') == page.count('action="/ratings"') > 0
    assert '<div class="ttl"' in page and '<div class="abs"' in page
    assert 'name="value" value="like"' in page and ">accept</button>" in page
    assert 'name="value" value="skip"' in page and ">pass</button>" in page
    assert 'value="dislike"' not in page
    assert 'action="/logout"' in page


@pytest.mark.integration
def test_the_agent_page_keeps_hashes_in_the_identifiers_table(
    seed: tuple[Seed, Database, ArtifactStore], inspector_client: TestClient
) -> None:
    fixture, _, _ = seed
    configuration_id = uuid4()
    genome = fixture.seed_genome(configuration_id, "hypothesis-led reading")

    page = inspector_client.get(f"/agents/{configuration_id}").text

    identifiers = page[page.index('<details class="ids">') : page.index("</details>")]
    assert genome.configuration_hash in identifiers
    assert genome.infra_hash in identifiers
    assert page.count(genome.configuration_hash) == 1
    assert '<a class="brand" href="/agents">' in page


@pytest.mark.integration
def test_the_run_page_keeps_hashes_in_the_identifiers_table(
    seed: tuple[Seed, Database, ArtifactStore], inspector_client: TestClient
) -> None:
    fixture, _, _ = seed
    snapshot_hash = fixture.seal_snapshot()
    run_id = fixture.create_run(
        sheet_hash=fixture.seal_sheet(),
        snapshot_hash=snapshot_hash,
        configuration_id=uuid4(),
    )

    page = inspector_client.get(f"/runs/{UUID(run_id)}").text

    identifiers = page[page.index('<details class="ids">') : page.index("</details>")]
    assert snapshot_hash in identifiers
    assert page.count(snapshot_hash) == 1
