from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.ratings.forecasts import (
    HumanQuestionOffer,
    is_offer_open,
    offer_human_questions,
    participation_status,
    seal_human_forecast,
)

BATCH_HASH = sha256(b"a-batch").hexdigest()
OPEN_HORIZON = "2999-01-01T00:00:00.000000Z"
PAST_HORIZON = "2000-01-01T00:00:00.000000Z"


def question(
    question_id: str,
    *,
    resolver_id: str = "citation_reach_365d",
    horizon: str = OPEN_HORIZON,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "target_definition_hash": sha256(question_id.encode()).hexdigest(),
        "resolver_id": resolver_id,
        "resolver_version": 1,
        "horizon": horizon,
    }


def test_only_qualified_citation_reach_questions_are_offered() -> None:
    qualified = question("11111111-1111-4111-8111-111111111111")
    unqualified = question(
        "22222222-2222-4222-8222-222222222222",
        resolver_id="late_citation_activity_365d",
    )
    offers = offer_human_questions(BATCH_HASH, [qualified, unqualified])
    assert [offer.question_id for offer in offers] == [qualified["question_id"]]


def test_at_most_three_questions_are_offered_and_fewer_leave_a_smaller_offer() -> None:
    questions = [
        question(f"1111111{index}-1111-4111-8111-111111111111") for index in range(5)
    ]
    offers = offer_human_questions(BATCH_HASH, questions)
    assert len(offers) == 3

    fewer = offer_human_questions(BATCH_HASH, questions[:2])
    assert len(fewer) == 2


def test_the_offered_ranking_is_identical_for_every_rater_and_every_call() -> None:
    questions = [
        question(f"1111111{index}-1111-4111-8111-111111111111") for index in range(5)
    ]
    first_read = offer_human_questions(BATCH_HASH, questions)
    second_read = offer_human_questions(BATCH_HASH, list(reversed(questions)))
    assert first_read == second_read


def test_an_offer_is_open_before_its_deadline_and_closed_after() -> None:
    open_offer = HumanQuestionOffer(question_id="q", deadline=OPEN_HORIZON)
    expired_offer = HumanQuestionOffer(question_id="q", deadline=PAST_HORIZON)
    now = datetime(2100, 1, 1, tzinfo=timezone.utc)
    assert is_offer_open(open_offer, now=now)
    assert not is_offer_open(expired_offer, now=now)


def test_participation_status_never_reports_a_synthetic_zero() -> None:
    now = datetime(2100, 1, 1, tzinfo=timezone.utc)
    open_offer = HumanQuestionOffer(question_id="q", deadline=OPEN_HORIZON)
    expired_offer = HumanQuestionOffer(question_id="q", deadline=PAST_HORIZON)

    assert participation_status(open_offer, answered=False, now=now) == "offered"
    assert participation_status(expired_offer, answered=False, now=now) == "expired"
    assert participation_status(expired_offer, answered=True, now=now) == "answered"
    assert participation_status(open_offer, answered=True, now=now) == "answered"


@dataclass
class _StorageResult:
    data: dict[str, Any]


