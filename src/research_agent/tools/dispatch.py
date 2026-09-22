"""The five-tool dispatcher: admission, snapshot binding and budget charging (AG-09).

``dispatch_tool`` is the one entry point the shared tool service exposes
to a run's loop. Its own job is narrow and non-negotiable: charge one
tool attempt for every call including a refusal (TDD-3.1.52), admit only
the run's own narrowed tool subset (AG-14) from a fixed table of five
names -- never a sixth, however a caller spells it -- bind the call to
the run's own snapshot before any read runs (AG-10), and parse its
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
from .snapshot import RunLookup, authorize_snapshot

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
    charge. Every response, accepted or refused, carries the run's
    remaining budgets (AG-27).
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
        authorize_snapshot(lookup, run_id, requested_snapshot_id)
        request = ToolRequest.parse(tool, raw_arguments)
        data = handlers[tool](request.arguments, budget)
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
