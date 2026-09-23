"""A run's tool trace: sequenced calls, refusals and terminal events (#297)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_loads
from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.runs import RunRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository
from research_agent.storage.submissions import SubmissionRepository
from research_agent.storage.trace import TraceRepository, validate_trace_payload
from test_run_terminal import PRODUCER, Storage, identity

pytestmark = pytest.mark.integration


class Harness:
    def __init__(self, storage: Storage, trace: TraceRepository) -> None:
        self.storage = storage
        self.trace = trace

    def request(
        self,
        run_id: str,
        *,
        call_id: str | None = None,
        tool: str = "query_cards",
        decision: str = "admitted",
        reason: str | None = None,
        command: CommandIdentity | None = None,
    ) -> dict[str, Any]:
        response = self.trace.execute(
            "request",
            identity=command or identity(),
            payload={
                "run_id": run_id,
                "call_id": call_id or str(uuid4()),
                "tool": tool,
                "request_hash": "a" * 64,
                "decision": decision,
                "reason": reason,
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
    ) -> dict[str, Any]:
        response = self.trace.execute(
            "terminal",
            identity=identity(),
            payload={
                "run_id": run_id,
                "call_id": call_id,
                "outcome": outcome,
                "response_hash": "b" * 64,
                "error_code": error_code,
                "retrieved_ids": ["c" * 64] if retrieved_ids is None else retrieved_ids,
                "budget_deltas": {"tool_calls": 1},
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
        assert bytes(row[0]).hex() == "a" * 64
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
            "request_hash": "a" * 64,
            "decision": "admitted",
            "reason": None,
        }
        if operation == "request"
        else {
            "run_id": str(uuid4()),
            "call_id": str(uuid4()),
            "outcome": "response",
            "response_hash": "b" * 64,
            "error_code": None,
            "retrieved_ids": ["c" * 64],
            "budget_deltas": {"tool_calls": 1},
        }
    )
    validate_trace_payload(operation, base)
    with pytest.raises(ContractValidationError):
        validate_trace_payload(operation, {**base, **change})
