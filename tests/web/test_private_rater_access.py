from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from starlette.testclient import TestClient

from research_agent.web.auth import (
    AuthenticationError,
    RaterDirectory,
    RaterPrincipal,
    SessionStore,
    authenticate_session,
    hash_credential,
    verify_csrf,
)

RATER_ONE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
RATER_TWO_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
RATER_ONE_CREDENTIAL = "correct-horse-battery-staple-one"


def test_exactly_two_rater_identities_may_be_provisioned() -> None:
    salt, digest = hash_credential("a")
    with pytest.raises(ValueError, match="exactly two"):
        RaterDirectory(
            (RaterPrincipal(rater_id=RATER_ONE_ID, salt=salt, credential_hash=digest),)
        )


def test_a_session_expires_after_its_lifetime() -> None:
    store = SessionStore()
    issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session = store.issue(RATER_ONE_ID, now=issued_at)

    still_valid = store.get(session.session_id, now=issued_at + timedelta(hours=23))
    assert still_valid is not None

    expired = store.get(session.session_id, now=issued_at + timedelta(hours=25))
    assert expired is None
    with pytest.raises(AuthenticationError):
        authenticate_session(
            store, session.session_id, now=issued_at + timedelta(hours=25)
        )


def test_csrf_verification_rejects_a_mismatched_or_missing_token() -> None:
    store = SessionStore()
    session = store.issue(RATER_ONE_ID)
    with pytest.raises(AuthenticationError):
        verify_csrf(session, "not-the-real-token")
    with pytest.raises(AuthenticationError):
        verify_csrf(session, None)
    verify_csrf(session, session.csrf_token)


@pytest.mark.integration
def test_an_unauthenticated_request_is_refused(rating_app_client: TestClient) -> None:
    response = rating_app_client.get("/", follow_redirects=False)
    assert response.status_code == 401


@pytest.mark.integration
def test_a_wrong_credential_is_refused_and_issues_no_session(
    rating_app_client: TestClient,
) -> None:
    response = rating_app_client.post(
        "/login", data={"credential": "not-a-real-credential"}
    )
    assert response.status_code == 401
    assert "rater_session" not in response.cookies


@pytest.mark.integration
def test_a_correct_credential_is_admitted_and_reaches_the_digest(
    rating_app_client: TestClient,
) -> None:
    login = rating_app_client.post(
        "/login", data={"credential": RATER_ONE_CREDENTIAL}, follow_redirects=False
    )
    assert login.status_code == 303
    assert "rater_session" in login.cookies

    root = rating_app_client.get("/")
    assert root.status_code == 200
    assert "digest_entry_id" in root.text


@pytest.mark.integration
def test_a_forged_csrf_token_is_refused(rating_app_client: TestClient) -> None:
    rating_app_client.post("/login", data={"credential": RATER_ONE_CREDENTIAL})

    response = rating_app_client.post(
        "/ratings",
        data={
            "digest_entry_id": str(uuid4()),
            "paper_hash": "a" * 64,
            "value": "like",
            "csrf_token": "a-forged-token",
        },
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_a_browser_supplied_rater_id_cannot_select_another_identity(
    rating_app_client: TestClient, postgres_dsn: str
) -> None:
    rating_app_client.post("/login", data={"credential": RATER_ONE_CREDENTIAL})
    csrf_token = _csrf_token(rating_app_client)
    digest_entry_id = "11111111-1111-4111-8111-111111111111"

    response = rating_app_client.post(
        "/ratings",
        data={
            "digest_entry_id": digest_entry_id,
            "paper_hash": "a" * 64,
            "value": "like",
            "csrf_token": csrf_token,
            "rater_id": str(RATER_TWO_ID),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        row = connection.execute(
            "SELECT rater_id FROM ratings WHERE digest_entry_id=%s", (digest_entry_id,)
        ).fetchone()
    assert row is not None
    assert row[0] == RATER_ONE_ID


def _csrf_token(client: TestClient) -> str:
    page = client.get("/").text
    marker = 'name="csrf_token" value="'
    start = page.index(marker) + len(marker)
    return page[start : page.index('"', start)]
