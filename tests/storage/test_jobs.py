from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.contracts.jobs import JobCheckpoint
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import (
    IdempotencyConflict,
    IntegrityFailure,
    LeaseExpired,
    StaleLease,
    UnavailableInput,
)
from research_agent.storage.jobs import JobRepository, LeaseFence
from research_agent.storage.ledger import LedgerRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class Storage:
    database: Database
    store: ArtifactStore
    artifacts: ArtifactRepository
    jobs: JobRepository

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

    def command(
        self,
        operation: str,
        payload: object,
        job_id: UUID | None = None,
        command: CommandIdentity | None = None,
    ) -> dict[str, Any]:
        if command is None and operation in {"renew", "checkpoint", "complete"}:
            subject = payload if operation == "renew" else payload["fence"]
            command = identity(UUID(subject["worker_id"]))
        response = self.jobs.execute(
            operation, identity=command or identity(), payload=payload, job_id=job_id
        )
        return dict(canonical_loads(response.body)["data"])

    def enqueue(self) -> tuple[UUID, str]:
        job_id = uuid4()
        artifact = self.artifact(b'{"input":1}')
        self.command(
            "enqueue",
            {
                "job_id": str(job_id),
                "kind": "extract",
                "input_manifest": artifact,
                "scheduled_at": "2020-01-01T00:00:00.000000Z",
            },
        )
        return job_id, artifact

    def claim(self, command: CommandIdentity | None = None) -> dict[str, Any]:
        command = command or identity()
        principal = command.principal_id
        return self.command(
            "claim",
            {"worker_id": str(principal), "kinds": ["extract"]},
            command=command,
        )["lease"]

    def expire(self, job_id: UUID) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE jobs SET expires_at=clock_timestamp()-interval '1 millisecond' WHERE id=%s",
                (job_id,),
            )


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> Storage:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    return Storage(
        database,
        store,
        ArtifactRepository(database, store),
        JobRepository(
            database,
            store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
    )


def fence(lease: dict[str, Any], command: CommandIdentity) -> dict[str, Any]:
    return {"worker_id": str(command.principal_id), "lease_epoch": lease["lease_epoch"]}


def test_expiry_checkpoint_resume_and_atomic_lifecycle(storage: Storage) -> None:
    job_id, input_hash = storage.enqueue()
    first_command = identity()
    first = storage.claim(first_command)
    checkpoint = storage.artifact(
        JobCheckpoint(
            1,
            str(job_id),
            "extract",
            (input_hash,),
            "c" * 64,
            (sha256_hex(b"completed"),),
            "next",
            (),
        ).to_canonical_json(),
        (input_hash,),
    )
    payload = {"fence": fence(first, first_command), "checkpoint": checkpoint}
    checkpoint_command = identity(first_command.principal_id)
    initial = storage.jobs.execute(
        "checkpoint", identity=checkpoint_command, payload=payload, job_id=job_id
    )
    storage.expire(job_id)
    replay = storage.jobs.execute(
        "checkpoint", identity=checkpoint_command, payload=payload, job_id=job_id
    )
    assert replay.replayed and initial.body == replay.body
    with pytest.raises(LeaseExpired):
        storage.command("checkpoint", payload, job_id)
    second_command = identity()
    second = storage.claim(second_command)
    assert second["lease_epoch"] == 2 and second["checkpoint"] == checkpoint
    with pytest.raises(StaleLease):
        storage.command("checkpoint", payload, job_id)
    output = storage.artifact(b'{"output":1}', (input_hash,))
    completed = storage.command(
        "complete",
        {
            "fence": fence(second, second_command),
            "result": {"kind": "committed", "output_hashes": [output]},
        },
        job_id,
    )
    assert completed["state"] == "committed"
    with storage.database.connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM job_checkpoints"
        ).fetchone() == (1,)
        row = connection.execute(
            "SELECT first_started_at,terminal_at,accumulated_active_duration_ns FROM jobs"
        ).fetchone()
        assert row and row[0] <= row[1] and row[2] > 0
        attempts = connection.execute(
            "SELECT lease_epoch,status,active_duration_ns FROM job_attempts ORDER BY lease_epoch"
        ).fetchall()
        assert [r[:2] for r in attempts] == [(1, "expired"), (2, "committed")]
        assert sum(r[2] for r in attempts) == row[2]
        assert connection.execute(
            "SELECT count(*) FROM ledger_records WHERE event_kind='job_transition'"
        ).fetchone() == (6,)
        LedgerRepository().verify(connection)


