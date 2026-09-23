from research_agent.contracts.forecasts import AdmissionRefusal
from research_agent.forecasts.admission import validate_issued_question

PAPER = "paper-1"
TARGET = "citation_reach_365d"
QUESTION_ID = "11111111-1111-4111-8111-111111111111"
ISSUED = {(PAPER, TARGET): QUESTION_ID}


def _request(
    *, paper_id: str, requested_type: str, question_id: str | None
) -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "requested_type": requested_type,
        "question_id": question_id,
    }


def test_issued_question_is_admitted() -> None:
    result = validate_issued_question(
        _request(paper_id=PAPER, requested_type=TARGET, question_id=QUESTION_ID),
        ISSUED,
    )
    assert not isinstance(result, AdmissionRefusal)
    assert result["question_id"] == QUESTION_ID


def test_forecast_without_an_issued_identity_is_refused() -> None:
    result = validate_issued_question(
        _request(paper_id=PAPER, requested_type=TARGET, question_id=None), ISSUED
    )
    assert isinstance(result, AdmissionRefusal)
    assert result.reason == "unissued_question"


def test_an_extra_question_id_is_refused() -> None:
    extra_id = "22222222-2222-4222-8222-222222222222"
    result = validate_issued_question(
        _request(paper_id=PAPER, requested_type=TARGET, question_id=extra_id), ISSUED
    )
    assert isinstance(result, AdmissionRefusal)
    assert result.reason == "unissued_question"


def test_a_familiar_target_paired_with_an_unissued_paper_is_refused() -> None:
    """A target this run legitimately holds a question for, paired with a
    paper it was never issued that question against, is still refused
    whole (TDD-3.1.29)."""

    result = validate_issued_question(
        _request(paper_id="paper-2", requested_type=TARGET, question_id=QUESTION_ID),
        ISSUED,
    )
    assert isinstance(result, AdmissionRefusal)
    assert result.reason == "unissued_question"


def test_refusal_diagnostics_stay_within_the_normal_tool_budget() -> None:
    result = validate_issued_question(
        _request(paper_id=PAPER, requested_type=TARGET, question_id=None), ISSUED
    )
    assert isinstance(result, AdmissionRefusal)
    assert len(result.request_hash) == 64
    assert len(result.attempted_type) <= 128
