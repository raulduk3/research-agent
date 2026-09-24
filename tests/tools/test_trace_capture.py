"""The run trace is what the service did, not what the agent says (SR-02).

TDD-2.1.2: a run whose agent claims a read it never made is driven through
the real loop and the shared tool service's HTTP path; a conduct check that
reads the externally captured trace finds only the calls actually made,
each with its request hash, decision and terminal event.
"""

from __future__ import annotations

import base64
from typing import Any
from uuid import uuid4

import pytest

from research_agent.agents.loop import ModelResponse, ToolCall, run_conversation
from research_agent.agents.messages import Message
from research_agent.agents.transcript import RecordingFailed
from research_agent.tools.service import RunToolDispatcher
from research_agent.contracts import canonical_json, canonical_loads, sha256_hex
from research_agent.storage.trace import TRACE_PAYLOAD_BOUND
from research_agent.tools.trace import TraceWriter, request_bytes, request_hash

from service_harness import (
    ATTENTION,
    World,
    envelope,
    latex_paper,
    lookup_args,
    tool_service,
)

pytestmark = pytest.mark.integration


class _ScriptedModel:
    def __init__(self, turns: list[ModelResponse]) -> None:
        self.turns = turns

    def complete(
        self, messages: list[dict[str, Any]], *, max_generation_tokens: int
    ) -> ModelResponse:
        return self.turns.pop(0)


class _Sink:
    def append(
        self, *, run_id: str, attempt: int, ordinal: int, kind: str, payload: bytes
    ) -> None:
        if not payload:
            raise RecordingFailed("empty exchange")


def _count(messages: Any) -> int:
    return 10


def test_a_claimed_read_absent_from_the_trace_is_not_believed(world: World) -> None:
    read = latex_paper("Attention", ATTENTION, {"Introduction": "attention"})
    claimed = latex_paper("Claimed", (0.0, 1.0, 0.0, 0.0), {"Method": "never read"})
    snapshot = world.seal_snapshot([read, claimed])
    run = world.create_run(snapshot, paper_id=read.family)
    turns = [
        ModelResponse(
            content={
                "note": f"I read every section of {claimed.family} in full.",
                "intent": "read",
            },
            tool_calls=(
                ToolCall("call-1", "query_cards", lookup_args(read.family)),
                ToolCall(
                    "call-2",
                    "query_cards",
                    {**lookup_args(claimed.family), "section": "Method"},
                ),
            ),
            generated_tokens=5,
        ),
        ModelResponse(content={"note": "done"}, tool_calls=(), generated_tokens=5),
    ]
    with world.serve() as storage:
        outcome = run_conversation(
            run_id=run,
            attempt=1,
            system_message=Message("system", {"content": "read"}),
            initial_message=Message("user", {"content": "go"}),
            allowed_tools=frozenset({"query_cards", "deep_read", "submit"}),
            client=_ScriptedModel(turns),
            dispatcher=RunToolDispatcher(tool_service(storage), snapshot_id=snapshot),
            sink=_Sink(),
            count_tokens=_count,
        )
    assert outcome.reason == "model_stopped"
    trace = world.trace_rows(run)
    # The conduct check reads the trace: one admitted card lookup and one
    # refused malformed call. No deep_read of the claimed paper exists, and
    # no id of its pinned card was ever retrieved.
    assert [(row["tool"], row["decision"]) for row in trace] == [
        ("query_cards", "admitted"),
        ("query_cards", "refused"),
    ]
    claimed_card = world.documents.family_pin(snapshot, claimed.family).card_hash
    assert all(claimed_card not in row["retrieved_ids"] for row in trace)
    assert trace[0]["outcome"] == "response"
    assert trace[1]["reason"] == "invalid_input"
    assert trace[1]["outcome"] is None
    assert [row["sequence"] for row in trace] == [1, 2]


def test_the_request_hash_covers_the_exact_call() -> None:
    call = {
        "run_id": "123e4567-e89b-42d3-a456-426614174010",
        "snapshot_id": "a" * 64,
        "tool": "query_cards",
        "raw_arguments": {"paper_ids": ["x"]},
    }
    assert request_hash(**call) == request_hash(**call)  # type: ignore[arg-type]
    for field, value in (
        ("run_id", "123e4567-e89b-42d3-a456-426614174011"),
        ("snapshot_id", "b" * 64),
        ("tool", "neighbors"),
        ("raw_arguments", {"paper_ids": ["y"]}),
    ):
        assert request_hash(**{**call, field: value}) != request_hash(**call)  # type: ignore[arg-type]
    # A call with no canonical form (admission refuses it) still has a hash.
    assert len(request_hash(**{**call, "raw_arguments": {1: float("nan")}})) == 64  # type: ignore[arg-type]


def _payload(stored: dict[str, Any]) -> bytes:
    return base64.b64decode(stored["bytes"])


def test_a_traced_call_resolves_to_the_bytes_the_service_sent(world: World) -> None:
    read = latex_paper("Attention", ATTENTION, {"Introduction": "attention"})
    snapshot = world.seal_snapshot([read])
    run = world.create_run(snapshot, paper_id=read.family)
    arguments = envelope(lookup_args(read.family))
    with world.serve() as storage:
        outcome = tool_service(storage).call(
            run_id=run,
            snapshot_id=snapshot,
            tool="query_cards",
            raw_call=arguments,
        )
    trace = world.trace.read(run)
    assert trace is not None
    [call] = trace["calls"]
    sent = request_bytes(
        run_id=run, snapshot_id=snapshot, tool="query_cards", raw_arguments=arguments
    )
    # Both stored payloads are the exact bytes the row's hashes cover, and
    # the response is the envelope the run received.
    assert _payload(call["request"]) == sent
    # The stored request is the call as the model sent it, note and intent
    # included (AG-39).
    stored = canonical_loads(sent)
    assert isinstance(stored, dict) and stored["arguments"] == {
        "note": "reading the cards",
        "intent": "scan",
        "arguments": lookup_args(read.family),
    }
    assert call["request_hash"] == sha256_hex(sent)
    response = call["terminal"]["response"]
    assert outcome.status == "ok"
    assert _payload(response) == canonical_json(outcome.data)
    assert call["terminal"]["response_hash"] == sha256_hex(_payload(response))
    assert call["request"]["truncated"] is False and response["truncated"] is False


def test_an_oversize_envelope_is_sent_cut_to_the_bound_and_flagged(
    world: World,
) -> None:
    read = latex_paper("Attention", ATTENTION, {"Introduction": "attention"})
    snapshot = world.seal_snapshot([read])
    run = world.create_run(snapshot, paper_id=read.family)
    envelope = {"status": "ok", "text": "x" * TRACE_PAYLOAD_BOUND}
    call_id = uuid4()
    with world.serve() as storage:
        writer = TraceWriter(storage)
        writer.request(
            run_id=run,
            call_id=call_id,
            tool="query_cards",
            request=b'{"tool":"query_cards"}',
            refusal=None,
        )
        writer.terminal(
            run_id=run,
            call_id=call_id,
            envelope=envelope,
            error_code=None,
            retrieved_ids=(),
            budget_deltas={"tool_calls": 1},
        )
    trace = world.trace.read(run)
    assert trace is not None
    terminal = trace["calls"][0]["terminal"]
    whole = canonical_json(envelope)
    assert terminal["response"]["truncated"] is True
    assert _payload(terminal["response"]) == whole[:TRACE_PAYLOAD_BOUND]
    assert terminal["response_hash"] == sha256_hex(whole)
