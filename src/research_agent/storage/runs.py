"""Immutable run specifications and their appended request/response events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json
from research_agent.contracts.runs import validate_run_payload
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.idempotency import StoredResponse


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RunRepository:
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
        value = validate_run_payload(operation, payload)
        if operation == "create":
            route, path_ids = "/v1/runs", {}
        elif operation == "append_event":
            route, path_ids = "/v1/runs/{id}/events", {"id": value["run_id"]}
        else:
            raise ValueError("unknown run operation")

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            if operation == "create":
                return self._create(connection, identity, value)
            return self._append_event(connection, identity, value)

        return self._commands.execute(identity, route, path_ids, value, mutate)

    def _create(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        slot = value["slot"]
        sheet = connection.execute(
            "SELECT 1 FROM sheets WHERE hash=decode(%s,'hex')", (slot["batch_id"],)
        ).fetchone()
        if sheet is None:
            raise UnavailableInput("run slot names an unsealed sheet")
        snapshot = connection.execute(
            "SELECT 1 FROM snapshots WHERE hash=decode(%s,'hex')",
            (value["snapshot_hash"],),
        ).fetchone()
        if snapshot is None:
            raise UnavailableInput("run specification names an unsealed snapshot")
        slot_holder = connection.execute(
            """SELECT id FROM runs WHERE batch_id=decode(%s,'hex') AND paper_id=%s
               AND configuration_id=%s AND attempt=%s FOR UPDATE""",
            (
                slot["batch_id"],
                slot["paper_id"],
                slot["configuration_id"],
                slot["attempt"],
            ),
        ).fetchone()
        if slot_holder is not None and str(slot_holder[0]) != value["run_id"]:
            raise StateConflict("run slot is already assigned to another run")
        budgets = canonical_json(value["budgets"])
        model_identity = canonical_json(value["model_identity"])
        checkpoint_dates = canonical_json(value["checkpoint_dates"])
        inserted = connection.execute(
            """INSERT INTO runs(
                   id, batch_id, paper_id, configuration_id, attempt, genome_hash,
                   seed, snapshot_hash, budgets, allowed_tools, model_identity,
                   checkpoint_dates, issued_question_ids, created_at
               ) VALUES(
                   %s, decode(%s,'hex'), %s, %s, %s, decode(%s,'hex'), %s,
                   decode(%s,'hex'), %s, %s, %s, %s, %s, clock_timestamp()
               ) ON CONFLICT (id) DO NOTHING RETURNING created_at""",
            (
                value["run_id"],
                slot["batch_id"],
                slot["paper_id"],
                slot["configuration_id"],
                slot["attempt"],
                value["genome_hash"],
                value["seed"],
                value["snapshot_hash"],
                budgets,
                value["allowed_tools"],
                model_identity,
                checkpoint_dates,
                value["issued_question_ids"],
            ),
        ).fetchone()
        if inserted is None:
            existing = connection.execute(
                "SELECT created_at FROM runs WHERE id=%s", (value["run_id"],)
            ).fetchone()
            assert existing is not None
            created_at = _utc(cast(datetime, existing[0]))
        else:
            created_at = _utc(cast(datetime, inserted[0]))
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="run_created",
            payload={"schema_version": 1, "created_at": created_at, **value},
            input_hashes=(),
        )
        return {"run_id": value["run_id"], "created_at": created_at, "receipt": receipt}

    def _append_event(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        run = connection.execute(
            "SELECT 1 FROM runs WHERE id=%s", (value["run_id"],)
        ).fetchone()
        if run is None:
            raise UnavailableInput("run event names an unknown run")
        latest = connection.execute(
            """SELECT ordinal FROM run_events
               WHERE run_id=%s AND attempt=%s
               ORDER BY ordinal DESC LIMIT 1 FOR UPDATE""",
            (value["run_id"], value["attempt"]),
        ).fetchone()
        expected = 0 if latest is None else cast(int, latest[0]) + 1
        if value["ordinal"] != expected:
            raise StateConflict("run event ordinal is not the next in order")
        connection.execute(
            """INSERT INTO run_events(run_id, attempt, ordinal, kind, payload_hash, recorded_at)
               VALUES(%s, %s, %s, %s, decode(%s,'hex'), clock_timestamp())""",
            (
                value["run_id"],
                value["attempt"],
                value["ordinal"],
                value["kind"],
                value["payload_hash"],
            ),
        )
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="run_event",
            payload={"schema_version": 1, **value},
            input_hashes=(),
        )
        return {
            "run_id": value["run_id"],
            "attempt": value["attempt"],
            "ordinal": value["ordinal"],
            "receipt": receipt,
        }
