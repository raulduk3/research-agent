"""Optional human forecast offers, kept independent of digest access (EN-34)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID, uuid4

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


class _SealedCommand(Protocol):
    data: Mapping[str, Any]


class SealCommands(Protocol):
    """The two storage calls a sealed human answer needs (matches StorageClient)."""

    def seal_sheet(
        self,
        *,
        questions: tuple[Mapping[str, Any], ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> _SealedCommand: ...

    def submit(
        self,
        *,
        sheet_hash: str,
        submitter_id: UUID,
        claims: tuple[Mapping[str, Any], ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> _SealedCommand: ...


@dataclass(frozen=True, slots=True)
class HumanForecastSeal:
    """What a rater sees after answering: sealed once, or refused with why."""

    accepted: bool
    reason: str | None


def seal_human_forecast(
    storage: SealCommands,
    *,
    offer: HumanQuestionOffer,
    question: Mapping[str, Any],
    rater_id: UUID,
    probability: float,
    evidence_hashes: Sequence[str],
    command_id: UUID,
    request_id: UUID,
    idempotency_key: UUID,
    now: datetime | None = None,
) -> HumanForecastSeal:
    """Seal one rater's answer to an offered question through the common path (EN-34).

    Before ``offer``'s deadline, an answer is sealed exactly as any other
    forecast is: storage's own sheet-then-submit seal, with the rater as
    submitter and its view receipts standing in for the evidence an agent
    run would have retrieved. After the deadline the answer is refused
    before storage is ever called, so a rater who misses the window is
    never blocked from rating the digest or reading it.
    """
    if str(question["question_id"]) != offer.question_id:
        raise ValueError("question does not match the offered question_id")
    if not is_offer_open(offer, now=now):
        return HumanForecastSeal(accepted=False, reason="offer expired")
    sealed = storage.seal_sheet(
        questions=(question,),
        command_id=uuid4(),
        request_id=uuid4(),
        idempotency_key=uuid4(),
    )
    result = storage.submit(
        sheet_hash=str(sealed.data["sheet_hash"]),
        submitter_id=rater_id,
        claims=(
            {
                "kind": "forecast",
                "question_id": offer.question_id,
                "evidence_hashes": list(evidence_hashes),
                "confidence": probability,
            },
        ),
        command_id=command_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )
    if bool(result.data["accepted"]):
        return HumanForecastSeal(accepted=True, reason=None)
    return HumanForecastSeal(accepted=False, reason=str(result.data["reason"]))
