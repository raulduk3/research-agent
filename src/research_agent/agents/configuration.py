"""Narrow a genome's admitted tool set from the fixed five, never widen it (AG-14).

``validate_tools`` is the admission-time check between a genome's
configured tool list and the run specification that fixes what a run's
tool calls will ever be allowed to name. It is deliberately the only
thing this module does for this slice: a genome's tools are the run's
``allowed_tools`` (``research_agent.contracts.runs.ALLOWED_TOOLS`` already
carries the five-name ceiling storage enforces), never a superset chosen
elsewhere.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..contracts.primitives import ContractValidationError
from ..contracts.runs import ALLOWED_TOOLS


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