def test_concurrent_duplicate_commands_and_lost_response_replay(
    storage: Storage,
) -> None:
    job_id, artifact = storage.enqueue()
    command = identity()
    payload = {"worker_id": str(command.principal_id), "kinds": ["extract"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: storage.jobs.execute(
                    "claim", identity=command, payload=payload
                ),
                range(2),
            )
        )
    assert responses[0].body == responses[1].body
    assert sum(response.replayed for response in responses) == 1
    restarted = JobRepository(
        storage.database,
        storage.store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    assert (
        restarted.execute("claim", identity=command, payload=payload).body
        == responses[0].body
    )
    with pytest.raises(IdempotencyConflict):
        restarted.execute(
            "claim", identity=command, payload={**payload, "kinds": ["capture"]}
        )
    with storage.database.connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM job_attempts WHERE job_id=%s", (job_id,)
        ).fetchone() == (1,)


def test_complete_replay_does_not_count_twice(storage: Storage) -> None:
    job_id, admitted = storage.enqueue()
    output = storage.artifact(b'{"output":1}', (admitted,))
    command = identity()
    lease = storage.claim(command)
    completion = identity(command.principal_id)
    payload = {
        "fence": fence(lease, command),
        "result": {"kind": "committed", "output_hashes": [output]},
    }
    first = storage.jobs.execute(
        "complete", identity=completion, payload=payload, job_id=job_id
    )
    with storage.database.connect() as connection:
        duration = connection.execute(
            "SELECT accumulated_active_duration_ns FROM jobs"
        ).fetchone()
    assert (
        storage.jobs.execute(
            "complete", identity=completion, payload=payload, job_id=job_id
        ).body
        == first.body
    )
    with storage.database.connect() as connection:
        assert (
            connection.execute(
                "SELECT accumulated_active_duration_ns FROM jobs"
            ).fetchone()
            == duration
        )
        assert connection.execute("SELECT count(*) FROM job_outputs").fetchone() == (1,)


def test_database_rejection_rolls_back_domain_ledger_and_command(
    storage: Storage,
) -> None:
    job_id, _ = storage.enqueue()
    command = identity()
    lease = storage.claim(command)
    with storage.database.connect() as connection:
        connection.execute("""CREATE FUNCTION refuse_event() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'injected database rejection'; END; $$""")
        connection.execute(
            "CREATE TRIGGER refuse_event BEFORE INSERT ON ledger_records FOR EACH ROW EXECUTE FUNCTION refuse_event()"
        )
        before = connection.execute("SELECT count(*) FROM ledger_records").fetchone()
    import psycopg

    completion = identity(command.principal_id)
    with pytest.raises(psycopg.errors.RaiseException):
        storage.command(
            "complete",
            {
                "fence": fence(lease, command),
                "result": {
                    "kind": "skipped",
                    "reason": "disabled",
                    "evidence_hashes": [],
                },
            },
            job_id,
            completion,
        )
    with storage.database.connect() as connection:
        assert connection.execute(
            "SELECT state,terminal_at,accumulated_active_duration_ns FROM jobs"
        ).fetchone() == ("running", None, 0)
        assert (
            connection.execute("SELECT count(*) FROM ledger_records").fetchone()
            == before
        )
        assert connection.execute(
            "SELECT count(*) FROM idempotency_records WHERE command_id=%s",
            (completion.command_id,),
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "fault",
    [
        "corrupt",
        "absent",
        "tombstoned",
        "config",
        "identity",
        "version",
        "declared_missing",
    ],
)
def test_checkpoint_resume_fails_closed(storage: Storage, fault: str) -> None:
    job_id, input_hash = storage.enqueue()
    command = identity()
    lease = storage.claim(command)
    dependency = storage.artifact(b'{"dependency":1}')
    checkpoint = storage.artifact(
        JobCheckpoint(
            1, str(job_id), "extract", (input_hash,), "c" * 64, (), None, (dependency,)
        ).to_canonical_json(),
        (input_hash, dependency),
    )
    if fault in {"config", "identity", "version", "declared_missing"}:
        from research_agent.contracts import canonical_json

        with storage.database.connect() as connection:
            verified = storage.jobs._verifier.verify(connection, checkpoint)
        with storage.store.open_verified(verified.raw_hash) as stream:
            document = canonical_loads(stream.read())
        if fault == "config":
            document["config_hash"] = "e" * 64
        if fault == "identity":
            document["job_id"] = str(uuid4())
        if fault == "version":
            document["schema_version"] = 2
        if fault == "declared_missing":
            document["output_hashes"] = ["f" * 64]
        bad = storage.artifact(canonical_json(document), (input_hash,))
        with pytest.raises((ValueError, IntegrityFailure, UnavailableInput)):
            storage.command(
                "checkpoint",
                {"fence": fence(lease, command), "checkpoint": bad},
                job_id,
            )
        return
    storage.command(
        "checkpoint", {"fence": fence(lease, command), "checkpoint": checkpoint}, job_id
    )
    storage.expire(job_id)
    with storage.database.connect() as connection:
        raw_dependency = storage.jobs._verifier.verify(connection, dependency).raw_hash
    if fault == "corrupt":
        storage.store.path_for(raw_dependency).write_bytes(b"corrupt")
    elif fault == "absent":
        storage.store.path_for(raw_dependency).unlink()
    else:
        with storage.database.connect() as connection:
            connection.execute(
                "INSERT INTO artifact_tombstones(id,artifact_hash,reason,policy_hash) VALUES(%s,decode(%s,'hex'),'deleted',decode(%s,'hex'))",
                (uuid4(), dependency, "a" * 64),
            )
    with pytest.raises((IntegrityFailure, UnavailableInput)):
        storage.claim()
    with storage.database.connect() as connection:
        assert connection.execute("SELECT lease_epoch FROM jobs").fetchone() == (1,)


