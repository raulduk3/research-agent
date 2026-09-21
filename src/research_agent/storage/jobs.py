"""Durable leased jobs with epoch fencing and checkpoint recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast
from uuid import UUID, uuid4

from psycopg import Connection

from research_agent.storage.database import Database
from research_agent.storage.errors import (
    LeaseExpired,
    StaleLease,
    StateConflict,
    UnavailableInput,
)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class LeaseFence:
    worker_id: UUID
    lease_epoch: int


@dataclass(frozen=True, slots=True)
class JobLease:
    job_id: UUID
    kind: str
    lease_epoch: int
    expires_at: str
    input_manifest: str
    checkpoint: str | None


@dataclass(frozen=True, slots=True)
class JobCompletion:
    job_id: UUID
    state: str
    terminal_at: str


class JobRepository:
    LEASE_SECONDS = 120

    def __init__(self, database: Database) -> None:
        self._database = database

    def enqueue(
        self,
        *,
        job_id: UUID,
        kind: str,
        input_manifest: str,
        scheduled_at: datetime,
    ) -> None:
        """Create work after its owning validated operation admits it."""

        def transaction(connection: Connection[tuple[object, ...]]) -> None:
            if not self._artifact_available(connection, input_manifest):
                raise UnavailableInput("job input artifact is absent or tombstoned")
            connection.execute(
                """
                INSERT INTO jobs(id, kind, state, input_manifest_hash, scheduled_at)
                VALUES (%s, %s, 'queued', decode(%s, 'hex'), %s)
                """,
                (job_id, kind, input_manifest, scheduled_at),
            )

        self._database.transaction(transaction)

    def claim(self, *, worker_id: UUID, kinds: tuple[str, ...]) -> JobLease | None:
        if not kinds or len(kinds) > 12 or len(set(kinds)) != len(kinds):
            raise ValueError("claim requires one to twelve distinct job kinds")

        def transaction(connection: Connection[tuple[object, ...]]) -> JobLease | None:
            now_row = connection.execute("SELECT clock_timestamp()").fetchone()
            assert now_row is not None
            now = cast(datetime, now_row[0])
            expired = connection.execute(
                """
                UPDATE jobs
                SET state = 'interrupted', worker_id = NULL, expires_at = NULL
                WHERE state = 'running' AND expires_at <= %s
                RETURNING id, lease_epoch
                """,
                (now,),
            ).fetchall()
            for job_id, lease_epoch in expired:
                connection.execute(
                    """
                    UPDATE job_attempts
                    SET ended_at = %s, status = 'expired'
                    WHERE job_id = %s AND lease_epoch = %s AND status = 'running'
                    """,
                    (now, job_id, lease_epoch),
                )

            row = connection.execute(
                """
                SELECT j.id, j.kind, j.lease_epoch, encode(j.input_manifest_hash, 'hex'),
                       encode(j.checkpoint_hash, 'hex')
                FROM jobs j
                JOIN artifacts a ON a.hash = j.input_manifest_hash
                LEFT JOIN artifact_tombstones t ON t.artifact_hash = a.hash
                WHERE j.state IN ('queued', 'interrupted')
                  AND j.scheduled_at <= %s
                  AND j.kind = ANY(%s)
                  AND t.artifact_hash IS NULL
                ORDER BY j.scheduled_at, j.id
                FOR UPDATE OF j SKIP LOCKED
                LIMIT 1
                """,
                (now, list(kinds)),
            ).fetchone()
            if row is None:
                return None
            claimed_job_id, kind = cast(UUID, row[0]), cast(str, row[1])
            lease_epoch = cast(int, row[2]) + 1
            lease_now_row = connection.execute("SELECT clock_timestamp()").fetchone()
            assert lease_now_row is not None
            lease_now = cast(datetime, lease_now_row[0])
            expires_row = connection.execute(
                "SELECT %s + make_interval(secs => %s)",
                (lease_now, self.LEASE_SECONDS),
            ).fetchone()
            assert expires_row is not None
            expires_at = cast(datetime, expires_row[0])
            connection.execute(
                """
                UPDATE jobs
                SET state = 'running', lease_epoch = %s, worker_id = %s,
                    expires_at = %s, first_started_at = COALESCE(first_started_at, %s)
                WHERE id = %s
                """,
                (lease_epoch, worker_id, expires_at, lease_now, claimed_job_id),
            )
            connection.execute(
                """
                INSERT INTO job_attempts(
                    id, job_id, lease_epoch, worker_id, started_at, status
                ) VALUES (%s, %s, %s, %s, %s, 'running')
                """,
                (uuid4(), claimed_job_id, lease_epoch, worker_id, lease_now),
            )
            return JobLease(
                claimed_job_id,
                kind,
                lease_epoch,
                _utc(expires_at),
                str(row[3]),
                None if row[4] is None else str(row[4]),
            )

        return self._database.serializable(transaction)

    def renew(self, *, job_id: UUID, fence: LeaseFence) -> str:
        def transaction(connection: Connection[tuple[object, ...]]) -> str:
            row, now = self._lock_fenced(connection, job_id, fence)
            expires_row = connection.execute(
                "SELECT %s + make_interval(secs => %s)",
                (now, self.LEASE_SECONDS),
            ).fetchone()
            assert expires_row is not None
            expires_at = cast(datetime, expires_row[0])
            connection.execute(
                "UPDATE jobs SET expires_at = %s WHERE id = %s",
                (expires_at, row[0]),
            )
            return _utc(expires_at)

        return self._database.serializable(transaction)

    def checkpoint(
        self, *, job_id: UUID, fence: LeaseFence, artifact_hash: str
    ) -> UUID:
        checkpoint_id = uuid4()

        def transaction(connection: Connection[tuple[object, ...]]) -> UUID:
            self._lock_fenced(connection, job_id, fence)
            if not self._artifact_available(connection, artifact_hash):
                raise UnavailableInput("checkpoint artifact is absent or tombstoned")
            connection.execute(
                """
                INSERT INTO job_checkpoints(id, job_id, lease_epoch, artifact_hash)
                VALUES (%s, %s, %s, decode(%s, 'hex'))
                """,
                (checkpoint_id, job_id, fence.lease_epoch, artifact_hash),
            )
            connection.execute(
                "UPDATE jobs SET checkpoint_hash = decode(%s, 'hex') WHERE id = %s",
                (artifact_hash, job_id),
            )
            return checkpoint_id

        return self._database.serializable(transaction)

    def complete(
        self,
        *,
        job_id: UUID,
        fence: LeaseFence,
        state: str,
        output_hashes: tuple[str, ...] = (),
    ) -> JobCompletion:
        if state not in {"committed", "failed", "skipped"}:
            raise ValueError("invalid terminal job state")
        if state == "committed" and not output_hashes:
            raise ValueError("committed jobs require at least one output")
        if state != "committed" and output_hashes:
            raise ValueError("failed or skipped jobs cannot publish outputs")
        if len(output_hashes) > 1000 or len(set(output_hashes)) != len(output_hashes):
            raise ValueError("job outputs must be distinct and bounded")

        def transaction(connection: Connection[tuple[object, ...]]) -> JobCompletion:
            _, now = self._lock_fenced(connection, job_id, fence)
            for ordinal, artifact_hash in enumerate(output_hashes):
                if not self._artifact_available(connection, artifact_hash):
                    raise UnavailableInput(
                        "job output artifact is absent or tombstoned"
                    )
                connection.execute(
                    """
                    INSERT INTO job_outputs(job_id, artifact_hash, ordinal)
                    VALUES (%s, decode(%s, 'hex'), %s)
                    """,
                    (job_id, artifact_hash, ordinal),
                )
            connection.execute(
                """
                UPDATE jobs
                SET state = %s, worker_id = NULL, expires_at = NULL, terminal_at = %s
                WHERE id = %s
                """,
                (state, now, job_id),
            )
            connection.execute(
                """
                UPDATE job_attempts SET ended_at = %s, status = %s
                WHERE job_id = %s AND lease_epoch = %s AND status = 'running'
                """,
                (now, state, job_id, fence.lease_epoch),
            )
            return JobCompletion(job_id, state, _utc(now))

        return self._database.serializable(transaction)

    @staticmethod
    def _artifact_available(
        connection: Connection[tuple[object, ...]], artifact_hash: str
    ) -> bool:
        return (
            connection.execute(
                """
                SELECT 1 FROM artifacts a
                LEFT JOIN artifact_tombstones t ON t.artifact_hash = a.hash
                WHERE a.hash = decode(%s, 'hex') AND t.artifact_hash IS NULL
                """,
                (artifact_hash,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _lock_fenced(
        connection: Connection[tuple[object, ...]], job_id: UUID, fence: LeaseFence
    ) -> tuple[tuple[object, ...], datetime]:
        now_row = connection.execute("SELECT clock_timestamp()").fetchone()
        assert now_row is not None
        now = cast(datetime, now_row[0])
        row = connection.execute(
            """
            SELECT id, state, worker_id, lease_epoch, expires_at
            FROM jobs WHERE id = %s FOR UPDATE
            """,
            (job_id,),
        ).fetchone()
        if row is None or str(row[1]) != "running":
            raise StateConflict("job is not running")
        if row[2] != fence.worker_id or cast(int, row[3]) != fence.lease_epoch:
            raise StaleLease("lease owner or epoch is stale")
        if cast(datetime, row[4]) <= now:
            raise LeaseExpired("lease has expired")
        return row, now
