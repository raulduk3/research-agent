"""What a tool handler receives and answers (AG-09, #287).

Every handler is called with an admitted call's parsed arguments and its
:class:`CallContext`, and returns a :class:`ToolAnswer` or raises
:class:`ToolError`. The answer names what it showed the run, so the trace
records it (TDD-2.1.2), and the extra budget it consumed, so the loop
charges it (AG-12); a handler never holds the run's budget itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["CallContext", "ToolAnswer", "ToolError", "ToolHandler"]


@dataclass(frozen=True, slots=True)
class CallContext:
    """The run and the snapshot hash one admitted call is answered for."""

    run_id: str
    snapshot_hash: str


@dataclass(frozen=True, slots=True)
class ToolAnswer:
    """One admitted call's answer and what it cost beyond the call itself.

    ``retrieved_ids`` are the artifact hashes the answer showed the run, as
    its trace records them (TDD-2.1.2). ``deep_reads`` and ``images`` are the
    extra budget dimensions the loop charges (AG-12); ``accepted_submit``
    marks the one call that ends the run with a sealed submission (AG-26).
    """

    data: Mapping[str, Any]
    retrieved_ids: tuple[str, ...] = ()
    deep_reads: int = 0
    images: int = 0
    accepted_submit: bool = False


class ToolError(Exception):
    """An admitted call that cannot be answered, with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolHandler(Protocol):
    """One tool's domain work over its already-validated arguments."""

    def __call__(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer: ...
