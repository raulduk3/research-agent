"""A run's tool trace: the external conduct record and the call notes.

:class:`TraceWriter` is SR-02's run trace (TDD-2.1.2). The shared tool
service writes it through storage, outside the run's control, for every
call a run makes: before executing a call it records the call's canonical
request hash and schema decision, which allocates the run's next call
sequence; a refused call is an entry with its refusal code; an admitted
call is then resolved by one terminal event carrying the response hash,
the artifact ids the answer showed the run and its budget deltas. Each
event also carries the bytes its hash covers, which storage keeps (#308).
Nothing the agent writes reaches these fields, so a check of the run's
conduct reads what the service did, never what the agent says it did.

:class:`RunTrace` keeps a call's own note and intent (AG-39), never its
domain arguments or response.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from ..contracts.canonical import CanonicalJsonError, canonical_json, sha256_hex
from ..contracts.tools import ToolCall
from ..storage.client import CommandResult
from ..storage.trace import bound_payload

__all__ = [
    "TraceEntry",
    "RunTrace",
    "TraceAppends",
    "TraceWriter",
    "request_bytes",
    "request_hash",
]

# The longest tool name a trace row holds; any longer name is agent text.
_TRACE_TOOL_CHARS = 64


def request_bytes(
    *, run_id: str, snapshot_id: str, tool: str, raw_arguments: object
) -> bytes:
    """The canonical bytes of one call exactly as the run made it.

    Arguments that have no canonical JSON form -- which admission refuses --
    are written as their representation, so even such a call has an entry.
    """

    call = {
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "tool": tool,
        "arguments": raw_arguments,
    }
    try:
        return canonical_json(call)
    except CanonicalJsonError:
        return repr(call).encode("utf-8", "backslashreplace")


def request_hash(
    *, run_id: str, snapshot_id: str, tool: str, raw_arguments: object
) -> str:
    """The hash of :func:`request_bytes`, the trace row's request hash."""

    return sha256_hex(
        request_bytes(
            run_id=run_id,
            snapshot_id=snapshot_id,
            tool=tool,
            raw_arguments=raw_arguments,
        )
    )


class TraceAppends(Protocol):
    """Storage's trace commands, as ``StorageClient`` exposes them (#297)."""

    def append_trace_request(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        tool: str,
        request_hash: str,
        decision: Literal["admitted", "refused"],
        reason: str | None,
        request_payload: bytes,
        request_truncated: bool,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult: ...

    def append_trace_terminal(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        outcome: Literal["response", "error"],
        response_hash: str,
        error_code: str | None,
        retrieved_ids: tuple[str, ...],
        budget_deltas: Mapping[str, int],
        response_payload: bytes,
        response_truncated: bool,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult: ...


class TraceWriter:
    """Record one run's calls in storage's external trace (TDD-2.1.2)."""

    def __init__(self, storage: TraceAppends) -> None:
        self._storage = storage

    def request(
        self,
        *,
        run_id: str,
        call_id: UUID,
        tool: str,
        request: bytes,
        refusal: str | None,
    ) -> int:
        """Record a call and its canonical *request* bytes before it runs.

        Returns the call sequence. *refusal* is the admission's refusal
        code, ``None`` for an admitted call. A tool name no trace row can
        hold is recorded as ``invalid``: it was refused as agent text before
        any tool could run. Storage keeps at most ``TRACE_PAYLOAD_BOUND``
        bytes of the request, flagged when cut.
        """

        recorded_tool = (
            tool
            if 1 <= len(tool) <= _TRACE_TOOL_CHARS and "\x00" not in tool
            else "invalid"
        )
        payload, truncated = bound_payload(request)
        result = self._storage.append_trace_request(
            run_id=UUID(run_id),
            call_id=call_id,
            tool=recorded_tool,
            request_hash=sha256_hex(request),
            decision="admitted" if refusal is None else "refused",
            reason=refusal,
            request_payload=payload,
            request_truncated=truncated,
            command_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
        return int(result.data["call_sequence"])

    def terminal(
        self,
        *,
        run_id: str,
        call_id: UUID,
        envelope: Mapping[str, Any],
        error_code: str | None,
        retrieved_ids: tuple[str, ...],
        budget_deltas: Mapping[str, int],
    ) -> None:
        """Resolve an admitted call with the exact envelope the run received.

        The envelope's canonical bytes are stored beside the row, bounded as
        a request's are.
        """

        response = canonical_json(envelope)
        payload, truncated = bound_payload(response)
        self._storage.append_trace_terminal(
            run_id=UUID(run_id),
            call_id=call_id,
            outcome="response" if error_code is None else "error",
            response_hash=sha256_hex(response),
            error_code=error_code,
            retrieved_ids=() if error_code is not None else retrieved_ids,
            budget_deltas=budget_deltas,
            response_payload=payload,
            response_truncated=truncated,
            command_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )


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
