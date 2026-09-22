"""Deterministic test doubles for the run loop: model client, dispatcher, sink."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_agent.agents.loop import ModelResponse, ToolCall, ToolOutcome
from research_agent.agents.messages import Message
from research_agent.agents.transcript import RecordingFailed
from research_agent.contracts.canonical import canonical_json

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "agent-responses"


def load_fixture(name: str) -> dict[str, Any]:
    """Load one recorded-response transcript fixture by file name."""

    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@dataclass
class RecordedResponseClient:
    """Replays a fixed, ordered script of model turns; makes no network call.

    Raises if the loop asks for one more turn than the script provides,
    so a test that expects the run to end early catches a loop that kept
    calling the model past its budget.
    """

    turns: list[dict[str, Any]]
    calls: int = field(default=0, init=False)

    def complete(
        self, messages: list[dict[str, Any]], *, max_generation_tokens: int
    ) -> ModelResponse:
        if self.calls >= len(self.turns):
            raise AssertionError(
                "recorded script exhausted: the loop made an extra model call"
            )
        turn = self.turns[self.calls]
        self.calls += 1
        return ModelResponse(
            content=turn["content"],
            tool_calls=tuple(
                ToolCall(call["tool_call_id"], call["name"], call["arguments"])
                for call in turn.get("tool_calls", [])
            ),
            generated_tokens=turn["generated_tokens"],
        )


@dataclass
class FixtureToolDispatcher:
    """Answers each tool call from a fixed table keyed by tool_call_id."""

    results: dict[str, dict[str, Any]]
    dispatched: list[str] = field(default_factory=list, init=False)

    def dispatch(self, call: ToolCall, *, run_id: str) -> ToolOutcome:
        self.dispatched.append(call.tool_call_id)
        result = self.results[call.tool_call_id]
        return ToolOutcome(
            status=result["status"],
            data=result.get("data", {}),
            deep_reads=result.get("deep_reads", 0),
            images=result.get("images", 0),
            accepted_submit=result.get("accepted_submit", False),
        )


@dataclass
class InMemoryRunEventSink:
    """Records every appended exchange event in order, for assertion.

    ``fail_after`` simulates a storage outage: the append at that index and
    every one after it raises :class:`RecordingFailed` instead of
    committing.
    """

    events: list[dict[str, Any]] = field(default_factory=list, init=False)
    fail_after: int | None = None

    def append(
        self, *, run_id: str, attempt: int, ordinal: int, kind: str, payload: bytes
    ) -> None:
        if self.fail_after is not None and len(self.events) >= self.fail_after:
            raise RecordingFailed("simulated storage failure")
        self.events.append(
            {
                "run_id": run_id,
                "attempt": attempt,
                "ordinal": ordinal,
                "kind": kind,
                "payload": payload,
            }
        )


def count_tokens(messages: Sequence[Message]) -> int:
    """A deterministic, injectable stand-in for the pinned text/image processor.

    Counts whitespace-delimited words across every message's canonical
    JSON body. It is not a real tokenizer; ``run_conversation`` treats
    whatever ``count_tokens`` callable it is given as authoritative, so
    tests can pick a counter that makes a budget boundary easy to hit
    exactly.
    """

    total = 0
    for message in messages:
        total += len(canonical_json(message.to_dict()).split())
    return total
