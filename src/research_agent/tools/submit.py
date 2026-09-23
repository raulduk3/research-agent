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
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts.primitives import ContractValidationError

__all__ = ["authorize_submit_scope"]


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
