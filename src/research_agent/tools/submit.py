"""submit's own scope check: the run's own paper id and issued questions (AG-26).

Every other constraint on a submit call already lives in the shared strict
schema (``contracts.tools``, ``contracts.submissions``): finite
probabilities, bounded rationales, distinct evidence ids. What that schema
cannot check on its own is whether the call actually names *this* run's
own paper and *its* issued questions, since those facts live in the run's
immutable specification, not in the call's own bytes. ``dispatch_tool``
calls :func:`authorize_submit_scope` with the run's own paper id and
issued question ids before a submit call ever reaches its handler, so a
submit naming another paper -- or covering fewer or more questions than
the run's own slot issued -- is refused whole (AG-26).

:class:`SubmitHandler` forwards an admitted submit to storage's commit
boundary, ``POST /v1/runs/{id}/submit`` (TDD-2.1.36), which rechecks it and
seals the answers and nomination in one transaction or records the
rejected attempt (SR-11). Only an accepted submission ends the run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID, uuid4

from ..contracts.primitives import ContractValidationError
from ..storage.client import CommandResult, StorageClientError
from .answers import CallContext, ToolAnswer, ToolError

__all__ = ["SubmitHandler", "SubmitRuns", "authorize_submit_scope"]


class SubmitRuns(Protocol):
    def submit_run(
        self,
        *,
        run_id: UUID,
        submission_id: UUID,
        answers: tuple[Mapping[str, Any], ...],
        nomination: Mapping[str, Any],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult: ...


class SubmitHandler:
    """Forward an admitted submit to storage's sealing transaction."""

    def __init__(self, *, storage: SubmitRuns) -> None:
        self._storage = storage

    def __call__(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer:
        try:
            result = self._storage.submit_run(
                run_id=UUID(context.run_id),
                submission_id=UUID(arguments["submission_id"]),
                answers=tuple(arguments["answers"]),
                nomination=arguments["nomination"],
                command_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            )
        except StorageClientError as error:
            if error.code == "state_conflict":
                raise ToolError("run_not_active", str(error)) from error
            raise
        data = dict(result.data)
        return ToolAnswer(
            {
                "kind": "submission",
                "accepted": data["accepted"] is True,
                "submission_id": data.get("submission_id"),
                "reason": data.get("reason"),
            },
            accepted_submit=data["accepted"] is True,
        )


def authorize_submit_scope(
    arguments: Mapping[str, Any],
    *,
    paper_id: str,
    issued_question_ids: frozenset[str],
) -> None:
    """Refuse a submit call naming another paper or an uneven question set.

    ``arguments`` is a submit call's already schema-validated arguments
    (``contracts.tools.ToolRequest.parse("submit", ...)``). Raises
    ``ContractValidationError`` when the nomination's ``paper_id`` is not
    *paper_id*, or when the answers' question ids are not exactly
    *issued_question_ids* -- storage rechecks the same facts inside its
    own sealing transaction (AG-26), so this is a defense-in-depth refusal
    at the dispatch layer, before a call ever reaches storage.
    """

    if arguments["nomination"]["paper_id"] != paper_id:
        raise ContractValidationError(
            "submit's nomination names a paper other than the run's own"
        )
    answer_ids = frozenset(answer["question_id"] for answer in arguments["answers"])
    if answer_ids != issued_question_ids:
        raise ContractValidationError(
            "submit's answers do not exactly cover the run's issued questions"
        )
