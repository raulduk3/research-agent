"""Real-storage and real-app fixtures shared by the rating app's web tests."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "storage"))

from test_digests import entry, identity, store_payload  # noqa: E402
from test_http import Jobs, _tls_material, server  # noqa: E402

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.storage.client import StorageClient
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.ratings import RatingRepository
from research_agent.storage.raters import RaterRepository
from research_agent.web.app import RatingAppConfig, create_app
from research_agent.web.auth import RaterDirectory, hash_credential
from research_agent.web.digest import default_fixture

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
RATER_ONE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
RATER_TWO_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
RATER_ONE_CREDENTIAL = "correct-horse-battery-staple-one"
RATER_TWO_CREDENTIAL = "correct-horse-battery-staple-two"


RATING_APP_SCOPES = frozenset({"ratings:record", "raters:read"})


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
def stored_digest_entry(_digests: DigestRepository) -> tuple[UUID, str, str]:
    """A digest entry backed by a real digest with its exact paper and batch."""

    entry_id = uuid4()
    paper_hash = "a" * 64
    payload = store_payload(entries=(entry(entry_id, paper_hash=paper_hash),))
    _digests.execute("store", identity=identity(), payload=payload)
    return entry_id, paper_hash, payload["batch_id"]


@pytest.fixture
def stored_digest_entry_id(stored_digest_entry: tuple[UUID, str, str]) -> UUID:
    """The id alone, for tests that need only a real stored digest entry."""

    return stored_digest_entry[0]


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
    raters = RaterRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    for rater_id, island, credential in (
        (RATER_ONE_ID, "cs", RATER_ONE_CREDENTIAL),
        (RATER_TWO_ID, "quant_ph", RATER_TWO_CREDENTIAL),
    ):
        salt, credential_hash = hash_credential(credential)
        raters.execute(
            "provision",
            identity=identity(),
            payload={
                "rater_id": str(rater_id),
                "island": island,
                "salt": salt,
                "credential_hash": credential_hash,
            },
        )
    tls = _tls_material(tmp_path)
    with server(
        Jobs(),
        tls,
        role="rating_app",
        extra_scopes=RATING_APP_SCOPES,
        ratings=ratings,
        raters=raters,
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
def rater_directory(storage_client: StorageClient) -> RaterDirectory:
    return RaterDirectory(storage_client)


@pytest.fixture
def rating_app_client(
    storage_client: StorageClient, rater_directory: RaterDirectory
) -> TestClient:
    app = create_app(
        RatingAppConfig(
            storage=storage_client,
            directory=rater_directory,
            digest=default_fixture(),
            public_origin="https://testserver",
        )
    )
    return TestClient(app, base_url="https://testserver")
