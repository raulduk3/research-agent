from __future__ import annotations

import threading
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient, StorageClientError
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.ratings import RatingRepository
from research_agent.storage.raters import RaterRepository
from tests.storage.test_http import Jobs, _tls_material

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def _hash(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def identity() -> CommandIdentity:
    return CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4())


def repository(database: Database, store: ArtifactStore) -> DigestRepository:
    return DigestRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )


def entry(
    entry_id: UUID,
    *,
    origin: str = "population",
    position: int = 0,
    paper_hash: str | None = None,
    service_source: str | None = None,
    candidate_pool_hash: str | None = None,
    inclusion_probability: float | None = None,
) -> dict[str, Any]:
    if origin == "service" and service_source is None:
        service_source = "svc"
    if origin == "random_control":
        candidate_pool_hash = candidate_pool_hash or _hash("pool")
        if inclusion_probability is None:
            inclusion_probability = 0.5
    return {
        "entry_id": str(entry_id),
        "paper_hash": paper_hash or _hash(f"paper-{entry_id}"),
        "origin": origin,
        "display_position": position,
        "service_source": service_source,
        "candidate_pool_hash": candidate_pool_hash,
        "inclusion_probability": inclusion_probability,
    }


def store_payload(
    *,
    digest_hash: str | None = None,
    batch_id: str | None = None,
    island: str = "cs",
    entries: tuple[dict[str, Any], ...] | None = None,
    nominations: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    unique = uuid4().hex
    entries = entries if entries is not None else (entry(uuid4()),)
    return {
        "digest_hash": digest_hash or _hash(f"digest-{unique}"),
        "batch_id": batch_id or _hash(f"batch-{unique}"),
        "island": island,
        "source_watermark": 7,
        "shuffle_seed": "0011223344556677",
        "entries": list(entries),
        "nominations": list(nominations),
    }


def seed_single_entry_digest(
    digests: DigestRepository, *, entry_id: UUID | None = None
) -> UUID:
    """Store a minimal one-entry digest and return its entry id.

    Shared by tests that only need a real, FK-satisfying ``digest_entries``
    row to rate against, not a digest's own behavior.
    """

    entry_id = entry_id or uuid4()
    digests.execute(
        "store",
        identity=identity(),
        payload=store_payload(entries=(entry(entry_id),)),
    )
    return entry_id


def seed_submission(database: Database) -> UUID:
    """Seal a minimal sheet and submission so a nomination can cite one.

    Raw SQL, not the sheet/submission repositories: this test only needs a
    real ``submissions`` row to nominate against, not to exercise sealing.
    """

    sheet_hash, submission_id, question_id = (
        _hash(f"sheet-{uuid4()}"),
        uuid4(),
        uuid4(),
    )
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO sheets(hash, sealed_at) VALUES(decode(%s,'hex'), now())",
            (sheet_hash,),
        )
        connection.execute(
            """INSERT INTO submissions(
                   id, sheet_hash, submitter_id, question_id, status,
                   confidence, horizon, sealed_at
               ) VALUES(%s, decode(%s,'hex'), %s, %s, 'sealed', 0.5, now(), now())""",
            (submission_id, sheet_hash, uuid4(), question_id),
        )
    return submission_id


def test_a_built_digest_round_trips_through_storage(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    digests = repository(database, ArtifactStore(artifact_root))
    population_id, control_id = uuid4(), uuid4()
    submission_id = seed_submission(database)
    configuration_id = uuid4()
    payload = store_payload(
        entries=(
            entry(population_id, origin="population", position=0),
            entry(control_id, origin="random_control", position=1),
        ),
        nominations=(
            {
                "entry_id": str(population_id),
                "configuration_id": str(configuration_id),
                "submission_id": str(submission_id),
                "preference": 1,
            },
        ),
    )
    result = digests.execute("store", identity=identity(), payload=payload)
    data = _data(result)
    assert data["digest_hash"] == payload["digest_hash"]

    stored = digests.read_with_provenance(payload["digest_hash"])
    assert stored is not None
    assert stored["batch_id"] == payload["batch_id"]
    assert stored["island"] == "cs"
    assert stored["source_watermark"] == 7
    assert stored["shuffle_seed"] == payload["shuffle_seed"]
    entries_by_id = {row["entry_id"]: row for row in stored["entries"]}
    assert entries_by_id[str(population_id)]["origin"] == "population"
    assert entries_by_id[str(population_id)]["nominations"] == [
        {
            "configuration_id": str(configuration_id),
            "submission_id": str(submission_id),
            "preference": 1,
        }
    ]
    assert entries_by_id[str(control_id)]["origin"] == "random_control"
    assert entries_by_id[str(control_id)]["candidate_pool_hash"] == _hash("pool")
    assert entries_by_id[str(control_id)]["nominations"] == []


def test_a_rater_read_carries_no_origin_or_nomination(
    postgres_dsn: str, artifact_root: Path
) -> None:
    digests = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    entry_id = uuid4()
    payload = store_payload(entries=(entry(entry_id, origin="service"),))
    digests.execute("store", identity=identity(), payload=payload)

    blind = digests.read_for_rater(island="cs", batch_id=payload["batch_id"])
    assert blind is not None
    assert blind["digest_hash"] == payload["digest_hash"]
    row = blind["entries"][0]
    assert set(row) == {"entry_id", "paper_hash", "display_position"}
    assert row["entry_id"] == str(entry_id)


def test_an_inspector_read_carries_origin_and_nominations(
    postgres_dsn: str, artifact_root: Path
) -> None:
    digests = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    entry_id = uuid4()
    payload = store_payload(entries=(entry(entry_id, origin="service"),))
    digests.execute("store", identity=identity(), payload=payload)

    full = digests.read_with_provenance(payload["digest_hash"])
    assert full is not None
    row = full["entries"][0]
    assert row["origin"] == "service"
    assert row["service_source"] == "svc"
    assert row["nominations"] == []


def test_storing_the_same_digest_hash_twice_is_idempotent(
    postgres_dsn: str, artifact_root: Path
) -> None:
    digests = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    payload = store_payload()
    first = _data(digests.execute("store", identity=identity(), payload=payload))
    second = _data(digests.execute("store", identity=identity(), payload=payload))
    assert first["digest_hash"] == second["digest_hash"]
    assert first["built_at"] == second["built_at"]

    with Database(postgres_dsn).connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM digest_entries WHERE digest_hash=decode(%s,'hex')",
            (payload["digest_hash"],),
        ).fetchone()
    assert count is not None and count[0] == 1


