"""A run's tool trace: sequenced calls, refusals and terminal events (#297)."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_loads, sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.runs import RunRepository
from research_agent.storage.settlements import SettlementRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository
from research_agent.storage.submissions import SubmissionRepository
from research_agent.storage.trace import (
    TRACE_PAYLOAD_BOUND,
    TraceRepository,
    bound_payload,
    validate_trace_payload,
)
from tests.storage.test_run_terminal import PRODUCER, Storage, identity

pytestmark = pytest.mark.integration


REQUEST = b'{"arguments":{"paper_ids":["x"]},"tool":"query_cards"}'
RESPONSE = b'{"cards":[],"status":"ok"}'


def _encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class Harness:
    def __init__(
        self, storage: Storage, trace: TraceRepository, store: ArtifactStore
    ) -> None:
        self.storage = storage
        self.trace = trace
        self.store = store

    def request(
        self,
        run_id: str,
        *,
        call_id: str | None = None,
        tool: str = "query_cards",
        decision: str = "admitted",
        reason: str | None = None,
        command: CommandIdentity | None = None,
        data: bytes = REQUEST,
    ) -> dict[str, Any]:
        stored, truncated = bound_payload(data)
        response = self.trace.execute(
            "request",
            identity=command or identity(),
            payload={
                "run_id": run_id,
                "call_id": call_id or str(uuid4()),
                "tool": tool,
                "request_hash": sha256_hex(data),
                "decision": decision,
                "reason": reason,
                "request_payload": _encoded(stored),
                "request_truncated": truncated,
            },
        )
        return dict(canonical_loads(response.body)["data"])

    def terminal(
        self,
        run_id: str,
        call_id: str,
        *,
        outcome: str = "response",
        error_code: str | None = None,
        retrieved_ids: list[str] | None = None,
        data: bytes = RESPONSE,
    ) -> dict[str, Any]:
        stored, truncated = bound_payload(data)
        response = self.trace.execute(
            "terminal",
            identity=identity(),
            payload={
                "run_id": run_id,
                "call_id": call_id,
                "outcome": outcome,
                "response_hash": sha256_hex(data),
                "error_code": error_code,
                "retrieved_ids": ["c" * 64] if retrieved_ids is None else retrieved_ids,
                "budget_deltas": {"tool_calls": 1},
                "response_payload": _encoded(stored),
                "response_truncated": truncated,
            },
        )
        return dict(canonical_loads(response.body)["data"])


@pytest.fixture
def harness(postgres_dsn: str, artifact_root: Path) -> Harness:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    kwargs = {
        "producer": PRODUCER,
        "config_hash": "c" * 64,
        "retention_policy_hash": "d" * 64,
    }
    return Harness(
        Storage(
            database,
            ArtifactRepository(database, store),
            SheetRepository(database, store, **kwargs),
            SnapshotRepository(database, store, **kwargs),
            RunRepository(database, store, **kwargs),
            SubmissionRepository(database, store, **kwargs),
        ),
        TraceRepository(database, store, **kwargs),
        store,
    )


def test_each_run_allocates_its_own_monotonic_call_sequence(harness: Harness) -> None:
    run_a, run_b = harness.storage.create_run(), harness.storage.create_run()
    sequences_a = [harness.request(run_a)["call_sequence"] for _ in range(3)]
    sequence_b = harness.request(run_b)["call_sequence"]
    assert sequences_a == [1, 2, 3]
    assert sequence_b == 1


def test_concurrent_requests_receive_distinct_gap_free_sequences(
    harness: Harness,
) -> None:
    run_id = harness.storage.create_run()

    def attempt(_: int) -> int | None:
        try:
            return int(harness.request(run_id)["call_sequence"])
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = [item for item in executor.map(attempt, range(3)) if item]
    with harness.storage.database.connect() as connection:
        rows = connection.execute(
            "SELECT call_sequence FROM run_trace_calls WHERE run_id=%s ORDER BY 1",
            (run_id,),
        ).fetchall()
    assert results
    assert sorted(results) == [row[0] for row in rows]
    assert [row[0] for row in rows] == list(range(1, len(rows) + 1))


def test_a_terminal_is_appended_beside_its_request_exactly_once(
    harness: Harness,
) -> None:
    run_id = harness.storage.create_run()
    call_id = str(uuid4())
    recorded = harness.request(run_id, call_id=call_id)
    ended = harness.terminal(run_id, call_id)
    assert ended["call_sequence"] == recorded["call_sequence"]
    with pytest.raises(StateConflict, match="already has its terminal"):
        harness.terminal(
            run_id, call_id, outcome="error", error_code="timeout", retrieved_ids=[]
        )
    with harness.storage.database.connect() as connection:
        row = connection.execute(
            """SELECT c.request_hash, t.outcome, t.retrieved_ids, t.budget_deltas
               FROM run_trace_calls c JOIN run_trace_terminals t
               USING (run_id, call_sequence) WHERE c.call_id=%s""",
            (call_id,),
        ).fetchone()
        assert row is not None
        assert bytes(row[0]).hex() == sha256_hex(REQUEST)
        assert row[1] == "response"
        assert [bytes(item).hex() for item in row[2]] == ["c" * 64]
        assert canonical_loads(bytes(row[3])) == {"tool_calls": 1}
        with pytest.raises(psycopg.Error):
            connection.execute(
                "UPDATE run_trace_calls SET decision='refused' WHERE call_id=%s",
                (call_id,),
            )


def test_a_refused_call_is_an_entry_and_takes_no_terminal(harness: Harness) -> None:
    run_id = harness.storage.create_run()
    call_id = str(uuid4())
    refused = harness.request(
        run_id,
        call_id=call_id,
        tool="rewrite_configuration",
        decision="refused",
        reason="tool_not_allowed",
    )
    assert refused["call_sequence"] == 1
    with pytest.raises(StateConflict, match="refused call"):
        harness.terminal(run_id, call_id)
    with harness.storage.database.connect() as connection:
        row = connection.execute(
            "SELECT tool, decision, reason FROM run_trace_calls WHERE call_id=%s",
            (call_id,),
        ).fetchone()
    assert row == ("rewrite_configuration", "refused", "tool_not_allowed")


def test_an_admitted_call_must_name_a_tool_the_run_allows(harness: Harness) -> None:
    run_id = harness.storage.create_run()
    with pytest.raises(StateConflict, match="does not allow"):
        harness.request(run_id, tool="deep_read")
    with pytest.raises(UnavailableInput, match="unknown run"):
        harness.request(str(uuid4()))
    with pytest.raises(UnavailableInput, match="unrecorded call"):
        harness.terminal(run_id, str(uuid4()))


def test_a_call_id_is_recorded_once_and_its_command_replays(harness: Harness) -> None:
    run_id = harness.storage.create_run()
    call_id, command = str(uuid4()), identity()
    first = harness.request(run_id, call_id=call_id, command=command)
    replay = harness.request(run_id, call_id=call_id, command=command)
    assert replay == first
    with pytest.raises(StateConflict, match="already recorded"):
        harness.request(run_id, call_id=call_id)


@pytest.mark.parametrize(
    ("operation", "change"),
    [
        ("request", {"decision": "refused", "reason": None}),
        ("request", {"decision": "admitted", "reason": "tool_not_allowed"}),
        ("request", {"extra": 1}),
        ("terminal", {"outcome": "error", "error_code": "timeout"}),
        ("terminal", {"error_code": "timeout"}),
        ("terminal", {"budget_deltas": {"free_calls": 1}}),
        ("terminal", {"retrieved_ids": ["c" * 64, "c" * 64]}),
        # A whole payload must hash to its row's hash, a truncated one must
        # be exactly the bound, and the bytes must be strict base64.
        ("request", {"request_payload": _encoded(RESPONSE)}),
        ("request", {"request_truncated": True}),
        ("request", {"request_payload": "not base64!"}),
        ("request", {"request_truncated": None}),
        ("terminal", {"response_payload": _encoded(REQUEST)}),
        (
            "terminal",
            {
                "response_payload": _encoded(b"x" * (TRACE_PAYLOAD_BOUND - 1)),
                "response_truncated": True,
            },
        ),
    ],
)
def test_trace_payloads_are_closed_and_consistent(
    operation: str, change: dict[str, Any]
) -> None:
    base: dict[str, Any] = (
        {
            "run_id": str(uuid4()),
            "call_id": str(uuid4()),
            "tool": "query_cards",
            "request_hash": sha256_hex(REQUEST),
            "decision": "admitted",
            "reason": None,
            "request_payload": _encoded(REQUEST),
            "request_truncated": False,
        }
        if operation == "request"
        else {
            "run_id": str(uuid4()),
            "call_id": str(uuid4()),
            "outcome": "response",
            "response_hash": sha256_hex(RESPONSE),
            "error_code": None,
            "retrieved_ids": ["c" * 64],
            "budget_deltas": {"tool_calls": 1},
            "response_payload": _encoded(RESPONSE),
            "response_truncated": False,
        }
    )
    validate_trace_payload(operation, base)
    with pytest.raises(ContractValidationError):
        validate_trace_payload(operation, {**base, **change})


def _stored(harness: Harness, artifact_hash: str) -> bytes:
    with harness.store.open_verified(artifact_hash) as stream:
        return stream.read()


def test_a_traced_call_resolves_byte_for_byte_from_the_artifact_store(
    harness: Harness,
) -> None:
    run_id = harness.storage.create_run()
    call_id = str(uuid4())
    harness.request(run_id, call_id=call_id)
    harness.terminal(run_id, call_id)
    with harness.storage.database.connect() as connection:
        row = connection.execute(
            """SELECT encode(c.request_artifact,'hex'), c.request_truncated,
                      encode(t.response_artifact,'hex'), t.response_truncated,
                      (SELECT kind FROM artifacts WHERE hash=c.request_artifact),
                      (SELECT kind FROM artifacts WHERE hash=t.response_artifact)
               FROM run_trace_calls c JOIN run_trace_terminals t
               USING (run_id, call_sequence) WHERE c.call_id=%s""",
            (call_id,),
        ).fetchone()
    assert row is not None
    request_artifact, request_cut, response_artifact, response_cut = row[:4]
    # A whole payload is stored under the row's own hash, so the hash the
    # trace recorded is the key its bytes are found by.
    assert request_artifact == sha256_hex(REQUEST) and request_cut is False
    assert response_artifact == sha256_hex(RESPONSE) and response_cut is False
    assert _stored(harness, str(request_artifact)) == REQUEST
    assert _stored(harness, str(response_artifact)) == RESPONSE
    assert row[4:] == ("trace_request", "trace_response")


def test_an_oversize_response_is_stored_truncated_and_flagged(
    harness: Harness,
) -> None:
    run_id = harness.storage.create_run()
    call_id = str(uuid4())
    envelope = b'{"text":"' + b"x" * TRACE_PAYLOAD_BOUND + b'"}'
    harness.request(run_id, call_id=call_id)
    harness.terminal(run_id, call_id, data=envelope)
    trace = harness.trace.read(run_id)
    assert trace is not None
    [call] = trace["calls"]
    response = call["terminal"]["response"]
    stored = base64.b64decode(response["bytes"])
    assert response["truncated"] is True
    assert stored == envelope[:TRACE_PAYLOAD_BOUND]
    # The row keeps the hash of what the run received; the cut bytes are
    # stored under their own hash, never passed off as the whole envelope.
    assert call["terminal"]["response_hash"] == sha256_hex(envelope)
    assert response["artifact_hash"] == sha256_hex(stored)
    assert _stored(harness, response["artifact_hash"]) == stored


def test_the_read_returns_each_call_in_order_with_its_payloads(
    harness: Harness,
) -> None:
    run_id = harness.storage.create_run()
    first, second, third = (str(uuid4()) for _ in range(3))
    harness.request(run_id, call_id=first, data=b'{"call":1}')
    harness.request(
        run_id,
        call_id=second,
        tool="rewrite_configuration",
        decision="refused",
        reason="tool_not_allowed",
        data=b'{"call":2}',
    )
    harness.request(run_id, call_id=third, data=b'{"call":3}')
    harness.terminal(run_id, third, data=b'{"answer":3}')
    harness.terminal(run_id, first, data=b'{"answer":1}')
    trace = harness.trace.read(run_id)
    assert trace is not None and trace["run_id"] == run_id
    calls = trace["calls"]
    assert [call["call_id"] for call in calls] == [first, second, third]
    assert [call["call_sequence"] for call in calls] == [1, 2, 3]
    assert [base64.b64decode(call["request"]["bytes"]) for call in calls] == [
        b'{"call":1}',
        b'{"call":2}',
        b'{"call":3}',
    ]
    # A refused call is an entry with its request and no terminal.
    assert calls[1]["decision"] == "refused" and calls[1]["terminal"] is None
    assert [
        base64.b64decode(calls[index]["terminal"]["response"]["bytes"])
        for index in (0, 2)
    ] == [b'{"answer":1}', b'{"answer":3}']
    assert harness.trace.read(str(uuid4())) is None


def test_the_since_read_replays_every_kind_in_ledger_order(harness: Harness) -> None:
    before = harness.trace.since(0, 500)["cursor"]
    run_id = harness.storage.create_run()
    call = str(uuid4())
    harness.request(run_id, call_id=call, data=b'{"call":1}')
    harness.terminal(run_id, call, data=b'{"answer":1}')
    harness.storage.void(run_id, "model_error")
    settlements = SettlementRepository(
        harness.storage.database,
        harness.store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    settlements.execute(
        "record",
        identity=identity(),
        payload={
            "run_id": run_id,
            "provider": "provider-a",
            "model": "model-a",
            "input_tokens": 12,
            "output_tokens": 3,
            "usage_source": "loop_count",
        },
    )
    page = harness.trace.since(before, 500)
    events = [event for event in page["events"] if event["run_id"] == run_id]
    assert [event["kind"] for event in events] == [
        "call",
        "terminal",
        "ending",
        "settlement",
    ]
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(set(sequences)) and page["cursor"] == sequences[-1]
    assert events[0]["call"]["terminal"] is None
    assert base64.b64decode(events[1]["call"]["terminal"]["response"]["bytes"]) == (
        b'{"answer":1}'
    )
    assert events[2]["ending"]["state"] == "void"
    assert events[3]["settlement"]["input_tokens"] == 12
    # Resuming from any event's sequence yields exactly the events after it.
    resumed = harness.trace.since(sequences[1], 500)["events"]
    assert [event["kind"] for event in resumed if event["run_id"] == run_id] == [
        "ending",
        "settlement",
    ]
    first = harness.trace.since(before, 1)
    assert [event["sequence"] for event in first["events"]] == sequences[:1]
    assert harness.trace.since(page["cursor"], 500) == {
        "events": [],
        "cursor": page["cursor"],
    }
    with pytest.raises(ContractValidationError):
        harness.trace.since(-1)


def test_only_a_row_recorded_before_payloads_may_lack_one(harness: Harness) -> None:
    run_id = harness.storage.create_run()
    harness.request(run_id)
    insert = """INSERT INTO run_trace_calls(
                    run_id, call_sequence, call_id, tool, request_hash, decision,
                    reason, started_at, ledger_sequence)
                SELECT run_id, 2, %s, tool, request_hash, decision, reason, %s,
                       ledger_sequence
                FROM run_trace_calls WHERE run_id=%s AND call_sequence=1"""
    with harness.storage.database.connect() as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(insert, (uuid4(), datetime.now(timezone.utc), run_id))
    with harness.storage.database.connect() as connection:
        connection.execute(
            insert, (uuid4(), datetime(2026, 1, 1, tzinfo=timezone.utc), run_id)
        )
        connection.commit()
    trace = harness.trace.read(run_id)
    assert trace is not None
    assert trace["calls"][1]["request"] is None
