"""Database-backed authorization for the implemented storage boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from psycopg import Connection

from research_agent.storage.database import Database


@dataclass(frozen=True, slots=True)
class JobScope:
    job_id: UUID
    lease_epoch: int


class StorageAuthorization:
    def __init__(self, database: Database) -> None:
        self._database = database

    def job_fence_allowed(
        self,
        *,
        principal_id: UUID,
        role_kinds: frozenset[str],
        job_id: UUID,
        lease_epoch: int,
        command_id: UUID,
        idempotency_key: UUID,
    ) -> bool:
        def check(connection: Connection[tuple[object, ...]]) -> bool:
            replay = connection.execute(
                """SELECT 1 FROM idempotency_records
                   WHERE principal_id=%s AND key=%s AND command_id=%s AND completed""",
                (principal_id, idempotency_key, command_id),
            ).fetchone()
            if replay is not None:
                historical = connection.execute(
                    """SELECT 1 FROM job_attempts a JOIN jobs j ON j.id=a.job_id
                       WHERE a.job_id=%s AND a.lease_epoch=%s AND a.worker_id=%s
                         AND j.kind=ANY(%s)""",
                    (job_id, lease_epoch, principal_id, list(role_kinds)),
                ).fetchone()
                return historical is not None
            row = connection.execute(
                """SELECT kind,state,worker_id,lease_epoch,expires_at>clock_timestamp()
                   FROM jobs WHERE id=%s""",
                (job_id,),
            ).fetchone()
            return bool(
                row is not None
                and str(row[0]) in role_kinds
                and row[1] == "running"
                and row[2] == principal_id
                and cast(int, row[3]) == lease_epoch
                and cast(bool, row[4])
            )

        return self._database.transaction(check)

    def command_completed(
        self, *, principal_id: UUID, command_id: UUID, idempotency_key: UUID
    ) -> bool:
        return self._database.transaction(
            lambda connection: connection.execute(
                """SELECT 1 FROM idempotency_records
                   WHERE principal_id=%s AND key=%s AND command_id=%s AND completed""",
                (principal_id, idempotency_key, command_id),
            ).fetchone()
            is not None
        )

    def artifact_in_job_scope(
        self,
        *,
        principal_id: UUID,
        role_kinds: frozenset[str],
        scope: JobScope,
        artifact_hash: str,
    ) -> bool:
        def check(connection: Connection[tuple[object, ...]]) -> bool:
            row = connection.execute(
                """SELECT kind,state,worker_id,lease_epoch,expires_at>clock_timestamp(),
                          encode(input_manifest_hash,'hex')
                   FROM jobs WHERE id=%s""",
                (scope.job_id,),
            ).fetchone()
            if not (
                row is not None
                and str(row[0]) in role_kinds
                and row[1] == "running"
                and row[2] == principal_id
                and cast(int, row[3]) == scope.lease_epoch
                and cast(bool, row[4])
            ):
                return False
            root = str(row[5])
            visible = connection.execute(
                """WITH RECURSIVE allowed(manifest_hash) AS (
                       SELECT decode(%s,'hex')
                       UNION
                       SELECT edge.input_hash
                       FROM artifact_production_edges edge
                       JOIN allowed ON edge.manifest_hash=allowed.manifest_hash
                   )
                   SELECT 1 FROM allowed
                   LEFT JOIN artifact_productions p ON p.manifest_hash=allowed.manifest_hash
                   WHERE allowed.manifest_hash=decode(%s,'hex')
                      OR p.artifact_hash=decode(%s,'hex') LIMIT 1""",
                (root, artifact_hash, artifact_hash),
            ).fetchone()
            return visible is not None

        return self._database.transaction(check)

    def job_scope_active(
        self,
        *,
        principal_id: UUID,
        role_kinds: frozenset[str],
        scope: JobScope,
    ) -> bool:
        def check(connection: Connection[tuple[object, ...]]) -> bool:
            row = connection.execute(
                """SELECT 1 FROM jobs WHERE id=%s AND kind=ANY(%s)
                   AND state='running' AND worker_id=%s AND lease_epoch=%s
                   AND expires_at>clock_timestamp()""",
                (scope.job_id, list(role_kinds), principal_id, scope.lease_epoch),
            ).fetchone()
            return row is not None

        return self._database.transaction(check)
