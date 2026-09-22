from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.contracts.snapshots import snapshot_identity
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput
from research_agent.storage.snapshots import SnapshotRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class Storage:
    database: Database
    store: ArtifactStore
    artifacts: ArtifactRepository
    snapshots: SnapshotRepository

    def artifact(self, payload: bytes, inputs: tuple[str, ...] = ()) -> str:
        digest = sha256_hex(payload)
        publication = self.artifacts.publish(
            [payload],
            expected_hash=digest,
            byte_length=len(payload),
            maximum_length=1024 * 1024,
            media_type="application/json",
            kind="manifest",
            input_hashes=inputs,
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            command_id=uuid4(),
        )
        return publication.manifest_hash

    def seal(self, payload: object) -> dict[str, Any]:
        response = self.snapshots.execute("seal", identity=identity(), payload=payload)
        return dict(canonical_loads(response.body)["data"])


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> Storage:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    return Storage(
        database,
        store,
        ArtifactRepository(database, store),
        SnapshotRepository(
            database,
            store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
    )


def test_seal_is_content_addressed_and_idempotent(storage: Storage) -> None:
    paper_manifest = storage.artifact(b'{"papers":["p1"]}')
    index_hash = "e" * 64
    payload = {
        "paper_manifest_hash": paper_manifest,
        "index_identity_hashes": [index_hash],
    }
    first = storage.seal(payload)
    assert first["snapshot_hash"] == snapshot_identity(paper_manifest, [index_hash])
    second = storage.seal(payload)
    assert second["snapshot_hash"] == first["snapshot_hash"]
    assert second["sealed_at"] == first["sealed_at"]
    with storage.database.connect() as connection:
        count = connection.execute("SELECT count(*) FROM snapshots").fetchone()
        assert count is not None and count[0] == 1


def test_seal_rejects_an_unpublished_paper_manifest(storage: Storage) -> None:
    with pytest.raises(UnavailableInput):
        storage.seal(
            {"paper_manifest_hash": "f" * 64, "index_identity_hashes": ["a" * 64]}
        )


def test_a_later_snapshot_does_not_alter_an_earlier_ones_pinned_manifest(
    storage: Storage,
) -> None:
    early_manifest = storage.artifact(b'{"papers":["p1"]}')
    early = storage.seal(
        {"paper_manifest_hash": early_manifest, "index_identity_hashes": ["a" * 64]}
    )
    later_manifest = storage.artifact(b'{"papers":["p1","p2"]}')
    storage.seal(
        {"paper_manifest_hash": later_manifest, "index_identity_hashes": ["a" * 64]}
    )
    with storage.database.connect() as connection:
        row = connection.execute(
            "SELECT encode(paper_manifest_hash,'hex') FROM snapshots WHERE hash=decode(%s,'hex')",
            (early["snapshot_hash"],),
        ).fetchone()
    assert row is not None and row[0] == early_manifest
