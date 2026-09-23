"""Admission-time genome checks: tool narrowing (AG-14) and island (AG-36).

``validate_tools`` is the admission-time check between a genome's
configured tool list and the run specification that fixes what a run's
tool calls will ever be allowed to name: a genome's tools are the run's
``allowed_tools`` (``research_agent.contracts.runs.ALLOWED_TOOLS`` already
carries the five-name ceiling storage enforces), never a superset chosen
elsewhere.

``validate_island`` is AG-36's admission check: every genome names exactly
one of the three islands ``orchestration.scheduler.ISLANDS`` admits, the
same set slot creation uses to route a paper to its island.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..contracts.primitives import ContractValidationError
from ..contracts.runs import ALLOWED_TOOLS
from ..orchestration.scheduler import ISLANDS


def validate_tools(tools: Sequence[str]) -> tuple[str, ...]:
    """Validate a configuration's tool list against the fixed five (AG-14).

    Rejects the entire configuration -- raises rather than silently
    dropping an unknown name -- when ``tools`` is empty, holds a
    duplicate, or names anything outside
    :data:`research_agent.contracts.runs.ALLOWED_TOOLS`. A configuration
    that passes admits exactly the ordered names given; nothing here can
    add a sixth tool or reorder the caller's list.
    """

    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        raise ContractValidationError("tools must be a list of tool names")
    if not 1 <= len(tools) <= len(ALLOWED_TOOLS):
        raise ContractValidationError(
            f"tools must hold 1 to {len(ALLOWED_TOOLS)} items"
        )
    if len(set(tools)) != len(tools):
        raise ContractValidationError("tools must be distinct")
    for tool in tools:
        if not isinstance(tool, str) or tool not in ALLOWED_TOOLS:
            raise ContractValidationError("tools names an inadmissible tool")
    return tuple(tools)


def validate_island(island: str) -> str:
    """Validate a genome's island against the fixed three (AG-36).

    Rejects the whole configuration -- raises rather than defaulting to an
    island -- when ``island`` is missing or names anything outside
    :data:`research_agent.orchestration.scheduler.ISLANDS`.
    """

    if not isinstance(island, str) or island not in ISLANDS:
        raise ContractValidationError(f"island must be one of {sorted(ISLANDS)}")
    return island
