"""What one run cost the system: tokens, timing, network, files, CPU, memory (#330).

The orchestrator records a run's resources once, after its settlement
(#251): each model call's input, cached input and output tokens with the
model identity the provider returned (#307), its latency and the bytes it
sent and received; the model endpoint and tool service address the run
reached; the run's start, first and last model call and end instants; the
process's CPU seconds and peak memory and the host's load at start and end;
and the worker image digest and run log path when the launcher knows them.

When the settlement's tokens came from the provider's usage records, the
calls must sum to them exactly: a record that disagrees is refused. The row
and its ``run_resources_recorded`` ledger event commit together and nothing
edits them.

``read`` adds what storage already holds: the queue wait from the run's
creation to its start, each tool call's service time from the trace, and
the artifact store paths of the trace's request and response payloads.
Nothing here reaches the agent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json, canonical_loads
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_sha256,
    validate_utc_instant,
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

MAXIMUM_MODEL_CALLS = 1000
PROCESS_KINDS = frozenset({"in_process", "container"})
_CALL_FIELDS = frozenset(
    {
        "turn_index",
        "model",
        "revision",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "latency_ms",
        "bytes_sent",
        "bytes_received",
    }
)
_PROCESS_FIELDS = frozenset(
    {"kind", "cpu_user_ms", "cpu_system_ms", "peak_rss_bytes", "load_start", "load_end"}
)
_FIELDS = frozenset(
    {
        "run_id",
        "started_at",
        "first_model_call_at",
        "last_model_call_at",
        "ended_at",
        "model_endpoint",
        "tool_service",
        "model_calls",
        "process",
        "image_digest",
        "run_log",
    }
)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= limit or "\x00" in value:
        raise ContractValidationError(f"resources {field} is invalid")
    return value


def _optional(value: object, check: Any) -> Any:
    return None if value is None else check(value)


def _fields(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"resources {name} has unknown or missing fields")
    return value


def _load(value: object) -> list[int]:
    """Host load averages over 1, 5 and 15 minutes, in hundredths."""

    if not isinstance(value, list) or len(value) != 3:
        raise ContractValidationError("resources load is three integers")
    return [validate_non_negative_int(item) for item in value]


def _call(value: object) -> dict[str, Any]:
    call = _fields(value, _CALL_FIELDS, "model call")
    return {
        "turn_index": validate_non_negative_int(call["turn_index"]),
        "model": _text(call["model"], "model", 128),
        "revision": _optional(
            call["revision"], lambda item: _text(item, "revision", 128)
        ),
        **{
            name: validate_non_negative_int(call[name])
            for name in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "latency_ms",
                "bytes_sent",
            )
        },
        "bytes_received": _optional(call["bytes_received"], validate_non_negative_int),
    }


def validate_resources_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a resources operation."""

    if operation != "record":
        raise ContractValidationError("unknown resources operation")
    value = _fields(payload, _FIELDS, "payload")
    calls = value["model_calls"]
    if not isinstance(calls, list) or len(calls) > MAXIMUM_MODEL_CALLS:
        raise ContractValidationError(
            f"model_calls must be a JSON array of at most {MAXIMUM_MODEL_CALLS}"
        )
    model_calls = [_call(item) for item in calls]
    if [call["turn_index"] for call in model_calls] != list(range(len(model_calls))):
        raise ContractValidationError("model_calls are numbered from zero in order")
    process = _fields(value["process"], _PROCESS_FIELDS, "process")
    if process["kind"] not in PROCESS_KINDS:
        raise ContractValidationError("resources process kind is invalid")
    started_at = validate_utc_instant(value["started_at"])
    ended_at = validate_utc_instant(value["ended_at"])
    first = _optional(value["first_model_call_at"], validate_utc_instant)
    last = _optional(value["last_model_call_at"], validate_utc_instant)
    if (first is None) != (not model_calls) or (first is None) != (last is None):
        raise ContractValidationError(
            "first and last model call instants are present exactly when calls are"
        )
    if not started_at <= (first or started_at) <= (last or ended_at) <= ended_at:
        raise ContractValidationError("resources instants are out of order")
    return {
        "run_id": validate_uuid4(value["run_id"]),
        "started_at": started_at,
        "first_model_call_at": first,
        "last_model_call_at": last,
        "ended_at": ended_at,
        "model_endpoint": _text(value["model_endpoint"], "model_endpoint", 512),
        "tool_service": _text(value["tool_service"], "tool_service", 512),
        "model_calls": model_calls,
        "process": {
            "kind": process["kind"],
            "cpu_user_ms": validate_non_negative_int(process["cpu_user_ms"]),
            "cpu_system_ms": validate_non_negative_int(process["cpu_system_ms"]),
            "peak_rss_bytes": validate_non_negative_int(process["peak_rss_bytes"]),
            "load_start": _load(process["load_start"]),
            "load_end": _load(process["load_end"]),
        },
        "image_digest": _optional(value["image_digest"], validate_sha256),
        "run_log": _optional(
            value["run_log"], lambda item: _text(item, "run_log", 1024)
        ),
    }