def test_a_different_digest_for_an_occupied_batch_and_island_conflicts(
    postgres_dsn: str, artifact_root: Path
) -> None:
    digests = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    batch_id = _hash("batch-fixed")
    digests.execute(
        "store", identity=identity(), payload=store_payload(batch_id=batch_id)
    )
    with pytest.raises(StateConflict):
        digests.execute(
            "store", identity=identity(), payload=store_payload(batch_id=batch_id)
        )


def test_a_rating_for_an_unknown_entry_is_refused(
    postgres_dsn: str, artifact_root: Path
) -> None:
    ratings = RatingRepository(
        Database(postgres_dsn),
        ArtifactStore(artifact_root),
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    with pytest.raises(UnavailableInput, match="unavailable"):
        ratings.execute(
            "record",
            identity=identity(),
            payload={
                "rater_id": str(uuid4()),
                "paper_hash": "a" * 64,
                "digest_entry_id": str(uuid4()),
                "value": "like",
            },
        )


def test_a_rating_is_accepted_for_a_stored_digest_entry(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    digests = repository(database, store)
    entry_id = seed_single_entry_digest(digests)
    rater_id = uuid4()
    raters = RaterRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    raters.execute(
        "provision",
        identity=identity(),
        payload={
            "rater_id": str(rater_id),
            "island": "cs",
            "salt": "a" * 32,
            "credential_hash": "b" * 64,
        },
    )
    ratings = RatingRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    result = ratings.execute(
        "record",
        identity=identity(),
        payload={
            "rater_id": str(rater_id),
            "paper_hash": _hash(f"paper-{entry_id}"),
            "digest_entry_id": str(entry_id),
            "value": "like",
        },
    )
    assert UUID(_data(result)["rating_id"])


def _data(response: Any) -> dict[str, Any]:
    envelope = cast(dict[str, Any], canonical_loads(response.body))
    return cast(dict[str, Any], envelope["data"])


def test_orchestrator_writes_rating_app_reads_blind_and_roles_cannot_cross(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    digests = repository(database, ArtifactStore(artifact_root))
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
            fingerprint: ServiceCapability(
                uuid4(), "orchestrator", frozenset({"digests:store"})
            ),
            wrong_fingerprint: ServiceCapability(
                uuid4(),
                "rating_app",
                frozenset({"digests:read", "digests:provenance", "digests:store"}),
            ),
        },
        tls_context=server_context,
        authorization=StorageAuthorization(database),
        digests=digests,
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        host, port = httpd.server_address[:2]

        def client(cert: str, scopes: frozenset[str]) -> StorageClient:
            return StorageClient(
                connect_host=str(host),
                port=int(port),
                server_hostname="localhost",
                ca_file=tmp_path / "ca.pem",
                client_cert_file=tmp_path / f"{cert}.pem",
                client_key_file=tmp_path / f"{cert}.key",
                scopes=scopes,
                timeout_seconds=5,
            )

        orchestrator = client("client", frozenset({"digests:store"}))
        rating_app = client(
            "wrong", frozenset({"digests:read", "digests:provenance", "digests:store"})
        )
        payload = store_payload()

        def write(caller: StorageClient) -> None:
            caller.store_digest(
                digest_hash=payload["digest_hash"],
                batch_id=payload["batch_id"],
                island=payload["island"],
                source_watermark=payload["source_watermark"],
                shuffle_seed=payload["shuffle_seed"],
                entries=tuple(payload["entries"]),
                nominations=(),
                command_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            )

        write(orchestrator)

        # The rating app's certificate carries the digests:provenance scope
        # too, but its role is not orchestrator or inspector, so the server
        # still refuses both the write and the provenance read.
        with pytest.raises(StorageClientError, match="capability does not permit"):
            write(rating_app)

        blind = rating_app.read_digest_for_rater(
            island=payload["island"], batch_id=payload["batch_id"]
        )
        assert set(blind.data["entries"][0]) == {
            "entry_id",
            "paper_hash",
            "display_position",
        }

        with pytest.raises(StorageClientError, match="route not found"):
            rating_app.read_digest_with_provenance(payload["digest_hash"])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
