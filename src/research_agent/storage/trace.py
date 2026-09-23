"""A run's externally captured tool trace (TDD-2.1.2, TDD-2.1.36, #297).

The shared tool service records every call a run makes here, through its
own storage route, before it executes the call: ``request`` allocates the
run's next call sequence and records the call's request hash and schema
decision. A refused call is an entry too, recorded with its refusal reason,
and it is already resolved; it takes no terminal event. An admitted call is
resolved by exactly one ``terminal`` event, a response or an error with its
response hash, the artifact ids it retrieved and its budget deltas. Nothing
edits a recorded row: a terminal is a second row, never an update of the
request, and both tables are immutable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_sha256,
    validate_uuid4,
)
from research_agent.contracts.runs import BUDGET_FIELDS
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.idempotency import StoredResponse

TRACE_DECISIONS = frozenset({"admitted", "refused"})
TRACE_OUTCOMES = frozenset({"response", "error"})
MAXIMUM_RETRIEVED_IDS = 100
_CODE = re.compile(r"[a-z][a-z_]{0,62}(:[a-z][a-z_]{0,62})?")


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _code(value: object, field: str) -> str:
    if not isinstance(value, str) or _CODE.fullmatch(value) is None:
        raise ContractValidationError(f"trace {field} is invalid")
    return value


def validate_trace_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a trace operation."""

    if operation == "request":
        fields = {"run_id", "call_id", "tool", "request_hash", "decision", "reason"}
        if not isinstance(payload, dict) or set(payload) != fields:
            raise ContractValidationError(
                "trace request payload has unknown or missing fields"
            )
        # A refused call may name any tool the agent wrote, so the name is
        # only bounded here; an admitted one must be a tool its run allows.
        tool = payload["tool"]
        if not isinstance(tool, str) or not 1 <= len(tool) <= 64 or "\x00" in tool:
            raise ContractValidationError("trace tool is invalid")
        decision = payload["decision"]
        if decision not in TRACE_DECISIONS:
            raise ContractValidationError("trace decision is invalid")
        refused = decision == "refused"
        if refused != (payload["reason"] is not None):
            raise ContractValidationError("a refused call, and only one, has a reason")
        return {
            "run_id": validate_uuid4(payload["run_id"]),
            "call_id": validate_uuid4(payload["call_id"]),
            "tool": tool,
            "request_hash": validate_sha256(payload["request_hash"]),
            "decision": decision,
            "reason": _code(payload["reason"], "reason") if refused else None,
        }
    if operation == "terminal":
        fields = {
            "run_id",
            "call_id",
            "outcome",
            "response_hash",
            "error_code",
            "retrieved_ids",
            "budget_deltas",
        }
        if not isinstance(payload, dict) or set(payload) != fields:
            raise ContractValidationError(
                "trace terminal payload has unknown or missing fields"
            )
        outcome = payload["outcome"]
        if outcome not in TRACE_OUTCOMES:
            raise ContractValidationError("trace outcome is invalid")
        failed = outcome == "error"
        if failed != (payload["error_code"] is not None):
            raise ContractValidationError("an error, and only one, has an error code")
        retrieved = payload["retrieved_ids"]
        if not isinstance(retrieved, list) or len(retrieved) > MAXIMUM_RETRIEVED_IDS:
            raise ContractValidationError(
                f"retrieved_ids must be a JSON array of at most {MAXIMUM_RETRIEVED_IDS}"
            )
        retrieved_ids = [validate_sha256(item) for item in retrieved]
        if len(set(retrieved_ids)) != len(retrieved_ids):
            raise ContractValidationError("retrieved_ids must be distinct")
        if failed and retrieved_ids:
            raise ContractValidationError("an error retrieves nothing")
        deltas = payload["budget_deltas"]
        if not isinstance(deltas, dict) or not set(deltas) <= BUDGET_FIELDS:
            raise ContractValidationError("budget_deltas names an unknown budget")
        return {
            "run_id": validate_uuid4(payload["run_id"]),
            "call_id": validate_uuid4(payload["call_id"]),
            "outcome": outcome,
            "response_hash": validate_sha256(payload["response_hash"]),
            "error_code": _code(payload["error_code"], "error_code")
            if failed
            else None,
            "retrieved_ids": retrieved_ids,
            "budget_deltas": {
                name: validate_non_negative_int(deltas[name]) for name in sorted(deltas)
            },
        }
    raise ContractValidationError("unknown trace operation")


