"""Settled inference spend: one row per run and the owner's cost windows (#251).

A run's settlement records what the loop received by the time the run
ended, however it ended: the provider and model that served it, input and
output tokens, and ``usage_source`` -- ``provider`` when every response
carried the provider's usage record, ``loop_count`` when the loop's own
counts filled any gap. ``cost_micros`` stays null until a price quote owner
exists (TDD Spending authorization); nothing here invents a price. Only the
orchestrator records a settlement, once per run, with its ``run_settled``
ledger event.

The owner's read sums ``cost_micros`` over priced rows of a UTC day and of
its month up to that day's end, and reports the unpriced rows' tokens
beside the sum, also per island and per configuration.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast
from uuid import UUID

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_uuid4,
)
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.idempotency import StoredResponse

USAGE_SOURCES = frozenset({"provider", "loop_count"})
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_TOTALS = """coalesce(sum(s.cost_micros), 0)::bigint,
             count(s.cost_micros),
             count(*) - count(s.cost_micros),
             coalesce(sum(s.input_tokens) FILTER (WHERE s.cost_micros IS NULL), 0)::bigint,
             coalesce(sum(s.output_tokens) FILTER (WHERE s.cost_micros IS NULL), 0)::bigint"""


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _name(value: object, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or "\x00" in value:
        raise ContractValidationError(f"settlement {field} is invalid")
    return value


def validate_day(value: object) -> date:
    """A UTC calendar day written ``YYYY-MM-DD``, nothing looser."""

    if not isinstance(value, str) or _DAY.fullmatch(value) is None:
        raise ContractValidationError("day must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ContractValidationError("day must be YYYY-MM-DD") from error


def validate_settlement_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a settlement operation."""

    if operation != "record":
        raise ContractValidationError("unknown settlement operation")
    if not isinstance(payload, dict) or set(payload) != {
        "run_id",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "usage_source",
    }:
        raise ContractValidationError(
            "settlement payload has unknown or missing fields"
        )
    if payload["usage_source"] not in USAGE_SOURCES:
        raise ContractValidationError("settlement usage_source is invalid")
    return {
        "run_id": validate_uuid4(payload["run_id"]),
        "provider": _name(payload["provider"], "provider"),
        "model": _name(payload["model"], "model"),
        "input_tokens": validate_non_negative_int(payload["input_tokens"]),
        "output_tokens": validate_non_negative_int(payload["output_tokens"]),
        "usage_source": payload["usage_source"],
    }


def _totals(row: tuple[object, ...]) -> dict[str, int]:
    return {
        "priced_micros": cast(int, row[0]),
        "priced_runs": cast(int, row[1]),
        "unpriced_runs": cast(int, row[2]),
        "unpriced_input_tokens": cast(int, row[3]),
        "unpriced_output_tokens": cast(int, row[4]),
    }


class SettlementRepository:
    """Records one settlement per run and reads the owner's cost windows."""

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
        value = validate_settlement_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._record(connection, identity, value)

        return self._commands.execute(identity, "/v1/settlements", {}, value, mutate)

    def _record(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        run = connection.execute(
            "SELECT 1 FROM runs WHERE id=%s", (value["run_id"],)
        ).fetchone()
        if run is None:
            raise UnavailableInput("settlement names an unknown run")
        settled = connection.execute(
            "SELECT 1 FROM run_settlements WHERE run_id=%s", (value["run_id"],)
        ).fetchone()
        if settled is not None:
            raise StateConflict("run is already settled")
        settled_at = datetime.now(timezone.utc)
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="run_settled",
            payload={
                "schema_version": 1,
                **value,
                "cost_micros": None,
                "settled_at": _utc(settled_at),
            },
            input_hashes=(),
        )
        inserted = connection.execute(
            """INSERT INTO run_settlements(
                   run_id, provider, model, input_tokens, output_tokens,
                   usage_source, cost_micros, settled_at, ledger_sequence
               ) VALUES(%s, %s, %s, %s, %s, %s, NULL, %s, %s)
               ON CONFLICT (run_id) DO NOTHING RETURNING run_id""",
            (
                value["run_id"],
                value["provider"],
                value["model"],
                value["input_tokens"],
                value["output_tokens"],
                value["usage_source"],
                settled_at,
                receipt["ledger_last"],
            ),
        ).fetchone()
        if inserted is None:
            raise StateConflict("run settled concurrently")
        return {
            "run_id": value["run_id"],
            "settled_at": _utc(settled_at),
            "receipt": receipt,
        }

    def costs(self, day: str) -> dict[str, Any]:
        """Settled spend of one UTC day and of its month up to that day's end."""

        parsed = validate_day(day)
        day_start = datetime.combine(parsed, time(), tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        month_start = day_start.replace(day=1)

        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            window = "s.settled_at >= %s AND s.settled_at < %s"
            day_row = connection.execute(
                f"SELECT {_TOTALS} FROM run_settlements s WHERE {window}",
                (day_start, day_end),
            ).fetchone()
            month_row = connection.execute(
                f"SELECT {_TOTALS} FROM run_settlements s WHERE {window}",
                (month_start, day_end),
            ).fetchone()
            assert day_row is not None and month_row is not None
            joined = f"""FROM run_settlements s
                JOIN runs r ON r.id = s.run_id
                LEFT JOIN genomes g ON g.configuration_id = r.configuration_id
                WHERE {window}"""
            islands = connection.execute(
                f"""SELECT g.island, {_TOTALS} {joined}
                    GROUP BY g.island ORDER BY g.island NULLS LAST""",
                (month_start, day_end),
            ).fetchall()
            configurations = connection.execute(
                f"""SELECT r.configuration_id, g.island, {_TOTALS} {joined}
                    GROUP BY r.configuration_id, g.island
                    ORDER BY r.configuration_id""",
                (month_start, day_end),
            ).fetchall()
            return {
                "day": parsed.isoformat(),
                "month": parsed.strftime("%Y-%m"),
                "day_totals": _totals(day_row),
                "month_totals": _totals(month_row),
                "islands": [{"island": row[0], **_totals(row[1:])} for row in islands],
                "configurations": [
                    {
                        "configuration_id": str(cast(UUID, row[0])),
                        "island": row[1],
                        **_totals(row[2:]),
                    }
                    for row in configurations
                ],
            }

        return self._database.transaction(read)
