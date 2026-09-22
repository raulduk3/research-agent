"""Issued question sheets sealed before any claim can be made against them."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.questions import sheet_identity, validate_sheet_payload
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.idempotency import StoredResponse


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SheetRepository:
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
        value = validate_sheet_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._seal(connection, identity, value)

        return self._commands.execute(identity, "/v1/sheets", {}, value, mutate)

    def _seal(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        questions = value["questions"]
        sheet_hash = sheet_identity(questions)
        row = connection.execute(
            """INSERT INTO sheets(hash, sealed_at) VALUES(decode(%s,'hex'), clock_timestamp())
               ON CONFLICT (hash) DO NOTHING RETURNING sealed_at""",
            (sheet_hash,),
        ).fetchone()
        created = row is not None
        if created:
            for ordinal, question in enumerate(questions):
                connection.execute(
                    """INSERT INTO sheet_questions(
                           sheet_hash, ordinal, question_id, target_definition_hash,
                           resolver_id, resolver_version, horizon
                       ) VALUES(decode(%s,'hex'), %s, %s, decode(%s,'hex'), %s, %s, %s)""",
                    (
                        sheet_hash,
                        ordinal,
                        question["question_id"],
                        question["target_definition_hash"],
                        question["resolver_id"],
                        question["resolver_version"],
                        question["horizon"],
                    ),
                )
        else:
            row = connection.execute(
                "SELECT sealed_at FROM sheets WHERE hash=decode(%s,'hex')",
                (sheet_hash,),
            ).fetchone()
        assert row is not None
        sealed_at = _utc(cast(datetime, row[0]))
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="sheet_sealed",
            payload={
                "schema_version": 1,
                "sheet_hash": sheet_hash,
                "questions": questions,
                "sealed_at": sealed_at,
            },
            input_hashes=(),
        )
        return {"sheet_hash": sheet_hash, "sealed_at": sealed_at, "receipt": receipt}
