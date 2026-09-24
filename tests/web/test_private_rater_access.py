from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from starlette.testclient import TestClient


from tests.storage.test_http import Authorization, Jobs, _tls_material  # noqa: E402

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.storage.client import StorageClient
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.preference import PreferenceRepository
from research_agent.storage.ratings import RatingRepository
from research_agent.storage.raters import RaterRepository
from research_agent.web.app import RatingAppConfig, create_app
from research_agent.web.auth import (
    AuthenticationError,
    RaterDirectory,
    RaterPrincipal,
    SessionStore,
    authenticate_session,
    authorize_island,
    hash_credential,
    verify_csrf,
)
from research_agent.web.digest import default_fixture, fixture_store_payload

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
RATER_ONE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
RATER_TWO_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
RATER_ONE_CREDENTIAL = "correct-horse-battery-staple-one"
RATER_TWO_CREDENTIAL = "correct-horse-battery-staple-two"
RATING_APP_SCOPES = frozenset({"ratings:record", "raters:read"})
OPERATOR_SCOPES = frozenset({"raters:provision"})


def test_a_rater_principal_refuses_an_unadmitted_island() -> None:
    salt, digest = hash_credential("a")
    with pytest.raises(ValueError, match="island"):
        RaterPrincipal(
            rater_id=RATER_ONE_ID, island="q_bio", salt=salt, credential_hash=digest
        )


def test_authorize_island_refuses_a_rater_bound_to_another_island() -> None:
    salt, digest = hash_credential("a")
    principal = RaterPrincipal(
        rater_id=RATER_ONE_ID, island="cs", salt=salt, credential_hash=digest
    )
    with pytest.raises(AuthenticationError):
        authorize_island(principal, "quant_ph")
    authorize_island(principal, "cs")


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


@pytest.fixture
def storage_server(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> Iterator[tuple[tuple[str, int], Path]]:
    """A real storage server with a rating_app identity and an operator identity.

    The operator identity provisions the two rater principals through storage
    (PL-22); it is never wired into the rating app itself, matching the
    operator-only route no rater or browser can reach.
    """
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    ratings = RatingRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    raters = RaterRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    digests = DigestRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    preference = PreferenceRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    digests.execute(
        "store",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload=fixture_store_payload(),
    )
    (
        server_context,
        _client_context,
        fingerprint,
        _wrong_context,
        wrong_fingerprint,
        _no_certificate_context,
    ) = _tls_material(tmp_path)
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {
            fingerprint: ServiceCapability(uuid4(), "rating_app", RATING_APP_SCOPES),
            wrong_fingerprint: ServiceCapability(uuid4(), "operator", OPERATOR_SCOPES),
        },
        tls_context=server_context,
        authorization=Authorization(),
        ratings=ratings,
        raters=raters,
        preference=preference,
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        host, port = httpd.server_address[:2]
        yield (str(host), int(port)), tmp_path
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


@pytest.fixture
def storage_client(storage_server: tuple[tuple[str, int], Path]) -> StorageClient:
    address, tmp_path = storage_server
    return StorageClient(
        connect_host=address[0],
        port=address[1],
        server_hostname="localhost",
        ca_file=tmp_path / "ca.pem",
        client_cert_file=tmp_path / "client.pem",
        client_key_file=tmp_path / "client.key",
        scopes=RATING_APP_SCOPES,
        timeout_seconds=5,
    )


@pytest.fixture
def _provisioned_raters(
    storage_server: tuple[tuple[str, int], Path],
) -> None:
    address, tmp_path = storage_server
    operator = StorageClient(
        connect_host=address[0],
        port=address[1],
        server_hostname="localhost",
        ca_file=tmp_path / "ca.pem",
        client_cert_file=tmp_path / "wrong.pem",
        client_key_file=tmp_path / "wrong.key",
        scopes=OPERATOR_SCOPES,
        timeout_seconds=5,
    )
    one_salt, one_hash = hash_credential(RATER_ONE_CREDENTIAL)
    two_salt, two_hash = hash_credential(RATER_TWO_CREDENTIAL)
    operator.provision_rater(
        rater_id=RATER_ONE_ID,
        island="cs",
        salt=one_salt,
        credential_hash=one_hash,
        command_id=uuid4(),
        request_id=uuid4(),
        idempotency_key=uuid4(),
    )
    operator.provision_rater(
        rater_id=RATER_TWO_ID,
        island="quant_ph",
        salt=two_salt,
        credential_hash=two_hash,
        command_id=uuid4(),
        request_id=uuid4(),
        idempotency_key=uuid4(),
    )


@pytest.fixture
def rater_directory(
    storage_client: StorageClient, _provisioned_raters: None
) -> RaterDirectory:
    return RaterDirectory(storage_client)


@pytest.fixture
def rating_app_client(
    storage_client: StorageClient, rater_directory: RaterDirectory
) -> TestClient:
    app = create_app(
        RatingAppConfig(
            storage=storage_client, directory=rater_directory, digest=default_fixture()
        )
    )
    return TestClient(app, base_url="https://testserver")


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
def test_both_provisioned_raters_authenticate_to_their_own_island(
    rating_app_client: TestClient, storage_client: StorageClient
) -> None:
    principals = {record.island: record for record in storage_client.list_raters()}
    assert principals["cs"].rater_id == RATER_ONE_ID
    assert principals["quant_ph"].rater_id == RATER_TWO_ID

    login_two = rating_app_client.post(
        "/login", data={"credential": RATER_TWO_CREDENTIAL}, follow_redirects=False
    )
    assert login_two.status_code == 303


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
