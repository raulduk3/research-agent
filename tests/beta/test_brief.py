"""The public brief and activity feed: words and numbers from stored rows, no model."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_agent.beta.brief import grade
from tests.beta.helpers import call, entry, feed, reading, reply
from tests.beta.test_api import PAPER, Api, _read

QUIET = {
    "runs": 0,
    "completed_runs": 0,
    "failed_runs": 0,
    "open_runs": 0,
    "failure_reasons": [],
    "readings": 0,
    "claims": 0,
    "paper_claims": 0,
    "verified_claims": 0,
    "readings_with_objections": 0,
    "papers": 0,
    "full_text_papers": 0,
    "papers_read": 0,
    "feedback_accept": 0,
    "feedback_pass": 0,
    "feedback_push_away": 0,
    "judged_readings": 0,
    "generations_committed": 0,
    "generations_skipped": 0,
    "cost_micros": 0,
}


@pytest.fixture
def api(tmp_path: Path) -> Api:
    return Api(tmp_path)


def test_an_empty_swarm_fails_and_says_why() -> None:
    graded = grade(QUIET, 50_000)

    assert graded["letter"] == "F"
    assert graded["score"] == 0
    # Nothing to measure is a zero, never a pass.
    assert all(not c["measured"] and c["score"] == 0 for c in graded["criteria"])
    assert {
        "ceiling": "F",
        "reason": "no agent has produced a single reading",
    } in graded["caps"]


def test_perfect_numbers_are_still_held_below_the_top() -> None:
    perfect = {
        **QUIET,
        "runs": 100,
        "completed_runs": 100,
        "readings": 100,
        "claims": 300,
        "paper_claims": 300,
        "verified_claims": 300,
        "readings_with_objections": 100,
        "papers": 100,
        "full_text_papers": 100,
        "papers_read": 100,
        "feedback_accept": 100,
        "judged_readings": 100,
        "generations_committed": 4,
    }

    graded = grade(perfect, 50_000)

    # Claims are never checked after submission, so the letter cannot pass A-.
    assert graded["letter"] == "A-"
    assert graded["score"] > 95


def test_the_brief_is_public_and_built_from_a_real_run(api: Api) -> None:
    operator = {"Authorization": "Bearer operator-pass"}
    _read(api, operator)

    answer = api.http.get(
        "/api/v1/public/brief?include=grade,numbers,claims,papers,limits"
    )

    assert answer.status_code == 200
    brief = answer.json()
    assert brief["numbers"]["readings"] == 1
    assert brief["numbers"]["verified_claims"] == 1
    assert brief["claims"][0]["paper_id"] == PAPER
    assert brief["claims"][0]["verified"] is True
    assert brief["claims"][0]["agent"] == "cs-reader@cs"
    assert brief["papers"]["held"] == 1 and brief["papers"]["waiting"] == 0
    # One reading and no feedback: the caps keep the letter at D or below.
    assert brief["grade"]["letter"] in {"D", "F"}
    assert any("too few to judge" in c["reason"] for c in brief["grade"]["caps"])
    assert any("claim is checked once" in item for item in brief["limits"])
    assert "You are one agent" not in answer.text


def test_a_caller_asks_for_sections_and_text(api: Api) -> None:
    only = api.http.get("/api/v1/public/brief?include=grade,limits").json()
    assert only["sections"] == ["grade", "limits"]
    assert "claims" not in only and "about" not in only

    text = api.http.get("/api/v1/public/brief?include=grade&format=text")
    assert text.headers["content-type"].startswith("text/markdown")
    assert text.text.startswith("# Atoll swarm brief")
    assert "## Grade: F" in text.text

    assert api.http.get("/api/v1/public/brief?include=nope").status_code == 422
    assert api.http.get("/api/v1/public/brief?island=nowhere").status_code == 404
    assert (
        api.http.get("/api/v1/public/brief?island=cs").json()["scope"]["island"] == "cs"
    )


def test_activity_names_each_step_and_the_papers_it_looked_at(api: Api) -> None:
    operator = {"Authorization": "Bearer operator-pass"}
    api.model.script = [
        reply(call("related_papers", {"query": "traces"})),
        reply(call("submit_reading", reading())),
    ]
    api.http.post(
        "/api/v1/ingest/arxiv",
        json={"category": "cs.AI", "advance": True},
        headers=operator,
    )

    feed = api.http.get("/api/v1/public/activity").json()

    kinds = [step["kind"] for step in feed["steps"]]
    assert kinds[0] == "run_started" and kinds[-1] == "run_completed"
    assert feed["steps"][0]["agent"] == "cs-reader@cs"
    assert feed["papers"][PAPER]["islands"]
    assert any(step["tool"] == "related_papers" for step in feed["steps"])
    # Only what a viewer draws: no prompt, no model text, no tool output.
    shown = str(feed)
    assert "payload" not in feed["steps"][0]
    assert "You are one agent" not in shown and "Visible traces" not in shown
    later = api.http.get(f"/api/v1/public/activity?after={feed['last_id']}").json()
    assert later["steps"] == []


def test_held_papers_carry_their_thesis_takeaways_and_a_way_back(api: Api) -> None:
    operator = {"Authorization": "Bearer operator-pass"}
    _read(api, operator)

    held = api.http.get("/api/v1/public/brief?include=papers").json()["papers"][
        "held_papers"
    ][0]

    assert held["thesis"] == reading()["thesis_quote"]
    assert [t["text"] for t in held["takeaways"]] == [
        "Visible traces alter the signal."
    ]
    assert held["takeaways"][0]["stance"] == "positive"
    assert held["read_by"] == "cs-reader@cs"
    assert held["href"] == f"/api/v1/public/papers/{PAPER}"

    record = api.http.get(held["href"]).json()
    assert record["held"] is True and record["let_go_after"] is None
    assert record["paper"]["title"] and record["readings"][0]["claims"][0]["verified"]
    assert record["readings"][0]["objections"] == reading()["objections"]
    text = api.http.get(held["href"] + "?format=text").text
    assert text.startswith("# ") and "Takeaways:" in text
    assert api.http.get("/api/v1/public/papers/nope").status_code == 404


def test_by_default_the_brief_is_what_the_swarm_learned(api: Api) -> None:
    operator = {"Authorization": "Bearer operator-pass"}
    _read(api, operator)

    brief = api.http.get("/api/v1/public/brief").json()

    assert brief["sections"] == ["about", "learned", "connections", "ideas"]
    assert "grade" not in brief and "claims" not in brief
    learned = brief["learned"][0]
    assert learned["paper_id"] == PAPER and learned["islands"] == ["cs"]
    assert learned["thesis"] == reading()["thesis_quote"]
    assert [t["text"] for t in learned["takeaways"]] == [
        "Visible traces alter the signal."
    ]
    assert learned["ideas"] == reading()["idea_seeds"]
    assert brief["ideas"][0]["paper_id"] == PAPER
    text = api.http.get("/api/v1/public/brief?format=text").text
    assert "## What the swarm learned" in text and "idea: Measure claim" in text


def test_readings_that_name_another_kept_paper_become_connections(api: Api) -> None:
    operator = {"Authorization": "Bearer operator-pass"}
    other = "2609.00002"
    api.feeds["cs.AI"] = feed(entry(PAPER), entry(other, title="Second paper"))
    api.http.post(
        "/api/v1/costs/budget",
        json={"fields": {"papers_per_pass": 10}},
        headers=operator,
    )
    api.http.post(
        "/api/v1/ingest/arxiv",
        json={"category": "cs.AI", "advance": False},
        headers=operator,
    )
    cs = api.bearer("cs", "cs-pass")
    linked = {**reading(), "related_papers": [f"{PAPER} adapted_method: same traces"]}
    for paper, submitted in ((PAPER, reading()), (other, linked)):
        api.model.script = [reply(call("submit_reading", submitted))]
        api.http.post("/api/v1/runs", json={"paper_id": paper}, headers=cs)

    links = api.http.get("/api/v1/public/brief?include=connections").json()[
        "connections"
    ]

    assert links == [
        {
            "from": other,
            "from_title": "Second paper",
            "to": PAPER,
            "to_title": entry(PAPER).title,
            "why": f"{PAPER} adapted_method: same traces",
        }
    ]


def test_letting_go_is_swarm_wide_and_can_be_undone(api: Api) -> None:
    operator = {"Authorization": "Bearer operator-pass"}
    _read(api, operator)
    cs = api.bearer("cs", "cs-pass")
    quant = api.bearer("quant", "quant-pass")

    assert api.http.post(f"/api/v1/papers/{PAPER}/release", json={}).status_code == 401
    # An island the paper never reached may not let it go for everyone.
    refused = api.http.post(f"/api/v1/papers/{PAPER}/release", json={}, headers=quant)
    assert refused.status_code == 403

    gone = api.http.post(f"/api/v1/papers/{PAPER}/release", json={}, headers=cs)
    assert gone.status_code == 200 and gone.json()["held"] is False

    papers = api.http.get("/api/v1/public/brief?include=papers").json()["papers"]
    assert (papers["held"], papers["released"]) == (0, 1)
    assert papers["recent_papers"] == []
    assert api.http.get("/api/v1/public/brief").json()["learned"] == []
    record = api.http.get(f"/api/v1/public/papers/{PAPER}").json()
    assert record["held"] is False and record["released"] is True
    island = api.http.get("/api/v1/islands/cs", headers=cs).json()
    assert island["papers"][0]["released"] is True and island["queue"] == []

    back = api.http.post(f"/api/v1/papers/{PAPER}/hold", json={}, headers=operator)
    assert back.json()["held"] is True
    papers = api.http.get("/api/v1/public/brief?include=papers").json()["papers"]
    assert papers["held"] == 1 and papers["recent_papers"][0]["held"] is True


def test_a_released_paper_leaves_every_islands_search(api: Api) -> None:
    from research_agent.beta.db import connect
    from research_agent.beta.papers import release_paper, search

    operator = {"Authorization": "Bearer operator-pass"}
    _read(api, operator)
    with connect(api.cfg.database) as db:
        assert search(db, "traces", island_id="cs")
        release_paper(db, PAPER, actor="test", note="", now=api.clock())
        # Gone for every island, not only the one that let it go.
        assert search(db, "traces", island_id="cs") == []
        assert search(db, "traces", island_id="quant") == []


def test_an_island_reads_only_its_own_papers(api: Api) -> None:
    from research_agent.beta.db import connect
    from research_agent.beta.papers import related_work_shortlist, search

    operator = {"Authorization": "Bearer operator-pass"}
    _read(api, operator)
    with connect(api.cfg.database) as db:
        # The paper reached cs by category; quant never got it.
        assert search(db, "traces", island_id="cs")
        assert search(db, "traces", island_id="quant") == []
        assert search(db, "traces") != []
        assert related_work_shortlist(db, PAPER, island_id="quant") == []


def test_a_cited_paper_an_agent_reads_joins_its_island(api: Api) -> None:
    from research_agent.beta.db import connect
    from research_agent.beta.papers import search

    operator = {"Authorization": "Bearer operator-pass"}
    _read(api, operator)
    cs = api.bearer("cs", "cs-pass")
    # cs reads the paper's abstract through a tool reference; quant cannot see it.
    api.model.script = [
        reply(
            call("cited_paper_text", {"reference": f"https://arxiv.org/abs/{PAPER}"})
        ),
        reply(call("submit_reading", reading())),
    ]
    api.feeds["cs.AI"] = feed(entry("2609.00002", title="Second"))
    api.http.post(
        "/api/v1/ingest/arxiv",
        json={"category": "cs.AI", "advance": False},
        headers=operator,
    )
    with connect(api.cfg.database) as db:
        # Stage: give quant the second paper only, by hand, so the read comes from quant.
        db.execute(
            "INSERT OR IGNORE INTO assignments(paper_id, island_id, reasons, created_at)"
            " VALUES ('2609.00002', 'quant', '[\"test\"]', '2026-09-10T12:00:00Z')"
        )
        db.commit()
    quant = api.bearer("quant", "quant-pass")
    api.http.post("/api/v1/runs", json={"paper_id": "2609.00002"}, headers=quant)
    with connect(api.cfg.database) as db:
        reached = db.execute(
            "SELECT reasons FROM assignments WHERE paper_id = ? AND island_id = 'quant'",
            (PAPER,),
        ).fetchone()
        assert reached is not None and "cited_by_run" in reached["reasons"]
        assert search(db, "traces", island_id="quant")
    assert cs
