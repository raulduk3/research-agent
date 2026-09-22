"""Optional human forecast offers, kept independent of digest access (EN-34)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from research_agent.contracts.primitives import validate_sha256, validate_utc_instant

QUALIFIED_RESOLVER_ID = "citation_reach_365d"
OFFERED_QUESTION_LIMIT = 3


@dataclass(frozen=True, slots=True)
class HumanQuestionOffer:
    """One question offered identically to every rater, independent of the digest."""

    question_id: str
    deadline: str


def offer_human_questions(
    batch_hash: str, questions: Sequence[Mapping[str, Any]]
) -> tuple[HumanQuestionOffer, ...]:
    """Rank a batch's qualified questions and offer the first few to every rater.

    Ranking is a pure function of ``batch_hash`` and each question's id, so
    every rater who reads the offer for a batch sees the identical set in the
    identical order, with no dependence on who asks or when.
    """
    validate_sha256(batch_hash)
    qualified = [
        question
        for question in questions
        if question["resolver_id"] == QUALIFIED_RESOLVER_ID
    ]
    ranked = sorted(qualified, key=lambda question: _rank_key(batch_hash, question))
    return tuple(
        HumanQuestionOffer(
            question_id=str(question["question_id"]),
            deadline=validate_utc_instant(question["horizon"]),
        )
        for question in ranked[:OFFERED_QUESTION_LIMIT]
    )


def is_offer_open(offer: HumanQuestionOffer, *, now: datetime | None = None) -> bool:
    """Return whether an authenticated answer to ``offer`` is still admitted."""
    current = now or datetime.now(timezone.utc)
    deadline = datetime.strptime(offer.deadline, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    return current < deadline


def participation_status(
    offer: HumanQuestionOffer, *, answered: bool, now: datetime | None = None
) -> str:
    """Classify an offer as offered, answered or expired; never a filled-in zero.

    Missing an offer's deadline must read as ``expired``, distinct from a
    forecast that was answered and distinct from one that scored badly, so
    reports never mistake a rater's silence for a submitted prediction.
    """
    if answered:
        return "answered"
    return "offered" if is_offer_open(offer, now=now) else "expired"


def _rank_key(batch_hash: str, question: Mapping[str, Any]) -> str:
    return sha256(f"{batch_hash}:{question['question_id']}".encode()).hexdigest()
