"""The rating app's /api/v1 twins: blinded digest, session and idempotent rating (#249)."""

from __future__ import annotations

from uuid import uuid4

import httpx
import psycopg
import pytest
from starlette.testclient import TestClient
from tests.web.api_contract import (
    WEB_DIR,
    check,
    check_refusal,
    html_fields_missing_from,
)
from tests.web import test_private_rater_access as rater_access

from research_agent.storage.client import StorageClient
from research_agent.web.app import RatingAppConfig, create_app
from research_agent.web.auth import RaterDirectory
from research_agent.web.digest import default_fixture

pytestmark = pytest.mark.integration

# The rating app over real storage with two provisioned raters.
storage_server = rater_access.storage_server
storage_client = rater_access.storage_client
_provisioned_raters = rater_access._provisioned_raters
rater_directory = rater_access.rater_directory
rating_app_client = rater_access.rating_app_client
RATER_ONE_CREDENTIAL = rater_access.RATER_ONE_CREDENTIAL

TEMPLATES = WEB_DIR / "templates"
ENTRY = "22222222-2222-4222-8222-222222222222"
#: What a rater may never see on an entry before rating it (SR-21, SR-22, SR-25).
WITHHELD = {
    "origin",
    "genome_hash",
    "nominations",
    "service_source",
    "probability",
    "rationale",
    "popularity_count",
    "jev",
    "reading",
}


def sign_in(client: TestClient) -> str:
    response = client.post("/api/v1/login", json={"credential": RATER_ONE_CREDENTIAL})
    data = check(response, "rating", "POST", "/api/v1/login")
    assert "rater_session" in response.cookies
    token = data["csrf_token"]
    assert isinstance(token, str)
    return token


def rate(
    client: TestClient, token: str, key: str, *, value: str = "like"
) -> httpx.Response:
    return client.post(
        "/api/v1/ratings",
        json={
            "digest_entry_id": ENTRY,
            "paper_hash": paper_hash(client),
            "value": value,
        },
        headers={"X-CSRF-Token": token, "Idempotency-Key": key},
    )


def paper_hash(client: TestClient) -> str:
    rows = client.get("/api/v1/digest").json()["data"]["rows"]["items"]
    return str(
        next(row["paper_hash"] for row in rows if row["digest_entry_id"] == ENTRY)
    )


def test_the_login_view_carries_the_page_fields(rating_app_client: TestClient) -> None:
    data = check(
        rating_app_client.get("/api/v1/login"), "rating", "GET", "/api/v1/login"
    )
    # The form's pre-login token guards the browser POST; the JSON login has none.
    assert (
        html_fields_missing_from(
            TEMPLATES / "login.html", data, page_only=frozenset({"csrf_token"})
        )
        == []
    )


def test_a_wrong_credential_is_refused_and_opens_no_session(
    rating_app_client: TestClient,
) -> None:
    response = rating_app_client.post("/api/v1/login", json={"credential": "wrong"})
    check_refusal(response, 401, "unauthenticated")
    assert "rater_session" not in response.cookies
    check_refusal(rating_app_client.get("/api/v1/digest"), 401, "unauthenticated")


def test_the_digest_is_blinded_and_carries_every_field_the_page_shows(
    rating_app_client: TestClient,
) -> None:
    sign_in(rating_app_client)
    data = check(
        rating_app_client.get("/api/v1/digest"), "rating", "GET", "/api/v1/digest"
    )
    # Saved ratings are the JSON twin's separate read, GET /api/v1/ratings.
    assert (
        html_fields_missing_from(
            TEMPLATES / "digest.html", data, page_only=frozenset({"saved_ratings"})
        )
        == []
    )
    html = rating_app_client.get("/").text
    for row in data["rows"]["items"]:
        assert not WITHHELD & set(row)
        assert row["digest_entry_id"] in html
    assert data["rows"]["next_cursor"] is None


