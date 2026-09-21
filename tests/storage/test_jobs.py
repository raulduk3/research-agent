from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg import Connection

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.errors import (
    LeaseExpired,
    StaleLease,
    StateConflict,
    UnavailableInput,
)
from research_agent.storage.jobs import JobRepository, LeaseFence

pytestmark = pytest.mark.integration


def _artifact(repository: ArtifactRepository, payload: bytes) -> str:
    identity = hashlib.sha256(payload).hexdigest()
    repository.publish(
        [payload],
        expected_hash=identity,
        byte_length=len(payload),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    return identity


def test_expired_job_resumes_with_new_epoch_and_fences_old_worker(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    artifacts = ArtifactRepository(database, ArtifactStore(artifact_root))
    input_hash = _artifact(artifacts, b'{"input":1}')
    checkpoint_hash = _artifact(artifacts, b'{"checkpoint":1}')
    output_hash = _artifact(artifacts, b'{"output":1}')
    jobs = JobRepository(database)
    job_id, first_worker, second_worker = uuid4(), uuid4(), uuid4()
    jobs.enqueue(
        job_id=job_id,
        kind="extract",
        input_manifest=input_hash,
        scheduled_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    first = jobs.claim(worker_id=first_worker, kinds=("extract",))
    assert first is not None and first.lease_epoch == 1

    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET expires_at = transaction_timestamp() - interval '1 second' "
            "WHERE id = %s",
            (job_id,),
        )
    second = jobs.claim(worker_id=second_worker, kinds=("extract",))
    assert second is not None and second.lease_epoch == 2

    with pytest.raises(StaleLease):
        jobs.checkpoint(
            job_id=job_id,
            fence=LeaseFence(first_worker, first.lease_epoch),
            artifact_hash=checkpoint_hash,
        )
    checkpoint_id = jobs.checkpoint(
        job_id=job_id,
        fence=LeaseFence(second_worker, second.lease_epoch),
        artifact_hash=checkpoint_hash,
    )
    completion = jobs.complete(
        job_id=job_id,
        fence=LeaseFence(second_worker, second.lease_epoch),
        state="committed",
        output_hashes=(output_hash,),
    )
    assert checkpoint_id is not None
    assert completion.state == "committed"
    with pytest.raises(StateConflict):
        jobs.renew(job_id=job_id, fence=LeaseFence(second_worker, second.lease_epoch))

    with database.connect() as connection:
        attempts = connection.execute(
            "SELECT lease_epoch, status FROM job_attempts WHERE job_id = %s ORDER BY lease_epoch",
            (job_id,),
        ).fetchall()
        output = connection.execute(
            "SELECT encode(artifact_hash, 'hex') FROM job_outputs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
    assert attempts == [(1, "expired"), (2, "committed")]
    assert output is not None and output[0] == output_hash


def test_fence_uses_database_wall_clock_after_transaction_starts(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    artifacts = ArtifactRepository(database, ArtifactStore(artifact_root))
    input_hash = _artifact(artifacts, b'{"clock-input":1}')
    jobs = JobRepository(database)
    job_id, worker_id = uuid4(), uuid4()
    jobs.enqueue(
        job_id=job_id,
        kind="extract",
        input_manifest=input_hash,
        scheduled_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    lease = jobs.claim(worker_id=worker_id, kinds=("extract",))
    assert lease is not None
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET expires_at = clock_timestamp() + interval '50 milliseconds' "
            "WHERE id = %s",
            (job_id,),
        )

    def cross_expiry(connection: Connection[tuple[object, ...]]) -> None:
        connection.execute("SELECT pg_sleep(0.1)")
        JobRepository._lock_fenced(
            connection, job_id, LeaseFence(worker_id, lease.lease_epoch)
        )

    with pytest.raises(LeaseExpired):
        database.serializable(cross_expiry)


def test_tombstoned_input_is_never_enqueued_or_claimed(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    artifacts = ArtifactRepository(database, ArtifactStore(artifact_root))
    first_hash = _artifact(artifacts, b'{"first-input":1}')
    second_hash = _artifact(artifacts, b'{"second-input":1}')
    jobs = JobRepository(database)
    queued_id = uuid4()
    jobs.enqueue(
        job_id=queued_id,
        kind="extract",
        input_manifest=first_hash,
        scheduled_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO artifact_tombstones(id, artifact_hash, reason, policy_hash)
            VALUES (%s, decode(%s, 'hex'), 'required deletion', decode(%s, 'hex'))
            """,
            (uuid4(), first_hash, "f" * 64),
        )
    assert jobs.claim(worker_id=uuid4(), kinds=("extract",)) is None

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO artifact_tombstones(id, artifact_hash, reason, policy_hash)
            VALUES (%s, decode(%s, 'hex'), 'required deletion', decode(%s, 'hex'))
            """,
            (uuid4(), second_hash, "f" * 64),
        )
    with pytest.raises(UnavailableInput):
        jobs.enqueue(
            job_id=uuid4(),
            kind="extract",
            input_manifest=second_hash,
            scheduled_at=datetime.now(timezone.utc),
        )


def test_simultaneous_workers_claim_distinct_jobs_and_epochs(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    artifacts = ArtifactRepository(database, ArtifactStore(artifact_root))
    input_hash = _artifact(artifacts, b'{"parallel-input":1}')
    jobs = JobRepository(database)
    job_ids = (uuid4(), uuid4())
    for job_id in job_ids:
        jobs.enqueue(
            job_id=job_id,
            kind="extract",
            input_manifest=input_hash,
            scheduled_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = list(
            executor.map(
                lambda worker: jobs.claim(worker_id=worker, kinds=("extract",)),
                (uuid4(), uuid4()),
            )
        )
    assert all(lease is not None for lease in leases)
    assert {lease.job_id for lease in leases if lease is not None} == set(job_ids)
    assert {lease.lease_epoch for lease in leases if lease is not None} == {1}
