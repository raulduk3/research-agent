"""The five-tool dispatcher: admission, snapshot binding and budget charging (AG-09).

``dispatch_tool`` is the one entry point the shared tool service exposes
to a run's loop. Its own job is narrow and non-negotiable: charge one
tool attempt for every call including a refusal (TDD-3.1.52), admit only
the run's own narrowed tool subset (AG-14) from a fixed table of five
names -- never a sixth, however a caller spells it -- bind the call to
the run's own snapshot before any read runs (AG-10), answer a
``deep_read`` or ``graph`` of a family that snapshot lacks with a recorded
paper request instead of a read (decision 0025), and parse its
domain arguments through the strict schemas of
:mod:`research_agent.contracts.tools` (AG-11). The actual domain work for
each tool -- resolving cards, ranking passages, rendering a page, sealing
a forecast -- is supplied by the caller as a :class:`ToolHandler` per
tool name, so this module owns admission and accounting, not storage
access.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ..agents.budgets import RunBudget, attach_remaining
from ..contracts.primitives import ContractValidationError
from ..contracts.tools import TOOL_NAMES, ToolRequest
from .snapshot import (
    PaperRequests,
    RunLookup,
    SnapshotMembership,
    answer_outside_snapshot,
    authorize_snapshot,
)
from .submit import authorize_submit_scope

__all__ = ["ToolHandler", "dispatch_tool"]


class ToolHandler(Protocol):
    """One tool's domain work over its already-validated arguments."""

    def __call__(
        self, arguments: Mapping[str, Any], budget: RunBudget
    ) -> dict[str, Any]:
        """Return the tool's JSON-ready response data, charging any extra
        budget dimension it consumes (deep reads, images) itself."""


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
    budget: RunBudget,
    context_tokens: int,
) -> dict[str, Any]:
    """Dispatch one tool call for *run_id*, charging its budget exactly once.

    Every call charges one tool attempt before anything else runs, so a
    refusal costs the run a call exactly as an accepted one does. An
    unknown name, a tool the run's own configuration narrowed away, or
    one absent from *handlers* is refused as ``tool_not_allowed`` without
    ever reaching a handler or a snapshot lookup. A snapshot mismatch or
    a malformed argument is refused as ``invalid_input``, still after the
    charge. A ``deep_read`` or ``graph`` naming a family outside the run's
    snapshot never reaches its handler: it answers ``not_in_snapshot``
    with storage's paper-request receipt. Every response, accepted or
    refused, carries the run's remaining budgets (AG-27).
    """

    budget.charge_tool_call()
    if tool not in TOOL_NAMES or tool not in handlers:
        return attach_remaining(
            _refusal("tool_not_allowed", "tool is not admitted"),
            budget,
            context_tokens=context_tokens,
        )
    allowed = lookup.allowed_tools_for(run_id)
    if tool not in allowed:
        return attach_remaining(
            _refusal("tool_not_allowed", "tool is not in this run's admitted set"),
            budget,
            context_tokens=context_tokens,
        )
    try:
        snapshot_hash = authorize_snapshot(lookup, run_id, requested_snapshot_id)
        request = ToolRequest.parse(tool, raw_arguments)
        if tool == "submit":
            authorize_submit_scope(
                request.arguments,
                paper_id=lookup.paper_id_for(run_id),
                issued_question_ids=lookup.issued_question_ids_for(run_id),
            )
        outside = answer_outside_snapshot(
            tool=tool,
            arguments=request.arguments,
            run_id=run_id,
            snapshot_hash=snapshot_hash,
            membership=membership,
            requests=paper_requests,
        )
        data = (
            outside
            if outside is not None
            else handlers[tool](request.arguments, budget)
        )
    except ContractValidationError as error:
        return attach_remaining(
            _refusal("invalid_input", str(error)),
            budget,
            context_tokens=context_tokens,
        )
    return attach_remaining(
        {"status": "ok", "code": None, "message": None, "data": data},
        budget,
        context_tokens=context_tokens,
    )


def _refusal(code: str, message: str) -> dict[str, Any]:
    return {"status": "refused", "code": code, "message": message, "data": None}
