"""Frozen snapshot records pinning the papers and indexes visible to a run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.snapshots import (
    snapshot_identity,
    validate_snapshot_payload,
)
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.verification import ArtifactVerifier


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SnapshotRepository:
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
        self._verifier = ArtifactVerifier(store)
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        value = validate_snapshot_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._seal(connection, identity, value)

        return self._commands.execute(identity, "/v1/snapshots", {}, value, mutate)

    def _seal(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        self._verifier.verify(connection, value["paper_manifest_hash"])
        snapshot_hash = snapshot_identity(
            value["paper_manifest_hash"], value["index_identity_hashes"]
        )
        row = connection.execute(
            """INSERT INTO snapshots(hash, paper_manifest_hash, sealed_at)
               VALUES(decode(%s,'hex'), decode(%s,'hex'), clock_timestamp())
               ON CONFLICT (hash) DO NOTHING RETURNING sealed_at""",
            (snapshot_hash, value["paper_manifest_hash"]),
        ).fetchone()
        created = row is not None
        if created:
            for ordinal, index_hash in enumerate(value["index_identity_hashes"]):
                connection.execute(
                    """INSERT INTO snapshot_indexes(snapshot_hash, ordinal, index_hash)
                       VALUES(decode(%s,'hex'), %s, decode(%s,'hex'))""",
                    (snapshot_hash, ordinal, index_hash),
                )
        else:
            row = connection.execute(
                "SELECT sealed_at FROM snapshots WHERE hash=decode(%s,'hex')",
                (snapshot_hash,),
            ).fetchone()
        assert row is not None
        sealed_at = _utc(cast(datetime, row[0]))
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="snapshot_sealed",
            payload={
                "schema_version": 1,
                "snapshot_hash": snapshot_hash,
                "paper_manifest_hash": value["paper_manifest_hash"],
                "index_identity_hashes": value["index_identity_hashes"],
                "sealed_at": sealed_at,
            },
            input_hashes=(value["paper_manifest_hash"],),
        )
        return {
            "snapshot_hash": snapshot_hash,
            "sealed_at": sealed_at,
            "receipt": receipt,
        }