class TraceRepository:
    """Records a run's tool calls and their terminal events (TDD-2.1.2)."""

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
        value = validate_trace_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            if operation == "request":
                return self._request(connection, identity, value)
            return self._terminal(connection, identity, value)

        route = (
            "/v1/runs/{id}/trace/requests"
            if operation == "request"
            else "/v1/runs/{id}/trace/terminals"
        )
        return self._commands.execute(
            identity, route, {"id": value["run_id"]}, value, mutate
        )

    def _request(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        run = connection.execute(
            "SELECT allowed_tools FROM runs WHERE id=%s", (value["run_id"],)
        ).fetchone()
        if run is None:
            raise UnavailableInput("trace request names an unknown run")
        if value["decision"] == "admitted" and value["tool"] not in cast(
            list[str], run[0]
        ):
            raise StateConflict("an admitted call names a tool the run does not allow")
        recorded = connection.execute(
            "SELECT 1 FROM run_trace_calls WHERE call_id=%s", (value["call_id"],)
        ).fetchone()
        if recorded is not None:
            raise StateConflict("trace call is already recorded")
        # The serializable transaction makes max+1 the run's one next sequence:
        # a concurrent request for the same run fails and is retried.
        row = connection.execute(
            """SELECT coalesce(max(call_sequence), 0) + 1 FROM run_trace_calls
               WHERE run_id=%s""",
            (value["run_id"],),
        ).fetchone()
        assert row is not None
        call_sequence = cast(int, row[0])
        started_at = datetime.now(timezone.utc)
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="trace_call_recorded",
            payload={
                "schema_version": 1,
                **value,
                "call_sequence": call_sequence,
                "started_at": _utc(started_at),
            },
            input_hashes=(),
        )
        connection.execute(
            """INSERT INTO run_trace_calls(
                   run_id, call_sequence, call_id, tool, request_hash, decision,
                   reason, started_at, ledger_sequence
               ) VALUES(%s, %s, %s, %s, decode(%s,'hex'), %s, %s, %s, %s)""",
            (
                value["run_id"],
                call_sequence,
                value["call_id"],
                value["tool"],
                value["request_hash"],
                value["decision"],
                value["reason"],
                started_at,
                receipt["ledger_last"],
            ),
        )
        return {
            "run_id": value["run_id"],
            "call_id": value["call_id"],
            "call_sequence": call_sequence,
            "started_at": _utc(started_at),
            "receipt": receipt,
        }

    def _terminal(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        call = connection.execute(
            """SELECT call_sequence, decision FROM run_trace_calls
               WHERE run_id=%s AND call_id=%s""",
            (value["run_id"], value["call_id"]),
        ).fetchone()
        if call is None:
            raise UnavailableInput("trace terminal names an unrecorded call")
        call_sequence = cast(int, call[0])
        if call[1] == "refused":
            raise StateConflict("a refused call takes no terminal event")
        ended = connection.execute(
            """SELECT 1 FROM run_trace_terminals
               WHERE run_id=%s AND call_sequence=%s""",
            (value["run_id"], call_sequence),
        ).fetchone()
        if ended is not None:
            raise StateConflict("trace call already has its terminal event")
        ended_at = datetime.now(timezone.utc)
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="trace_terminal_recorded",
            payload={
                "schema_version": 1,
                **value,
                "call_sequence": call_sequence,
                "ended_at": _utc(ended_at),
            },
            input_hashes=(),
        )
        connection.execute(
            """INSERT INTO run_trace_terminals(
                   run_id, call_sequence, outcome, response_hash, error_code,
                   retrieved_ids, budget_deltas, ended_at, ledger_sequence
               ) VALUES(%s, %s, %s, decode(%s,'hex'), %s, %s, %s, %s, %s)""",
            (
                value["run_id"],
                call_sequence,
                value["outcome"],
                value["response_hash"],
                value["error_code"],
                [bytes.fromhex(item) for item in value["retrieved_ids"]],
                canonical_json(value["budget_deltas"]),
                ended_at,
                receipt["ledger_last"],
            ),
        )
        return {
            "run_id": value["run_id"],
            "call_id": value["call_id"],
            "call_sequence": call_sequence,
            "ended_at": _utc(ended_at),
            "receipt": receipt,
        }
