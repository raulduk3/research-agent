from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from research_agent.agents.budgets import (
    ASK_CALLS_LIMIT,
    DEEP_READS_LIMIT,
    GENERATION_TOKENS_LIMIT,
    IMAGES_LIMIT,
    MODEL_CALLS_LIMIT,
    TOOL_CALLS_LIMIT,
    WALL_TIME_SECONDS_LIMIT,
    RunBudget,
)
from research_agent.agents.loop import ToolDispatcher, run_conversation
from research_agent.agents.messages import (
    SnapshotDescription,
    assemble_system_prompt,
    build_initial_message,
)
from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.client import (
    CommandResult,
    ResponseMetadata,
    RunSpecificationRecord,
)
from research_agent.tools.service import RunToolDispatcher, ToolService
from research_agent.tools.trace import TraceWriter

from tests.agents.support import (
    FixtureToolDispatcher,
    InMemoryRunEventSink,
    RecordedResponseClient,
    count_tokens,
    load_fixture,
)

ALLOWED_TOOLS = frozenset({"query_cards", "neighbors", "graph", "deep_read", "submit"})
SNAPSHOT = SnapshotDescription(
    snapshot_hash="a" * 64,
    sealed_at="2027-01-01T00:00:00.000000Z",
    paper_count=1,
)


def _messages() -> tuple[Any, Any]:
    system = assemble_system_prompt("Read the paper and cite your evidence.")
    initial = build_initial_message(
        paper_id="paper-a",
        questions=[],
        budgets={"tool_calls": TOOL_CALLS_LIMIT},
        snapshot=SNAPSHOT,
    )
    return system, initial


def _run(
    *,
    client: RecordedResponseClient,
    dispatcher: ToolDispatcher,
    sink: InMemoryRunEventSink | None = None,
    budget: RunBudget | None = None,
    allowed_tools: frozenset[str] = ALLOWED_TOOLS,
    elapsed_seconds: Any = None,
) -> Any:
    system, initial = _messages()
    return run_conversation(
        run_id="11111111-1111-4111-8111-111111111111",
        attempt=1,
        system_message=system,
        initial_message=initial,
        allowed_tools=allowed_tools,
        client=client,
        dispatcher=dispatcher,
        sink=sink if sink is not None else InMemoryRunEventSink(),
        count_tokens=count_tokens,
        budget=budget,
        elapsed_seconds=elapsed_seconds,
    )


def test_accepted_submit_ends_the_run_submitted() -> None:
    fixture = load_fixture("two_turn_submit.json")
    client = RecordedResponseClient(turns=fixture["turns"])
    dispatcher = FixtureToolDispatcher(results=fixture["tool_results"])
    sink = InMemoryRunEventSink()

    outcome = _run(client=client, dispatcher=dispatcher, sink=sink)

    assert outcome.status == "submitted"
    assert outcome.reason is None
    assert dispatcher.dispatched == ["call-1", "call-2"]
    assert [event["kind"] for event in sink.events] == [
        "request",
        "response",
        "request",
        "response",
    ]
    assert client.calls == 2


def test_replaying_the_same_fixture_twice_is_deterministic() -> None:
    fixture = load_fixture("two_turn_submit.json")

    def run_once() -> tuple[str, list[bytes]]:
        client = RecordedResponseClient(turns=fixture["turns"])
        dispatcher = FixtureToolDispatcher(results=fixture["tool_results"])
        sink = InMemoryRunEventSink()
        outcome = _run(client=client, dispatcher=dispatcher, sink=sink)
        return outcome.status, [event["payload"] for event in sink.events]

    first_status, first_payloads = run_once()
    second_status, second_payloads = run_once()

    assert first_status == "submitted"
    assert first_status == second_status
    assert first_payloads == second_payloads


def test_model_stop_without_submit_is_void() -> None:
    client = RecordedResponseClient(
        turns=[
            {
                "content": {"note": "I think the answer is yes.", "intent": "forecast"},
                "tool_calls": [],
                "generated_tokens": 40,
            }
        ]
    )
    dispatcher = FixtureToolDispatcher(results={})

    outcome = _run(client=client, dispatcher=dispatcher)

    assert outcome.status == "void"
    assert outcome.reason == "model_stopped"
    assert dispatcher.dispatched == []


class _TraceStorage:
    """The storage commands the tool service reads and writes, kept in memory."""

    def __init__(self, allowed_tools: frozenset[str]) -> None:
        self.allowed_tools = allowed_tools
        self.requests: list[dict[str, Any]] = []
        self.terminals: list[dict[str, Any]] = []

    def read_run_specification(self, run_id: UUID) -> RunSpecificationRecord:
        return RunSpecificationRecord(
            run_id=run_id,
            snapshot_hash=SNAPSHOT.snapshot_hash,
            allowed_tools=self.allowed_tools,
            paper_id="paper-a",
            issued_question_ids=frozenset(),
            active=True,
        )

    def append_trace_request(self, **entry: Any) -> CommandResult:
        self.requests.append(entry)
        return CommandResult(
            request_id=str(entry["request_id"]),
            data={"call_sequence": len(self.requests)},
            response=ResponseMetadata(201, (), b""),
        )

    def append_trace_terminal(self, **entry: Any) -> CommandResult:
        self.terminals.append(entry)
        return CommandResult(
            request_id=str(entry["request_id"]),
            data={},
            response=ResponseMetadata(201, (), b""),
        )


