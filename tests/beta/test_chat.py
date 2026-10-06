"""Chat answers from stored swarm data, links back, and stores no transcript."""

from __future__ import annotations

import sqlite3
from typing import Any

import httpx
import pytest

from research_agent.beta import spec as specs
from research_agent.beta.budget import budget_state
from research_agent.beta.chat import answer_question
from research_agent.beta.config import BetaConfig
from research_agent.beta.costs import record_cost_receipt
from research_agent.beta.errors import Invalid
from research_agent.beta.islands import assign_paper
from research_agent.beta.models import ChatCompletionsClient, ModelCallFailed
from research_agent.beta.papers import upsert_paper
from research_agent.beta.runs import create_run, execute_run
from tests.beta.helpers import (
    PROVIDER,
    FakeClock,
    ScriptedClient,
    call,
    entry,
    reading,
    reply,
)

PAPER = "2609.00001"


@pytest.fixture
def run_id(db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock) -> str:
    """One stored paper with one completed reading on the cs island."""
    paper = entry(PAPER)
    receipt = record_cost_receipt(
        db,
        action="ingest",
        owner_kind="ingest_pass",
        owner_id="IP-test",
        parent_kind="source",
        parent_id="arxiv:cs.AI",
        unit_type="arxiv_request",
        quantity=1,
        amount_micros=0,
        now=clock(),
    )
    revision, spec = specs.current_spec(db)
    upsert_paper(db, paper, receipt, clock())
    assign_paper(db, spec, paper, 2, clock())
    created = create_run(
        db,
        spec=spec,
        revision=revision,
        provider=PROVIDER,
        clock=clock,
        paper_id=PAPER,
        island_id="cs",
        genome_id="cs-reader",
    )
    db.commit()
    execute_run(
        cfg.database,
        created,
        client=ScriptedClient([reply(call("submit_reading", reading()))]),
        provider=PROVIDER,
        clock=clock,
    )
    return created


def _ask(
    db: sqlite3.Connection, clock: FakeClock, message: str, **overrides: Any
) -> dict[str, Any]:
    spec = specs.current_spec(db)[1]
    arguments: dict[str, Any] = {
        "island": specs.find_island(spec, "cs"),
        "message": message,
        "synthesize": False,
        "state": budget_state(db, spec, clock(), provider_configured=True),
        "provider": PROVIDER,
        "client": None,
        "clock": clock,
    }
    arguments.update(overrides)
    return answer_question(db, **arguments)