def _sum(calls: list[dict[str, Any]], field: str) -> int:
    return sum(int(call[field]) for call in calls)


class ResourceRepository:
    """Records one run's resources and reads them with the trace's timing."""

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
        self._store = store
        self._commands = CommandTransaction(database)
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        value = validate_resources_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._record(connection, identity, value)

        return self._commands.execute(
            identity, "/v1/runs/{id}/resources", {"id": value["run_id"]}, value, mutate
        )

    def _record(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        settlement = connection.execute(
            """SELECT input_tokens, output_tokens, usage_source FROM run_settlements
               WHERE run_id=%s""",
            (value["run_id"],),
        ).fetchone()
        if settlement is None:
            raise UnavailableInput("resources name a run that is not settled")
        calls = value["model_calls"]
        totals = {
            name: _sum(calls, name)
            for name in ("input_tokens", "cached_input_tokens", "output_tokens")
        }
        # A settlement from the provider's usage records is the calls' sum;
        # one the loop counted may cover a turn the provider never answered.
        if settlement[2] == "provider" and (
            totals["input_tokens"] != settlement[0]
            or totals["output_tokens"] != settlement[1]
        ):
            raise StateConflict("model calls do not sum to the run's settlement")
        recorded = connection.execute(
            "SELECT 1 FROM run_resources WHERE run_id=%s", (value["run_id"],)
        ).fetchone()
        if recorded is not None:
            raise StateConflict("run resources are already recorded")
        recorded_at = datetime.now(timezone.utc)
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="run_resources_recorded",
            payload={"schema_version": 1, **value, "recorded_at": _utc(recorded_at)},
            input_hashes=(),
        )
        connection.execute(
            """INSERT INTO run_resources(
                   run_id, record, model_calls, input_tokens, cached_input_tokens,
                   output_tokens, recorded_at, ledger_sequence
               ) VALUES(%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                value["run_id"],
                canonical_json(value),
                len(calls),
                totals["input_tokens"],
                totals["cached_input_tokens"],
                totals["output_tokens"],
                recorded_at,
                receipt["ledger_last"],
            ),
        )
        return {
            "run_id": value["run_id"],
            "recorded_at": _utc(recorded_at),
            "receipt": receipt,
        }

    def read(self, run_id: str) -> dict[str, Any] | None:
        """A run's resources section, or ``None`` before they are recorded."""

        validate_uuid4(run_id)

        def select(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[tuple[object, ...], list[tuple[object, ...]]] | None:
            row = connection.execute(
                """SELECT r.record, r.recorded_at, runs.created_at
                   FROM run_resources r JOIN runs ON runs.id = r.run_id
                   WHERE r.run_id=%s""",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            calls = connection.execute(
                """SELECT c.call_sequence, c.tool, c.started_at, t.ended_at,
                          encode(c.request_artifact,'hex'),
                          encode(t.response_artifact,'hex')
                   FROM run_trace_calls c
                   LEFT JOIN run_trace_terminals t
                     ON t.run_id = c.run_id AND t.call_sequence = c.call_sequence
                   WHERE c.run_id=%s ORDER BY c.call_sequence""",
                (run_id,),
            ).fetchall()
            return row, calls

        selected = self._database.transaction(select)
        if selected is None:
            return None
        row, calls = selected
        record = cast(dict[str, Any], canonical_loads(bytes(cast(bytes, row[0]))))
        created_at = cast(datetime, row[2])
        started_at = _instant(record["started_at"])
        ended_at = _instant(record["ended_at"])
        first = record["first_model_call_at"]
        tool_calls = []
        for call in calls:
            started = cast(datetime, call[2])
            ended = cast(datetime | None, call[3])
            tool_calls.append(
                {
                    "call_sequence": call[0],
                    "tool": call[1],
                    "service_ms": None if ended is None else _ms(ended - started),
                    "request_path": self._path(call[4]),
                    "response_path": self._path(call[5]),
                }
            )
        return {
            **record,
            "recorded_at": _utc(cast(datetime, row[1])),
            "slot_created_at": _utc(created_at),
            "queue_wait_ms": max(0, _ms(started_at - created_at)),
            "first_model_call_to_end_ms": None
            if first is None
            else _ms(ended_at - _instant(first)),
            "wall_ms": _ms(ended_at - started_at),
            "tokens": {
                name: _sum(record["model_calls"], name)
                for name in ("input_tokens", "cached_input_tokens", "output_tokens")
            },
            "tool_calls": tool_calls,
        }

    def _path(self, artifact: object) -> str | None:
        return None if artifact is None else str(self._store.path_for(str(artifact)))


def _ms(delta: Any) -> int:
    return int(delta.total_seconds() * 1000)