def test_simultaneous_workers_claim_distinct_jobs(storage: Storage) -> None:
    jobs = {storage.enqueue()[0], storage.enqueue()[0]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _: storage.claim(), range(2)))
    assert {UUID(lease["job_id"]) for lease in leases} == jobs


def test_fence_samples_clock_after_waiting_for_row_lock(storage: Storage) -> None:
    job_id, _ = storage.enqueue()
    command = identity()
    lease = storage.claim(command)
    from threading import Event

    ready = Event()
    with storage.database.connect() as blocker:
        blocker.execute(
            "UPDATE jobs SET expires_at=clock_timestamp()+interval '50 milliseconds' WHERE id=%s",
            (job_id,),
        )

        def check() -> None:
            def transaction(connection: Connection[tuple[object, ...]]) -> None:
                ready.set()
                JobRepository._lock_fenced(
                    connection,
                    job_id,
                    LeaseFence(command.principal_id, lease["lease_epoch"]),
                )

            storage.database.transaction(transaction)

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(check)
            assert ready.wait(2)
            blocker.execute("SELECT pg_sleep(0.1)")
            blocker.commit()
            with pytest.raises(LeaseExpired):
                pending.result()


def test_enqueue_renew_and_empty_claim_are_exact_replays(storage: Storage) -> None:
    command = identity()
    payload = {"worker_id": str(command.principal_id), "kinds": ["extract"]}
    empty = storage.jobs.execute("claim", identity=command, payload=payload)
    job_id, admitted = storage.enqueue()
    assert (
        storage.jobs.execute("claim", identity=command, payload=payload).body
        == empty.body
    )
    queued_command = identity()
    queued_payload = {
        "job_id": str(uuid4()),
        "kind": "capture",
        "input_manifest": admitted,
        "scheduled_at": "2020-01-01T00:00:00.000000Z",
    }
    first = storage.jobs.execute(
        "enqueue", identity=queued_command, payload=queued_payload
    )
    assert (
        storage.jobs.execute(
            "enqueue", identity=queued_command, payload=queued_payload
        ).body
        == first.body
    )
    worker = identity()
    lease = storage.claim(worker)
    renewal = identity(worker.principal_id)
    renewed = storage.jobs.execute(
        "renew", identity=renewal, payload=fence(lease, worker), job_id=job_id
    )
    storage.expire(job_id)
    assert (
        storage.jobs.execute(
            "renew", identity=renewal, payload=fence(lease, worker), job_id=job_id
        ).body
        == renewed.body
    )
    with pytest.raises(LeaseExpired):
        storage.command("renew", fence(lease, worker), job_id)


