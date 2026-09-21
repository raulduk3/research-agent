from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from psycopg.errors import CheckViolation
from psycopg.errors import ObjectNotInPrerequisiteState

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ArtifactRef, ProducerVersion, canonical_loads
from research_agent.storage.artifacts import ArtifactPublication, ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import (
    IdempotencyConflict,
    IntegrityFailure,
    UnavailableInput,
)
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.verification import ArtifactVerifier

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion(
    image_digest="a" * 64, source_commit="b" * 40, contract_version=1
)


def _identity(
    *, key: UUID | None = None, command: UUID | None = None
) -> CommandIdentity:
    return CommandIdentity(uuid4(), key or uuid4(), command or uuid4(), uuid4())


def _publish_command(
    repository: ArtifactRepository,
    payload: bytes,
    identity: CommandIdentity,
    *,
    inputs: tuple[str, ...] = (),
) -> StoredResponse:
    return repository.publish_command(
        [payload],
        identity=identity,
        expected_hash=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=inputs,
        producer_version=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        source_available_at=None,
    )


def _publish(
    repository: ArtifactRepository,
    payload: bytes,
    *,
    inputs: tuple[str, ...] = (),
    kind: str = "manifest",
    producer: ProducerVersion = PRODUCER,
    config_hash: str = "c" * 64,
    retention_policy_hash: str = "d" * 64,
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
        producer_version=producer,
        config_hash=config_hash,
        retention_policy_hash=retention_policy_hash,
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
    assert derived.receipt.artifact_id == derived.manifest_hash
    with database.connect() as connection:
        edge = connection.execute(
            """
            SELECT encode(input_hash, 'hex') FROM artifact_production_edges
            WHERE manifest_hash = decode(%s, 'hex')
            """,
            (derived.manifest_hash,),
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
            1, derived.manifest_hash
        )
    with ArtifactStore(artifact_root).open_verified(
        derived.manifest_hash
    ) as manifest_stream:
        manifest = canonical_loads(manifest_stream.read())
    assert isinstance(manifest, dict)
    assert manifest["artifact_hash"] == derived.artifact_hash
    assert manifest["input_hashes"] == [source.artifact_hash]
    assert manifest["producer_version"] == {
        "contract_version": 1,
        "image_digest": "a" * 64,
        "source_commit": "b" * 40,
    }
    assert receipt_count is not None and receipt_count[0] == 3
    (metadata, stream) = repository.read(derived.artifact_hash)
    with stream:
        assert metadata == (len(b'{"derived":1}'), "application/json")
        assert stream.read() == b'{"derived":1}'

    independent = _publish(repository, b'{"derived":1}', inputs=())
    assert independent.artifact_hash == derived.artifact_hash
    assert independent.manifest_hash != derived.manifest_hash


def test_concurrent_identical_publication_reuses_bytes_with_distinct_manifests(
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
    assert len({item.manifest_hash for item in publications}) == 2
    assert {item.ledger.sequence for item in publications} == {1, 2}
    assert sum(item.blob_created for item in publications) == 1


def test_identical_bytes_allow_distinct_producing_provenance(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    repository = ArtifactRepository(database, ArtifactStore(artifact_root))
    payload = b'{"same-bytes":true}'
    first = _publish(repository, payload)
    second = _publish(
        repository,
        payload,
        producer=ProducerVersion(
            image_digest="e" * 64,
            source_commit="f" * 40,
            contract_version=1,
        ),
        config_hash="1" * 64,
        retention_policy_hash="2" * 64,
    )

    assert first.artifact_hash == second.artifact_hash
    assert first.manifest_hash != second.manifest_hash
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT encode(manifest_hash, 'hex'), encode(config_hash, 'hex'),
                   encode(retention_policy_hash, 'hex')
            FROM artifact_productions
            WHERE artifact_hash = decode(%s, 'hex')
            ORDER BY created_at, manifest_hash
            """,
            (first.artifact_hash,),
        ).fetchall()
    assert len(rows) == 2
    assert {str(row[0]) for row in rows} == {
        first.manifest_hash,
        second.manifest_hash,
    }
    assert {str(row[1]) for row in rows} == {"c" * 64, "1" * 64}
    assert {str(row[2]) for row in rows} == {"d" * 64, "2" * 64}


def test_verifier_resolves_exact_production_and_complete_dag(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    repository = ArtifactRepository(database, store)
    source = _publish(repository, b'{"source-production":1}')
    derived = _publish(
        repository,
        b'{"derived-production":1}',
        inputs=(source.manifest_hash,),
        config_hash="1" * 64,
    )

    with database.connect() as connection:
        verified = ArtifactVerifier(store).verify(connection, derived.manifest_hash)

    assert verified.raw_hash == derived.artifact_hash
    assert verified.config_hash == "1" * 64
    assert verified.input_hashes == (source.manifest_hash,)
    assert verified.kind == "manifest"


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
    with pytest.raises(ObjectNotInPrerequisiteState):
        with database.connect() as connection:
            connection.execute(
                "UPDATE artifact_productions SET created_at = clock_timestamp() "
                "WHERE manifest_hash = decode(%s, 'hex')",
                (publication.manifest_hash,),
            )


def test_publish_command_replays_original_response_after_lost_response(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    repository = ArtifactRepository(database, ArtifactStore(artifact_root))
    identity = _identity()

    first = _publish_command(repository, b'{"command":1}', identity)
    replay = _publish_command(repository, b'{"command":1}', identity)
    existing = _publish_command(repository, b'{"command":1}', _identity())

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.status_code == first.status_code
    assert replay.body == first.body
    assert first.status_code == replay.status_code == 201
    assert existing.status_code == 200
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM ledger_records").fetchone() == (
            2,
        )
        assert connection.execute(
            "SELECT count(*) FROM artifact_productions"
        ).fetchone() == (2,)


def test_publish_command_conflict_and_failed_mutation_rollback_identity(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    repository = ArtifactRepository(database, ArtifactStore(artifact_root))
    identity = _identity()
    _publish_command(repository, b'{"first":1}', identity)
    with pytest.raises(IdempotencyConflict):
        _publish_command(repository, b'{"changed":1}', identity)

    retryable_identity = _identity()
    with pytest.raises(UnavailableInput):
        _publish_command(
            repository,
            b'{"missing-input":1}',
            retryable_identity,
            inputs=("e" * 64,),
        )
    recovered = _publish_command(repository, b'{"recovered":1}', retryable_identity)
    assert recovered.replayed is False


def test_concurrent_same_publish_command_commits_once(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    repository = ArtifactRepository(database, ArtifactStore(artifact_root))
    identity = _identity()
    barrier = Barrier(2)

    def publish(_: int) -> StoredResponse:
        barrier.wait()
        return _publish_command(repository, b'{"concurrent-command":1}', identity)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, range(2)))

    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].body == results[1].body
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM ledger_records").fetchone() == (
            1,
        )


def test_publish_command_revalidates_uploaded_bytes_and_refuses_unowned_source_time(
    postgres_dsn: str, artifact_root: Path
) -> None:
    repository = ArtifactRepository(
        Database(postgres_dsn), ArtifactStore(artifact_root)
    )
    payload = b'{"existing":1}'
    _publish_command(repository, payload, _identity())
    with pytest.raises(IntegrityFailure, match="bytes do not match declaration"):
        repository.publish_command(
            [b'{"changed!":1}'],
            identity=_identity(),
            expected_hash=hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
            maximum_length=1024,
            media_type="application/json",
            kind="manifest",
            input_hashes=(),
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            source_available_at=None,
        )
    with pytest.raises(IntegrityFailure, match="capture-evidence validation"):
        repository.publish_command(
            [payload],
            identity=_identity(),
            expected_hash=hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
            maximum_length=1024,
            media_type="application/json",
            kind="source_response",
            input_hashes=(),
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            source_available_at="2026-09-21T00:00:00.000000Z",
        )
