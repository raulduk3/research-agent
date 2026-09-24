"""The owner commands' /api/v1 twins: CSRF header, idempotency and refusals (#249)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from tests.web import test_owner_actions_app as actions
from tests.web.api_contract import (
    WEB_DIR,
    check,
    check_refusal,
    html_fields_missing_from,
)

pytestmark = pytest.mark.integration

# Owns the storage services build_owner_app starts for each test.
storage_service = actions.storage_service


@pytest.fixture
def owner_app(postgres_dsn: str, artifact_root: Path) -> actions.OwnerApp:
    return actions.build_owner_app(
        postgres_dsn, artifact_root, members=actions.POPULATION_FLOOR
    )


def sign_in(app: actions.OwnerApp) -> str:
    response = app.client.post("/api/v1/login", json={"credential": actions.CREDENTIAL})
    token = check(response, "actions", "POST", "/api/v1/login")["csrf_token"]
    assert isinstance(token, str)
    return token


def post(
    app: actions.OwnerApp,
    path: str,
    body: dict[str, str],
    *,
    token: str,
    key: str | None = None,
) -> httpx.Response:
    headers = {"X-CSRF-Token": token, "Idempotency-Key": key or str(uuid4())}
    return app.client.post(path, json=body, headers=headers)


def test_an_edit_is_admitted_once_per_key_and_shown_in_the_retrospective(
    owner_app: actions.OwnerApp,
) -> None:
    token = sign_in(owner_app)
    path = f"/api/v1/agents/{owner_app.founder_id}/admit"
    body = {"lineage_id": "owner-edit", "prompt": "rewritten prompt"}
    key = str(uuid4())
    admitted = check(
        post(owner_app, path, body, token=token, key=key),
        "actions",
        "POST",
        "/api/v1/agents/{configuration_id}/admit",
    )
    again = post(owner_app, path, body, token=token, key=key)
    assert (again.status_code, again.json()["data"]) == (201, admitted)
    assert again.headers["X-Replayed"] == "true"

    retrospective = check(
        owner_app.client.get("/api/v1/retrospective"),
        "actions",
        "GET",
        "/api/v1/retrospective",
    )
    template = WEB_DIR / "actions" / "templates" / "retrospective.html"
    assert html_fields_missing_from(template, retrospective) == []
    assert [
        row["configuration_id"] for row in retrospective["admissions"]["items"]
    ] == [admitted["configuration_id"]]

    other = post(owner_app, path, {"lineage_id": "other"}, token=token, key=key)
    assert check_refusal(other, 409, "state_conflict")["field"] == "Idempotency-Key"


def test_an_edit_with_a_forged_token_stores_nothing(
    owner_app: actions.OwnerApp,
) -> None:
    sign_in(owner_app)
    forged = post(
        owner_app,
        f"/api/v1/agents/{owner_app.founder_id}/admit",
        {"lineage_id": "owner-edit", "prompt": "rewritten prompt"},
        token="forged",
    )
    assert check_refusal(forged, 403, "forbidden")["field"] == "X-CSRF-Token"
    assert owner_app.actions.retrospective() == ((), ())


def test_a_refused_edit_names_its_reason(owner_app: actions.OwnerApp) -> None:
    token = sign_in(owner_app)
    refused = post(
        owner_app,
        f"/api/v1/agents/{owner_app.founder_id}/admit",
        {"lineage_id": "owner-edit", "prompt": "one", "scan_policy": "two"},
        token=token,
    )
    assert check_refusal(refused, 409, "state_conflict")["message"] == "invalid_edit"
    stray = post(
        owner_app,
        f"/api/v1/agents/{owner_app.founder_id}/admit",
        {"lineage_id": "owner-edit", "owner_id": str(uuid4())},
        token=token,
    )
    assert check_refusal(stray, 422, "invalid_request")["field"] == "owner_id"


def test_a_retirement_is_recorded_and_a_second_one_conflicts(
    owner_app: actions.OwnerApp,
) -> None:
    token = sign_in(owner_app)
    path = f"/api/v1/agents/{owner_app.member_ids[0]}/retire"
    retired = check(
        post(owner_app, path, {}, token=token),
        "actions",
        "POST",
        "/api/v1/agents/{configuration_id}/retire",
    )
    assert retired == {"configuration_id": str(owner_app.member_ids[0])}
    again = post(owner_app, path, {}, token=token)
    assert check_refusal(again, 409, "state_conflict")["message"] == "already_retired"
    missing_key = owner_app.client.post(path, headers={"X-CSRF-Token": token})
    assert check_refusal(missing_key, 400, "invalid_request")["field"] == (
        "Idempotency-Key"
    )


def test_a_seed_is_admitted_and_an_unknown_island_is_refused(
    owner_app: actions.OwnerApp,
) -> None:
    token = sign_in(owner_app)
    body = {
        "island": "quant-ph",
        "lineage_id": "owner-seed",
        "template_configuration_id": str(owner_app.founder_id),
        "prompt": "a seeded prompt",
        "scan_policy": "scan",
        "read_policy": "read",
        "probability_assignment_rule": "one sample",
    }
    seeded = check(
        post(owner_app, "/api/v1/seed", body, token=token),
        "actions",
        "POST",
        "/api/v1/seed",
    )
    agent = check(
        owner_app.client.get(f"/api/v1/agents/{seeded['configuration_id']}"),
        "actions",
        "GET",
        "/api/v1/agents/{configuration_id}",
    )
    assert agent["admission"]["kind"] == "seed"
    refused = post(owner_app, "/api/v1/seed", {**body, "island": "astro"}, token=token)
    check_refusal(refused, 422, "invalid_request")
    missing = post(owner_app, "/api/v1/seed", {"island": "cs"}, token=token)
    check_refusal(missing, 422, "invalid_request")


def test_logout_revokes_the_session(owner_app: actions.OwnerApp) -> None:
    token = sign_in(owner_app)
    ended = check(
        post(owner_app, "/api/v1/logout", {}, token=token),
        "actions",
        "POST",
        "/api/v1/logout",
    )
    assert ended == {"authenticated": False}
    check_refusal(owner_app.client.get("/api/v1/retrospective"), 401, "unauthenticated")
