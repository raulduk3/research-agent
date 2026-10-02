"""Chat answers from stored swarm data, links back, and stores no transcript."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from research_agent.beta import spec as specs
from research_agent.beta.budget import budget_state
from research_agent.beta.chat import NO_SUPPORT, answer_question
from research_agent.beta.config import BetaConfig
from research_agent.beta.costs import record_cost_receipt
from research_agent.beta.errors import Invalid
from research_agent.beta.islands import assign_paper
from research_agent.beta.models import ModelCallFailed
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


def test_a_topic_the_store_lacks_gets_no_support_and_no_links(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    answer = _ask(db, clock, "tell me about medieval bookbinding")

    assert answer["supported"] is False
    assert answer["links"] == []
    assert answer["answer"] == NO_SUPPORT


def test_named_objects_and_costs_are_answered_from_their_records(
    db: sqlite3.Connection, clock: FakeClock, run_id: str
) -> None:
    named = _ask(db, clock, f"what happened in {run_id}?")
    assert named["links"][0]["kind"] == "run" and named["links"][0]["id"] == run_id
    assert "status completed" in named["links"][0]["snippet"]

    cost = _ask(db, clock, "how much has this island spent?")
    # The question names both the island and its spend: one link for each fact.
    by_title = {item["title"]: item for item in cost["links"]}
    assert by_title["CS island cost"]["href"] == "/islands/cs"
    assert "settled cost 0.0020 USD" in by_title["CS island cost"]["snippet"]
    assert by_title["CS island activity"]["snippet"] == (
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
    assert answer["cost_micros"] == 2_000
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


def test_an_empty_or_oversized_question_is_refused(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    with pytest.raises(Invalid):
        _ask(db, clock, "   ")
    with pytest.raises(Invalid):
        _ask(db, clock, "x" * 2001)