class FakeSealCommands:
    """Records calls a real StorageClient would make, without touching storage."""

    def __init__(self, *, submit_response: dict[str, Any] | None = None) -> None:
        self.sheet_calls: list[tuple[dict[str, Any], ...]] = []
        self.submit_calls: list[dict[str, Any]] = []
        self._submit_response = submit_response or {
            "accepted": True,
            "submission_ids": [str(uuid4())],
            "receipt": {},
        }

    def seal_sheet(
        self,
        *,
        questions: tuple[dict[str, Any], ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> _StorageResult:
        self.sheet_calls.append(questions)
        return _StorageResult({"sheet_hash": "a" * 64, "sealed_at": OPEN_HORIZON})

    def submit(
        self,
        *,
        sheet_hash: str,
        submitter_id: UUID,
        claims: tuple[dict[str, Any], ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> _StorageResult:
        self.submit_calls.append(
            {
                "sheet_hash": sheet_hash,
                "submitter_id": submitter_id,
                "claims": claims,
            }
        )
        return _StorageResult(self._submit_response)


RATER_ID = UUID("11111111-1111-4111-8111-111111111111")
OFFERED_QUESTION_ID = "22222222-2222-4222-8222-222222222222"


def _identity() -> dict[str, UUID]:
    return {
        "command_id": uuid4(),
        "request_id": uuid4(),
        "idempotency_key": uuid4(),
    }


def test_seal_human_forecast_seals_a_valid_answer_before_the_deadline() -> None:
    offer = HumanQuestionOffer(question_id=OFFERED_QUESTION_ID, deadline=OPEN_HORIZON)
    definition = question(OFFERED_QUESTION_ID)
    storage = FakeSealCommands()
    now = datetime(2100, 1, 1, tzinfo=timezone.utc)

    result = seal_human_forecast(
        storage,
        offer=offer,
        question=definition,
        rater_id=RATER_ID,
        probability=0.6,
        evidence_hashes=[sha256(b"view-receipt").hexdigest()],
        now=now,
        **_identity(),
    )

    assert result.accepted is True
    assert result.reason is None
    assert storage.sheet_calls == [(definition,)]
    submitted = storage.submit_calls[0]
    assert submitted["submitter_id"] == RATER_ID
    assert submitted["sheet_hash"] == "a" * 64
    (claim,) = submitted["claims"]
    assert claim["question_id"] == OFFERED_QUESTION_ID
    assert claim["confidence"] == 0.6


def test_seal_human_forecast_refuses_after_the_deadline() -> None:
    offer = HumanQuestionOffer(question_id=OFFERED_QUESTION_ID, deadline=PAST_HORIZON)
    definition = question(OFFERED_QUESTION_ID)
    storage = FakeSealCommands()
    now = datetime(2100, 1, 1, tzinfo=timezone.utc)

    result = seal_human_forecast(
        storage,
        offer=offer,
        question=definition,
        rater_id=RATER_ID,
        probability=0.6,
        evidence_hashes=[sha256(b"view-receipt").hexdigest()],
        now=now,
        **_identity(),
    )

    assert result.accepted is False
    assert result.reason == "offer expired"
    assert storage.sheet_calls == []
    assert storage.submit_calls == []


def test_seal_human_forecast_reports_a_duplicate_refused_by_storage() -> None:
    offer = HumanQuestionOffer(question_id=OFFERED_QUESTION_ID, deadline=OPEN_HORIZON)
    definition = question(OFFERED_QUESTION_ID)
    storage = FakeSealCommands(
        submit_response={
            "accepted": False,
            "reason": "submitter already has a sealed claim for this question",
            "receipt": {},
        }
    )
    now = datetime(2100, 1, 1, tzinfo=timezone.utc)

    result = seal_human_forecast(
        storage,
        offer=offer,
        question=definition,
        rater_id=RATER_ID,
        probability=0.6,
        evidence_hashes=[sha256(b"view-receipt").hexdigest()],
        now=now,
        **_identity(),
    )

    assert result.accepted is False
    assert result.reason == "submitter already has a sealed claim for this question"


def test_seal_human_forecast_rejects_a_question_the_offer_never_named() -> None:
    offer = HumanQuestionOffer(question_id=OFFERED_QUESTION_ID, deadline=OPEN_HORIZON)
    mismatched = question("33333333-3333-4333-8333-333333333333")
    storage = FakeSealCommands()

    with pytest.raises(ValueError):
        seal_human_forecast(
            storage,
            offer=offer,
            question=mismatched,
            rater_id=RATER_ID,
            probability=0.6,
            evidence_hashes=[sha256(b"view-receipt").hexdigest()],
            **_identity(),
        )
    assert storage.sheet_calls == []
