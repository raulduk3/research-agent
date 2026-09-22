"""A minimal, append-only record of a run's accepted tool-call notes and
intents, in call order (AG-39).

This is SR-02's "run trace" narrowed to exactly the boundary AG-39 needs:
a call's own note and intent, never its domain arguments, its response, or
anything about the run itself. The full run trace SR-02 describes, and how
the loop supplies one call after another to it, belong to the orchestration
layer that does not exist yet; nothing here anticipates that shape beyond
what recording one call's note and intent requires.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.tools import ToolCall

__all__ = ["TraceEntry", "RunTrace"]


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """One accepted tool call's note and intent, as the trace records it."""

    tool: str
    note: str
    intent: str


@dataclass(slots=True)
class RunTrace:
    """A run's tool-call notes and intents, in the order calls were made.

    Append-only: ``record`` is the only way to add an entry, and nothing
    already recorded can be changed or removed, the same rule SR-14 gives
    the ledger applied at this narrower boundary.
    """

    _entries: list[TraceEntry] = field(default_factory=list)

    def record(self, call: ToolCall) -> TraceEntry:
        """Append *call*'s note and intent as the next trace entry."""

        entry = TraceEntry(tool=call.tool, note=call.note, intent=call.intent)
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[TraceEntry, ...]:
        return tuple(self._entries)