def test_a_known_topic_is_answered_with_links_to_the_paper_and_the_run(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    answer = _ask(db, clock, "what do we know about visible traces?")

    assert answer["supported"] and answer["mode"] == "retrieval"
    links = {(link["kind"], link["id"]): link for link in answer["links"]}
    assert links[("paper", PAPER)]["href"] == f"/papers/{PAPER}"
    assert links[("run", run_id)]["href"] == f"/runs/{run_id}"
    assert "Tool-using agents learn when traces are visible" in answer["answer"]
    # Retrieval is free and still leaves its receipt.
    [receipt] = answer["receipt_ids"]
    row = db.execute(
        "SELECT action, amount_micros, island_id FROM cost_receipts WHERE id = ?",
        (receipt,),
    ).fetchone()
    assert tuple(row) == ("chat_retrieval", 0, "cs")
    assert answer["answer_id"] == receipt


def test_a_topic_the_store_lacks_still_gets_swarm_context(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    answer = _ask(db, clock, "tell me about medieval bookbinding")

    assert answer["supported"] is True
    assert any(link["kind"] == "island" for link in answer["links"])
    assert any(link["kind"] == "paper" for link in answer["links"])
    assert "The swarm is looking across" in answer["answer"]


def test_deictic_island_questions_get_the_island_record(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    answer = _ask(db, clock, "you?")

    assert answer["supported"] is True
    links = {(link["kind"], link["id"]): link for link in answer["links"]}
    assert links[("island", "cs")]["snippet"] == "1 papers assigned, 1 runs, 1 readings"
    assert "CS island" in answer["answer"]


def test_named_objects_and_costs_are_answered_from_their_records(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    named = _ask(db, clock, f"what happened in {run_id}?")
    named_links = {(link["kind"], link["id"]): link for link in named["links"]}
    assert "status completed" in named_links[("run", run_id)]["snippet"]

    cost = _ask(db, clock, "how much has this island spent?")
    # The question names both the island and its spend: one link for each fact.
    by_title = {item["title"]: item for item in cost["links"]}
    assert by_title["CS island cost"]["href"] == "/islands/cs"
    assert "settled cost 0.0005 USD" in by_title["CS island cost"]["snippet"]
    assert by_title["CS island swarm"]["snippet"] == (
        "1 papers assigned, 1 runs, 1 readings"
    )


def test_chat_keeps_no_transcript(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    question = "zebrafinch visible traces question nobody stored"

    _ask(db, clock, question)
    db.commit()

    tables = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'search_index_%'"
        )
    ]
    for table in tables:
        for row in db.execute(f"SELECT * FROM {table}"):
            assert "zebrafinch" not in " ".join(str(value) for value in row)


def test_a_paid_answer_is_refused_over_budget_and_retrieval_still_answers(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    spec = specs.current_spec(db)[1]
    record_cost_receipt(
        db,
        action="model_call",
        owner_kind="run",
        owner_id=run_id,
        parent_kind="paper",
        parent_id=PAPER,
        unit_type="tokens",
        quantity=1,
        amount_micros=50_000_000,
        now=clock(),
        island_id="cs",
    )
    client = ScriptedClient([reply(text="should never be asked")])

    answer = _ask(
        db,
        clock,
        "visible traces",
        synthesize=True,
        client=client,
        state=budget_state(db, spec, clock(), provider_configured=True),
    )

    assert client.requests == []
    assert answer["paid"] == {
        "requested": True,
        "used": False,
        "refused": "budget_mode_stored_data_only",
    }
    assert answer["supported"] and answer["mode"] == "retrieval"
    assert answer["cost_micros"] == 0


def test_a_paid_answer_within_budget_is_written_from_the_records_and_charged(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    client = ScriptedClient(
        [reply(text="Trace review reduces unsupported claims [1].")]
    )

    answer = _ask(db, clock, "visible traces", synthesize=True, client=client)

    assert answer["mode"] == "synthesized"
    assert answer["answer"] == "Trace review reduces unsupported claims [1]."
    assert answer["links"], "the written answer keeps the links it was built from"
    assert answer["cost_micros"] == 500
    assert len(answer["receipt_ids"]) == 2
    # The model saw the stored records and no tools.
    assert "Stored records" in client.requests[0]["messages"][1]["content"]
    assert client.requests[0]["tools"] == []


def test_a_failed_paid_answer_falls_back_and_leaves_an_unsettled_receipt(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    client = ScriptedClient([ModelCallFailed("provider answered 500")])

    answer = _ask(db, clock, "visible traces", synthesize=True, client=client)

    assert answer["mode"] == "retrieval"
    assert answer["paid"]["refused"] == "model_call_failed"
    settlement = db.execute(
        "SELECT settlement FROM cost_receipts WHERE action = 'chat_answer'"
    ).fetchone()[0]
    assert settlement == "unsettled"


@pytest.mark.parametrize("malformed", ["message", "usage", None])
def test_a_malformed_paid_answer_keeps_its_receipts_after_rollback(
    db: sqlite3.Connection, clock: FakeClock, run_id: str, malformed: str | None
) -> None:
    body = {"choices": [{"message": {"content": "Trace review helps [1]."}}]}
    if malformed == "message":
        body["choices"][0]["message"] = "invalid"
    else:
        body["usage"] = {
            "prompt_tokens": "invalid" if malformed else 1000,
            "completion_tokens": 200,
        }
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=body)

    client = ChatCompletionsClient(PROVIDER, transport=httpx.MockTransport(handler))
    answer = _ask(db, clock, "visible traces", synthesize=True, client=client)
    db.rollback()

    assert len(requests) == 1
    assert answer["mode"] == ("retrieval" if malformed else "synthesized")
    assert answer["paid"]["refused"] == ("model_call_failed" if malformed else None)
    if malformed:
        assert "Tool-using agents learn when traces are visible" in answer["answer"]
    else:
        assert answer["answer"] == "Trace review helps [1]."
        assert answer["cost_micros"] == 500
    rows = db.execute(
        "SELECT id, action, provider, estimated, settlement, amount_micros"
        " FROM cost_receipts WHERE owner_kind = 'chat' ORDER BY action"
    ).fetchall()
    assert [row["action"] for row in rows] == ["chat_answer", "chat_retrieval"]
    assert {row["id"] for row in rows} == set(answer["receipt_ids"])
    assert tuple(rows[0])[2:5] == (
        "test-provider",
        int(malformed is not None),
        "unsettled" if malformed else "settled",
    )
    assert rows[0]["amount_micros"] > 0
    assert budget_state(
        db, specs.current_spec(db)[1], clock(), True
    ).month_unsettled_count == int(malformed is not None)


def test_an_empty_or_oversized_question_is_refused(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    with pytest.raises(Invalid):
        _ask(db, clock, "   ")
    with pytest.raises(Invalid):
        _ask(db, clock, "x" * 2001)


@pytest.mark.parametrize(
    "text",
    ["An invented result.", "An invented result [1].", "An invented result [999]."],
)
def test_generated_claims_are_not_verified_by_retrieved_links(
    db: sqlite3.Connection, clock: FakeClock, text: str
) -> None:
    answer = _ask(
        db,
        clock,
        "an unknown topic",
        synthesize=True,
        client=ScriptedClient([reply(text=text)]),
    )
    assert answer["links"]
    assert answer["answer"] == text
    assert answer["supported"] is False
    assert answer["mode"] == "synthesized"
