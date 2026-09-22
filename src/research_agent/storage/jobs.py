"""Command-idempotent leased jobs with atomic ledger and checkpoint recovery."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, cast
from uuid import UUID, uuid4

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json, canonical_loads
from research_agent.contracts.jobs import JobCheckpoint, validate_job_payload
from research_agent.contracts.primitives import validate_sha256, validate_uuid4
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import (
    IntegrityFailure,
    LeaseExpired,
    StaleLease,
    StateConflict,
)
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.verification import ArtifactVerifier


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class LeaseFence:
    worker_id: UUID
    lease_epoch: int


class JobRepository:
    LEASE_SECONDS = 120

    def __init__(
        self,
        database: Database,
        store: ArtifactStore,
        *,
        producer: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
    ) -> None:
        validate_sha256(config_hash)
        validate_sha256(retention_policy_hash)
        self._commands = CommandTransaction(database)
        self._store = store
        self._verifier = ArtifactVerifier(store)
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)
        # Monotonic values are never persisted or compared across storage processes.
        self._clock_id = uuid4()
        self._timers: dict[tuple[UUID, int], tuple[int, int]] = {}
        self._timer_lock = Lock()

    def execute(
        self,
        operation: str,
        *,
        identity: CommandIdentity,
        payload: object,
        job_id: UUID | None = None,
    ) -> StoredResponse:
        value = validate_job_payload(operation, payload)
        if operation == "claim":
            subject = value["worker_id"]
        elif operation in {"renew", "checkpoint", "complete"}:
            subject = (value if operation == "renew" else value["fence"])["worker_id"]
        else:
            subject = str(identity.principal_id)
        if subject != str(identity.principal_id):
            raise StaleLease("worker identity does not match authenticated principal")
        if operation in {"renew", "checkpoint", "complete"}:
            validate_uuid4(str(job_id))
        elif job_id is not None:
            raise ValueError("this operation has no job path")
        route = (
            "internal/jobs/enqueue"
            if operation == "enqueue"
            else "/v1/jobs/claim"
            if operation == "claim"
            else f"/v1/jobs/{{id}}/{operation}"
        )

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            if operation == "enqueue":
                return self._enqueue(connection, identity, value)
            if operation == "claim":
                return self._claim(connection, identity, value)
            assert job_id is not None
            return self._update(connection, identity, operation, job_id, value)

        response = self._commands.execute(
            identity,
            route,
            {} if job_id is None else {"id": str(job_id)},
            value,
            mutate,
        )
        if operation in {"claim", "renew"} and not response.replayed:
            data = cast(dict[str, Any], canonical_loads(response.body))["data"]
            lease = data.get("lease") if operation == "claim" else data
            if lease is None:
                return response
            timer_job_id = UUID(lease["job_id"]) if operation == "claim" else job_id
            assert timer_job_id is not None
            epoch = (
                lease["lease_epoch"] if operation == "claim" else value["lease_epoch"]
            )
            expires_at = datetime.strptime(
                lease["expires_at"], "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
            start = time.monotonic_ns()
            remaining = max(
                0,
                int(
                    (expires_at - datetime.now(timezone.utc)).total_seconds()
                    * 1_000_000_000
                ),
            )
            with self._timer_lock:
                timer = self._timers.get((timer_job_id, epoch))
                timer_start = start if timer is None else timer[0]
                self._timers[(timer_job_id, epoch)] = (
                    timer_start,
                    start + remaining,
                )
        return response

    def _enqueue(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        job_id = UUID(value["job_id"])
        self._verify_dag(connection, value["input_manifest"])
        connection.execute(
            """INSERT INTO jobs(id,kind,state,input_manifest_hash,scheduled_at)
               VALUES(%s,%s,'queued',decode(%s,'hex'),%s)""",
            (job_id, value["kind"], value["input_manifest"], value["scheduled_at"]),
        )
        receipt = self._event(
            connection, identity, job_id, "enqueue", (value["input_manifest"],)
        )
        return {"job_id": str(job_id), "receipt": receipt}

    def _claim(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        expired = connection.execute(
            """SELECT id, lease_epoch, expires_at FROM jobs
               WHERE state='running' AND expires_at<=clock_timestamp()
               ORDER BY id FOR UPDATE SKIP LOCKED"""
        ).fetchall()
        for raw_id, epoch, expiry in expired:
            expired_id = cast(UUID, raw_id)
            self._account(connection, expired_id, cast(int, epoch))
            connection.execute(
                """UPDATE jobs SET state='interrupted',worker_id=NULL,expires_at=NULL
                   WHERE id=%s""",
                (expired_id,),
            )
            connection.execute(
                """UPDATE job_attempts SET status='expired',ended_at=%s
                   WHERE job_id=%s AND lease_epoch=%s""",
                (expiry, expired_id, epoch),
            )
            self._event(connection, identity, expired_id, "expire", ())
        row = connection.execute(
            """SELECT j.id,j.kind,j.lease_epoch,encode(j.input_manifest_hash,'hex'),
                      encode(j.checkpoint_hash,'hex')
               FROM jobs j JOIN artifacts a ON a.hash=j.input_manifest_hash
               LEFT JOIN artifact_tombstones t ON t.artifact_hash=a.hash
               WHERE j.state IN ('queued','interrupted') AND j.scheduled_at<=clock_timestamp()
                 AND j.kind=ANY(%s) AND t.artifact_hash IS NULL
               ORDER BY j.scheduled_at,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
            (value["kinds"],),
        ).fetchone()
        if row is None:
            return {"lease": None}
        job_id, epoch = cast(UUID, row[0]), cast(int, row[2]) + 1
        self._verify_dag(connection, str(row[3]))
        if row[4] is not None:
            self._verify_checkpoint(connection, job_id, str(row[4]), str(row[3]))
        now = self._now(connection)
        expires = connection.execute(
            "SELECT %s + make_interval(secs => %s)", (now, self.LEASE_SECONDS)
        ).fetchone()
        assert expires is not None
        connection.execute(
            """UPDATE jobs SET state='running',lease_epoch=%s,worker_id=%s,
               expires_at=%s,first_started_at=COALESCE(first_started_at,%s) WHERE id=%s""",
            (epoch, UUID(value["worker_id"]), expires[0], now, job_id),
        )
        connection.execute(
            """INSERT INTO job_attempts(id,job_id,lease_epoch,worker_id,started_at,status,clock_id)
               VALUES(%s,%s,%s,%s,%s,'running',%s)""",
            (uuid4(), job_id, epoch, UUID(value["worker_id"]), now, self._clock_id),
        )
        self._event(connection, identity, job_id, "claim", (str(row[3]),))
        return {
            "lease": {
                "job_id": str(job_id),
                "kind": row[1],
                "lease_epoch": epoch,
                "expires_at": _utc(cast(datetime, expires[0])),
                "input_manifest": row[3],
                "checkpoint": row[4],
            }
        }

    def _update(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        operation: str,
        job_id: UUID,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        fence_value = value if operation == "renew" else value["fence"]
        fence = LeaseFence(UUID(fence_value["worker_id"]), fence_value["lease_epoch"])
        locked, now = self._lock_fenced(connection, job_id, fence)
        references: tuple[str, ...] = ()
        result: dict[str, Any]
        if operation == "renew":
            expiry = connection.execute(
                "SELECT %s + make_interval(secs => %s)", (now, self.LEASE_SECONDS)
            ).fetchone()
            assert expiry is not None
            connection.execute(
                "UPDATE jobs SET expires_at=%s WHERE id=%s", (expiry[0], job_id)
            )
            # Only committed renewal may extend measured activity: the persisted expiry
            # is also checked by _account before accepting any measured interval.
            result = {"expires_at": _utc(cast(datetime, expiry[0]))}
        elif operation == "checkpoint":
            current = connection.execute(
                "SELECT encode(input_manifest_hash,'hex') FROM jobs WHERE id=%s",
                (job_id,),
            ).fetchone()
            assert current is not None
            self._verify_checkpoint(
                connection, job_id, value["checkpoint"], str(current[0])
            )
            checkpoint_id = uuid4()
            connection.execute(
                """INSERT INTO job_checkpoints(id,job_id,lease_epoch,artifact_hash)
                   VALUES(%s,%s,%s,decode(%s,'hex'))""",
                (checkpoint_id, job_id, fence.lease_epoch, value["checkpoint"]),
            )
            connection.execute(
                "UPDATE jobs SET checkpoint_hash=decode(%s,'hex') WHERE id=%s",
                (value["checkpoint"], job_id),
            )
            references = (value["checkpoint"],)
            result = {"checkpoint_id": str(checkpoint_id)}
        else:
            outcome = value["result"]
            state = outcome["kind"]
            references = tuple(
                outcome.get("output_hashes", outcome.get("evidence_hashes", []))
            )
            if state == "failed":
                references = tuple(outcome["error"]["evidence_ids"])
            for artifact_hash in references:
                self._verify_dag(connection, artifact_hash)
            if state == "committed":
                admitted_row = connection.execute(
                    "SELECT encode(input_manifest_hash,'hex') FROM jobs WHERE id=%s",
                    (job_id,),
                ).fetchone()
                assert admitted_row is not None
                for artifact_hash in references:
                    produced = self._verifier.verify(connection, artifact_hash)
                    if str(admitted_row[0]) not in produced.input_hashes:
                        raise IntegrityFailure(
                            "output does not declare the admitted job input"
                        )
                for ordinal, artifact_hash in enumerate(references):
                    connection.execute(
                        "INSERT INTO job_outputs(job_id,artifact_hash,ordinal) VALUES(%s,decode(%s,'hex'),%s)",
                        (job_id, artifact_hash, ordinal),
                    )
            _, terminal_at = self._lock_fenced(connection, job_id, fence)
            self._account(connection, job_id, fence.lease_epoch)
            connection.execute(
                """UPDATE jobs SET state=%s,worker_id=NULL,expires_at=NULL,terminal_at=%s,
                   result_body=%s WHERE id=%s""",
                (state, terminal_at, canonical_json(outcome), job_id),
            )
            connection.execute(
                "UPDATE job_attempts SET status=%s,ended_at=%s WHERE job_id=%s AND lease_epoch=%s",
                (state, terminal_at, job_id, fence.lease_epoch),
            )
            result = {"job_id": str(job_id), "state": state}
        # Recheck after potentially expensive filesystem verification, before publishing.
        if operation != "complete":
            self._lock_fenced(connection, job_id, fence)
            self._account(connection, job_id, fence.lease_epoch)
        elif self._now(connection) >= cast(datetime, locked[4]):
            raise LeaseExpired("lease expired while verifying outputs")
        result["receipt"] = self._event(
            connection, identity, job_id, operation, references
        )
        if self._now(connection) >= cast(datetime, locked[4]):
            raise LeaseExpired("lease expired before ledger commit")
        return result

    def _account(
        self, connection: Connection[tuple[object, ...]], job_id: UUID, epoch: int
    ) -> None:
        row = connection.execute(
            """SELECT a.clock_id,a.active_duration_ns,j.expires_at>clock_timestamp()
               FROM job_attempts a JOIN jobs j ON j.id=a.job_id
               WHERE a.job_id=%s AND a.lease_epoch=%s""",
            (job_id, epoch),
        ).fetchone()
        assert row is not None
        with self._timer_lock:
            timer = self._timers.get((job_id, epoch))
        if timer is None or row[0] != self._clock_id:
            connection.execute(
                "UPDATE job_attempts SET duration_complete=false WHERE job_id=%s AND lease_epoch=%s",
                (job_id, epoch),
            )
            return
        start, deadline = timer
        measured = max(0, min(time.monotonic_ns(), deadline) - start)
        previous = cast(int, row[1])
        measured = max(previous, measured)
        connection.execute(
            "UPDATE job_attempts SET active_duration_ns=%s WHERE job_id=%s AND lease_epoch=%s",
            (measured, job_id, epoch),
        )
        connection.execute(
            "UPDATE jobs SET accumulated_active_duration_ns=accumulated_active_duration_ns+%s WHERE id=%s",
            (measured - previous, job_id),
        )

    def _event(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        job_id: UUID,
        action: str,
        references: tuple[str, ...],
    ) -> dict[str, Any]:
        row = connection.execute(
            """SELECT state,lease_epoch,encode(checkpoint_hash,'hex'),
               accumulated_active_duration_ns,first_started_at,terminal_at,
               kind,encode(input_manifest_hash,'hex'),result_body,
               NOT EXISTS(SELECT 1 FROM job_attempts a WHERE a.job_id=jobs.id AND NOT a.duration_complete)
               FROM jobs WHERE id=%s""",
            (job_id,),
        ).fetchone()
        assert row is not None
        return self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="job_transition",
            payload={
                "schema_version": 1,
                "job_id": str(job_id),
                "action": action,
                "state": row[0],
                "lease_epoch": row[1],
                "job_kind": row[6],
                "input_manifest": row[7],
                "result": None
                if row[8] is None
                else canonical_loads(bytes(cast(bytes, row[8]))),
                "duration_complete": row[9],
                "checkpoint": row[2],
                "active_duration_ns": row[3],
                "artifact_hashes": list(references),
                "first_started_at": None
                if row[4] is None
                else _utc(cast(datetime, row[4])),
                "terminal_at": None if row[5] is None else _utc(cast(datetime, row[5])),
            },
            input_hashes=references,
        )

    def _verify_dag(
        self, connection: Connection[tuple[object, ...]], artifact_hash: str
    ) -> None:
        self._verifier.verify(connection, artifact_hash)

    def _verify_checkpoint(
        self,
        connection: Connection[tuple[object, ...]],
        job_id: UUID,
        checkpoint_hash: str,
        input_hash: str,
    ) -> None:
        verified = self._verifier.verify(connection, checkpoint_hash)
        with self._store.open_verified(verified.raw_hash) as stream:
            checkpoint = JobCheckpoint.from_json(stream.read())
        if checkpoint.job_id != str(job_id) or checkpoint.input_hashes != (input_hash,):
            raise IntegrityFailure(
                "checkpoint does not belong to the exact admitted job input"
            )
        for dependency in (*checkpoint.input_hashes, *checkpoint.output_hashes):
            self._verify_dag(connection, dependency)
        admitted = self._verifier.verify(connection, input_hash)
        if (
            admitted.config_hash != checkpoint.config_hash
            or verified.config_hash != checkpoint.config_hash
        ):
            raise IntegrityFailure(
                "checkpoint configuration differs from admitted input"
            )
        if not set((*checkpoint.input_hashes, *checkpoint.output_hashes)).issubset(
            verified.input_hashes
        ):
            raise IntegrityFailure(
                "checkpoint declared dependencies are missing from producing manifest"
            )

    @staticmethod
    def _now(connection: Connection[tuple[object, ...]]) -> datetime:
        row = connection.execute("SELECT clock_timestamp()").fetchone()
        assert row is not None
        return cast(datetime, row[0])

    @staticmethod
    def _lock_fenced(
        connection: Connection[tuple[object, ...]], job_id: UUID, fence: LeaseFence
    ) -> tuple[tuple[object, ...], datetime]:
        row = connection.execute(
            "SELECT id,state,worker_id,lease_epoch,expires_at FROM jobs WHERE id=%s FOR UPDATE",
            (job_id,),
        ).fetchone()
        now = JobRepository._now(connection)
        if row is None or row[1] != "running":
            raise StateConflict("job is not running")
        if row[2] != fence.worker_id or row[3] != fence.lease_epoch:
            raise StaleLease("lease owner or epoch is stale")
        if cast(datetime, row[4]) <= now:
            raise LeaseExpired("lease has expired")
        return row, now
