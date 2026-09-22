from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.tools import ToolCall
from research_agent.tools.submit import SubmitCall, parse_submit_call
from research_agent.tools.trace import RunTrace

PAPER_ID = "123e4567-e89b-42d3-a456-426614174000"
QUESTION_ID = "123e4567-e89b-42d3-a456-426614174002"
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


def _forecast_claim() -> dict[str, object]:
    return {
        "kind": "forecast",
        "question_id": QUESTION_ID,
        "evidence_hashes": [EVIDENCE_HASH],
        "confidence": 0.5,
    }


def _submit_call(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "note": NOTE,
        "intent": "decide",
        "arguments": {"claims": [_forecast_claim()]},
        "rationales": [None],
    }
    base.update(overrides)
    return base


# -- ToolCall envelope (AG-36) -----------------------------------------


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


# -- submit's per-claim rationale (AG-37) --------------------------------


def test_submit_call_accepts_no_rationale() -> None:
    submitted = parse_submit_call(_submit_call())
    assert isinstance(submitted, SubmitCall)
    assert submitted.rationales == (None,)


def test_submit_call_accepts_a_rationale_within_bound() -> None:
    text = "cites the primary result table directly"
    submitted = parse_submit_call(_submit_call(rationales=[text]))
    assert submitted.rationales == (text,)


def test_submit_call_rejects_a_rationale_over_the_word_bound() -> None:
    over_bound = " ".join("word" for _ in range(121))
    with pytest.raises(ContractValidationError):
        parse_submit_call(_submit_call(rationales=[over_bound]))


def test_submit_call_rejects_mismatched_rationale_count() -> None:
    with pytest.raises(ContractValidationError):
        parse_submit_call(_submit_call(rationales=[None, None]))


def test_submit_call_rejects_missing_rationales_field() -> None:
    envelope = _submit_call()
    del envelope["rationales"]
    with pytest.raises(ContractValidationError):
        parse_submit_call(envelope)


def test_submit_call_claims_are_unaffected_by_rationale_presence() -> None:
    without = parse_submit_call(_submit_call(rationales=[None]))
    with_text = parse_submit_call(
        _submit_call(rationales=["because the table says so"])
    )
    assert without.call.arguments["claims"] == with_text.call.arguments["claims"]
    assert without.call.arguments["claims"] == [_forecast_claim()]


# -- RunTrace (AG-36) -----------------------------------------------------


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
