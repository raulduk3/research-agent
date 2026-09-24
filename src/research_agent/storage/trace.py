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

Each row also stores the bytes it hashes (#308): the canonical request the
service admitted or refused, and the envelope the run received, each as an
artifact written in the same transaction as its row. A payload over
``TRACE_PAYLOAD_BOUND`` arrives cut to that bound and is stored flagged as
truncated, under the hash of the stored bytes; a whole payload is stored
under the row's own request or response hash. ``read`` gives the owner a
run's rows in call order with both payloads resolved.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import (
    ProducerVersion,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
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
from research_agent.storage.errors import (
    IntegrityFailure,
    StateConflict,
    UnavailableInput,
)
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.queries import run_ending

TRACE_DECISIONS = frozenset({"admitted", "refused"})
TRACE_OUTCOMES = frozenset({"response", "error"})
MAXIMUM_RETRIEVED_IDS = 100
# The most bytes of one request or response a trace row stores; a larger
# payload is stored cut to this length and flagged as truncated.
TRACE_PAYLOAD_BOUND = 256 * 1024
_CODE = re.compile(r"[a-z][a-z_]{0,62}(:[a-z][a-z_]{0,62})?")


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _code(value: object, field: str) -> str:
    if not isinstance(value, str) or _CODE.fullmatch(value) is None:
        raise ContractValidationError(f"trace {field} is invalid")
    return value


def bound_payload(data: bytes) -> tuple[bytes, bool]:
    """The bytes a trace row stores for *data*, and whether they were cut."""

    return data[:TRACE_PAYLOAD_BOUND], len(data) > TRACE_PAYLOAD_BOUND


def _payload(encoded: object, truncated: object, digest: str, field: str) -> bytes:
    """Decode a row's stored payload and check it against the row's hash.

    A whole payload hashes to the row's own hash; a truncated one is
    exactly the bound long, the prefix the service cut.
    """

    if not isinstance(encoded, str) or not isinstance(truncated, bool):
        raise ContractValidationError(f"trace {field} is invalid")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ContractValidationError(f"trace {field} is not base64") from error
    if truncated:
        if len(data) != TRACE_PAYLOAD_BOUND:
            raise ContractValidationError(
                f"a truncated trace {field} is exactly {TRACE_PAYLOAD_BOUND} bytes"
            )
    elif len(data) > TRACE_PAYLOAD_BOUND or sha256_hex(data) != digest:
        raise ContractValidationError(f"trace {field} does not match its hash")
    return data


def validate_trace_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a trace operation."""

    if operation == "request":
        fields = {
            "run_id",
            "call_id",
            "tool",
            "request_hash",
            "decision",
            "reason",
            "request_payload",
            "request_truncated",
        }
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
        digest = validate_sha256(payload["request_hash"])
        _payload(
            payload["request_payload"],
            payload["request_truncated"],
            digest,
            "request_payload",
        )
        return {
            "run_id": validate_uuid4(payload["run_id"]),
            "call_id": validate_uuid4(payload["call_id"]),
            "tool": tool,
            "request_hash": digest,
            "decision": decision,
            "reason": _code(payload["reason"], "reason") if refused else None,
            "request_payload": payload["request_payload"],
            "request_truncated": payload["request_truncated"],
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
            "response_payload",
            "response_truncated",
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
        digest = validate_sha256(payload["response_hash"])
        _payload(
            payload["response_payload"],
            payload["response_truncated"],
            digest,
            "response_payload",
        )
        return {
            "run_id": validate_uuid4(payload["run_id"]),
            "call_id": validate_uuid4(payload["call_id"]),
            "outcome": outcome,
            "response_hash": digest,
            "error_code": _code(payload["error_code"], "error_code")
            if failed
            else None,
            "retrieved_ids": retrieved_ids,
            "budget_deltas": {
                name: validate_non_negative_int(deltas[name]) for name in sorted(deltas)
            },
            "response_payload": payload["response_payload"],
            "response_truncated": payload["response_truncated"],
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
        self._database = database
        self._store = store
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
        event = {key: item for key, item in value.items() if key != "request_payload"}
        artifact = self._store_payload(
            connection,
            value["request_payload"],
            truncated=value["request_truncated"],
            kind="trace_request",
        )
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="trace_call_recorded",
            payload={
                "schema_version": 1,
                **event,
                "request_artifact": artifact,
                "call_sequence": call_sequence,
                "started_at": _utc(started_at),
            },
            input_hashes=(artifact,),
        )
        connection.execute(
            """INSERT INTO run_trace_calls(
                   run_id, call_sequence, call_id, tool, request_hash, decision,
                   reason, started_at, ledger_sequence, request_artifact,
                   request_truncated
               ) VALUES(%s, %s, %s, %s, decode(%s,'hex'), %s, %s, %s, %s,
                        decode(%s,'hex'), %s)""",
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
                artifact,
                value["request_truncated"],
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
        event = {key: item for key, item in value.items() if key != "response_payload"}
        artifact = self._store_payload(
            connection,
            value["response_payload"],
            truncated=value["response_truncated"],
            kind="trace_response",
        )
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="trace_terminal_recorded",
            payload={
                "schema_version": 1,
                **event,
                "response_artifact": artifact,
                "call_sequence": call_sequence,
                "ended_at": _utc(ended_at),
            },
            input_hashes=(artifact,),
        )
        connection.execute(
            """INSERT INTO run_trace_terminals(
                   run_id, call_sequence, outcome, response_hash, error_code,
                   retrieved_ids, budget_deltas, ended_at, ledger_sequence,
                   response_artifact, response_truncated
               ) VALUES(%s, %s, %s, decode(%s,'hex'), %s, %s, %s, %s, %s,
                        decode(%s,'hex'), %s)""",
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
                artifact,
                value["response_truncated"],
            ),
        )
        return {
            "run_id": value["run_id"],
            "call_id": value["call_id"],
            "call_sequence": call_sequence,
            "ended_at": _utc(ended_at),
            "receipt": receipt,
        }

    def _store_payload(
        self,
        connection: Connection[tuple[object, ...]],
        encoded: str,
        *,
        truncated: bool,
        kind: str,
    ) -> str:
        """Install one row's payload bytes and artifact record; return its hash.

        The trace route is the only writer of these kinds. Identical bytes,
        the request of a repeated call for one, are one artifact.
        """

        data = base64.b64decode(encoded, validate=True)
        digest = sha256_hex(data)
        self._store.commit(
            [data],
            expected_hash=digest,
            expected_length=len(data),
            maximum_length=TRACE_PAYLOAD_BOUND,
        )
        producer = self._events.producer
        connection.execute(
            """INSERT INTO artifacts(hash, byte_length, media_type, kind,
               retention_policy_hash, producer_image_digest, producer_source_commit,
               producer_contract_version, config_hash)
               VALUES (decode(%s,'hex'), %s, %s, %s, decode(%s,'hex'),
               decode(%s,'hex'), decode(%s,'hex'), %s, decode(%s,'hex'))
               ON CONFLICT DO NOTHING""",
            (
                digest,
                len(data),
                "application/octet-stream"
                if truncated or not _is_json(data)
                else "application/json",
                kind,
                self._events.retention_policy_hash,
                producer.image_digest,
                producer.source_commit,
                producer.contract_version,
                self._events.config_hash,
            ),
        )
        return digest

    def read(self, run_id: str) -> dict[str, Any] | None:
        """A run's trace in call order with both payloads resolved (#308).

        ``None`` for a run storage does not hold. Each payload is its stored
        bytes, base64-encoded, beside its artifact hash and truncated flag;
        a row recorded before payloads were stored has ``null`` in its
        place, and a call not yet resolved has a ``null`` terminal.
        """

        validate_uuid4(run_id)

        def select(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]] | None:
            run = connection.execute(
                "SELECT 1 FROM runs WHERE id=%s", (run_id,)
            ).fetchone()
            if run is None:
                return None
            return connection.execute(
                """SELECT c.call_sequence, c.call_id, c.tool,
                          encode(c.request_hash,'hex'), c.decision, c.reason,
                          c.started_at, encode(c.request_artifact,'hex'),
                          c.request_truncated, t.outcome,
                          encode(t.response_hash,'hex'), t.error_code,
                          t.retrieved_ids, t.budget_deltas, t.ended_at,
                          encode(t.response_artifact,'hex'), t.response_truncated
                   FROM run_trace_calls c
                   LEFT JOIN run_trace_terminals t
                     ON t.run_id = c.run_id AND t.call_sequence = c.call_sequence
                   WHERE c.run_id=%s ORDER BY c.call_sequence""",
                (run_id,),
            ).fetchall()

        rows = self._database.transaction(select)
        if rows is None:
            return None
        return {"run_id": run_id, "calls": [self._call(row) for row in rows]}

    def since(self, cursor: int, limit: int = 100) -> dict[str, Any]:
        """Trace calls, terminals, run endings and settlements recorded after
        *cursor*, in ledger order (#327).

        Each event's ``sequence`` is its ledger record's, one total order
        across all four kinds; the ledger head is held until commit, so a
        later sequence never commits before an earlier one and a reader
        resuming from the last sequence it saw misses nothing. A call event
        carries the call with a ``null`` terminal; a terminal event carries
        the call again with its terminal, as the paper page's trace renders
        it. ``cursor`` is the last event's sequence, or the one given when
        nothing is new.
        """

        if cursor < 0 or not 1 <= limit <= 500:
            raise ContractValidationError("cursor or limit is out of range")
        run = """JOIN runs r ON r.id = c.run_id
                 LEFT JOIN genomes g ON g.configuration_id = r.configuration_id"""
        call_columns = """c.call_sequence, c.call_id, c.tool,
                          encode(c.request_hash,'hex'), c.decision, c.reason,
                          c.started_at, encode(c.request_artifact,'hex'),
                          c.request_truncated"""

        def select(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[str, tuple[object, ...]]]:
            def rows(kind: str, sql: str) -> list[tuple[str, tuple[object, ...]]]:
                found = connection.execute(sql, (cursor, limit)).fetchall()
                return [(kind, row) for row in found]

            return [
                *rows(
                    "call",
                    f"""SELECT c.ledger_sequence, r.id, r.paper_id, g.island,
                               {call_columns}, NULL, NULL, NULL, NULL, NULL,
                               NULL, NULL, NULL
                        FROM run_trace_calls c {run}
                        WHERE c.ledger_sequence > %s
                        ORDER BY c.ledger_sequence LIMIT %s""",
                ),
                *rows(
                    "terminal",
                    f"""SELECT t.ledger_sequence, r.id, r.paper_id, g.island,
                               {call_columns}, t.outcome,
                               encode(t.response_hash,'hex'), t.error_code,
                               t.retrieved_ids, t.budget_deltas, t.ended_at,
                               encode(t.response_artifact,'hex'),
                               t.response_truncated
                        FROM run_trace_terminals t
                        JOIN run_trace_calls c
                          ON c.run_id = t.run_id
                         AND c.call_sequence = t.call_sequence {run}
                        WHERE t.ledger_sequence > %s
                        ORDER BY t.ledger_sequence LIMIT %s""",
                ),
                *[
                    (kind, (*row, run_ending(connection, row[1])))
                    for kind, row in rows(
                        "ending",
                        """SELECT p.ledger_sequence, r.id, r.paper_id, g.island
                           FROM run_ending_positions p
                           JOIN runs r ON r.id = p.run_id
                           LEFT JOIN genomes g
                             ON g.configuration_id = r.configuration_id
                           WHERE p.ledger_sequence > %s
                           ORDER BY p.ledger_sequence LIMIT %s""",
                    )
                ],
                *rows(
                    "settlement",
                    """SELECT s.ledger_sequence, r.id, r.paper_id, g.island,
                              s.provider, s.model, s.input_tokens,
                              s.output_tokens, s.usage_source, s.cost_micros,
                              s.settled_at
                       FROM run_settlements s
                       JOIN runs r ON r.id = s.run_id
                       LEFT JOIN genomes g ON g.configuration_id = r.configuration_id
                       WHERE s.ledger_sequence > %s
                       ORDER BY s.ledger_sequence LIMIT %s""",
                ),
            ]

        found = sorted(
            self._database.transaction(select), key=lambda item: cast(int, item[1][0])
        )[:limit]
        events = [self._event(kind, row) for kind, row in found]
        return {
            "events": events,
            "cursor": events[-1]["sequence"] if events else cursor,
        }

    def _event(self, kind: str, row: tuple[object, ...]) -> dict[str, Any]:
        event: dict[str, Any] = {
            "sequence": row[0],
            "kind": kind,
            "run_id": str(row[1]),
            "paper_id": None if row[2] is None else str(row[2]),
            "island": row[3],
        }
        rest = row[4:]
        if kind in ("call", "terminal"):
            event["call"] = self._call(rest)
        elif kind == "ending":
            event["ending"] = rest[0]
        else:
            event["settlement"] = {
                "provider": rest[0],
                "model": rest[1],
                "input_tokens": rest[2],
                "output_tokens": rest[3],
                "usage_source": rest[4],
                "cost_micros": rest[5],
                "settled_at": _utc(cast(datetime, rest[6])),
            }
        return event

    def _call(self, row: tuple[object, ...]) -> dict[str, Any]:
        terminal: dict[str, Any] | None = None
        if row[9] is not None:
            terminal = {
                "outcome": row[9],
                "response_hash": row[10],
                "error_code": row[11],
                "retrieved_ids": [
                    bytes(item).hex() for item in cast(list[bytes], row[12])
                ],
                "budget_deltas": canonical_loads(bytes(cast(bytes, row[13]))),
                "ended_at": _utc(cast(datetime, row[14])),
                "response": self._resolve(row[15], row[16]),
            }
        return {
            "call_sequence": row[0],
            "call_id": str(row[1]),
            "tool": row[2],
            "request_hash": row[3],
            "decision": row[4],
            "reason": row[5],
            "started_at": _utc(cast(datetime, row[6])),
            "request": self._resolve(row[7], row[8]),
            "terminal": terminal,
        }

    def _resolve(self, artifact: object, truncated: object) -> dict[str, Any] | None:
        if artifact is None:
            return None
        digest = str(artifact)
        try:
            with self._store.open_verified(digest) as stream:
                data = stream.read()
        except (FileNotFoundError, IntegrityFailure) as error:
            raise IntegrityFailure("a stored trace payload is unreadable") from error
        return {
            "artifact_hash": digest,
            "truncated": bool(truncated),
            "bytes": base64.b64encode(data).decode("ascii"),
        }


def _is_json(data: bytes) -> bool:
    try:
        json.loads(data)
    except ValueError:
        return False
    return True
