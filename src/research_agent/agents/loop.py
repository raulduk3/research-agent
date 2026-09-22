"""The canonical single-conversation run worker (AG-08).

One conversation between the agent model and the run's tools, with no
layer between them: nothing adds, removes, reorders or rewrites a
message, the loop only reserves budget, sends the next request, dispatches
whatever native tool calls the model made and appends their exact
responses. The run ends at the first accepted submit, an exhausted
budget, a plain model stop, or a conversation that no longer fits its
context -- and any of the last three leaves the run void (AG-15).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from research_agent.agents.budgets import BudgetExhausted, RunBudget, attach_remaining
from research_agent.agents.messages import Message, TokenCounter, prepare_request
from research_agent.agents.transcript import (
    RecordingFailed,
    RunEventSink,
    record_exchange,
)
from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.runs import ALLOWED_TOOLS


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One native tool call the agent model made, exactly as it made it."""

    tool_call_id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """One model turn: a content payload plus zero or more native tool calls.

    An empty ``tool_calls`` means the model stopped without invoking any
    tool -- a plain stop, which ends the run void when no submit was
    already accepted (AG-15).
    """

    content: dict[str, Any]
    tool_calls: tuple[ToolCall, ...]
    generated_tokens: int


class ModelClient(Protocol):
    """The pinned agent model, reached through the canonical conversation alone."""

    def complete(
        self, messages: list[dict[str, Any]], *, max_generation_tokens: int
    ) -> ModelResponse: ...


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """One tool call's result, as the dispatcher reports it to the loop.

    ``deep_reads`` and ``images`` charge their own budgets in addition to
    the one tool-call attempt every dispatch charges, and
    ``accepted_submit`` marks the one call the loop treats as ending the
    run with a sealed submission (AG-26).
    """

    status: str
    data: dict[str, Any]
    deep_reads: int = 0
    images: int = 0
    accepted_submit: bool = False


class ToolDispatcher(Protocol):
    """The run's tool service: query_cards, neighbors, graph, deep_read, submit.

    Until the real dispatcher (#117) integrates, a fixture-driven stand-in
    satisfies this same interface (AG-09).
    """

    def dispatch(self, call: ToolCall, *, run_id: str) -> ToolOutcome: ...


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """How one call to :func:`run_conversation` ended.

    ``status`` is ``"submitted"`` only for the run that executed an
    accepted submit; every other ending -- a stopped model, an exhausted
    budget, an unrecorded exchange or a conversation too large for its
    context -- is void (AG-15). Durably marking a run void is a storage
    transition outside this loop's ownership; this outcome is the loop's
    own account of why it stopped.
    """

    status: str
    reason: str | None
    exchange_count: int


TOOL_NOT_ALLOWED = ToolOutcome(status="error", data={"error": "tool_not_allowed"})


def run_conversation(
    *,
    run_id: str,
    attempt: int,
    system_message: Message,
    initial_message: Message,
    allowed_tools: frozenset[str],
    client: ModelClient,
    dispatcher: ToolDispatcher,
    sink: RunEventSink,
    count_tokens: TokenCounter,
    budget: RunBudget | None = None,
    elapsed_seconds: Callable[[], float] | None = None,
) -> RunOutcome:
    """Run one canonical conversation to its first accepted submit or void ending.

    ``allowed_tools`` is the run's already-validated tool allowlist (AG-14);
    a name outside it is refused as ``tool_not_allowed`` before dispatch,
    exactly as a name outside the fixed five would be. ``elapsed_seconds``
    lets a caller inject a deterministic clock for tests; it defaults to
    a monotonic wall clock.
    """

    invalid = allowed_tools - ALLOWED_TOOLS
    if invalid:
        raise ContractValidationError(
            f"allowed_tools names an inadmissible tool: {sorted(invalid)}"
        )

    clock = elapsed_seconds or _elapsed_since(time.monotonic())
    budget = budget if budget is not None else RunBudget()

    conversation: list[Message] = [system_message, initial_message]
    ordinal = 0

    while True:
        try:
            budget.charge_elapsed(clock())
        except BudgetExhausted as exhausted:
            return RunOutcome("void", f"budget_exhausted:{exhausted.budget}", ordinal)

        try:
            payload, context_tokens = prepare_request(
                conversation, count_tokens=count_tokens
            )
            reservation = budget.reserve_model_call(context_tokens)
        except BudgetExhausted as exhausted:
            return RunOutcome("void", f"budget_exhausted:{exhausted.budget}", ordinal)

        try:
            record_exchange(
                sink,
                run_id=run_id,
                attempt=attempt,
                ordinal=ordinal,
                kind="request",
                payload=payload,
            )
        except RecordingFailed:
            return RunOutcome("void", "recording_failed", ordinal)
        ordinal += 1

        response = client.complete(
            [message.to_dict() for message in conversation],
            max_generation_tokens=reservation,
        )

        response_payload = canonical_json(
            {
                "content": response.content,
                "tool_calls": [call.to_dict() for call in response.tool_calls],
                "generated_tokens": response.generated_tokens,
            }
        )
        try:
            record_exchange(
                sink,
                run_id=run_id,
                attempt=attempt,
                ordinal=ordinal,
                kind="response",
                payload=response_payload,
            )
        except RecordingFailed:
            return RunOutcome("void", "recording_failed", ordinal)
        ordinal += 1

        try:
            budget.charge_generation_tokens(response.generated_tokens)
        except BudgetExhausted as exhausted:
            # The response is recorded above because it was truly received;
            # a response exceeding the remaining allowance is not executed,
            # so no tool call from it is dispatched (Appendix A: Launch profile).
            return RunOutcome("void", f"budget_exhausted:{exhausted.budget}", ordinal)

        conversation.append(
            Message(
                "assistant",
                {
                    "content": response.content,
                    "tool_calls": [call.to_dict() for call in response.tool_calls],
                },
            )
        )

        if not response.tool_calls:
            return RunOutcome("void", "model_stopped", ordinal)

        for call in response.tool_calls:
            try:
                budget.charge_tool_call()
            except BudgetExhausted as exhausted:
                return RunOutcome(
                    "void", f"budget_exhausted:{exhausted.budget}", ordinal
                )

            if call.name not in allowed_tools:
                outcome = TOOL_NOT_ALLOWED
            else:
                outcome = dispatcher.dispatch(call, run_id=run_id)
                try:
                    if outcome.deep_reads:
                        budget.charge_deep_read()
                    if outcome.images:
                        budget.charge_images(outcome.images)
                except BudgetExhausted as exhausted:
                    return RunOutcome(
                        "void", f"budget_exhausted:{exhausted.budget}", ordinal
                    )

            envelope = attach_remaining(
                outcome.data, budget, context_tokens=context_tokens
            )
            conversation.append(
                Message(
                    "tool",
                    {"tool_call_id": call.tool_call_id, "content": envelope},
                )
            )

            if outcome.status == "ok" and outcome.accepted_submit:
                return RunOutcome("submitted", None, ordinal)


def _elapsed_since(start: float) -> Callable[[], float]:
    def elapsed() -> float:
        return time.monotonic() - start

    return elapsed
