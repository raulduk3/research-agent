from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.tools import ToolCall
from research_agent.tools.submit import authorize_submit_scope
from research_agent.tools.trace import RunTrace

PAPER_ID = "123e4567-e89b-42d3-a456-426614174000"
OTHER_PAPER_ID = "123e4567-e89b-42d3-a456-426614174001"
QUESTION_ID = "123e4567-e89b-42d3-a456-426614174002"
OTHER_QUESTION_ID = "123e4567-e89b-42d3-a456-426614174003"
EVIDENCE_HASH = "b" * 64

NOTE = "read the abstract for the reported effect size"
INTENT = "read"


def _neighbors_call(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "note": NOTE,
        "intent": INTENT,
        "arguments": {"paper_id": PAPER_ID, "limit": None},
    }
    base.update(overrides)
    return base


def _submit_arguments(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "submission_id": "123e4567-e89b-42d3-a456-426614174004",
        "answers": [
            {
                "question_id": QUESTION_ID,
                "probability": 0.5,
                "rationale": "cites the primary result table directly",
                "evidence_ids": [EVIDENCE_HASH],
            }
        ],
        "nomination": {
            "paper_id": PAPER_ID,
            "recommend": True,
            "preference": 0.6,
            "rationale": "worth reading",
        },
    }
    base.update(overrides)
    return base


# -- ToolCall envelope (AG-39) -----------------------------------------


def test_tool_call_accepts_a_valid_note_and_intent() -> None:
    call = ToolCall.parse("neighbors", _neighbors_call())
    assert call.note == NOTE
    assert call.intent == INTENT
    assert call.arguments == {"paper_id": PAPER_ID, "limit": 5}


def test_tool_call_rejects_missing_note() -> None:
    envelope = _neighbors_call()
    del envelope["note"]
    with pytest.raises(ContractValidationError):
        ToolCall.parse("neighbors", envelope)


def test_tool_call_rejects_missing_intent() -> None:
    envelope = _neighbors_call()
    del envelope["intent"]
    with pytest.raises(ContractValidationError):
        ToolCall.parse("neighbors", envelope)


def test_tool_call_rejects_extra_envelope_field() -> None:
    with pytest.raises(ContractValidationError):
        ToolCall.parse("neighbors", {**_neighbors_call(), "extra": 1})


def test_tool_call_rejects_empty_note() -> None:
    with pytest.raises(ContractValidationError):
        ToolCall.parse("neighbors", _neighbors_call(note=""))


def test_tool_call_rejects_note_over_the_word_bound() -> None:
    over_bound = " ".join("word" for _ in range(61))
    with pytest.raises(ContractValidationError):
        ToolCall.parse("neighbors", _neighbors_call(note=over_bound))


def test_tool_call_accepts_note_at_the_word_bound() -> None:
    at_bound = " ".join("word" for _ in range(60))
    call = ToolCall.parse("neighbors", _neighbors_call(note=at_bound))
    assert call.note == at_bound


def test_tool_call_rejects_intent_outside_the_fixed_set() -> None:
    with pytest.raises(ContractValidationError):
        ToolCall.parse("neighbors", _neighbors_call(intent="browse"))


def test_tool_call_rejects_call_whose_domain_arguments_fail() -> None:
    with pytest.raises(ContractValidationError):
        ToolCall.parse(
            "neighbors",
            _neighbors_call(arguments={"paper_id": "not-a-uuid", "limit": None}),
        )


def test_tool_call_enforces_envelope_for_every_tool() -> None:
    calls = {
        "query_cards": {
            "paper_ids": None,
            "query": "graph neural nets",
            "mode": None,
            "paper_id": None,
            "limit": None,
        },
        "graph": {"paper_id": PAPER_ID, "direction": None, "limit": None},
        "deep_read": {
            "paper_id": PAPER_ID,
            "section_id": "Abstract",
            "pages": None,
            "next_span": None,
        },
    }
    for tool, arguments in calls.items():
        accepted = ToolCall.parse(
            tool, {"note": NOTE, "intent": "scan", "arguments": arguments}
        )
        assert accepted.note == NOTE
        with pytest.raises(ContractValidationError):
            ToolCall.parse(tool, {"intent": "scan", "arguments": arguments})


# -- submit's own paper/question scope (AG-26) ---------------------------


def test_authorize_submit_scope_accepts_the_runs_own_paper_and_questions() -> None:
    authorize_submit_scope(
        _submit_arguments(),
        paper_id=PAPER_ID,
        issued_question_ids=frozenset({QUESTION_ID}),
    )


def test_authorize_submit_scope_rejects_a_nomination_naming_another_paper() -> None:
    with pytest.raises(ContractValidationError):
        authorize_submit_scope(
            _submit_arguments(
                nomination={
                    **_submit_arguments()["nomination"],  # type: ignore[dict-item]
                    "paper_id": OTHER_PAPER_ID,
                }
            ),
            paper_id=PAPER_ID,
            issued_question_ids=frozenset({QUESTION_ID}),
        )


def test_authorize_submit_scope_rejects_fewer_than_the_issued_questions() -> None:
    with pytest.raises(ContractValidationError):
        authorize_submit_scope(
            _submit_arguments(),
            paper_id=PAPER_ID,
            issued_question_ids=frozenset({QUESTION_ID, OTHER_QUESTION_ID}),
        )


def test_authorize_submit_scope_rejects_an_answer_outside_the_issued_set() -> None:
    with pytest.raises(ContractValidationError):
        authorize_submit_scope(
            _submit_arguments(),
            paper_id=PAPER_ID,
            issued_question_ids=frozenset({OTHER_QUESTION_ID}),
        )


def test_authorize_submit_scope_admits_zero_answers_for_a_questionless_slot() -> None:
    authorize_submit_scope(
        _submit_arguments(answers=[]),
        paper_id=PAPER_ID,
        issued_question_ids=frozenset(),
    )


# -- RunTrace (AG-39) -----------------------------------------------------


def test_run_trace_records_calls_in_order() -> None:
    trace = RunTrace()
    first = ToolCall.parse("neighbors", _neighbors_call())
    second = ToolCall.parse(
        "neighbors",
        _neighbors_call(note="compare the two neighbor lists", intent="compare"),
    )
    trace.record(first)
    trace.record(second)
    assert [entry.note for entry in trace.entries] == [first.note, second.note]
    assert [entry.intent for entry in trace.entries] == ["read", "compare"]
    assert all(entry.tool == "neighbors" for entry in trace.entries)


def test_run_trace_entries_are_immutable() -> None:
    trace = RunTrace()
    trace.record(ToolCall.parse("neighbors", _neighbors_call()))
    entries = trace.entries
    assert isinstance(entries, tuple)
    with pytest.raises(AttributeError):
        entries[0].note = "changed"  # type: ignore[misc]
