"""Bind a submit call's claims to retrieved evidence and issued questions.

These functions are the tools' pre-storage gate (SR-07 to SR-10): they run
against data the tool service already holds for this run -- the evidence
ids its own completed tool calls actually returned, and the questions the
run's own sheet issued -- before a claim ever reaches the storage-owned
atomic seal (EN-03, ``storage.forecasts.seal_forecasts``). Storage checks
the sheet and evidence exist at all; these functions check the claim is
honest about *this run's* conduct, which storage has no way to see.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from datetime import datetime, timedelta, timezone
from typing import Any

from ..contracts.primitives import (
    ContractValidationError,
    validate_probability as _validate_probability,
    validate_utc_instant,
)

ADMITTED_EVENT_WINDOW_DAYS = (365, 180, 60)
MATURITY_ALLOWANCE_DAYS = 90


def bind_question(
    questions: Mapping[str, Mapping[str, Any]], question_id: str
) -> Mapping[str, Any]:
    """Resolve *question_id* to its immutable definition on the run's sheet (SR-08).

    ``questions`` is keyed by ``question_id`` from the run's own sealed
    sheet (Appendix A), never interpreted from agent free text and never
    accepting an agent-supplied resolver or target override: the returned
    record is exactly the stored ``Question`` the sheet issued. A claim
    naming any other id, including another shard's question, is rejected
    whole rather than silently dropped.
    """

    try:
        return questions[question_id]
    except KeyError:
        raise ContractValidationError(
            "claim names a question this run's sheet never issued"
        ) from None


def validate_evidence(
    evidence_ids: Sequence[str], retrieved_evidence_ids: Set[str]
) -> tuple[str, ...]:
    """Require every cited evidence id to be one this run actually retrieved (SR-07).

    ``retrieved_evidence_ids`` is the set of ids this run's own completed,
    successful tool calls returned; an id merely existing in the snapshot
    is not enough; an id from another run's calls is not enough. One to
    five distinct ids are required, matching the submit schema's own
    bound; any id absent from ``retrieved_evidence_ids`` rejects the whole
    claim rather than sealing the siblings that did check out.
    """

    if not 1 <= len(evidence_ids) <= 5:
        raise ContractValidationError("evidence_ids must hold 1 to 5 items")
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ContractValidationError("evidence_ids must be distinct")
    unretrieved = [item for item in evidence_ids if item not in retrieved_evidence_ids]
    if unretrieved:
        raise ContractValidationError("claim cites evidence this run never retrieved")
    return tuple(evidence_ids)


def validate_horizon(first_public_at: str, horizon: str, event_window_days: int) -> str:
    """Require a question's horizon to be its own target's fixed event end (SR-09).

    The agent supplies no horizon; the submit schema has no field for one
    (an override is an unknown field, refused before this runs). This
    checks the *question's own* stored horizon against the derivation
    policy instead: exactly ``event_window_days`` after the target's
    verified first-public origin, separate from the
    ``MATURITY_ALLOWANCE_DAYS`` resolution allowance applied after that
    end. ``event_window_days`` is the issued question's own registered
    target definition (365 for the three citation targets, 180 for
    ``venue_180d``, 60 for ``early_citation_rank_60d``); a value outside
    ``ADMITTED_EVENT_WINDOW_DAYS`` or a horizon that disagrees with it is
    rejected rather than trusted.
    """

    if event_window_days not in ADMITTED_EVENT_WINDOW_DAYS:
        raise ContractValidationError(
            "event_window_days is not an admitted registry window"
        )
    validate_utc_instant(first_public_at)
    validate_utc_instant(horizon)
    origin = datetime.strptime(first_public_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    end = datetime.strptime(horizon, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    if end - origin != timedelta(days=event_window_days):
        raise ContractValidationError(
            f"question horizon is not the origin's {event_window_days}-day event window"
        )
    return horizon


def validate_probability(value: object) -> int | float:
    """Require a finite JSON probability in [0, 1] (SR-10).

    Booleans, numeric strings, omission and nonfinite values are all
    rejected here rather than coerced; the canonical numeric value is
    returned unchanged for the sealed ledger record.
    """

    return _validate_probability(value)