def test_one_idempotency_key_records_once_and_a_second_rating_conflicts(
    rating_app_client: TestClient, postgres_dsn: str
) -> None:
    token = sign_in(rating_app_client)
    key = str(uuid4())
    first = rate(rating_app_client, token, key)
    recorded = check(first, "rating", "POST", "/api/v1/ratings")
    again = rate(rating_app_client, token, key)
    assert again.status_code == 201
    assert again.json()["data"] == recorded
    assert again.headers["X-Replayed"] == "true"
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        count = connection.execute(
            "SELECT count(*) FROM ratings WHERE digest_entry_id=%s", (ENTRY,)
        ).fetchone()
    assert count == (1,)

    conflict = rate(rating_app_client, token, str(uuid4()), value="dislike")
    error = check_refusal(conflict, 409, "state_conflict")
    assert error["message"] == "already rated"


def test_a_retry_after_a_restart_is_replayed_by_storage_not_recorded_again(
    rating_app_client: TestClient,
    storage_client: StorageClient,
    rater_directory: RaterDirectory,
) -> None:
    key = str(uuid4())
    recorded = check(
        rate(rating_app_client, sign_in(rating_app_client), key),
        "rating",
        "POST",
        "/api/v1/ratings",
    )
    restarted = TestClient(
        create_app(
            RatingAppConfig(
                storage=storage_client,
                directory=rater_directory,
                digest=default_fixture(),
                public_origin="https://testserver",
            )
        ),
        base_url="https://testserver",
        headers={"Origin": "https://testserver"},
    )
    retry = rate(restarted, sign_in(restarted), key)
    assert check(retry, "rating", "POST", "/api/v1/ratings") == recorded
    assert "X-Replayed" not in retry.headers


def test_a_rating_without_its_headers_or_with_a_stray_field_is_refused(
    rating_app_client: TestClient,
) -> None:
    token = sign_in(rating_app_client)
    body = {"digest_entry_id": ENTRY, "paper_hash": "a" * 64, "value": "like"}
    missing_token = rating_app_client.post(
        "/api/v1/ratings", json=body, headers={"Idempotency-Key": "k"}
    )
    assert check_refusal(missing_token, 403, "forbidden")["field"] == "X-CSRF-Token"
    forged = rating_app_client.post(
        "/api/v1/ratings",
        json=body,
        headers={"X-CSRF-Token": "forged", "Idempotency-Key": "k"},
    )
    assert check_refusal(forged, 403, "forbidden")["field"] == "X-CSRF-Token"
    missing_key = rating_app_client.post(
        "/api/v1/ratings", json=body, headers={"X-CSRF-Token": token}
    )
    assert check_refusal(missing_key, 400, "invalid_request")["field"] == (
        "Idempotency-Key"
    )
    stray = rating_app_client.post(
        "/api/v1/ratings",
        json={**body, "rater_id": str(uuid4())},
        headers={"X-CSRF-Token": token, "Idempotency-Key": "k"},
    )
    assert check_refusal(stray, 422, "invalid_request")["field"] == "rater_id"


def test_logout_needs_the_session_token_then_revokes_the_session(
    rating_app_client: TestClient,
) -> None:
    token = sign_in(rating_app_client)
    forged = rating_app_client.post(
        "/api/v1/logout",
        json={},
        headers={"X-CSRF-Token": "forged", "Idempotency-Key": str(uuid4())},
    )
    assert check_refusal(forged, 403, "forbidden")["field"] == "X-CSRF-Token"
    check(rating_app_client.get("/api/v1/digest"), "rating", "GET", "/api/v1/digest")

    ended = check(
        rating_app_client.post(
            "/api/v1/logout",
            json={},
            headers={"X-CSRF-Token": token, "Idempotency-Key": str(uuid4())},
        ),
        "rating",
        "POST",
        "/api/v1/logout",
    )
    assert ended == {"authenticated": False}
    check_refusal(rating_app_client.get("/api/v1/digest"), 401, "unauthenticated")
