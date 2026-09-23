"""The owner actions app over real storage: admit, retire, seed (#139)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.storage.actions import POPULATION_FLOOR, OwnerActions
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.owners import OwnerRepository
from research_agent.web.actions.app import ActionsAppConfig, create_app
from research_agent.web.auth import OwnerDirectory, hash_credential

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
PROFILE_HASH = "a" * 64
INFRA_HASH = "b" * 64
OWNER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
CREDENTIAL = "owner-credential-for-tests"
CORPUS = ("2301.12345v1",)
FOUNDER_PROMPT = "evidence first prompt"


def genome(lineage: str, *, founder: bool = False, prompt: str | None = None) -> Genome:
    return Genome(
        lineage_id=lineage,
        island="cs",
        infra_hash=INFRA_HASH,
        emphasis={
            "prompt": prompt if prompt is not None else f"prompt-{lineage}",
            "scan_policy": "scan",
            "read_policy": "read",
            "probability_assignment_rule": "one sample",
        },
        founder=founder,
    )


@dataclass
class OwnerApp:
    client: TestClient
    founder_id: UUID
    member_ids: list[UUID]
    actions: OwnerActions

    def sign_in(self, credential: str = CREDENTIAL) -> None:
        response = self.client.post("/login", data={"credential": credential})
        assert response.status_code == 303

    def csrf(self, path: str) -> str:
        page = self.client.get(path)
        assert page.status_code == 200
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert match is not None
        return match.group(1)


def build_owner_app(
    postgres_dsn: str,
    artifact_root: Path,
    *,
    members: int,
    cycles: int | None = 2,
    funded: bool = True,
) -> OwnerApp:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    settings = {
        "producer": PRODUCER,
        "config_hash": "c" * 64,
        "retention_policy_hash": "d" * 64,
    }
    owners = OwnerRepository(database, store, **settings)
    salt, credential_hash = hash_credential(CREDENTIAL)
    owners.execute(
        "provision",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "owner_id": str(OWNER_ID),
            "salt": salt,
            "credential_hash": credential_hash,
        },
    )
    population = PopulationStore(database, store, **settings)
    founder_id = uuid4()
    population.record_seed(
        configuration_id=founder_id,
        genome=genome("founder", founder=True, prompt=FOUNDER_PROMPT),
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    member_ids = []
    for index in range(members):
        configuration_id = uuid4()
        population.record_seed(
            configuration_id=configuration_id,
            genome=genome(f"member-{index}"),
            profile_hash=PROFILE_HASH,
            command_id=uuid4(),
        )
        member_ids.append(configuration_id)
    actions = OwnerActions(database, store, **settings)
    app = create_app(
        ActionsAppConfig(
            actions=actions,
            directory=OwnerDirectory(owners),
            corpus_identifiers=CORPUS,
            profile_hash=PROFILE_HASH,
            budget_funded=funded,
            completed_weekly_cycles=cycles,
        )
    )
    client = TestClient(app, base_url="https://testserver", follow_redirects=False)
    return OwnerApp(client, founder_id, member_ids, actions)


@pytest.fixture
def owner_app(postgres_dsn: str, artifact_root: Path) -> OwnerApp:
    return build_owner_app(postgres_dsn, artifact_root, members=POPULATION_FLOOR)


def edit_form(owner_app: OwnerApp, token: str, **overrides: str) -> dict[str, str]:
    form = {
        "csrf_token": token,
        "lineage_id": "owner-edit",
        "prompt": FOUNDER_PROMPT,
        "scan_policy": "scan",
        "read_policy": "read",
        "probability_assignment_rule": "one sample",
    }
    form.update(overrides)
    return form


def test_every_route_refuses_a_visitor_without_an_owner_session(
    owner_app: OwnerApp,
) -> None:
    agent = f"/agents/{owner_app.founder_id}"
    client = owner_app.client
    assert client.get("/").status_code == 401
    assert client.get(agent).status_code == 401
    assert client.get("/seed").status_code == 401
    assert client.post(f"{agent}/retire", data={"csrf_token": "x"}).status_code == 401
    assert client.post(f"{agent}/admit", data={"csrf_token": "x"}).status_code == 401
    assert client.post("/seed", data={"csrf_token": "x"}).status_code == 401


def test_a_wrong_credential_and_a_rater_session_cookie_are_refused(
    owner_app: OwnerApp,
) -> None:
    refused = owner_app.client.post("/login", data={"credential": "not-the-owner"})
    assert refused.status_code == 401
    assert "owner_session" not in refused.cookies

    owner_app.client.cookies.set("rater_session", "anything", domain="testserver")
    assert owner_app.client.get("/").status_code == 401


def test_the_agent_page_is_prefilled_from_the_stored_genome(
    owner_app: OwnerApp,
) -> None:
    owner_app.sign_in()
    page = owner_app.client.get(f"/agents/{owner_app.founder_id}")
    assert page.status_code == 200
    assert f">{FOUNDER_PROMPT}</textarea>" in page.text
    assert "a founder is never retired" in page.text
    assert "/retire" not in page.text


def test_an_edit_admits_a_new_genome_and_leaves_its_source_untouched(
    owner_app: OwnerApp,
) -> None:
    owner_app.sign_in()
    source = f"/agents/{owner_app.founder_id}"
    source_page = owner_app.client.get(source).text
    token = owner_app.csrf(source)

    response = owner_app.client.post(
        f"{source}/admit", data=edit_form(owner_app, token, prompt="rewritten prompt")
    )
    assert response.status_code == 303
    child = owner_app.client.get(response.headers["location"])
    assert "rewritten prompt" in child.text
    assert f"edit admission from {owner_app.founder_id}" in child.text
    assert str(OWNER_ID) in child.text

    assert owner_app.client.get(source).text == source_page


def test_an_edit_with_a_bad_csrf_token_is_refused_and_stores_nothing(
    owner_app: OwnerApp,
) -> None:
    owner_app.sign_in()
    response = owner_app.client.post(
        f"/agents/{owner_app.founder_id}/admit",
        data=edit_form(owner_app, "forged", prompt="rewritten prompt"),
    )
    assert response.status_code == 403
    assert owner_app.actions.retrospective() == ((), ())


def test_an_edit_changing_two_parts_is_refused_with_its_reason(
    owner_app: OwnerApp,
) -> None:
    owner_app.sign_in()
    source = f"/agents/{owner_app.founder_id}"
    token = owner_app.csrf(source)
    response = owner_app.client.post(
        f"{source}/admit",
        data=edit_form(owner_app, token, prompt="one", scan_policy="two"),
    )
    assert (response.status_code, response.json()["detail"]) == (409, "invalid_edit")


def test_an_edit_is_refused_until_a_weekly_cycle_has_been_recorded(
    postgres_dsn: str, artifact_root: Path
) -> None:
    app = build_owner_app(
        postgres_dsn, artifact_root, members=POPULATION_FLOOR, cycles=None
    )
    app.sign_in()
    source = f"/agents/{app.founder_id}"
    response = app.client.post(
        f"{source}/admit", data=edit_form(app, app.csrf(source), prompt="new")
    )
    assert (response.status_code, response.json()["detail"]) == (409, "cycle_disabled")


def test_a_retirement_is_recorded_and_shown_in_the_history_and_retrospective(
    owner_app: OwnerApp,
) -> None:
    owner_app.sign_in()
    target = f"/agents/{owner_app.member_ids[0]}"
    response = owner_app.client.post(
        f"{target}/retire", data={"csrf_token": owner_app.csrf(target)}
    )
    assert response.status_code == 303

    page = owner_app.client.get(target)
    assert "retirement requested" in page.text
    assert "already requested for removal" in page.text
    retrospective = owner_app.client.get("/")
    assert str(owner_app.member_ids[0]) in retrospective.text


def test_a_retirement_crossing_the_population_floor_is_refused_with_its_reason(
    postgres_dsn: str, artifact_root: Path
) -> None:
    app = build_owner_app(postgres_dsn, artifact_root, members=POPULATION_FLOOR - 1)
    app.sign_in()
    target = f"/agents/{app.member_ids[0]}"
    response = app.client.post(
        f"{target}/retire", data={"csrf_token": app.csrf(target)}
    )
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "population_floor",
    )


def test_a_seeded_variant_is_admitted_from_a_copied_form(owner_app: OwnerApp) -> None:
    owner_app.sign_in()
    path = f"/seed?template={owner_app.founder_id}"
    form_page = owner_app.client.get(path)
    assert f">{FOUNDER_PROMPT}</textarea>" in form_page.text

    response = owner_app.client.post(
        "/seed",
        data={
            "csrf_token": owner_app.csrf(path),
            "island": "quant-ph",
            "lineage_id": "owner-seed",
            "template_configuration_id": str(owner_app.founder_id),
            "prompt": "a seeded prompt",
            "scan_policy": "scan",
            "read_policy": "read",
            "probability_assignment_rule": "one sample",
        },
    )
    assert response.status_code == 303
    page = owner_app.client.get(response.headers["location"])
    assert "seed admission" in page.text and str(OWNER_ID) in page.text


def seed_form(app: OwnerApp, **overrides: str) -> dict[str, str]:
    form = {
        "csrf_token": app.csrf("/seed"),
        "island": "quant-ph",
        "lineage_id": "owner-seed",
        "template_configuration_id": str(app.founder_id),
        "prompt": "a seeded prompt",
        "scan_policy": "scan",
        "read_policy": "read",
        "probability_assignment_rule": "one sample",
    }
    form.update(overrides)
    return form


def test_a_seed_is_refused_while_the_budget_is_not_funded(
    postgres_dsn: str, artifact_root: Path
) -> None:
    app = build_owner_app(
        postgres_dsn, artifact_root, members=POPULATION_FLOOR, funded=False
    )
    app.sign_in()
    response = app.client.post("/seed", data=seed_form(app))
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "budget_not_funded",
    )


def test_a_seed_naming_an_unknown_island_is_refused(owner_app: OwnerApp) -> None:
    owner_app.sign_in()
    response = owner_app.client.post("/seed", data=seed_form(owner_app, island="astro"))
    assert response.status_code == 422


def test_an_unrated_digest_entry_never_appears_on_an_action_page(
    owner_app: OwnerApp, stored_digest_entry_id: UUID
) -> None:
    owner_app.sign_in()
    pages = [
        owner_app.client.get("/"),
        owner_app.client.get(f"/agents/{owner_app.founder_id}"),
        owner_app.client.get(f"/seed?template={owner_app.founder_id}"),
    ]
    for page in pages:
        assert page.status_code == 200
        assert str(stored_digest_entry_id) not in page.text
        assert "digest" not in page.text.lower()
        assert "nominat" not in page.text.lower()
