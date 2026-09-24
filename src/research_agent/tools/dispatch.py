"""The five-tool dispatcher: admission, snapshot binding and one answer (AG-09).

``dispatch_tool`` answers one tool call in process. Its job is narrow:
admit only the run's own narrowed tool subset (AG-14) from a fixed table of
five names -- never a sixth, however a caller spells it -- bind the call to
the run's own snapshot before any read runs (AG-10), answer a ``deep_read``
or ``graph`` of a family that snapshot lacks with a recorded paper request
instead of a read (decision 0025), and parse its domain arguments through
the strict schemas of :mod:`research_agent.contracts.tools` (AG-11). The
admission itself is :func:`research_agent.tools.admission.admit_request`;
the domain work for each tool -- resolving cards, ranking passages,
rendering a page, sealing a forecast -- is a :class:`ToolHandler` per tool
name, which reports what it retrieved and what extra budget it consumed.

Budget charging is not done here. The run's loop owns the run's budget and
charges one tool call for every call it forwards, a refusal included
(TDD-3.1.52); the tool service runs in its own container and never holds
that budget (#287). A caller that does hold it may pass it so the answer
carries the remaining budgets (AG-27); nothing here charges it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..agents.budgets import RunBudget, attach_remaining
from .admission import Admission, Refusal, admit_request
from .answers import CallContext, ToolAnswer, ToolError, ToolHandler
from .snapshot import (
    PaperRequests,
    RunLookup,
    SnapshotMembership,
    answer_outside_snapshot,
)

__all__ = [
    "CallContext",
    "ToolAnswer",
    "ToolError",
    "ToolHandler",
    "answer_envelope",
    "dispatch_tool",
    "error_envelope",
    "execute_admitted",
    "refusal_envelope",
]


def refusal_envelope(code: str, message: str) -> dict[str, Any]:
    return {"status": "refused", "code": code, "message": message, "data": None}


def answer_envelope(answer: ToolAnswer) -> dict[str, Any]:
    return {"status": "ok", "code": None, "message": None, "data": dict(answer.data)}


def error_envelope(error: ToolError) -> dict[str, Any]:
    return {
        "status": "error",
        "code": error.code,
        "message": error.message,
        "data": None,
    }


def execute_admitted(
    admission: Admission,
    *,
    run_id: str,
    handlers: Mapping[str, ToolHandler],
    membership: SnapshotMembership,
    paper_requests: PaperRequests,
) -> ToolAnswer:
    """Answer one admitted call from the run's own snapshot.

    A ``deep_read`` or ``graph`` naming a family the snapshot lacks never
    reaches its handler; storage's paper-request receipt is the answer.
    """

    outside = answer_outside_snapshot(
        tool=admission.tool,
        arguments=admission.arguments,
        run_id=run_id,
        snapshot_hash=admission.snapshot_hash,
        membership=membership,
        requests=paper_requests,
    )
    if outside is not None:
        return ToolAnswer(outside)
    return handlers[admission.tool](
        admission.arguments, CallContext(run_id, admission.snapshot_hash)
    )


def dispatch_tool(
    *,
    tool: str,
    raw_arguments: object,
    run_id: str,
    requested_snapshot_id: str,
    lookup: RunLookup,
    handlers: Mapping[str, ToolHandler],
    membership: SnapshotMembership,
    paper_requests: PaperRequests,
    budget: RunBudget | None = None,
    context_tokens: int = 0,
) -> dict[str, Any]:
    """Answer one tool call for *run_id* and return its envelope.

    An unknown name, a tool the run's own configuration narrowed away, or
    one absent from *handlers* is refused as ``tool_not_allowed`` without
    ever reaching a handler or a snapshot lookup. A snapshot mismatch or a
    malformed argument is refused as ``invalid_input``. A handler that
    cannot answer is an ``error`` with its code. When *budget* is given the
    envelope carries its remaining budgets; it is read, never charged.
    """

    admitted = admit_request(
        tool=tool,
        raw_arguments=raw_arguments,
        run_id=run_id,
        requested_snapshot_id=requested_snapshot_id,
        lookup=lookup,
        handlers=frozenset(handlers),
    )
    if isinstance(admitted, Refusal):
        envelope = refusal_envelope(admitted.code, admitted.message)
    else:
        try:
            envelope = answer_envelope(
                execute_admitted(
                    admitted,
                    run_id=run_id,
                    handlers=handlers,
                    membership=membership,
                    paper_requests=paper_requests,
                )
            )
        except ToolError as error:
            envelope = error_envelope(error)
    if budget is None:
        return envelope
    return attach_remaining(envelope, budget, context_tokens=context_tokens)
