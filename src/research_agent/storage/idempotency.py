"""Durable command idempotency within caller-owned transactions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from psycopg import Connection
from research_agent.contracts import canonical_json
from research_agent.storage.errors import IdempotencyConflict


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status_code: int
    body: bytes
    replayed: bool


def command_content_hash(
    route_template: str, path_ids: dict[str, str], payload: object
) -> bytes:
    body = canonical_json(
        {"route_template": route_template, "path_ids": path_ids, "payload": payload}
    )
    return hashlib.sha256(body).digest()


class IdempotencyRepository:
    """Claim and complete commands without autonomous commits."""

    def begin(
        self,
        connection: Connection[tuple[object, ...]],
        *,
        principal_id: UUID,
        key: UUID,
        command_id: UUID,
        content_hash: bytes,
    ) -> StoredResponse | None:
        claimed = connection.execute(
            """
            INSERT INTO idempotency_records(
                principal_id, key, command_id, content_hash, status_code, response_body
            ) VALUES (%s, %s, %s, %s, NULL, NULL)
            ON CONFLICT DO NOTHING
            RETURNING key
            """,
            (principal_id, key, command_id, content_hash),
        ).fetchone()
        if claimed is not None:
            return None

        existing = connection.execute(
            """
            SELECT command_id, content_hash, status_code, response_body, completed
            FROM idempotency_records
            WHERE principal_id = %s AND key = %s
            FOR UPDATE
            """,
            (principal_id, key),
        ).fetchone()
        if existing is not None:
            if not existing[4]:
                raise IdempotencyConflict("idempotency command is incomplete")
            if bytes(cast(bytes | memoryview, existing[1])) != content_hash:
                raise IdempotencyConflict(
                    "idempotency key was reused for different content"
                )
            return StoredResponse(
                cast(int, existing[2]),
                bytes(cast(bytes | memoryview, existing[3])),
                True,
            )

        command = connection.execute(
            """
            SELECT key, content_hash, status_code, response_body, completed
            FROM idempotency_records
            WHERE principal_id = %s AND command_id = %s
            FOR UPDATE
            """,
            (principal_id, command_id),
        ).fetchone()
        if command is not None:
            if not command[4]:
                raise IdempotencyConflict("idempotency command is incomplete")
            if bytes(cast(bytes | memoryview, command[1])) != content_hash:
                raise IdempotencyConflict("command id was reused for different content")
            return StoredResponse(
                cast(int, command[2]), bytes(cast(bytes | memoryview, command[3])), True
            )
        return None

    def finish(
        self,
        connection: Connection[tuple[object, ...]],
        *,
        principal_id: UUID,
        key: UUID,
        command_id: UUID,
        content_hash: bytes,
        status_code: int,
        response_body: bytes,
    ) -> StoredResponse:
        updated = connection.execute(
            """
            UPDATE idempotency_records
            SET status_code = %s, response_body = %s,
                committed_at = transaction_timestamp(), completed = true
            WHERE principal_id = %s AND key = %s AND command_id = %s
              AND content_hash = %s AND completed = false
            """,
            (status_code, response_body, principal_id, key, command_id, content_hash),
        )
        if updated.rowcount != 1:
            raise IdempotencyConflict(
                "command identity is not owned by this transaction"
            )
        return StoredResponse(status_code, response_body, False)
