"""Bind a submit call's claims to this run's own conduct, then seal atomically (EN-03).

``seal_forecasts`` joins the tools' per-run sealing gate (SR-07, SR-08,
SR-10; :mod:`research_agent.environment.sealing`) to storage's
already-transactional submission seal
(:class:`~research_agent.storage.submissions.SubmissionRepository`,
itself SR-07 to SR-11's structural owner). It adds exactly the one check
storage cannot make on its own: that every claim names a question this
run's own sheet actually issued and, for a forecast, cites only evidence
this run's own tool calls actually retrieved. Storage re-validates claim
shape and sheet membership independently; this never widens what storage
would accept, only narrows it further before storage ever sees a
submission it should reject.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from typing import Any

from ..environment.sealing import bind_question, validate_evidence, validate_probability
from .idempotency import StoredResponse
from .commands import CommandIdentity
from .submissions import SubmissionRepository

__all__ = ["seal_forecasts"]


def seal_forecasts(
    submissions: SubmissionRepository,
    *,
    identity: CommandIdentity,
    sheet_hash: str,
    submitter_id: str,
    claims: list[Mapping[str, Any]],
    questions: Mapping[str, Mapping[str, Any]],
    retrieved_evidence_ids: Set[str],
) -> StoredResponse:
    """Validate *claims* against this run's own conduct, then seal atomically.

    ``questions`` is the run's own issued sheet, keyed by ``question_id``;
    ``retrieved_evidence_ids`` is the set of evidence ids this run's own
    completed, successful tool calls actually returned. A claim naming a
    question absent from ``questions``, or a forecast citing evidence
    absent from ``retrieved_evidence_ids``, raises before storage's
    transaction ever opens -- no sibling claim in the same submit call is
    sealed either. Claims are the already strictly validated shape
    :func:`research_agent.contracts.submissions.parse_claims` produces;
    this does not re-parse them.
    """

    for claim in claims:
        bind_question(questions, claim["question_id"])
        if claim["kind"] == "forecast":
            validate_evidence(claim["evidence_hashes"], retrieved_evidence_ids)
            validate_probability(claim["confidence"])
    return submissions.execute(
        "submit",
        identity=identity,
        payload={
            "sheet_hash": sheet_hash,
            "submitter_id": submitter_id,
            "claims": list(claims),
        },
    )
