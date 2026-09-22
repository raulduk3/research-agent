"""One immutable rating per rater, paper and digest entry (IN-10)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.submissions import validate_rating_payload
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict
from research_agent.storage.idempotency import StoredResponse


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RatingRepository:
    def __init__(
        self,
        database: Database,
        store: ArtifactStore,
        *,
        producer: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
    ) -> None:
        self._commands = CommandTransaction(database)
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        value = validate_rating_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._record(connection, identity, value)

        return self._commands.execute(identity, "/v1/ratings", {}, value, mutate)

    def _record(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        rating_id = uuid4()
        inserted = connection.execute(
            """INSERT INTO ratings(id, rater_id, paper_hash, digest_entry_id, value, rated_at)
               VALUES(%s, %s, decode(%s,'hex'), %s, %s, clock_timestamp())
               ON CONFLICT (rater_id, digest_entry_id) DO NOTHING RETURNING rated_at""",
            (
                rating_id,
                value["rater_id"],
                value["paper_hash"],
                value["digest_entry_id"],
                value["value"],
            ),
        ).fetchone()
        if inserted is None:
            raise StateConflict("rater already rated this digest entry")
        rated_at = _utc(cast(datetime, inserted[0]))
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="rating_recorded",
            payload={
                "schema_version": 1,
                "rating_id": str(rating_id),
                "rated_at": rated_at,
                **value,
            },
            input_hashes=(),
        )
        return {"rating_id": str(rating_id), "rated_at": rated_at, "receipt": receipt}
