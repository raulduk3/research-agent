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
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.quarantine import entry_is_quarantined


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
        self._database = database
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
        authorized = connection.execute(
            """SELECT encode(e.paper_hash,'hex'), p.island, d.island
               FROM rater_principals p
               JOIN digest_entries e ON e.entry_id = %s
               JOIN digests d ON d.hash = e.digest_hash
               WHERE p.rater_id = %s""",
            (value["digest_entry_id"], value["rater_id"]),
        ).fetchone()
        if (
            authorized is None
            or authorized[0] != value["paper_hash"]
            or _digest_island(cast(str, authorized[1])) != authorized[2]
        ):
            raise UnavailableInput("rating entry is unavailable to this rater")
        if entry_is_quarantined(connection, value["digest_entry_id"]):
            raise StateConflict("digest entry holds only quarantined run output")
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

    def rated_entries(self, rater_id: str) -> tuple[dict[str, str], ...]:
        """The entries one rater has rated, without the rating's value.

        The value is the rater's own; a reader that only needs to know
        whether an entry was rated learns nothing else (SR-25).
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[dict[str, str], ...]:
            rows = connection.execute(
                """SELECT digest_entry_id, encode(paper_hash,'hex')
                   FROM ratings WHERE rater_id=%s ORDER BY rated_at, id""",
                (rater_id,),
            ).fetchall()
            return tuple(
                {"entry_id": str(row[0]), "paper_hash": cast(str, row[1])}
                for row in rows
            )

        return self._database.transaction(read)

    def ratings_in_batch(
        self, rater_id: str, batch_id: str
    ) -> tuple[dict[str, str], ...]:
        """One rater's own ratings of a batch's digest entries, with their values.

        Only the rater's own session reaches this read (#252); it is the
        record of what that rater did, so the value is theirs to see.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[dict[str, str], ...]:
            rows = connection.execute(
                """SELECT r.id, r.digest_entry_id, encode(r.paper_hash,'hex'),
                          r.value, r.rated_at
                   FROM ratings r
                   JOIN digest_entries e ON e.entry_id = r.digest_entry_id
                   JOIN digests d ON d.hash = e.digest_hash
                   WHERE r.rater_id = %s AND d.batch_id = decode(%s,'hex')
                   ORDER BY r.rated_at, r.id""",
                (rater_id, batch_id),
            ).fetchall()
            return tuple(
                {
                    "rating_id": str(row[0]),
                    "digest_entry_id": str(row[1]),
                    "paper_hash": cast(str, row[2]),
                    "value": cast(str, row[3]),
                    "rated_at": _utc(cast(datetime, row[4])),
                }
                for row in rows
            )

        return self._database.transaction(read)


def _digest_island(rater_island: str) -> str | None:
    """Map the rater-binding spelling to the stored digest spelling."""

    return {"cs": "cs", "quant_ph": "quant-ph"}.get(rater_island)
