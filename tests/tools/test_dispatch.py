from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest

from research_agent.agents.budgets import TOOL_CALLS_LIMIT, RunBudget
from research_agent.tools.answers import CallContext, ToolAnswer, ToolError
from research_agent.tools.dispatch import dispatch_tool

from service_harness import envelope

RUN_ID = "123e4567-e89b-42d3-a456-426614174000"
SNAPSHOT_HASH = "a" * 64
OTHER_SNAPSHOT_HASH = "b" * 64
PAPER_ID = "123e4567-e89b-42d3-a456-426614174001"
OTHER_PAPER_ID = "123e4567-e89b-42d3-a456-426614174005"
QUESTION_ID = "123e4567-e89b-42d3-a456-426614174006"
EVIDENCE_HASH = "c" * 64
ABSENT_PAPER_ID = "123e4567-e89b-42d3-a456-426614174008"
REQUEST_ID = "123e4567-e89b-42d3-a456-426614174009"


class _Lookup:
    def __init__(
        self,
        snapshot_hash: str = SNAPSHOT_HASH,
        allowed: frozenset[str] | None = None,
        paper_id: str = PAPER_ID,
        issued_question_ids: frozenset[str] | None = None,
    ) -> None:
        self.snapshot_hash = snapshot_hash
        self.allowed = allowed or frozenset({"query_cards", "submit"})
        self.paper_id = paper_id
        self.issued_question_ids = (
            frozenset({QUESTION_ID})
            if issued_question_ids is None
            else issued_question_ids
        )

    def snapshot_hash_for(self, run_id: str) -> str:
        return self.snapshot_hash

    def allowed_tools_for(self, run_id: str) -> frozenset[str]:
        return self.allowed

    def paper_id_for(self, run_id: str) -> str:
        return self.paper_id

    def issued_question_ids_for(self, run_id: str) -> frozenset[str]:
        return self.issued_question_ids


class _Membership:
    def __init__(self, held: frozenset[str] = frozenset({PAPER_ID})) -> None:
        self.held = held
        self.calls: list[tuple[str, str]] = []

    def holds_family(self, snapshot_hash: str, family_id: str) -> bool:
        self.calls.append((snapshot_hash, family_id))
        return family_id in self.held


@dataclass(frozen=True)
class _Recorded:
    data: Mapping[str, Any]


class _PaperRequests:
    def __init__(self, outcome: str = "requested") -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    def record_paper_request(self, **call: Any) -> _Recorded:
        self.calls.append(call)
        exhausted = self.outcome == "request_budget_exhausted"
        return _Recorded(
            {
                "outcome": self.outcome,
                "request_id": None if exhausted else REQUEST_ID,
                "family_id": str(call["family_id"]),
                "receipt": None,
            }
        )


def _deep_read_args(paper_id: str) -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "section_id": "introduction",
        "pages": None,
        "next_span": None,
    }


def _submit_args(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "submission_id": "123e4567-e89b-42d3-a456-426614174007",
        "answers": [
            {
                "question_id": QUESTION_ID,
                "probability": 0.4,
                "rationale": "the method section supports this",
                "evidence_ids": [EVIDENCE_HASH],
            }
        ],
        "nomination": {
            "paper_id": PAPER_ID,
            "recommend": True,
            "preference": 0.5,
            "rationale": "worth a look",
        },
    }
    base.update(overrides)
    return base