class _Unreachable:
    """A handler or snapshot read that a refused call must never reach."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("a refused call reached the tool's work")

    def __getattr__(self, name: str) -> Any:
        return self


@pytest.mark.parametrize(
    ("tool", "allowed_tools"),
    [
        ("browse", ALLOWED_TOOLS),
        ("query_cards", frozenset({"submit"})),
    ],
)
def test_a_tool_outside_the_run_is_refused_traced_and_charged_once(
    tool: str, allowed_tools: frozenset[str]
) -> None:
    client = RecordedResponseClient(
        turns=[
            {
                "content": {"note": "reading", "intent": "scan"},
                "tool_calls": [
                    {
                        "tool_call_id": "call-1",
                        "name": tool,
                        "arguments": {"paper_ids": ["paper-a"]},
                    }
                ],
                "generated_tokens": 10,
            },
            {
                "content": {"note": "giving up", "intent": "stop"},
                "tool_calls": [],
                "generated_tokens": 10,
            },
        ]
    )
    storage = _TraceStorage(allowed_tools)
    work = _Unreachable()
    service = ToolService(
        specifications=storage,
        handlers={name: work for name in ALLOWED_TOOLS},
        membership=work,
        paper_requests=work,
        trace=TraceWriter(storage),
    )
    budget = RunBudget()
    sink = InMemoryRunEventSink()

    outcome = _run(
        client=client,
        dispatcher=RunToolDispatcher(service, snapshot_id=SNAPSHOT.snapshot_hash),
        sink=sink,
        budget=budget,
        allowed_tools=allowed_tools,
    )

    assert outcome.status == "void"
    assert outcome.reason == "model_stopped"
    # One refused entry in the external trace, never resolved, since
    # nothing ran; the loop's charge is the call's only charge.
    assert [
        (entry["tool"], entry["decision"], entry["reason"])
        for entry in storage.requests
    ] == [(tool, "refused", "tool_not_allowed")]
    assert storage.terminals == []
    assert work.calls == 0
    assert budget.tool_calls == 1
    # The model is told of the refusal in the next request.
    assert b'"code":"tool_not_allowed"' in sink.events[2]["payload"]


def test_unadmitted_tool_name_raises_before_the_run_starts() -> None:
    client = RecordedResponseClient(turns=[])
    dispatcher = FixtureToolDispatcher(results={})
    with pytest.raises(ContractValidationError):
        _run(client=client, dispatcher=dispatcher, allowed_tools=frozenset({"browse"}))


def _looping_client(count: int) -> RecordedResponseClient:
    return RecordedResponseClient(
        turns=[
            {
                "content": {"note": "reading again", "intent": "scan"},
                "tool_calls": [
                    {
                        "tool_call_id": f"call-{index}",
                        "name": "query_cards",
                        "arguments": {"paper_ids": ["paper-a"]},
                    }
                ],
                "generated_tokens": 1,
            }
            for index in range(count)
        ]
    )


def _looping_dispatcher(count: int) -> FixtureToolDispatcher:
    return FixtureToolDispatcher(
        results={
            f"call-{index}": {"status": "ok", "data": {"paper_cards": []}}
            for index in range(count)
        }
    )


def test_model_calls_budget_stops_the_run_with_no_further_call() -> None:
    client = _looping_client(2)
    dispatcher = _looping_dispatcher(2)
    budget = RunBudget(model_calls=MODEL_CALLS_LIMIT - 1)

    outcome = _run(client=client, dispatcher=dispatcher, budget=budget)

    assert outcome.status == "void"
    assert outcome.reason == "budget_exhausted:model_calls"
    assert client.calls == 1
    assert budget.model_calls == MODEL_CALLS_LIMIT


def test_tool_calls_budget_stops_before_dispatch() -> None:
    client = _looping_client(1)
    dispatcher = _looping_dispatcher(1)
    budget = RunBudget(tool_calls=TOOL_CALLS_LIMIT)

    outcome = _run(client=client, dispatcher=dispatcher, budget=budget)

    assert outcome.status == "void"
    assert outcome.reason == "budget_exhausted:tool_calls"
    assert dispatcher.dispatched == []


def test_deep_reads_budget_stops_after_dispatch() -> None:
    client = RecordedResponseClient(
        turns=[
            {
                "content": {"note": "deep reading", "intent": "inspect"},
                "tool_calls": [
                    {
                        "tool_call_id": "call-1",
                        "name": "deep_read",
                        "arguments": {"paper_id": "paper-a", "section": "results"},
                    }
                ],
                "generated_tokens": 1,
            }
        ]
    )
    dispatcher = FixtureToolDispatcher(
        results={"call-1": {"status": "ok", "data": {}, "deep_reads": 1}}
    )
    budget = RunBudget(deep_reads=DEEP_READS_LIMIT)

    outcome = _run(client=client, dispatcher=dispatcher, budget=budget)

    assert outcome.status == "void"
    assert outcome.reason == "budget_exhausted:deep_reads"
    assert dispatcher.dispatched == ["call-1"]


def test_ask_calls_budget_stops_after_dispatch() -> None:
    client = RecordedResponseClient(
        turns=[
            {
                "content": {"note": "asking Jev", "intent": "inspect"},
                "tool_calls": [
                    {
                        "tool_call_id": "call-1",
                        "name": "ask",
                        "arguments": {"kind": "yes_no"},
                    }
                ],
                "generated_tokens": 1,
            }
        ]
    )
    dispatcher = FixtureToolDispatcher(
        results={"call-1": {"status": "ok", "data": {}, "ask_calls": 1}}
    )
    budget = RunBudget(ask_calls=ASK_CALLS_LIMIT)

    outcome = _run(
        client=client,
        dispatcher=dispatcher,
        budget=budget,
        allowed_tools=ALLOWED_TOOLS | {"ask"},
    )

    assert outcome.status == "void"
    assert outcome.reason == "budget_exhausted:ask_calls"
    assert dispatcher.dispatched == ["call-1"]


def test_images_budget_stops_after_dispatch() -> None:
    client = RecordedResponseClient(
        turns=[
            {
                "content": {"note": "deep reading a figure", "intent": "inspect"},
                "tool_calls": [
                    {
                        "tool_call_id": "call-1",
                        "name": "deep_read",
                        "arguments": {"paper_id": "paper-a", "section": "figures"},
                    }
                ],
                "generated_tokens": 1,
            }
        ]
    )
    dispatcher = FixtureToolDispatcher(
        results={"call-1": {"status": "ok", "data": {}, "images": 1}}
    )
    budget = RunBudget(images=IMAGES_LIMIT)

    outcome = _run(client=client, dispatcher=dispatcher, budget=budget)

    assert outcome.status == "void"
    assert outcome.reason == "budget_exhausted:images"
    assert dispatcher.dispatched == ["call-1"]


def test_generation_tokens_budget_records_the_response_then_voids() -> None:
    client = RecordedResponseClient(
        turns=[
            {
                "content": {"note": "a long turn", "intent": "forecast"},
                "tool_calls": [
                    {
                        "tool_call_id": "call-1",
                        "name": "submit",
                        "arguments": {},
                    }
                ],
                "generated_tokens": 20,
            }
        ]
    )
    dispatcher = FixtureToolDispatcher(
        results={"call-1": {"status": "ok", "data": {}, "accepted_submit": True}}
    )
    budget = RunBudget(generation_tokens=GENERATION_TOKENS_LIMIT - 10)
    sink = InMemoryRunEventSink()

    outcome = _run(client=client, dispatcher=dispatcher, budget=budget, sink=sink)

    assert outcome.status == "void"
    assert outcome.reason == "budget_exhausted:generation_tokens"
    # The response was truly received, so it is still recorded even though
    # its generated tokens are not executed (Appendix A: Launch profile).
    assert [event["kind"] for event in sink.events] == ["request", "response"]
    assert dispatcher.dispatched == []


def test_wall_time_budget_stops_before_any_call() -> None:
    client = RecordedResponseClient(turns=[])
    dispatcher = FixtureToolDispatcher(results={})

    outcome = _run(
        client=client,
        dispatcher=dispatcher,
        elapsed_seconds=lambda: float(WALL_TIME_SECONDS_LIMIT),
    )

    assert outcome.status == "void"
    assert outcome.reason == "budget_exhausted:wall_time_seconds"
    assert client.calls == 0


def test_context_budget_ends_the_run_as_budget_exhaustion() -> None:
    client = RecordedResponseClient(turns=[])
    dispatcher = FixtureToolDispatcher(results={})
    system, initial = _messages()

    outcome = run_conversation(
        run_id="11111111-1111-4111-8111-111111111111",
        attempt=1,
        system_message=system,
        initial_message=initial,
        allowed_tools=ALLOWED_TOOLS,
        client=client,
        dispatcher=dispatcher,
        sink=InMemoryRunEventSink(),
        count_tokens=lambda _: 65536,
    )

    assert outcome.status == "void"
    assert outcome.reason == "budget_exhausted:context_tokens"
    assert client.calls == 0


def test_recording_failure_stops_the_loop_and_voids_the_run() -> None:
    fixture = load_fixture("two_turn_submit.json")
    client = RecordedResponseClient(turns=fixture["turns"])
    dispatcher = FixtureToolDispatcher(results=fixture["tool_results"])
    sink = InMemoryRunEventSink(fail_after=0)

    outcome = _run(client=client, dispatcher=dispatcher, sink=sink)

    assert outcome.status == "void"
    assert outcome.reason == "recording_failed"
    assert client.calls == 0
