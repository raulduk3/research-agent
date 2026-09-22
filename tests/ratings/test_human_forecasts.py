from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from research_agent.ratings.forecasts import (
    HumanQuestionOffer,
    is_offer_open,
    offer_human_questions,
    participation_status,
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
