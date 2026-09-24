"""Real-storage and real-app fixtures shared by the rating app's web tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from starlette.testclient import TestClient


from tests.storage.test_digests import seed_single_entry_digest  # noqa: E402
from tests.storage.test_http import Jobs, _tls_material, server  # noqa: E402

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.storage.client import StorageClient
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.ratings import RatingRepository
from research_agent.web.app import RatingAppConfig, create_app
from research_agent.web.auth import RaterDirectory, RaterPrincipal, hash_credential
from research_agent.web.digest import default_fixture

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
RATER_ONE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
RATER_TWO_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
RATER_ONE_CREDENTIAL = "correct-horse-battery-staple-one"
RATER_TWO_CREDENTIAL = "correct-horse-battery-staple-two"


RATING_APP_SCOPES = frozenset({"ratings:record"})


@pytest.fixture
def _digests(postgres_dsn: str, artifact_root: Path) -> DigestRepository:
    return DigestRepository(
        Database(postgres_dsn),
        ArtifactStore(artifact_root),
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )


@pytest.fixture
def stored_digest_entry_id(_digests: DigestRepository) -> UUID:
    """A digest entry id backed by a real, minimal stored digest.

    Rating an arbitrary id would now be refused by the storage foreign key
    from ``ratings`` to ``digest_entries`` (#179); tests that only care about
    the rating path, not a digest's own content, seed through this instead.
    """

    return seed_single_entry_digest(_digests)


@pytest.fixture
def storage_server(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> Iterator[tuple[tuple[str, int], Path]]:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    ratings = RatingRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    tls = _tls_material(tmp_path)
    with server(
        Jobs(),
        tls,
        role="rating_app",
        extra_scopes=RATING_APP_SCOPES,
        ratings=ratings,
    ) as (address, _context, _wrong_context, _no_certificate_context):
        yield address, tmp_path


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
def forbidden_storage_client(
    storage_server: tuple[tuple[str, int], Path],
) -> StorageClient:
    """A client whose certificate is authenticated but never granted rating scopes."""
    address, tmp_path = storage_server
    return StorageClient(
        connect_host=address[0],
        port=address[1],
        server_hostname="localhost",
        ca_file=tmp_path / "ca.pem",
        client_cert_file=tmp_path / "wrong.pem",
        client_key_file=tmp_path / "wrong.key",
        scopes=frozenset({"ratings:record"}),
        timeout_seconds=5,
    )


@pytest.fixture
def rater_directory() -> RaterDirectory:
    one_salt, one_hash = hash_credential(RATER_ONE_CREDENTIAL)
    two_salt, two_hash = hash_credential(RATER_TWO_CREDENTIAL)
    return RaterDirectory(
        (
            RaterPrincipal(
                rater_id=RATER_ONE_ID, salt=one_salt, credential_hash=one_hash
            ),
            RaterPrincipal(
                rater_id=RATER_TWO_ID, salt=two_salt, credential_hash=two_hash
            ),
        )
    )


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
