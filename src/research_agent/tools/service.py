"""The one shared tool service every run's calls go through (PL-20, TDD-2.1.36).

:class:`ToolService` answers one call at a time and keeps no conversation
state. For each call it reads the run's stored specification from storage
-- never a field of the call -- and admits the call against it, its note
and intent envelope (AG-39) before its domain arguments (TDD-2.1.5);
records the call as the run sent it, envelope and all, in the run's
external trace before anything runs, a refusal included (TDD-2.1.2);
answers an admitted call from the snapshot the specification names
(PL-21); and resolves the trace entry with the exact envelope the run
receives. What it keeps across calls is
only sealed snapshot content, keyed by snapshot hash (``tools.snapshots``),
so nothing one run's call leaves behind is readable by another's.

Budgets belong to the run's loop: the loop charges one tool call for every
call it forwards and charges the deep reads, images and asks an answer
reports (AG-12, decision 0031). :class:`RunToolDispatcher` is the loop's side of the service for
one run, supplying the snapshot id from the run's own trusted context
(TDD-3.1.51), never from the model's call.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID, uuid4

from ..agents.loop import ToolCall, ToolOutcome
from ..storage.client import RunSpecificationRecord, StorageClientError
from .admission import Refusal, admit_request
from .answers import ToolAnswer, ToolError, ToolHandler
from .dispatch import (
    answer_envelope,
    error_envelope,
    execute_admitted,
    refusal_envelope,
)
from .lookup import SpecificationLookup
from .snapshot import PaperRequests, SnapshotMembership
from .trace import TraceWriter, request_bytes

__all__ = ["RunSpecifications", "RunToolDispatcher", "ToolService"]


class RunSpecifications(Protocol):
    def read_run_specification(self, run_id: UUID) -> RunSpecificationRecord: ...


class ToolService:
    """Admit, trace and answer each tool call against its run's stored record."""

    def __init__(
        self,
        *,
        specifications: RunSpecifications,
        handlers: Mapping[str, ToolHandler],
        membership: SnapshotMembership,
        paper_requests: PaperRequests,
        trace: TraceWriter,
    ) -> None:
        self._specifications = specifications
        self._handlers = dict(handlers)
        self._membership = membership
        self._paper_requests = paper_requests
        self._trace = trace

    def call(
        self, *, run_id: str, snapshot_id: str, tool: str, raw_call: object
    ) -> ToolOutcome:
        """Answer one call of *run_id*, recording it before it runs.

        *raw_call* is the ``{note, intent, arguments}`` envelope the model
        sent (AG-39), and the trace records it whole. A run storage does not
        hold is refused with nothing recorded, since there is no run to
        record it against.
        """

        try:
            specification = self._specifications.read_run_specification(UUID(run_id))
        except StorageClientError as error:
            if error.status_code != 404:
                raise
            return ToolOutcome(
                "refused", refusal_envelope("unknown_run", "the run is not known")
            )
        lookup = SpecificationLookup(specification)
        admitted = admit_request(
            tool=tool,
            raw_call=raw_call,
            run_id=run_id,
            requested_snapshot_id=snapshot_id,
            lookup=lookup,
            handlers=frozenset(self._handlers),
            active=lookup.active,
        )
        call_id = uuid4()
        self._trace.request(
            run_id=run_id,
            call_id=call_id,
            tool=tool,
            request=request_bytes(
                run_id=run_id,
                snapshot_id=snapshot_id,
                tool=tool,
                raw_arguments=raw_call,
            ),
            refusal=admitted.code if isinstance(admitted, Refusal) else None,
        )
        if isinstance(admitted, Refusal):
            return ToolOutcome(
                "refused", refusal_envelope(admitted.code, admitted.message)
            )
        try:
            answer = execute_admitted(
                admitted,
                run_id=run_id,
                handlers=self._handlers,
                membership=self._membership,
                paper_requests=self._paper_requests,
            )
        except ToolError as error:
            envelope = error_envelope(error)
            self._resolve(run_id, call_id, envelope, error.code, ToolAnswer({}))
            return ToolOutcome("error", envelope)
        except Exception:
            # An earlier call left unresolved blocks sealing (TDD-2.1.2), so
            # an unexpected failure is still resolved before it propagates.
            envelope = error_envelope(
                ToolError("internal_error", "the call could not be answered")
            )
            self._resolve(run_id, call_id, envelope, "internal_error", ToolAnswer({}))
            raise
        envelope = answer_envelope(answer)
        self._resolve(run_id, call_id, envelope, None, answer)
        return ToolOutcome(
            "ok",
            envelope,
            deep_reads=answer.deep_reads,
            images=answer.images,
            ask_calls=answer.ask_calls,
            accepted_submit=answer.accepted_submit,
        )

    def _resolve(
        self,
        run_id: str,
        call_id: UUID,
        envelope: Mapping[str, Any],
        error_code: str | None,
        answer: ToolAnswer,
    ) -> None:
        deltas = {"tool_calls": 1}
        if answer.deep_reads:
            deltas["deep_reads"] = answer.deep_reads
        if answer.images:
            deltas["images"] = answer.images
        if answer.ask_calls:
            deltas["ask_calls"] = answer.ask_calls
        self._trace.terminal(
            run_id=run_id,
            call_id=call_id,
            envelope=envelope,
            error_code=error_code,
            retrieved_ids=tuple(dict.fromkeys(answer.retrieved_ids)),
            budget_deltas=deltas,
        )


class RunToolDispatcher:
    """One run's loop-side view of the shared service (``agents.loop``)."""

    def __init__(self, service: ToolService, *, snapshot_id: str) -> None:
        self._service = service
        self._snapshot_id = snapshot_id

    def dispatch(self, call: ToolCall, *, run_id: str) -> ToolOutcome:
        return self._service.call(
            run_id=run_id,
            snapshot_id=self._snapshot_id,
            tool=call.name,
            raw_call=call.arguments,
        )
