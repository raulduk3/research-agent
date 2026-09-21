from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation
from psycopg.errors import ObjectNotInPrerequisiteState

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ArtifactRef, ProducerVersion
from research_agent.storage.artifacts import ArtifactPublication, ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.errors import IntegrityFailure, UnavailableInput

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion(
    image_digest="a" * 64, source_commit="b" * 40, contract_version=1
)


def _publish(
    repository: ArtifactRepository,
    payload: bytes,
    *,
    inputs: tuple[str, ...] = (),
    kind: str = "manifest",
) -> ArtifactPublication:
    identity = hashlib.sha256(payload).hexdigest()
    return repository.publish(
        [payload],
        expected_hash=identity,
        byte_length=len(payload),
        maximum_length=1024,
        media_type="application/json",
        kind=kind,
        input_hashes=inputs,
        producer_version=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )


def test_publication_commits_blob_dependencies_and_ledger_atomically(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    repository = ArtifactRepository(database, ArtifactStore(artifact_root))
    source = _publish(repository, b'{"source":1}')
    derived = _publish(repository, b'{"derived":1}', inputs=(source.artifact_hash,))

    assert derived.ledger.sequence == source.ledger.sequence + 1
    assert derived.receipt.committed_ledger_sequence == derived.ledger.sequence
    assert derived.receipt.artifact_id == derived.artifact_hash
    with database.connect() as connection:
        edge = connection.execute(
            """
            SELECT encode(input_hash, 'hex') FROM artifact_edges
            WHERE output_hash = decode(%s, 'hex')
            """,
            (derived.artifact_hash,),
        ).fetchone()
        payload_row = connection.execute(
            "SELECT encode(payload_hash, 'hex') FROM ledger_records WHERE sequence = %s",
            (derived.ledger.sequence,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT count(*) FROM artifact_publication_receipts WHERE committed_ledger_sequence = %s",
            (derived.ledger.sequence,),
        ).fetchone()
    assert edge is not None and edge[0] == source.artifact_hash
    assert payload_row is not None
    payload_hash = str(payload_row[0])
    with ArtifactStore(artifact_root).open_verified(payload_hash) as payload_stream:
        assert ArtifactRef.from_json(payload_stream.read()) == ArtifactRef(
            1, derived.artifact_hash
        )
    assert receipt_count is not None and receipt_count[0] == 2
    (metadata, stream) = repository.read(derived.artifact_hash)
    with stream:
        assert metadata == (len(b'{"derived":1}'), "application/json")
        assert stream.read() == b'{"derived":1}'

    with pytest.raises(IntegrityFailure):
        _publish(repository, b'{"derived":1}', inputs=())


def test_concurrent_identical_publication_reuses_one_reference(
    postgres_dsn: str, artifact_root: Path
) -> None:
    repository = ArtifactRepository(
        Database(postgres_dsn), ArtifactStore(artifact_root)
    )
    barrier = Barrier(2)

    def publish(_: int) -> ArtifactPublication:
        barrier.wait()
        return _publish(repository, b'{"same":true}')

    with ThreadPoolExecutor(max_workers=2) as executor:
        publications = list(executor.map(publish, range(2)))

    assert {item.artifact_hash for item in publications} == {
        hashlib.sha256(b'{"same":true}').hexdigest()
    }
    assert {item.ledger.sequence for item in publications} == {1}


def test_missing_dependency_rejects_reference_but_leaves_reusable_orphan_blob(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    repository = ArtifactRepository(database, store)
    payload = b'{"orphan":true}'
    identity = hashlib.sha256(payload).hexdigest()

    with pytest.raises(UnavailableInput):
        _publish(repository, payload, inputs=("e" * 64,))

    assert store.path_for(identity).read_bytes() == payload
    with database.connect() as connection:
        row = connection.execute(
            "SELECT count(*) FROM artifacts WHERE hash = decode(%s, 'hex')",
            (identity,),
        ).fetchone()
        assert row is not None and row[0] == 0

    publication = _publish(repository, payload)
    assert publication.blob_created is False


def test_database_failure_occurs_after_blob_commit_without_partial_reference(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    repository = ArtifactRepository(database, store)
    payload = b"bytes first"
    identity = hashlib.sha256(payload).hexdigest()

    with pytest.raises(CheckViolation):
        _publish(repository, payload, kind="not-a-kind")

    assert store.path_for(identity).read_bytes() == payload
    with database.connect() as connection:
        row = connection.execute("SELECT count(*) FROM artifacts").fetchone()
        assert row is not None and row[0] == 0
        receipts = connection.execute(
            "SELECT count(*) FROM artifact_publication_receipts"
        ).fetchone()
        assert receipts is not None and receipts[0] == 0


def test_tombstone_and_publication_receipt_are_immutable(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    publication = _publish(
        ArtifactRepository(database, ArtifactStore(artifact_root)), b'{"retained":1}'
    )
    tombstone_id = uuid4()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO artifact_tombstones(id, artifact_hash, reason, policy_hash)
            VALUES (%s, decode(%s, 'hex'), 'policy', decode(%s, 'hex'))
            """,
            (tombstone_id, publication.artifact_hash, "f" * 64),
        )
    with pytest.raises(ObjectNotInPrerequisiteState):
        with database.connect() as connection:
            connection.execute(
                "DELETE FROM artifact_tombstones WHERE id = %s", (tombstone_id,)
            )
    with pytest.raises(ObjectNotInPrerequisiteState):
        with database.connect() as connection:
            connection.execute(
                "UPDATE artifact_publication_receipts SET published_at = clock_timestamp() "
                "WHERE artifact_hash = decode(%s, 'hex')",
                (publication.artifact_hash,),
            )
