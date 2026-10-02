"""One-paper runs: creation, the tool harness, the trace and its replay."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from research_agent.beta import spec as specs
from research_agent.beta.config import BetaConfig
from research_agent.beta.costs import record_cost_receipt, sum_cost_scope
from research_agent.beta.errors import Conflict, Invalid, NotFound, Unavailable
from research_agent.beta.islands import assign_paper
from research_agent.beta.models import ModelCallFailed
from research_agent.beta.papers import load_passages, upsert_paper
from research_agent.beta.projections import build_run_projection
from research_agent.beta.runs import (
    ARGUMENTS_NOT_JSON,
    LAST_CALL_NOTICE,
    NEXT_IS_LAST_NOTICE,
    RETRY_NOTICE,
    STEP_OUTPUT_TOKENS,
    SUBMIT_OUTPUT_TOKENS,
    advance_swarm,
    append_run_event,
    create_run,
    execute_run,
    sweep_interrupted_runs,
    validate_reading_submission,
)
from tests.beta.helpers import (
    ABSTRACT,
    PROVIDER,
    FakeClock,
    ScriptedClient,
    call,
    entry,
    reading,
    reply,
)

PAPER = "2609.00001"


def _store(
    db: sqlite3.Connection, clock: FakeClock, paper_id: str = PAPER, **fields: Any
) -> None:
    paper = entry(paper_id, **fields)
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
    upsert_paper(db, paper, receipt, clock())
    assign_paper(db, specs.current_spec(db)[1], paper, 2, clock())
    db.commit()


def _create(db: sqlite3.Connection, clock: FakeClock, **overrides: Any) -> str:
    revision, spec = specs.current_spec(db)
    arguments: dict[str, Any] = {
        "spec": spec,
        "revision": revision,
        "provider": PROVIDER,
        "clock": clock,
        "paper_id": PAPER,
        "island_id": "cs",
        "genome_id": "cs-reader",
    }
    arguments.update(overrides)
    run_id = create_run(db, **arguments)
    db.commit()
    return run_id


def _execute(
    cfg: BetaConfig, clock: FakeClock, run_id: str, script, **kwargs: Any
) -> ScriptedClient:
    client = ScriptedClient(script)
    execute_run(
        cfg.database,
        run_id,
        client=client,
        provider=PROVIDER,
        clock=clock,
        **kwargs,
    )
    return client


def _kinds(view) -> list[str]:
    return [event["kind"] for event in view["events"]]


def test_a_run_is_one_paper_under_one_agent_and_refuses_anything_else(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _store(db, clock)

    with pytest.raises(NotFound):
        _create(db, clock, paper_id="2609.99999")
    with pytest.raises(NotFound):
        _create(db, clock, genome_id="nobody")
    with pytest.raises(Invalid, match="belongs to island quant"):
        _create(db, clock, genome_id="quant-reader")
    with pytest.raises(Unavailable, match="model_provider_not_configured"):
        _create(db, clock, provider=None)
    assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0

    run_id = _create(db, clock, seed=7)

    run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert (run["paper_id"], run["genome_id"], run["genome_version"]) == (
        PAPER,
        "cs-reader",
        1,
    )
    assert (run["status"], run["seed"], run["spec_revision"]) == ("queued", 7, 1)
    assert len(run["prompt_hash"]) == 64 and run["estimate_micros"] > 0


def test_a_switched_off_agent_starts_no_run(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _store(db, clock)
    _, spec = specs.current_spec(db)
    off = specs.patch_genome(spec, "cs", "cs-reader", {"active": False})
    specs.apply_spec(db, off, actor="operator", now=clock())

    with pytest.raises(Conflict, match="genome_inactive"):
        _create(db, clock)


def test_a_run_records_every_step_in_order_with_receipts_and_locators(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    quote = "Visible traces change the training signal"

    client = _execute(
        cfg,
        clock,
        run_id,
        [
            reply(call("paper_text", {})),
            reply(
                call("capture_note", {"text": "Central claim.", "quote": quote}),
                call("related_papers", {"query": "trace visibility"}),
            ),
            reply(call("submit_reading", reading(quote))),
        ],
    )

    view = build_run_projection(db, run_id)
    assert view["run"]["status"] == "completed"
    assert _kinds(view) == [
        "run_started",
        "prompt",
        # The stored abstract is short, so it was placed in the prompt and read there.
        "paper_read",
        "model_call",
        "tool_call",
        "model_call",
        "note",
        "tool_call",
        "tool_call",
        "model_call",
        "tool_call",
        "reading_submitted",
        "run_completed",
    ]
    assert [event["seq"] for event in view["events"]] == list(range(1, 14))
    assert view["last_seq"] == 13
    assert view["events"][2]["payload"]["placed_in_prompt"] is True
    assert ABSTRACT in view["run"]["prompt"]["user"]
    assert "no other section exists" in view["run"]["prompt"]["user"]

    # Each model call is paid work and links the receipt that settles it.
    model_calls = [e for e in view["events"] if e["kind"] == "model_call"]
    receipt_ids = {receipt["id"] for receipt in view["receipts"]}
    assert all(e["receipt_id"] in receipt_ids for e in model_calls)
    assert all(e["cost_state"] == "settled" for e in model_calls)
    assert view["cost"]["settled_micros"] == 3 * 500
    assert view["cost"]["receipt_count"] == 3

    # The passage read and the quoted note point at characters of the abstract.
    read = next(e for e in view["events"] if e["kind"] == "paper_read")
    assert read["locator"] == {
        "paper_id": PAPER,
        "source_kind": "abstract",
        "passage_id": f"{PAPER}:abstract",
        "page": None,
        "char_start": 0,
        "char_end": len(ABSTRACT),
        "quote": ABSTRACT[:240],
        "section": f"{PAPER}:abstract",
    }
    note = next(e for e in view["events"] if e["kind"] == "note")
    start = ABSTRACT.index(quote)
    assert (note["locator"]["char_start"], note["locator"]["char_end"]) == (
        start,
        start + len(quote),
    )
    assert note["locator"]["quote"] == quote
    # The replay line and its cost are read off the stored step, not written anew.
    first_call = model_calls[0]
    assert first_call["body"] == "Model call 1: 1000 tokens in, 200 out"
    assert (first_call["cost_micros"], first_call["model"]) == (500, "test-model")
    tool = next(e for e in view["events"] if e["kind"] == "tool_call")
    assert (tool["tool"], tool["input"]) == ("paper_text", "{}")
    assert "paper map only" in tool["output"]
    assert ABSTRACT not in tool["output"]
    assert view["events"][0]["id"] == view["events"][0]["seq"] == 1
    assert view["run"]["cost_micros"] == view["cost_micros"] == 1_500
    assert view["paper"]["sections"][0]["id"] == f"{PAPER}:abstract"
    assert note["payload"]["quote_verified"] is True

    claim = view["reading"]["claims"][0]
    assert claim["cited"] and claim["evidence"][0]["locator"]["char_start"] == start
    assert view["conduct"]["tool_calls"] == [
        "paper_text",
        "capture_note",
        "related_papers",
        "submit_reading",
    ]
    # Read once in the prompt; the broad paper_text call returned only a map.
    assert view["conduct"]["passages_read"] == [f"{PAPER}:abstract"]
    # The model was sent the stored prompt, then its own turns and tool results.
    assert (
        client.requests[0]["messages"][0]["content"] == view["run"]["prompt"]["system"]
    )
    assert client.requests[1]["messages"][-1]["role"] == "tool"


def test_a_run_can_import_a_cited_arxiv_paper_without_returning_the_whole_text(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    db.execute(
        "UPDATE papers SET cited_papers = ? WHERE id = ?",
        ('["https://arxiv.org/abs/2609.00077 A focused cited paper"]', PAPER),
    )
    run_id = _create(db, clock)
    long_text = "This cited paper has a bounded section. " * 400

    def fetch_paper(paper_id: str):
        assert paper_id == "2609.00077"
        return entry(
            paper_id, title="A focused cited paper", abstract="Cited abstract."
        )

    def fetch_text(paper_id: str, version: int) -> str:
        assert (paper_id, version) == ("2609.00077", 1)
        return (
            '<html><body><section id="S1" class="ltx_section">'
            '<h2 class="ltx_title">1 Cited section</h2>'
            f"<p>{long_text}</p></section></body></html>"
        )

    _execute(
        cfg,
        clock,
        run_id,
        [
            reply(
                call(
                    "cited_paper_text",
                    {"reference": "https://arxiv.org/abs/2609.00077"},
                )
            ),
            reply(call("submit_reading", reading())),
        ],
        fetch_paper=fetch_paper,
        fetch_text=fetch_text,
    )

    view = build_run_projection(db, run_id)
    tool = next(
        e
        for e in view["events"]
        if e["kind"] == "tool_call" and e["payload"]["name"] == "cited_paper_text"
    )
    assert tool["payload"]["result"]["paper"]["id"] == "2609.00077"
    assert tool["payload"]["result"]["outline"][0] == (
        "- 2609.00077:abstract: Abstract (15 characters)"
    )
    assert "1 Cited section" in tool["payload"]["result"]["outline"][1]
    assert "5 parts" in tool["payload"]["result"]["outline"][1]
    assert "This cited paper has a bounded section" not in tool["output"]
    assert (
        db.execute("SELECT COUNT(*) FROM papers WHERE id = '2609.00077'").fetchone()[0]
        == 1
    )


def test_replay_can_be_read_from_a_sequence_onward(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    _execute(cfg, clock, run_id, [reply(call("submit_reading", reading()))])

    tail = build_run_projection(db, run_id, after_seq=4)

    assert [event["seq"] for event in tail["events"]] == [5, 6, 7]
    # Conduct is counted over the whole trace, not the part asked for.
    assert tail["conduct"]["model_calls"] == 1


def test_a_tool_the_agent_was_not_given_is_refused_and_does_nothing(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    _, spec = specs.current_spec(db)
    narrow = specs.patch_genome(
        spec, "cs", "cs-reader", {"allowed_tools": ["paper_text", "submit_reading"]}
    )
    specs.apply_spec(db, narrow, actor="operator", now=clock())
    run_id = _create(db, clock)

    client = _execute(
        cfg,
        clock,
        run_id,
        [
            reply(call("capture_note", {"text": "Not permitted."})),
            reply(call("submit_reading", reading())),
        ],
    )

    view = build_run_projection(db, run_id)
    assert client.requests[0]["tools"] == ["paper_text", "submit_reading"]
    assert view["conduct"]["refused_tool_calls"] == [
        {"name": "capture_note", "error": "tool_not_allowed"}
    ]
    assert "note" not in _kinds(view)
    assert view["run"]["status"] == "completed"


def test_a_failure_mid_run_keeps_the_trace_and_the_cost(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)

    _execute(
        cfg,
        clock,
        run_id,
        [reply(call("paper_text", {})), ModelCallFailed("provider answered 502")],
    )

    view = build_run_projection(db, run_id)
    assert (view["run"]["status"], view["run"]["failure"]) == (
        "failed",
        "model_call_failed",
    )
    assert _kinds(view)[-2:] == ["model_call", "run_failed"]
    failed_call = view["events"][-2]
    assert failed_call["payload"]["error"] == "provider answered 502"
    assert failed_call["cost_state"] == "unsettled" and failed_call["receipt_id"]
    # The first call's settled charge and the prompt are still there.
    assert view["cost"]["settled_micros"] == 500
    assert view["cost"]["unsettled_count"] == 1
    assert view["run"]["prompt"]["hash"] and view["reading"] is None


def test_what_the_agent_says_it_did_is_not_what_the_run_page_reports(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    claimed = reading()
    claimed["summary"] = "I called related_papers five times and read every section."

    _execute(cfg, clock, run_id, [reply(call("submit_reading", claimed))])

    view = build_run_projection(db, run_id)
    assert view["reading"]["summary"] == claimed["summary"]
    assert view["conduct"]["tool_calls"] == ["submit_reading"]
    # One passage was read, in the prompt; no related_papers call was ever made.
    assert view["conduct"]["passages_read"] == [f"{PAPER}:abstract"]


def test_the_last_model_call_offers_only_submission_and_the_notice_is_recorded(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    idle = reply(call("cost_state", {}))

    client = _execute(cfg, clock, run_id, [idle, idle, idle, idle])

    view = build_run_projection(db, run_id)
    assert (view["run"]["status"], view["run"]["failure"]) == (
        "failed",
        "model_call_limit",
    )
    assert len(client.requests) == view["run"]["limits"]["max_model_calls"] == 4
    assert client.requests[-1]["tools"] == ["submit_reading"]
    last = [e for e in view["events"] if e["kind"] == "model_call"][-1]
    assert last["payload"]["harness_notice"] == LAST_CALL_NOTICE
    # The fourth call asked for a tool it was no longer offered.
    assert view["conduct"]["refused_tool_calls"][-1]["name"] == "cost_state"


def test_tool_calls_past_the_limit_are_refused_but_submission_still_ends_the_run(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    _, spec = specs.current_spec(db)
    tight = specs.patch_budget(spec, {"max_tool_calls": 1})
    specs.apply_spec(db, tight, actor="operator", now=clock())
    run_id = _create(db, clock)

    _execute(
        cfg,
        clock,
        run_id,
        [
            reply(call("paper_text", {}, "a"), call("cost_state", {}, "b")),
            reply(call("submit_reading", reading())),
        ],
    )

    view = build_run_projection(db, run_id)
    assert view["conduct"]["refused_tool_calls"] == [
        {"name": "cost_state", "error": "tool_call_limit"}
    ]
    assert view["run"]["status"] == "completed"


def test_a_metadata_reading_puts_the_abstract_in_the_prompt_and_offers_one_tool(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    _, spec = specs.current_spec(db)
    cheap = specs.patch_island(spec, "cs", {"reading_mode": "metadata"})
    specs.apply_spec(db, cheap, actor="operator", now=clock())
    run_id = _create(db, clock)

    client = _execute(cfg, clock, run_id, [reply(call("submit_reading", reading()))])

    view = build_run_projection(db, run_id)
    assert view["run"]["reading_mode"] == "metadata"
    assert client.requests[0]["tools"] == ["submit_reading"]
    assert ABSTRACT in view["run"]["prompt"]["user"]
    assert _kinds(view)[:3] == ["run_started", "prompt", "paper_read"]
    assert view["run"]["status"] == "completed"


def test_the_per_run_cap_cuts_model_calls_before_the_run_starts(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _store(db, clock)
    _, spec = specs.current_spec(db)
    specs.apply_spec(
        db,
        specs.patch_budget(spec, {"per_run_max_micros": 14_000}),
        actor="operator",
        now=clock(),
    )

    run_id = _create(db, clock)

    run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert run["estimate_micros"] <= 14_000
    assert '"max_model_calls":1' in run["limits"]
    # One call cannot use tools first, so the run became a metadata reading.
    assert run["reading_mode"] == "metadata"


def test_every_call_has_room_to_reason_and_the_submission_has_more(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    step = reply(call("cost_state", {}))

    client = _execute(
        cfg, clock, run_id, [step, step, step, reply(call("submit_reading", reading()))]
    )

    view = build_run_projection(db, run_id)
    # The genome asks for 900; a model that reasons first needs the floor.
    assert [request["max_output_tokens"] for request in client.requests] == [
        STEP_OUTPUT_TOKENS,
        STEP_OUTPUT_TOKENS,
        STEP_OUTPUT_TOKENS,
        SUBMIT_OUTPUT_TOKENS,
    ]
    limits = view["run"]["limits"]
    assert (limits["max_output_tokens"], limits["submit_output_tokens"]) == (
        STEP_OUTPUT_TOKENS,
        SUBMIT_OUTPUT_TOKENS,
    )
    assert limits["submit_retries"] == 1
    # The agent is told one call ahead that only submission remains.
    calls = [e["payload"] for e in view["events"] if e["kind"] == "model_call"]
    assert calls[2]["harness_notice"] == NEXT_IS_LAST_NOTICE
    assert calls[3]["harness_notice"] == LAST_CALL_NOTICE
    assert view["run"]["status"] == "completed"


def test_a_cut_off_submission_gets_one_retry_told_why_and_can_succeed(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    step = reply(call("cost_state", {}))
    # What the live server saw: the submission's JSON stopped mid-way.
    truncated = reply(
        call("submit_reading", '{"claims":[{"depends_on_paper": true, "evid')
    )

    client = _execute(
        cfg,
        clock,
        run_id,
        [step, step, step, truncated, reply(call("submit_reading", reading()))],
    )

    view = build_run_projection(db, run_id)
    assert view["run"]["status"] == "completed"
    assert len(client.requests) == 5
    assert client.requests[4]["tools"] == ["submit_reading"]
    retry = [e["payload"] for e in view["events"] if e["kind"] == "model_call"][4]
    assert retry["harness_notice"] == RETRY_NOTICE.format(problem=ARGUMENTS_NOT_JSON)
    # The model was told why its call was refused, not just a code.
    refused = next(
        m
        for m in client.requests[4]["messages"]
        if m["role"] == "tool" and "arguments_not_json" in m["content"]
    )
    assert "cut off" in refused["content"]


def test_a_rejected_submission_on_the_last_call_is_retried_with_the_field(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    step = reply(call("cost_state", {}))
    incomplete = reading()
    del incomplete["idea_seeds"]

    _execute(
        cfg,
        clock,
        run_id,
        [
            step,
            step,
            step,
            reply(call("submit_reading", incomplete)),
            reply(call("submit_reading", reading())),
        ],
    )

    view = build_run_projection(db, run_id)
    assert view["run"]["status"] == "completed"
    retry = [e["payload"] for e in view["events"] if e["kind"] == "model_call"][4]
    assert "field idea_seeds" in retry["harness_notice"]


def test_a_run_gets_one_retry_only_and_says_how_the_last_call_failed(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    step = reply(call("cost_state", {}))
    cut_off = reply(text="", output_tokens=SUBMIT_OUTPUT_TOKENS)
    cut_off = type(cut_off)(**{**cut_off.__dict__, "finish_reason": "length"})

    first = _create(db, clock)
    client = _execute(cfg, clock, first, [step, step, step, cut_off, cut_off, step])
    # Four calls and one retry; the sixth answer in the script is never asked for.
    assert len(client.requests) == 5
    assert build_run_projection(db, first)["run"]["failure"] == "output_truncated"

    _store(db, clock, "2609.00002")
    second = _create(db, clock, paper_id="2609.00002")
    talk = reply(text="Here is my reading.")
    _execute(cfg, clock, second, [step, step, step, talk, talk])
    assert build_run_projection(db, second)["run"]["failure"] == "no_reading_submitted"

    _store(db, clock, "2609.00003")
    third = _create(db, clock, paper_id="2609.00003")
    bad = reading()
    bad["claims"] = []
    _execute(
        cfg,
        clock,
        third,
        [
            step,
            step,
            step,
            reply(call("submit_reading", bad)),
            reply(call("submit_reading", bad)),
        ],
    )
    assert build_run_projection(db, third)["run"]["failure"] == "submission_rejected"


def test_the_passage_names_live_agents_guessed_now_find_the_abstract(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)

    _execute(
        cfg,
        clock,
        run_id,
        [
            # Every one of these was sent by an agent on the live server.
            reply(
                call("paper_text", {"passage_id": "abstract"}, "a"),
                call("paper_text", {"passage_id": ""}, "b"),
                call("paper_text", {}, "c"),
            ),
            reply(
                call("paper_text", {"passage_id": f"{PAPER}:intro"}, "d"),
                call("paper_text", {"passage_id": "1"}, "e"),
            ),
            reply(call("submit_reading", reading())),
        ],
    )

    view = build_run_projection(db, run_id)
    results = {
        e["payload"]["call_id"]: e["payload"]["result"]
        for e in view["events"]
        if e["kind"] == "tool_call" and e["payload"]["name"] == "paper_text"
    }
    assert results["a"]["passages"][0]["passage_id"] == f"{PAPER}:abstract"
    for mapped in ("b", "c"):
        assert results[mapped]["passages"] == []
        assert results[mapped]["available_passages"] == [f"{PAPER}:abstract"]
        assert "paper map only" in results[mapped]["note"]
    for missing in ("d", "e"):
        assert results[missing]["error"] == "unknown_passage"
        assert results[missing]["available_passages"] == [f"{PAPER}:abstract"]
    assert view["run"]["status"] == "completed"


def test_stored_text_too_long_for_the_prompt_is_listed_and_read_by_tool(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock, abstract="Long study. " * 600)
    run_id = _create(db, clock)

    _execute(
        cfg,
        clock,
        run_id,
        [
            reply(call("paper_text", {})),
            reply(call("submit_reading", reading("Long study."))),
        ],
    )

    view = build_run_projection(db, run_id)
    user = view["run"]["prompt"]["user"]
    assert f"- {PAPER}:abstract: Abstract (7,200 characters)" in user
    assert "Long study. Long study." not in user
    assert _kinds(view)[:4] == [
        "run_started",
        "prompt",
        "model_call",
        "tool_call",
    ]
    tool = next(e for e in view["events"] if e["kind"] == "tool_call")
    assert "paper map only" in tool["payload"]["result"]["note"]
    assert not any(e["kind"] == "paper_read" for e in view["events"])


def test_a_run_that_spends_past_its_cap_is_stopped_with_its_trace(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    # The provider reports far more input than the estimate allowed for.
    costly = reply(call("paper_text", {}), input_tokens=200_000)

    client = _execute(cfg, clock, run_id, [costly, reply(call("cost_state", {}))])

    view = build_run_projection(db, run_id)
    assert (view["run"]["status"], view["run"]["failure"]) == ("failed", "run_cost_cap")
    assert len(client.requests) == 1
    assert view["cost"]["settled_micros"] == 50_250
    assert _kinds(view)[-1] == "run_failed"
    assert view["events"][-1]["payload"]["spent_micros"] == 50_250


def test_a_queued_run_reserves_its_estimate_against_the_daily_budget(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _store(db, clock)
    _store(db, clock, "2609.00002")
    _, spec = specs.current_spec(db)
    first = _create(db, clock)
    estimate = db.execute(
        "SELECT estimate_micros FROM runs WHERE id = ?", (first,)
    ).fetchone()[0]
    # A hard budget that fits one estimate and not two.
    tight = specs.patch_budget(
        spec, {"daily_soft_micros": estimate, "daily_hard_micros": estimate + 10}
    )
    specs.apply_spec(db, tight, actor="operator", now=clock())

    with pytest.raises(Conflict, match="daily_hard_budget_exhausted"):
        _create(db, clock, paper_id="2609.00002")


def test_an_edit_after_a_run_does_not_change_what_the_run_was(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    _execute(cfg, clock, run_id, [reply(call("submit_reading", reading()))])
    before = build_run_projection(db, run_id)

    _, spec = specs.current_spec(db)
    edited = specs.patch_genome(spec, "cs", "cs-reader", {"prompt": "Entirely new."})
    specs.apply_spec(db, edited, actor="operator", now=clock())

    after = build_run_projection(db, run_id)
    assert after["run"]["prompt"] == before["run"]["prompt"]
    assert after["genome"] == before["genome"]
    assert after["genome"]["version"] == after["run"]["genome_version"] == 1
    assert after["genome"]["prompt"] != "Entirely new."
    assert specs.find_genome(specs.current_spec(db)[1], "cs-reader")[1]["version"] == 2


def test_reading_validation_requires_every_field_and_evidence_for_text_claims(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _store(db, clock)
    passages = load_passages(db, PAPER)

    for missing in ("summary", "claims", "objections", "related_papers", "idea_seeds"):
        partial = reading()
        del partial[missing]
        with pytest.raises(Invalid) as refused:
            validate_reading_submission(partial, PAPER, passages)
        assert refused.value.field == missing

    uncited = reading()
    uncited["claims"] = [{"text": "The paper proves it."}]
    with pytest.raises(Invalid, match="needs an evidence quote"):
        validate_reading_submission(uncited, PAPER, passages)

    invented = reading("words that are not in the abstract")
    invented["claims"].append({"text": "From the title.", "depends_on_paper": False})
    accepted = validate_reading_submission(invented, PAPER, passages)
    # An unfound quote is kept and marked; it never counts as a citation.
    assert accepted["claims"][0]["evidence"][0]["verified"] is False
    assert accepted["claims"][0]["cited"] is False
    assert accepted["claims"][1] == {
        "text": "From the title.",
        "depends_on_paper": False,
        "evidence": [],
        "cited": False,
    }

    too_many = reading()
    too_many["objections"] = [f"objection {i}" for i in range(8)]
    too_many["idea_seeds"] = [f"seed {i}" for i in range(8)]
    accepted = validate_reading_submission(too_many, PAPER, passages)
    assert accepted["objections"] == [f"objection {i}" for i in range(6)]
    assert accepted["idea_seeds"] == [f"seed {i}" for i in range(6)]


def test_a_rejected_submission_leaves_the_run_open_for_a_corrected_one(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    incomplete = reading()
    del incomplete["objections"]

    _execute(
        cfg,
        clock,
        run_id,
        [
            reply(call("submit_reading", incomplete)),
            reply(call("submit_reading", reading())),
        ],
    )

    view = build_run_projection(db, run_id)
    submissions = [
        e["payload"]["result"]
        for e in view["events"]
        if e["kind"] == "tool_call" and e["payload"]["name"] == "submit_reading"
    ]
    assert submissions[0]["accepted"] is False
    assert submissions[0]["field"] == "objections"
    assert submissions[1] == {"accepted": True}
    assert db.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 1


def test_a_model_call_event_cannot_be_written_without_its_receipt(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)

    with pytest.raises(ValueError, match="needs its cost receipt"):
        append_run_event(db, run_id, "model_call", {"index": 1}, now=clock())
    with pytest.raises(ValueError, match="unknown run event kind"):
        append_run_event(db, run_id, "timeline_entry", {}, now=clock())


def test_idle_agents_take_the_newest_unread_paper_and_say_why_they_wait(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _store(db, clock, "2609.00001")
    clock.advance(minutes=5)
    _store(db, clock, "2609.00002")
    revision, spec = specs.current_spec(db)

    def advance():
        result = advance_swarm(
            db, spec=spec, revision=revision, provider=PROVIDER, clock=clock
        )
        db.commit()
        return result

    first = advance()

    [started] = first["started"]
    assert (started["agent"], started["paper_id"]) == ("cs-reader@cs", "2609.00002")
    assert {"agent": "quant-reader@quant", "reason": "queue_empty"} in first["waiting"]

    # While it is reading, the agent takes nothing more.
    assert advance() == {
        "started": [],
        "waiting": [
            {"agent": "cs-reader@cs", "reason": "working"},
            {"agent": "quant-reader@quant", "reason": "queue_empty"},
            {"agent": "bio-reader@bio", "reason": "queue_empty"},
            {"agent": "general-reader@general", "reason": "queue_empty"},
        ],
    }

    _execute(cfg, clock, started["run_id"], [reply(call("submit_reading", reading()))])
    second = advance()
    assert [item["paper_id"] for item in second["started"]] == ["2609.00001"]
    _execute(
        cfg,
        clock,
        second["started"][0]["run_id"],
        [ModelCallFailed("provider answered 500")],
    )
    # A paper the agent already attempted, even one it failed, is not retaken.
    assert advance()["started"] == []


def test_agents_wait_with_the_budget_reason_when_runs_are_stopped(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _store(db, clock)
    _, spec = specs.current_spec(db)
    specs.apply_spec(
        db,
        specs.patch_budget(spec, {"pause_new_runs": True}),
        actor="operator",
        now=clock(),
    )
    revision, spec = specs.current_spec(db)

    result = advance_swarm(
        db, spec=spec, revision=revision, provider=PROVIDER, clock=clock
    )

    assert result["started"] == []
    assert {"agent": "cs-reader@cs", "reason": "runs_paused"} in result["waiting"]


def test_runs_left_open_by_a_stopped_process_are_closed_with_their_trace(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _store(db, clock)
    run_id = _create(db, clock)
    db.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run_id,))
    append_run_event(db, run_id, "run_started", {"paper_id": PAPER}, now=clock())

    assert sweep_interrupted_runs(db, clock()) == 1

    view = build_run_projection(db, run_id)
    assert (view["run"]["status"], view["run"]["failure"]) == (
        "failed",
        "interrupted_by_restart",
    )
    assert _kinds(view) == ["run_started", "run_failed"]
    assert sum_cost_scope(db, "run_id", run_id)["receipt_count"] == 0