def test_wrong_principal_and_unrelated_output_are_refused(storage: Storage) -> None:
    job_id, admitted = storage.enqueue()
    worker = identity()
    lease = storage.claim(worker)
    with pytest.raises(StaleLease):
        storage.jobs.execute(
            "renew", identity=identity(), payload=fence(lease, worker), job_id=job_id
        )
    with pytest.raises(IntegrityFailure):
        storage.command(
            "complete",
            {
                "fence": fence(lease, worker),
                "result": {"kind": "committed", "output_hashes": [admitted]},
            },
            job_id,
        )
    with storage.database.connect() as connection:
        assert connection.execute("SELECT state FROM jobs").fetchone() == ("running",)
        assert connection.execute("SELECT count(*) FROM job_outputs").fetchone() == (0,)


def test_restart_preserves_duration_and_marks_unmeasured_interval(
    storage: Storage,
) -> None:
    job_id, _ = storage.enqueue()
    worker = identity()
    lease = storage.claim(worker)
    storage.command("renew", fence(lease, worker), job_id)
    with storage.database.connect() as connection:
        prior = connection.execute(
            "SELECT accumulated_active_duration_ns FROM jobs"
        ).fetchone()
    restarted = JobRepository(
        storage.database,
        storage.store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    restarted.execute(
        "complete",
        identity=identity(worker.principal_id),
        job_id=job_id,
        payload={
            "fence": fence(lease, worker),
            "result": {"kind": "skipped", "reason": "disabled", "evidence_hashes": []},
        },
    )
    with storage.database.connect() as connection:
        assert (
            connection.execute(
                "SELECT accumulated_active_duration_ns FROM jobs"
            ).fetchone()
            == prior
        )
        assert connection.execute(
            "SELECT duration_complete FROM job_attempts"
        ).fetchone() == (False,)


def test_distinct_production_config_cannot_resume_wrong_checkpoint(
    storage: Storage,
) -> None:
    job_id, admitted = storage.enqueue()
    worker = identity()
    lease = storage.claim(worker)
    body = b'{"input":1}'
    alternate = storage.artifacts.publish(
        [body],
        expected_hash=sha256_hex(body),
        byte_length=len(body),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash="e" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    checkpoint = storage.artifact(
        JobCheckpoint(
            1, str(job_id), "extract", (admitted,), "e" * 64, (), None, ()
        ).to_canonical_json(),
        (admitted,),
    )
    assert alternate.artifact_hash == sha256_hex(body)
    with pytest.raises(IntegrityFailure):
        storage.command(
            "checkpoint",
            {"fence": fence(lease, worker), "checkpoint": checkpoint},
            job_id,
        )


def test_commit_time_failure_rolls_back_event_and_idempotency(storage: Storage) -> None:
    import psycopg

    job_id, _ = storage.enqueue()
    worker = identity()
    lease = storage.claim(worker)
    with storage.database.connect() as connection:
        before = connection.execute("SELECT count(*) FROM ledger_records").fetchone()
        connection.execute("""CREATE FUNCTION reject_commit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'commit refused'; END; $$""")
        connection.execute("""CREATE CONSTRAINT TRIGGER reject_commit AFTER INSERT ON ledger_records
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_commit()""")
    command = identity(worker.principal_id)
    with pytest.raises(psycopg.errors.RaiseException):
        storage.command(
            "complete",
            {
                "fence": fence(lease, worker),
                "result": {
                    "kind": "skipped",
                    "reason": "disabled",
                    "evidence_hashes": [],
                },
            },
            job_id,
            command,
        )
    with storage.database.connect() as connection:
        assert (
            connection.execute("SELECT count(*) FROM ledger_records").fetchone()
            == before
        )
        assert connection.execute("SELECT state FROM jobs").fetchone() == ("running",)
        assert connection.execute(
            "SELECT count(*) FROM idempotency_records WHERE command_id=%s",
            (command.command_id,),
        ).fetchone() == (0,)
        LedgerRepository().verify(connection)
