from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from research_agent.agents.budgets import (
    TOOL_CALLS_LIMIT,
    BudgetExhausted,
    RunBudget,
)
from research_agent.tools.dispatch import dispatch_tool

RUN_ID = "123e4567-e89b-42d3-a456-426614174000"
SNAPSHOT_HASH = "a" * 64
OTHER_SNAPSHOT_HASH = "b" * 64
PAPER_ID = "123e4567-e89b-42d3-a456-426614174001"
OTHER_PAPER_ID = "123e4567-e89b-42d3-a456-426614174005"
QUESTION_ID = "123e4567-e89b-42d3-a456-426614174006"
EVIDENCE_HASH = "c" * 64


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
        self.result = result or {"ok": True}

    def __call__(
        self, arguments: Mapping[str, Any], budget: RunBudget
    ) -> dict[str, Any]:
        self.calls.append(arguments)
        return self.result


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


def test_dispatch_tool_returns_data_and_attaches_remaining_budgets() -> None:
    handler = _RecordingHandler({"cards": []})
    budget = RunBudget()
    response = dispatch_tool(
        tool="query_cards",
        raw_arguments=_query_cards_args(),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": handler},
        budget=budget,
        context_tokens=10,
    )
    assert response["status"] == "ok"
    assert response["data"] == {"cards": []}
    assert response["remaining_budgets"]["tool_calls"] == TOOL_CALLS_LIMIT - 1
    assert response["context_tokens"] == 10
    assert len(handler.calls) == 1
    assert budget.tool_calls == 1


def test_dispatch_tool_refuses_an_unknown_tool_and_still_charges_a_call() -> None:
    handler = _RecordingHandler()
    budget = RunBudget()
    response = dispatch_tool(
        tool="browse",
        raw_arguments={},
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"browse": handler},
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "tool_not_allowed"
    assert response["data"] is None
    assert budget.tool_calls == 1
    assert handler.calls == []


def test_dispatch_tool_refuses_a_tool_the_runs_configuration_narrowed_away() -> None:
    handler = _RecordingHandler()
    budget = RunBudget()
    response = dispatch_tool(
        tool="submit",
        raw_arguments={"claims": []},
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(allowed=frozenset({"query_cards"})),
        handlers={"query_cards": handler, "submit": handler},
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
        raw_arguments=_query_cards_args(),
        run_id=RUN_ID,
        requested_snapshot_id=OTHER_SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": handler},
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "invalid_input"
    assert handler.calls == []
    assert budget.tool_calls == 1


def test_dispatch_tool_refuses_malformed_arguments_before_the_handler_runs() -> None:
    handler = _RecordingHandler()
    budget = RunBudget()
    response = dispatch_tool(
        tool="query_cards",
        raw_arguments={"unexpected": "field"},
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"query_cards": handler},
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "invalid_input"
    assert handler.calls == []
    assert budget.tool_calls == 1


def test_dispatch_tool_accepts_a_submit_within_the_runs_own_scope() -> None:
    handler = _RecordingHandler({"accepted": True})
    budget = RunBudget()
    response = dispatch_tool(
        tool="submit",
        raw_arguments=_submit_args(),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"submit": handler},
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
        raw_arguments=_submit_args(
            nomination={**_submit_args()["nomination"], "paper_id": OTHER_PAPER_ID}  # type: ignore[dict-item]
        ),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(),
        handlers={"submit": handler},
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
        raw_arguments=_submit_args(answers=[]),
        run_id=RUN_ID,
        requested_snapshot_id=SNAPSHOT_HASH,
        lookup=_Lookup(issued_question_ids=frozenset({QUESTION_ID})),
        handlers={"submit": handler},
        budget=budget,
        context_tokens=0,
    )
    assert response["status"] == "refused"
    assert response["code"] == "invalid_input"
    assert handler.calls == []


def test_dispatch_tool_raises_when_the_tool_call_budget_is_exhausted() -> None:
    handler = _RecordingHandler()
    budget = RunBudget(tool_calls=40)
    with pytest.raises(BudgetExhausted):
        dispatch_tool(
            tool="query_cards",
            raw_arguments=_query_cards_args(),
            run_id=RUN_ID,
            requested_snapshot_id=SNAPSHOT_HASH,
            lookup=_Lookup(),
            handlers={"query_cards": handler},
            budget=budget,
            context_tokens=0,
        )
    assert handler.calls == []
