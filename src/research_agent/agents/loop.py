"""The canonical single-conversation run worker (AG-08).

One conversation between the agent model and the run's tools, with no
layer between them: nothing adds, removes, reorders or rewrites a
message, the loop only reserves budget, sends the next request, dispatches
whatever native tool calls the model made and appends their exact
responses. The run ends at the first accepted submit, an exhausted
budget, a plain model stop, or a conversation that no longer fits its
context -- and any of the last three leaves the run void (AG-15). Every
ending, and a model or tool call that raises, hands the caller one account
of the tokens received through its ``settle`` callable (#251), so the loop
itself never writes storage.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
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
class TokenUsage:
    """The provider's own usage record for one model response."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """One model turn: a content payload plus zero or more native tool calls.

    An empty ``tool_calls`` means the model stopped without invoking any
    tool -- a plain stop, which ends the run void when no submit was
    already accepted (AG-15). ``usage`` is the provider's usage record
    when the response carried one.
    """

    content: dict[str, Any]
    tool_calls: tuple[ToolCall, ...]
    generated_tokens: int
    usage: TokenUsage | None = None


class ModelClient(Protocol):
    """The pinned agent model, reached through the canonical conversation alone."""

    def complete(
        self, messages: list[dict[str, Any]], *, max_generation_tokens: int
    ) -> ModelResponse: ...


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """One tool call's result, as the dispatcher reports it to the loop.

    ``status`` is ``ok``, ``refused`` or ``error``, and ``data`` is the
    envelope the model receives. The loop charges the one tool-call attempt
    of every call it forwards; ``deep_reads``, ``images`` and ``ask_calls``
    are the extra budgets the answer consumed, which the loop charges too. The dispatcher
    charges nothing (#287). ``accepted_submit`` marks the one call the loop
    treats as ending the run with a sealed submission (AG-26).
    """

    status: str
    data: dict[str, Any]
    deep_reads: int = 0
    images: int = 0
    ask_calls: int = 0
    accepted_submit: bool = False


class ToolDispatcher(Protocol):
    """The run's tool service: query_cards, neighbors, graph, deep_read, ask, submit.

    ``tools.service.RunToolDispatcher`` is the shared tool service's side
    of this interface; a fixture-driven stand-in satisfies it in tests
    (AG-09). The dispatcher admits or refuses each call it receives against
    the run's stored specification and records either (SR-05).
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

    ``input_tokens`` and ``output_tokens`` total every response the run
    received. ``usage_source`` is ``provider`` only when every one of them
    carried the provider's usage record; otherwise the loop's own counts
    (the prepared context and ``generated_tokens``) fill the gaps and it is
    ``loop_count`` (#251).
    """

    status: str
    reason: str | None
    exchange_count: int
    input_tokens: int = 0
    output_tokens: int = 0
    usage_source: str = "loop_count"


@dataclass(slots=True)
class _Spend:
    """What the conversation has recorded and received, kept across a raise."""

    exchanges: int = 0
    responses: int = 0
    counted_by_loop: bool = False
    input_tokens: int = 0
    output_tokens: int = 0

    def receive(self, response: ModelResponse, context_tokens: int) -> None:
        self.responses += 1
        if response.usage is None:
            self.counted_by_loop = True
            self.input_tokens += context_tokens
            self.output_tokens += response.generated_tokens
        else:
            self.input_tokens += response.usage.input_tokens
            self.output_tokens += response.usage.output_tokens

    def settled(self, outcome: RunOutcome) -> RunOutcome:
        by_provider = self.responses > 0 and not self.counted_by_loop
        return replace(
            outcome,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            usage_source="provider" if by_provider else "loop_count",
        )


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
    settle: Callable[[RunOutcome], None] | None = None,
) -> RunOutcome:
    """Run one canonical conversation to its first accepted submit or void ending.

    ``allowed_tools`` is the run's already-validated tool allowlist (AG-14).
    The loop does not refuse a call itself: the dispatcher checks every call
    against the run's stored specification, refuses a name outside it as
    ``tool_not_allowed`` and records the refusal in the run's trace, and the
    loop charges the call its one tool call. ``elapsed_seconds``
    lets a caller inject a deterministic clock for tests; it defaults to
    a monotonic wall clock.

    ``settle`` receives the returned outcome exactly once, however the run
    ended. When the model client or the dispatcher raises, it receives a
    void outcome with reason ``loop_error`` and the tokens of every
    response already received, and the exception then propagates.
    """

    invalid = allowed_tools - ALLOWED_TOOLS
    if invalid:
        raise ContractValidationError(
            f"allowed_tools names an inadmissible tool: {sorted(invalid)}"
        )

    spend = _Spend()
    try:
        ended = _converse(
            run_id=run_id,
            attempt=attempt,
            conversation=[system_message, initial_message],
            allowed_tools=allowed_tools,
            client=client,
            dispatcher=dispatcher,
            sink=sink,
            count_tokens=count_tokens,
            budget=budget if budget is not None else RunBudget(),
            clock=elapsed_seconds or _elapsed_since(time.monotonic()),
            spend=spend,
        )
    except Exception:
        if settle is not None:
            settle(spend.settled(RunOutcome("void", "loop_error", spend.exchanges)))
        raise
    outcome = spend.settled(ended)
    if settle is not None:
        settle(outcome)
    return outcome


def _converse(
    *,
    run_id: str,
    attempt: int,
    conversation: list[Message],
    allowed_tools: frozenset[str],
    client: ModelClient,
    dispatcher: ToolDispatcher,
    sink: RunEventSink,
    count_tokens: TokenCounter,
    budget: RunBudget,
    clock: Callable[[], float],
    spend: _Spend,
) -> RunOutcome:
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
        spend.exchanges = ordinal

        response = client.complete(
            [message.to_dict() for message in conversation],
            max_generation_tokens=reservation,
        )
        spend.receive(response, context_tokens)

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
        spend.exchanges = ordinal

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
            # The one charge of this call, a refusal included (TDD-3.1.52).
            try:
                budget.charge_tool_call()
            except BudgetExhausted as exhausted:
                return RunOutcome(
                    "void", f"budget_exhausted:{exhausted.budget}", ordinal
                )

            # Every call is forwarded, a name outside the run's tools
            # included: the service refuses it and records the refusal in
            # the run's external trace (SR-02, TDD-2.1.2).
            outcome = dispatcher.dispatch(call, run_id=run_id)
            try:
                if outcome.deep_reads:
                    budget.charge_deep_read()
                if outcome.images:
                    budget.charge_images(outcome.images)
                if outcome.ask_calls:
                    budget.charge_ask()
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
