"""The public brief and activity feed: words and numbers from stored rows, no model."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_agent.beta.brief import grade
from tests.beta.helpers import call, reading, reply
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

    answer = api.http.get("/api/v1/public/brief")

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
    assert any("no person has judged" in c["reason"] for c in brief["grade"]["caps"])
    assert any("claim is checked once" in item for item in brief["limits"])
    assert "You are one agent" not in answer.text


def test_a_caller_asks_for_sections_and_text(api: Api) -> None:
    only = api.http.get("/api/v1/public/brief?include=grade,limits").json()
    assert only["sections"] == ["grade", "limits"]
    assert "claims" not in only and "about" not in only

    text = api.http.get("/api/v1/public/brief?format=text")
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