class _RecordingHandler:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[Mapping[str, Any]] = []
        self.contexts: list[CallContext] = []
        self.result = result or {"ok": True}

    def __call__(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer:
        self.calls.append(arguments)
        self.contexts.append(context)
        return ToolAnswer(self.result)


def _query_cards_args(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "paper_ids": [PAPER_ID],
        "query": None,
        "mode": None,
        "paper_id": None,
        "limit": None,
    }
    base.update(overrides)
    return base


def test_dispatch_tool_answers_and_reads_the_budget_without_charging_it() -> None:
    # The loop charges each call once (#287); the dispatcher only reads it.
    handler = _RecordingHandler({"cards": []})
    budget = RunBudget(tool_calls=3)
    response = dispatch_tool(
        tool="query_cards",
        raw_call=envelope(_query_cards_args()),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
        budget=budget,
        context_tokens=10,
    )
    assert response["status"] == "ok"
    assert response["data"] == {"cards": []}
    assert response["remaining_budgets"]["tool_calls"] == TOOL_CALLS_LIMIT - 3
    assert response["context_tokens"] == 10
    assert len(handler.calls) == 1
    assert handler.contexts == [CallContext(RUN_ID, SNAPSHOT_HASH)]
    assert budget.tool_calls == 3


def test_dispatch_tool_without_a_budget_answers_the_bare_envelope() -> None:
    response = dispatch_tool(
        tool="query_cards",
        raw_call=envelope(_query_cards_args()),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": _RecordingHandler({"cards": []})},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
    )
    assert response == {
        "status": "ok",
        "code": None,
        "message": None,
        "data": {"cards": []},
    }


def test_dispatch_tool_answers_a_handler_error_with_its_code() -> None:
    def failing(arguments: Mapping[str, Any], context: CallContext) -> ToolAnswer:
        raise ToolError("graph_unavailable", "no graph is pinned")

    response = dispatch_tool(
        tool="graph",
        raw_call=envelope({"paper_id": PAPER_ID, "direction": None, "limit": None}),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(allowed=frozenset({"graph"})),
        handlers={"graph": failing},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
    )
    assert response == {
        "status": "error",
        "code": "graph_unavailable",
        "message": "no graph is pinned",
        "data": None,
    }


def test_dispatch_tool_refuses_an_unknown_tool_without_charging() -> None:
    handler = _RecordingHandler()
    budget = RunBudget()
    response = dispatch_tool(
        tool="browse",
        raw_call=envelope({}),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"browse": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "tool_not_allowed"
    assert response["data"] is None
    assert budget.tool_calls == 0
    assert handler.calls == []


def test_dispatch_tool_refuses_a_tool_the_runs_configuration_narrowed_away() -> None:
    handler = _RecordingHandler()
    budget = RunBudget()
    response = dispatch_tool(
        tool="submit",
        raw_call=envelope({"claims": []}),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(allowed=frozenset({"query_cards"})),
        handlers={"query_cards": handler, "submit": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "tool_not_allowed"
    assert handler.calls == []


def test_dispatch_tool_refuses_a_snapshot_the_run_does_not_own() -> None:
    handler = _RecordingHandler()
    budget = RunBudget()
    response = dispatch_tool(
        tool="query_cards",
        raw_call=envelope(_query_cards_args()),
        run_id=RUN_ID,
        requested_snapshot_id=OTHER_SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "invalid_input"
    assert handler.calls == []
    assert budget.tool_calls == 0


def test_dispatch_tool_refuses_malformed_arguments_before_the_handler_runs() -> None:
    handler = _RecordingHandler()
    budget = RunBudget()
    response = dispatch_tool(
        tool="query_cards",
        raw_call=envelope({"unexpected": "field"}),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "invalid_input"
    assert handler.calls == []
    assert budget.tool_calls == 0


_OVER_BOUND_NOTE = " ".join(["word"] * 61)
_BAD_ENVELOPES = {
    "missing note": {"intent": "scan"},
    "missing intent": {"note": "reading the cards"},
    "intent outside the list": {"note": "reading the cards", "intent": "browse"},
    "note over the bound": {"note": _OVER_BOUND_NOTE, "intent": "scan"},
}


def _valid_args(tool: str) -> object:
    return {
        "query_cards": _query_cards_args(),
        "neighbors": {"paper_id": PAPER_ID, "limit": None},
        "graph": {"paper_id": PAPER_ID, "direction": None, "limit": None},
        "deep_read": _deep_read_args(PAPER_ID),
        "submit": _submit_args(),
    }[tool]


@pytest.mark.parametrize("fault", sorted(_BAD_ENVELOPES))
@pytest.mark.parametrize(
    "tool", ["query_cards", "neighbors", "graph", "deep_read", "submit"]
)
def test_dispatch_tool_refuses_a_bad_note_or_intent_before_any_read(
    tool: str, fault: str
) -> None:
    # The domain arguments are valid, so only the envelope refuses the call.
    handler = _RecordingHandler()
    membership = _Membership()
    requests = _PaperRequests()
    lookup = _Lookup(
        allowed=frozenset({"query_cards", "neighbors", "graph", "deep_read", "submit"})
    )
    raw_call = {**_BAD_ENVELOPES[fault], "arguments": _valid_args(tool)}
    response = dispatch_tool(
        tool=tool,
        raw_call=raw_call,
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=lookup,
        handlers={tool: handler},
        membership=membership,
        paper_requests=requests,
    )
    assert (response["status"], response["code"]) == ("refused", "invalid_input")
    assert handler.calls == []
    assert membership.calls == [] and requests.calls == []
    # The same arguments in a well-formed envelope are answered.
    accepted = dispatch_tool(
        tool=tool,
        raw_call=envelope(_valid_args(tool)),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=lookup,
        handlers={tool: handler},
        membership=membership,
        paper_requests=requests,
    )
    assert accepted["status"] == "ok"


def test_dispatch_tool_refuses_bare_arguments_without_their_envelope() -> None:
    handler = _RecordingHandler()
    response = dispatch_tool(
        tool="query_cards",
        raw_call=_query_cards_args(),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
    )
    assert (response["status"], response["code"]) == ("refused", "invalid_input")
    assert handler.calls == []


def test_dispatch_tool_accepts_a_submit_within_the_runs_own_scope() -> None:
    handler = _RecordingHandler({"accepted": True})
    budget = RunBudget()
    response = dispatch_tool(
        tool="submit",
        raw_call=envelope(_submit_args()),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"submit": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "ok"
    assert len(handler.calls) == 1


def test_dispatch_tool_refuses_a_submit_naming_another_paper() -> None:
    handler = _RecordingHandler()
    budget = RunBudget()
    response = dispatch_tool(
        tool="submit",
        raw_call=envelope(
            _submit_args(
                nomination={**_submit_args()["nomination"], "paper_id": OTHER_PAPER_ID}  # type: ignore[dict-item]
            )
        ),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"submit": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "invalid_input"
    assert handler.calls == []


def test_dispatch_tool_refuses_a_submit_not_covering_the_issued_questions() -> None:
    handler = _RecordingHandler()
    budget = RunBudget()
    response = dispatch_tool(
        tool="submit",
        raw_call=envelope(_submit_args(answers=[])),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(issued_question_ids=frozenset({QUESTION_ID})),
        handlers={"submit": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "invalid_input"
    assert handler.calls == []


def test_dispatch_tool_leaves_an_exhausted_budget_to_the_loop() -> None:
    # The loop stops before forwarding a call past the budget; the
    # dispatcher never charges, so it cannot charge a second time.
    handler = _RecordingHandler()
    budget = RunBudget(tool_calls=TOOL_CALLS_LIMIT)
    response = dispatch_tool(
        tool="query_cards",
        raw_call=envelope(_query_cards_args()),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests(),
        budget=budget,
        context_tokens=0,
    )
    assert response["remaining_budgets"]["tool_calls"] == 0
    assert budget.tool_calls == TOOL_CALLS_LIMIT


def test_dispatch_tool_records_a_request_for_a_family_the_snapshot_lacks() -> None:
    handler = _RecordingHandler()
    membership = _Membership()
    requests = _PaperRequests()
    budget = RunBudget()
    response = dispatch_tool(
        tool="deep_read",
        raw_call=envelope(_deep_read_args(ABSENT_PAPER_ID)),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(allowed=frozenset({"deep_read"})),
        handlers={"deep_read": handler},
        membership=membership,
        paper_requests=requests,
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "ok"
    assert response["data"] == {
        "kind": "not_in_snapshot",
        "paper_id": ABSENT_PAPER_ID,
        "request": {"outcome": "requested", "request_id": REQUEST_ID},
    }
    assert handler.calls == []
    assert membership.calls == [(SNAPSHOT_HASH, ABSENT_PAPER_ID)]
    assert len(requests.calls) == 1
    call = requests.calls[0]
    assert call["run_id"] == UUID(RUN_ID)
    assert call["family_id"] == UUID(ABSENT_PAPER_ID)
    # The request names the run's own bound snapshot, never a caller's claim.
    assert call["snapshot_hash"] == SNAPSHOT_HASH
    assert budget.tool_calls == 0


def test_dispatch_tool_answers_graph_outside_the_snapshot_with_the_receipt() -> None:
    handler = _RecordingHandler()
    response = dispatch_tool(
        tool="graph",
        raw_call=envelope(
            {"paper_id": ABSENT_PAPER_ID, "direction": None, "limit": None}
        ),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(allowed=frozenset({"graph"})),
        handlers={"graph": handler},
        membership=_Membership(),
        paper_requests=_PaperRequests("request_budget_exhausted"),
        budget=RunBudget(),
        context_tokens=0,
    )
    assert response["data"] == {
        "kind": "not_in_snapshot",
        "paper_id": ABSENT_PAPER_ID,
        "request": {"outcome": "request_budget_exhausted", "request_id": None},
    }
    assert handler.calls == []


def test_dispatch_tool_reads_a_family_the_snapshot_holds_without_a_request() -> None:
    handler = _RecordingHandler({"text": "section"})
    requests = _PaperRequests()
    response = dispatch_tool(
        tool="deep_read",
        raw_call=envelope(_deep_read_args(PAPER_ID)),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(allowed=frozenset({"deep_read"})),
        handlers={"deep_read": handler},
        membership=_Membership(),
        paper_requests=requests,
        budget=RunBudget(),
        context_tokens=0,
    )
    assert response["data"] == {"text": "section"}
    assert len(handler.calls) == 1
    assert requests.calls == []


def test_dispatch_tool_never_requests_a_paper_from_another_tool() -> None:
    handler = _RecordingHandler({"cards": []})
    membership = _Membership(held=frozenset())
    requests = _PaperRequests()
    dispatch_tool(
        tool="query_cards",
        raw_call=envelope(_query_cards_args(paper_ids=[ABSENT_PAPER_ID])),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": handler},
        membership=membership,
        paper_requests=requests,
        budget=RunBudget(),
        context_tokens=0,
    )
    assert len(handler.calls) == 1
    assert membership.calls == []
    assert requests.calls == []


def test_dispatch_tool_records_no_request_for_a_snapshot_the_run_does_not_own() -> None:
    requests = _PaperRequests()
    response = dispatch_tool(
        tool="deep_read",
        raw_call=envelope(_deep_read_args(ABSENT_PAPER_ID)),
        run_id=RUN_ID,
        requested_snapshot_id=OTHER_SNAPSHOT_HASH,
        lookup=_Lookup(allowed=frozenset({"deep_read"})),
        handlers={"deep_read": _RecordingHandler()},
        membership=_Membership(),
        paper_requests=requests,
        budget=RunBudget(),
        context_tokens=0,
    )
    assert response["code"] == "invalid_input"
    assert requests.calls == []
