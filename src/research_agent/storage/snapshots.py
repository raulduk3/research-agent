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
from research_agent.storage.errors import UnavailableInput
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
        if operation == "seal":
            route, path_ids = "/v1/snapshots", {}
        else:
            route, path_ids = (
                "/v1/snapshots/{hash}/items",
                {"hash": value["snapshot_hash"]},
            )

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            if operation == "seal":
                return self._seal(connection, identity, value)
            return self._pin_items(connection, identity, value)

        return self._commands.execute(identity, route, path_ids, value, mutate)

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

    def _pin_items(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_hash, sheet_hash = value["snapshot_hash"], value["sheet_hash"]
        if (
            connection.execute(
                "SELECT 1 FROM snapshots WHERE hash=decode(%s,'hex')", (snapshot_hash,)
            ).fetchone()
            is None
        ):
            raise UnavailableInput("pin_items names an unsealed snapshot")
        if (
            connection.execute(
                "SELECT 1 FROM sheets WHERE hash=decode(%s,'hex')", (sheet_hash,)
            ).fetchone()
            is None
        ):
            raise UnavailableInput("pin_items names an unsealed sheet")
        for item in value["items"]:
            for hash_field in (
                "card_hash",
                "overview_hash",
                "passage_index_hash",
                "graph_hash",
            ):
                artifact_hash = item[hash_field]
                if artifact_hash is not None:
                    self._verifier.verify(connection, artifact_hash)
            connection.execute(
                """INSERT INTO snapshot_items(
                       snapshot_hash, paper_family_id, paper_version_id, card_hash,
                       overview_hash, passage_index_hash, graph_hash
                   ) VALUES(
                       decode(%s,'hex'), %s, %s, decode(%s,'hex'),
                       decode(%s,'hex'), decode(%s,'hex'), decode(%s,'hex')
                   ) ON CONFLICT (snapshot_hash, paper_version_id) DO NOTHING""",
                (
                    snapshot_hash,
                    item["paper_family_id"],
                    item["paper_version_id"],
                    item["card_hash"],
                    item["overview_hash"],
                    item["passage_index_hash"],
                    item["graph_hash"],
                ),
            )
        connection.execute(
            """INSERT INTO snapshot_sheets(snapshot_hash, sheet_hash)
               VALUES(decode(%s,'hex'), decode(%s,'hex'))
               ON CONFLICT (snapshot_hash, sheet_hash) DO NOTHING""",
            (snapshot_hash, sheet_hash),
        )
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="snapshot_items_pinned",
            payload={
                "schema_version": 1,
                "snapshot_hash": snapshot_hash,
                "sheet_hash": sheet_hash,
                "items": value["items"],
            },
            input_hashes=tuple(
                item[field]
                for item in value["items"]
                for field in (
                    "card_hash",
                    "overview_hash",
                    "passage_index_hash",
                    "graph_hash",
                )
                if item[field] is not None
            ),
        )
        return {
            "snapshot_hash": snapshot_hash,
            "sheet_hash": sheet_hash,
            "pinned_count": len(value["items"]),
            "receipt": receipt,
        }
