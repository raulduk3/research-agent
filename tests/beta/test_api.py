"""The HTTP surface: plain JSON, sessions, edit scope and the web app's routes."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from research_agent.beta.app import create_app, wire
from research_agent.beta.db import connect
from research_agent.beta.ingest import SourceFailed
from tests.beta.helpers import (
    ABSTRACT,
    FakeClock,
    ScriptedClient,
    call,
    config,
    entry,
    feed,
    reading,
    reply,
)

ORIGIN = "https://swarm.example.app"
PAPER = "2609.00001"
# The test clock starts at 2026-09-10T12:00:00Z.
NOON = 1789041600


class Api:
    """The app on a temporary store, with a scripted model and fixed feeds."""

    def __init__(self, tmp_path: Path, **overrides: Any) -> None:
        self.clock = FakeClock()
        self.cfg = config(tmp_path, **overrides)
        self.model = ScriptedClient([])
        self.feeds: dict[str, str] = {"cs.AI": feed(entry(PAPER))}
        self.http = TestClient(
            create_app(
                self.cfg,
                model_client=self.model,
                clock=self.clock,
                fetch=self.fetch,
                sleep=lambda _: None,
            )
        )

    def fetch(self, category: str, limit: int) -> str:
        if category not in self.feeds:
            raise SourceFailed(f"no answer for {category}")
        return self.feeds[category]

    def bearer(self, island: str, password: str) -> dict[str, str]:
        answer = self.http.post(
            "/api/v1/login", json={"island": island, "password": password}
        )
        assert answer.status_code == 200, answer.text
        return {"Authorization": f"Bearer {answer.json()['token']}"}

    def rows(self, sql: str) -> list[sqlite3.Row]:
        with connect(self.cfg.database) as db:
            return db.execute(sql).fetchall()


@pytest.fixture
def api(tmp_path: Path) -> Api:
    return Api(tmp_path)


@pytest.fixture
def cs(api: Api) -> dict[str, str]:
    return api.bearer("cs", "cs-pass")


@pytest.fixture
def operator(api: Api) -> dict[str, str]:
    return {"Authorization": "Bearer operator-pass"}


def _ingest(api: Api, operator: dict[str, str], **body: Any) -> dict[str, Any]:
    answer = api.http.post(
        "/api/v1/ingest/arxiv",
        json={"category": "cs.AI", "advance": False, **body},
        headers=operator,
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


def _read(api: Api, operator: dict[str, str]) -> str:
    """Ingest the paper and let the cs agent read it; return the run id."""
    api.model.script = [
        reply(call("paper_text", {})),
        reply(call("submit_reading", reading())),
    ]
    summary = _ingest(api, operator, advance=True)
    return summary["advance"]["started"][0]["run_id"]


def test_health_and_the_public_storm_need_no_session(api: Api) -> None:
    assert api.http.get("/health").json() == {
        "status": "ok",
        "schema_version": 4,
        "provider_configured": True,
    }

    answer = api.http.get("/api/v1/public/storm")

    assert answer.status_code == 200
    storm = answer.json()
    assert [island["id"] for island in storm["islands"]] == [
        "cs",
        "quant",
        "bio",
        "general",
    ]
    assert (storm["papers"], storm["runs"], storm["cost_micros"]) == (0, 0, 0)
    assert storm["islands"][0]["paper_count"] == 0
    assert storm["budget"]["target_micros"] == 50_000_000
    assert storm["budget"]["mode"] == "normal"
    assert storm["agents"][0]["address"] == "cs-reader@cs"
    assert storm["unavailable"] == []
    # The public view shows activity, never a prompt or a token.
    assert "prompt" not in answer.text and "token" not in answer.text


def test_everything_else_refuses_a_caller_with_no_session(api: Api) -> None:
    for path in (
        "/api/v1/islands",
        "/api/v1/islands/cs",
        f"/api/v1/papers/{PAPER}",
        "/api/v1/runs/R-0000000000",
        "/api/v1/costs/budget",
        "/api/v1/agents",
        "/api/v1/swarm/spec",
    ):
        refused = api.http.get(path)
        assert refused.status_code == 401, path
        assert refused.json() == {
            "detail": "sign in to an island first",
            "code": "unauthenticated",
            "field": None,
        }
    # A write with a well-formed body and no token is refused the same way.
    for path, body in (
        ("/api/v1/chat", {"message": "anything"}),
        (
            "/api/v1/feedback",
            {"target_kind": "paper", "target_id": PAPER, "signal": "accept"},
        ),
        ("/api/v1/runs", {"paper_id": PAPER}),
        ("/api/v1/genomes", {"parent_id": "cs-reader", "prompt": "Unsigned."}),
        ("/api/v1/agents/cs-reader", {"fields": {"prompt": "Unsigned."}}),
        ("/api/v1/costs/budget", {"fields": {"monthly_budget_micros": 1}}),
        ("/api/v1/ingest/arxiv", {}),
        ("/api/v1/swarm/advance", {}),
    ):
        assert api.http.post(path, json=body).status_code == 401, path
    assert api.rows("SELECT COUNT(*) FROM spec_revisions")[0][0] == 1


def test_login_binds_an_island_to_its_own_credential_and_stores_nothing(
    api: Api,
) -> None:
    def login(**body: str) -> Any:
        return api.http.post("/api/v1/login", json=body)

    # The right island with another island's credential is refused.
    assert login(island="cs", password="quant-pass").status_code == 403
    assert login(island="nowhere", password="cs-pass").status_code == 404
    # An island with no credential configured accepts none.
    assert login(island="bio", password="anything").status_code == 403
    assert login(credential="not-a-password").status_code == 401

    opened = login(island="quant", password="quant-pass").json()

    assert (opened["island"], opened["role"]) == ("quant", "island")
    assert opened["token"].startswith("v1.")
    assert opened["expires_at"] == NOON + 30 * 24 * 3600
    assert opened["budget"]["island"]["island_id"] == "quant"
    # One field is enough too: the credential names its island.
    assert login(credential="cs-pass").json()["island"] == "cs"
    assert login(credential="operator-pass").json()["role"] == "operator"
    # No session row, no transcript row: the only stored rows are the seeded spec.
    counts = api.rows(
        "SELECT (SELECT COUNT(*) FROM spec_revisions), (SELECT COUNT(*) FROM feedback),"
        " (SELECT COUNT(*) FROM cost_receipts), (SELECT COUNT(*) FROM idempotency)"
    )[0]
    assert tuple(counts) == (1, 0, 0, 0)


def test_a_session_expires_and_a_tampered_token_is_refused(
    api: Api, cs: dict[str, str]
) -> None:
    token = cs["Authorization"]
    forged = {"Authorization": token[:-1] + ("0" if token[-1] != "0" else "1")}
    assert api.http.get("/api/v1/session", headers=forged).status_code == 401

    whoami = api.http.get("/api/v1/session", headers=cs)
    assert (whoami.json()["island"], whoami.json()["role"]) == ("cs", "island")
    api.clock.advance(days=31)
    expired = api.http.get("/api/v1/session", headers=cs)
    assert expired.status_code == 401
    assert expired.json()["detail"] == "the session has expired"


def test_cors_admits_the_configured_origin_with_credentials_and_no_other(
    api: Api,
) -> None:
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }

    allowed = api.http.options("/api/v1/chat", headers={"Origin": ORIGIN, **preflight})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert allowed.headers["access-control-allow-credentials"] == "true"
    simple = api.http.get("/api/v1/public/storm", headers={"Origin": ORIGIN})
    assert simple.headers["access-control-allow-origin"] == ORIGIN

    other = api.http.options(
        "/api/v1/chat", headers={"Origin": "https://elsewhere.example", **preflight}
    )
    assert "access-control-allow-origin" not in other.headers


def test_times_go_out_as_whole_seconds() -> None:
    sent = wire(
        {
            "created_at": "2026-09-10T12:00:00Z",
            "note": "2026-09-10T12:00:00Z",
            "runs": [{"finished_at": "2026-09-10T12:00:01Z", "started_at": None}],
        }
    )

    assert sent == {
        "created_at": NOON,
        # Only time fields are converted; text that looks like a time is left alone.
        "note": "2026-09-10T12:00:00Z",
        "runs": [{"finished_at": NOON + 1, "started_at": None}],
    }


def test_ingestion_is_the_operators_and_reports_what_it_stored(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    refused = api.http.post("/api/v1/ingest/arxiv", json={}, headers=cs)
    assert refused.status_code == 403

    summary = _ingest(api, operator)

    assert (summary["stored"], summary["status"]) == (1, "completed")
    assert summary["assigned"] == [{"paper_id": PAPER, "island_id": "cs"}]
    assert summary["advance"] == {"started": [], "waiting": []}
    assert summary["budget"]["mode"] == "normal"


def test_ingestion_lets_idle_agents_start_reading_on_their_own(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    api.model.script = [
        reply(call("paper_text", {})),
        reply(call("submit_reading", reading())),
    ]

    summary = _ingest(api, operator, advance=True)

    [started] = summary["advance"]["started"]
    assert started["agent"] == "cs-reader@cs" and started["paper_id"] == PAPER
    view = api.http.get(f"/api/v1/runs/{started['run_id']}", headers=cs).json()
    assert view["run"]["status"] == "completed"
    assert view["budget"]["month_to_date_micros"] == 1_000


def test_a_run_started_through_the_api_can_be_watched_and_replayed(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    _ingest(api, operator)
    api.model.script = [
        reply(call("paper_text", {})),
        reply(call("submit_reading", reading())),
    ]
    key = {"Idempotency-Key": "one-request"}

    accepted = api.http.post(
        "/api/v1/runs", json={"paper_id": PAPER}, headers={**cs, **key}
    )

    assert accepted.status_code == 202
    run_id = accepted.json()["run_id"]
    # The same request sent again answers with the same run and starts nothing.
    again = api.http.post(
        "/api/v1/runs", json={"paper_id": PAPER}, headers={**cs, **key}
    )
    assert again.json()["run_id"] == run_id
    assert api.rows("SELECT COUNT(*) FROM runs")[0][0] == 1

    view = api.http.get(f"/api/v1/runs/{run_id}", headers=cs).json()
    run = view["run"]
    assert (run["status"], run["paper_id"], run["genome_id"], run["island_id"]) == (
        "completed",
        PAPER,
        "cs-reader",
        "cs",
    )
    assert run["created_at"] == NOON
    # The events are the replay, in stored order, each with what a page shows.
    assert [event["id"] for event in view["events"]] == list(range(1, 10))
    assert [event["kind"] for event in view["events"]][:5] == [
        "run_started",
        "prompt",
        "paper_read",
        "model_call",
        "tool_call",
    ]
    step = view["events"][4]
    assert (step["run_id"], step["tool"], step["created_at"]) == (
        run_id,
        "paper_text",
        NOON,
    )
    read = view["events"][2]
    assert read["locator"]["section"] == f"{PAPER}:abstract"
    assert read["locator"]["quote"] == ABSTRACT
    assert read["locator"]["page"] is None
    assert "paper map only" in step["output"]
    assert ABSTRACT not in step["output"]
    assert sum(event["cost_micros"] for event in view["events"]) == view["cost_micros"]
    # The paper and the genome the run used come with it; no second call is needed.
    assert view["paper"]["id"] == PAPER and view["paper"]["summary"] == ABSTRACT
    assert view["genome"]["id"] == "cs-reader" and view["genome"]["prompt"]
    assert view["reading"]["summary"] == reading()["summary"]
    assert view["budget"]["island"]["island_id"] == "cs"

    tail = api.http.get(f"/api/v1/runs/{run_id}?after=7", headers=cs).json()
    assert [event["kind"] for event in tail["events"]] == [
        "reading_submitted",
        "run_completed",
    ]


def test_a_run_refused_by_the_budget_answers_with_the_reason(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    _ingest(api, operator)
    paused = api.http.post(
        "/api/v1/costs/budget",
        json={"fields": {"pause_new_runs": True}},
        headers=operator,
    )
    assert paused.status_code == 200

    refused = api.http.post("/api/v1/runs", json={"paper_id": PAPER}, headers=cs)

    assert refused.status_code == 409
    assert refused.json()["code"] == "state_conflict"
    assert refused.json()["detail"].startswith("runs_paused:")
    # Browsing stays up while runs are stopped.
    paper = api.http.get(f"/api/v1/papers/{PAPER}", headers=cs)
    assert paper.status_code == 200
    assert paper.json()["budget"]["runs_refusal"] == "runs_paused"
    island = api.http.get("/api/v1/islands/cs", headers=cs).json()
    assert island["runs_remaining_today"] == 0
    assert island["agents"][0]["state"] == "blocked"


def test_without_a_provider_a_run_is_unavailable_and_nothing_is_invented(
    tmp_path: Path,
) -> None:
    api = Api(tmp_path, provider=None)
    operator = {"Authorization": "Bearer operator-pass"}
    _ingest(api, operator)

    refused = api.http.post(
        "/api/v1/runs", json={"paper_id": PAPER, "island_id": "cs"}, headers=operator
    )

    assert refused.status_code == 503
    assert refused.json()["code"] == "unavailable"
    assert api.rows("SELECT COUNT(*) FROM runs")[0][0] == 0
    assert api.rows("SELECT COUNT(*) FROM readings")[0][0] == 0


def test_the_island_paper_and_agent_views_carry_the_cascade_and_the_cost(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    run_id = _read(api, operator)

    island = api.http.get("/api/v1/islands/cs", headers=cs).json()
    assert (island["island"]["name"], island["island"]["state"]) == (
        "CS island",
        "idle",
    )
    assert island["cost_micros"] == island["month_cost_micros"] == 1_000
    assert island["budget_share"] == 0.4
    # 40% of the daily hard budget, less today's spend, at the per-run cap.
    assert island["runs_remaining_today"] == (int(3_333_332 * 0.4) - 1_000) // 50_000
    [paper_row] = island["papers"]
    assert (paper_row["id"], paper_row["run_count"], paper_row["cost_micros"]) == (
        PAPER,
        1,
        1_000,
    )
    assert island["queue"] == []
    [run_row] = island["runs"]
    assert (run_row["id"], run_row["cost_micros"], run_row["status"]) == (
        run_id,
        1_000,
        "completed",
    )
    [agent_row] = island["agents"]
    assert (agent_row["id"], agent_row["island_id"]) == ("cs-reader", "cs")
    assert agent_row["prompt"] and "submit_reading" in agent_row["allowed_tools"]
    assert (agent_row["parent_id"], agent_row["generation"]) == (None, 0)
    assert agent_row["cost_micros"] == 1_000 and agent_row["active"] is True
    assert len(island["readings"]) == 1 and island["evolution"] == []
    assert island["unavailable"] == []

    view = api.http.get(f"/api/v1/papers/{PAPER}", headers=cs).json()
    assert list(view)[:6] == [
        "paper",
        "assignments",
        "readings",
        "runs",
        "feedback",
        "feedback_totals",
    ]
    paper = view["paper"]
    assert (paper["summary"], paper["text_status"]) == (ABSTRACT, "abstract_only")
    assert paper["url"] == f"https://arxiv.org/abs/{PAPER}v1"
    assert paper["pdf_url"] == f"https://arxiv.org/pdf/{PAPER}v1"
    assert paper["fetched_at"] == NOON
    assert paper["sections"] == [
        {
            "id": f"{PAPER}:abstract",
            "title": "Abstract",
            "kind": "abstract",
            "page": None,
            "char_start": 0,
            "char_end": len(ABSTRACT),
            "text": ABSTRACT,
        }
    ]
    [assignment] = view["assignments"]
    assert (assignment["paper_id"], assignment["island_id"]) == (PAPER, "cs")
    assert assignment["reasons"] == ["primary_category:cs.AI", "focus_keyword:agents"]
    assert assignment["reason"] == "primary_category:cs.AI, focus_keyword:agents"
    assert view["runs"][0]["tool_call_count"] == 2
    assert view["readings"][0]["run_id"] == run_id
    assert view["cost_micros"] == 1_000
    assert view["cost_by_island"] == {"cs": 1_000}

    listed = api.http.get("/api/v1/agents?island=cs", headers=cs).json()
    assert [agent["address"] for agent in listed["agents"]] == ["cs-reader@cs"]
    agent = api.http.get("/api/v1/agents/cs-reader@cs", headers=cs).json()
    assert agent["agent"]["state"] == "idle"
    assert agent["agent"]["stats"]["completed"] == 1
    assert agent["runs"][0]["id"] == run_id
    assert agent["cost_micros"] == 1_000
    assert len(agent["versions"]) == 1


def test_an_island_session_edits_its_own_agents_and_nothing_beyond(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    edited = api.http.post(
        "/api/v1/agents/cs-reader",
        json={"fields": {"prompt": "Read for flaws."}, "note": "sharper"},
        headers=cs,
    )
    assert edited.status_code == 200
    assert (edited.json()["revision"], edited.json()["applied"]) == (2, True)

    for path, fields in (
        ("/api/v1/agents/quant-reader", {"prompt": "Not mine."}),
        ("/api/v1/islands/quant", {"focus": "Not mine."}),
        ("/api/v1/islands/cs", {"budget_share": 0.9}),
        ("/api/v1/costs/budget", {"monthly_budget_micros": 900_000_000}),
    ):
        refused = api.http.post(path, json={"fields": fields}, headers=cs)
        assert refused.status_code == 403, path
    spec = api.http.get("/api/v1/swarm/spec", headers=cs).json()
    assert spec["revision"] == 2 and spec["spec"]["budget"] == {}

    own = api.http.post(
        "/api/v1/islands/cs", json={"fields": {"focus": "agents only"}}, headers=cs
    )
    assert own.status_code == 200
    raised = api.http.post(
        "/api/v1/costs/budget",
        json={"fields": {"agents_per_paper": 2}},
        headers=operator,
    )
    assert raised.json()["changes"][0]["kind"] == "budget"


def test_the_web_apps_agent_form_saves_a_new_version_and_keeps_past_runs(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    run_id = _read(api, operator)
    before = api.http.get(f"/api/v1/runs/{run_id}", headers=cs).json()["genome"]

    saved = api.http.post(
        "/api/v1/genomes",
        json={
            "island_id": "cs",
            "parent_id": "cs-reader",
            "prompt": "Read for flaws.",
            "tools": "paper_text,submit_reading",
        },
        headers=cs,
    )

    assert saved.status_code == 200 and saved.json()["applied"] is True
    [agent] = api.http.get("/api/v1/islands/cs", headers=cs).json()["agents"]
    assert (agent["version"], agent["prompt"]) == (2, "Read for flaws.")
    assert agent["allowed_tools"] == ["paper_text", "submit_reading"]
    assert agent["parent_id"] == "cs-reader"
    # The run made under version 1 still shows the genome it used.
    after = api.http.get(f"/api/v1/runs/{run_id}", headers=cs).json()["genome"]
    assert after == before and after["version"] == 1

    other = api.http.post(
        "/api/v1/genomes",
        json={"parent_id": "quant-reader", "prompt": "Not mine."},
        headers=cs,
    )
    assert other.status_code == 403


def test_an_edit_can_be_previewed_guarded_and_undone(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    preview = api.http.post(
        "/api/v1/agents/cs-reader",
        json={"fields": {"prompt": "Read for flaws."}, "dry_run": True},
        headers=cs,
    ).json()
    assert preview["applied"] is False and preview["changes"][0]["fields"] == ["prompt"]

    api.http.post(
        "/api/v1/agents/cs-reader",
        json={"fields": {"prompt": "Read for flaws."}},
        headers=cs,
    )
    stale = api.http.post(
        "/api/v1/agents/cs-reader",
        json={"fields": {"prompt": "Written against an old copy."}, "base_revision": 1},
        headers=cs,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"].startswith("spec_changed:")

    undone = api.http.post(
        "/api/v1/agents/cs-reader/versions/1/restore", json={}, headers=cs
    ).json()
    assert undone["applied"] and undone["restored_from"] == 1
    agent = api.http.get("/api/v1/agents/cs-reader", headers=cs).json()
    assert agent["agent"]["version"] == 3
    assert agent["agent"]["lineage"]["origin"] == "restore"
    assert [item["version"] for item in agent["versions"]] == [1, 2, 3]
    assert agent["versions"][0]["prompt"] == agent["agent"]["prompt"]

    whole = api.http.post(
        "/api/v1/swarm/revisions/2/restore", json={}, headers=operator
    ).json()
    assert whole["revision"] == 4
    log = api.http.get("/api/v1/swarm/revisions", headers=cs).json()
    assert [item["revision"] for item in log["revisions"]] == [4, 3, 2, 1]
    assert log["revisions"][0]["created_at"] == NOON
    restore = api.http.post("/api/v1/swarm/revisions/1/restore", json={}, headers=cs)
    assert restore.status_code == 403


def test_an_invalid_edit_names_the_field_and_changes_nothing(
    api: Api, cs: dict[str, str]
) -> None:
    refused = api.http.post(
        "/api/v1/agents/cs-reader",
        json={"fields": {"allowed_tools": ["paper_text"]}},
        headers=cs,
    )

    assert refused.status_code == 422
    assert refused.json() == {
        "detail": "a genome must allow submit_reading",
        "code": "invalid_request",
        "field": "islands[0].genomes[0].allowed_tools",
    }
    assert api.rows("SELECT COUNT(*) FROM spec_revisions")[0][0] == 1


def test_feedback_is_accepted_on_every_target_and_scoped_to_the_island(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    run_id = _read(api, operator)
    reading_id = api.rows("SELECT id FROM readings")[0][0]
    answer = api.http.post(
        "/api/v1/chat", json={"message": "visible traces"}, headers=cs
    ).json()

    targets = [
        ("island", "cs"),
        ("paper", PAPER),
        ("run", run_id),
        ("reading", reading_id),
        ("idea", f"{reading_id}#0"),
        ("chat", answer["answer_id"]),
    ]
    for kind, target in targets:
        stored = api.http.post(
            "/api/v1/feedback",
            json={"target_kind": kind, "target_id": target, "signal": "accept"},
            headers=cs,
        )
        assert stored.status_code == 201, (kind, stored.text)
        assert stored.json()["feedback"]["island_id"] == "cs"
    # The web app's own words for the same thing are taken as sent.
    web = api.http.post(
        "/api/v1/feedback",
        json={
            "island_id": "cs",
            "target_type": "run",
            "target_id": run_id,
            "signal": "not_useful",
            "note": "thin",
        },
        headers={**cs, "Idempotency-Key": "once"},
    )
    assert web.status_code == 201 and web.json()["feedback"]["signal"] == "pass"
    repeat = api.http.post(
        "/api/v1/feedback",
        json={"target_type": "run", "target_id": run_id, "signal": "not_useful"},
        headers={**cs, "Idempotency-Key": "once"},
    )
    assert repeat.json()["feedback"]["id"] == web.json()["feedback"]["id"]

    for body, status in (
        ({"target_kind": "run", "target_id": "R-missing", "signal": "accept"}, 404),
        (
            {"target_kind": "idea", "target_id": f"{reading_id}#9", "signal": "accept"},
            404,
        ),
        ({"target_kind": "island", "target_id": "nowhere", "signal": "accept"}, 404),
        ({"target_kind": "paper", "target_id": PAPER, "signal": "adore"}, 422),
        ({"target_kind": "genome", "target_id": "cs-reader", "signal": "accept"}, 422),
        ({"target_id": PAPER, "signal": "accept"}, 422),
        (
            {
                "target_kind": "paper",
                "target_id": PAPER,
                "signal": "pass",
                "island_id": "quant",
            },
            403,
        ),
    ):
        refused = api.http.post("/api/v1/feedback", json=body, headers=cs)
        assert refused.status_code == status, body

    island = api.http.get("/api/v1/islands/cs", headers=cs).json()
    assert island["feedback_totals"] == {"accept": 6, "pass": 1, "push_away": 0}
    assert len(island["feedback"]) == 7
    run = api.http.get(f"/api/v1/runs/{run_id}", headers=cs).json()
    # Island and paper feedback do not name the run; run, reading and idea do.
    assert run["feedback_totals"] == {"accept": 3, "pass": 1, "push_away": 0}
    assert run["cost"]["cost_per_useful_feedback_micros"] == 1_000 // 3


def test_chat_writes_an_answer_from_stored_text_by_default(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    _read(api, operator)
    api.model.script = [reply(text="Visible traces change what agents learn [1].")]

    answer = api.http.post(
        "/api/v1/chat", json={"message": "visible traces"}, headers=cs
    ).json()

    # The web app sends only the message; a written answer is the default.
    assert (answer["mode"], answer["answer"]) == (
        "synthesized",
        "Visible traces change what agents learn [1].",
    )
    assert answer["paid"] == {"requested": True, "used": True, "refused": None}
    # The cost is this answer's own, not the island's running total.
    assert answer["cost_micros"] == 500
    request = api.model.requests[-1]
    assert request["max_output_tokens"] == 2500 and request["tools"] == []
    # The model read the stored abstract and the agent's reading, not search fragments.
    shown = request["messages"][1]["content"]
    assert ABSTRACT in shown
    assert reading()["summary"] in shown
    first = answer["links"][0]
    assert {"id": PAPER, "kind": "paper"}.items() <= first.items()
    assert "record" not in first
    reading_link = next(link for link in answer["links"] if link["kind"] == "run")
    assert reading_link["title"].startswith("Reading of ")


def test_chat_without_a_model_answers_in_a_sentence_not_a_dump(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    _read(api, operator)

    answer = api.http.post(
        "/api/v1/chat",
        json={"message": "visible traces", "synthesize": False},
        headers=cs,
    ).json()

    assert answer["mode"] == "retrieval" and answer["cost_micros"] == 0
    assert answer["answer"].startswith(
        "The swarm has 1 paper and 1 reading that match."
    )
    assert "[1]" not in answer["answer"]
    assert answer["budget"]["island"]["month_micros"] == 1_000
    unknown = api.http.post(
        "/api/v1/chat",
        json={"message": "medieval bookbinding", "synthesize": False},
        headers=cs,
    ).json()
    assert unknown["supported"] is False and unknown["links"] == []


def test_the_budget_view_states_every_tracked_figure_and_lever(
    api: Api, cs: dict[str, str]
) -> None:
    state = api.http.get("/api/v1/costs/budget", headers=cs).json()["state"]

    for figure in (
        "target_micros",
        "month_to_date_micros",
        "projected_month_micros",
        "daily_soft_micros",
        "daily_hard_micros",
    ):
        assert isinstance(state[figure], int), figure
    assert set(state["levers"]) >= {
        "per_run_max_micros",
        "per_chat_max_micros",
        "papers_per_pass",
        "agents_per_paper",
        "islands_per_paper",
        "max_tool_calls",
        "max_model_calls",
        "max_output_tokens",
        "pause_new_runs",
    }
    assert state["plan"]["mode"] == "normal"
    assert {island["island_id"] for island in state["islands"]} == {
        "cs",
        "quant",
        "bio",
        "general",
    }
    assert round(sum(island["share"] for island in state["islands"]), 3) == 1.0


def test_a_tightened_budget_stops_work_and_shows_on_every_page(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    _ingest(api, operator)
    tight = api.http.post(
        "/api/v1/costs/budget",
        json={"fields": {"monthly_budget_micros": 3_000}},
        headers=operator,
    )
    assert tight.json()["budget"]["target_micros"] == 3_000

    # A budget under one run's estimate admits nothing: the agent waits, named.
    waiting = api.http.post("/api/v1/swarm/advance", json={}, headers=operator).json()

    assert waiting["started"] == []
    assert {"agent": "cs-reader@cs", "reason": "monthly_budget_exhausted"} in waiting[
        "waiting"
    ]
    assert api.rows("SELECT COUNT(*) FROM runs")[0][0] == 0
    assert api.http.get("/api/v1/public/storm").json()["budget"]["mode"] == "normal"

    api.http.post(
        "/api/v1/costs/budget",
        json={"fields": {"monthly_budget_micros": 0}},
        headers=operator,
    )
    for path in (f"/api/v1/papers/{PAPER}", "/api/v1/islands/cs", "/api/v1/agents"):
        budget = api.http.get(path, headers=cs).json()["budget"]
        assert budget["mode"] == "stored_data_only", path
        assert budget["runs_refusal"] == "monthly_budget_reached"
    chat = api.http.post(
        "/api/v1/chat",
        json={"message": "visible traces", "synthesize": True},
        headers=cs,
    ).json()
    # Stored-data chat stays up; the paid answer is refused with the reason.
    assert chat["supported"] and chat["mode"] == "retrieval"
    assert chat["paid"]["refused"] == "budget_mode_stored_data_only"
    assert api.model.requests == []


def test_an_unknown_route_and_a_malformed_body_answer_with_detail(
    api: Api, cs: dict[str, str]
) -> None:
    missing = api.http.get("/api/v1/nowhere", headers=cs)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found", "code": "not_found", "field": None}

    malformed = api.http.post("/api/v1/chat", json={"synthesize": True}, headers=cs)
    assert malformed.status_code == 422
    assert malformed.json() == {
        "detail": "Field required",
        "code": "invalid_request",
        "field": "message",
    }


def test_a_restart_closes_open_runs_and_keeps_the_stored_swarm(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    _ingest(api, operator)
    # A run left running with no process behind it, as after a crash.
    with connect(api.cfg.database) as db:
        db.execute(
            "INSERT INTO runs(id, paper_id, island_id, genome_id, genome_version,"
            " spec_revision, genome, seed, status, reading_mode, prompt_system,"
            " prompt_user, prompt_hash, model, limits, estimate_micros, created_at)"
            " VALUES ('R-crashed000', ?, 'cs', 'cs-reader', 1, 1, '{}', 1, 'running',"
            " 'abstract', 's', 'u', 'h', 'm', '{}', 0, '2026-09-10T12:00:00Z')",
            (PAPER,),
        )

    create_app(api.cfg, model_client=api.model, clock=api.clock, fetch=api.fetch)

    status = api.rows("SELECT status, failure FROM runs")[0]
    assert tuple(status) == ("failed", "interrupted_by_restart")
    assert api.rows("SELECT COUNT(*) FROM papers")[0][0] == 1
    assert api.rows("SELECT COUNT(*) FROM spec_revisions")[0][0] == 1


def test_evolution_is_toggled_by_the_operator_and_per_island_by_the_island(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    spec = api.http.get("/api/v1/swarm/spec", headers=cs).json()["spec"]
    assert spec["evolution"] == {} and spec["islands"][0]["evolve"] is True

    refused = api.http.post(
        "/api/v1/swarm/evolution", json={"fields": {"enabled": False}}, headers=cs
    )
    assert refused.status_code == 403
    off = api.http.post(
        "/api/v1/swarm/evolution",
        json={"fields": {"enabled": False}},
        headers=operator,
    ).json()
    assert off["changes"] == [
        {
            "kind": "evolution",
            "id": "evolution",
            "island_id": None,
            "fields": ["enabled"],
        }
    ]
    forced = api.http.post(
        "/api/v1/swarm/evolve", json={"force": True}, headers=operator
    ).json()
    assert forced["generations"] == []

    own = api.http.post(
        "/api/v1/islands/cs", json={"fields": {"evolve": False}}, headers=cs
    )
    assert own.status_code == 200
    island = api.http.get("/api/v1/islands/cs", headers=cs).json()
    assert island["island"]["evolve"] is False and island["evolution"] == []
    evolve = api.http.post("/api/v1/swarm/evolve", json={}, headers=cs)
    assert evolve.status_code == 403


def test_finished_runs_evolve_an_island_and_the_page_lists_each_decision(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    api.feeds["cs.AI"] = feed(entry("2609.00001"), entry("2609.00002"))
    api.http.post(
        "/api/v1/swarm/evolution",
        json={"fields": {"runs_threshold": 2}},
        headers=operator,
    )
    _ingest(api, operator)
    for _ in range(2):
        api.model.script = [reply(call("submit_reading", reading()))]
        advanced = api.http.post("/api/v1/swarm/advance", json={}, headers=operator)
        assert len(advanced.json()["started"]) == 1

    island = api.http.get("/api/v1/islands/cs", headers=cs).json()

    steps = {step["genome_id"]: step for step in island["evolution"]}
    assert (steps["cs-reader"]["decision"], steps["cs-reader"]["generation"]) == (
        "retained",
        1,
    )
    assert steps["cs-gen1"]["decision"] == "created" and steps["cs-gen1"]["reason"]
    addresses = [agent["address"] for agent in island["agents"]]
    assert addresses == ["cs-reader@cs", "cs-gen1@cs"]
    child = api.http.get("/api/v1/agents/cs-gen1", headers=cs).json()["agent"]
    assert child["lineage"]["origin"] == "mutation"
    assert (child["parent_id"], child["generation"]) == ("cs-reader", 1)


def test_the_island_switches_are_flipped_one_at_a_time_by_the_islands_own_session(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    island = api.http.get("/api/v1/islands/cs", headers=cs).json()
    assert (island["evolution_enabled"], island["mutation_enabled"]) == (True, True)
    assert island["swarm_evolution_enabled"] is True

    flipped = api.http.post(
        "/api/v1/islands/cs/settings", json={"mutation_enabled": False}, headers=cs
    )
    assert flipped.status_code == 200 and flipped.json()["applied"] is True
    island = api.http.get("/api/v1/islands/cs", headers=cs).json()
    assert (island["evolution_enabled"], island["mutation_enabled"]) == (True, False)
    api.http.post(
        "/api/v1/islands/cs/settings", json={"evolution_enabled": False}, headers=cs
    )
    island = api.http.get("/api/v1/islands/cs", headers=cs).json()
    assert (island["evolution_enabled"], island["mutation_enabled"]) == (False, False)
    # A flip is a spec revision like any other edit, so it can be undone.
    log = api.http.get("/api/v1/swarm/revisions", headers=cs).json()["revisions"]
    assert [item["changes"][0]["fields"] for item in log[:2]] == [
        ["evolve"],
        ["mutate"],
    ]

    for path, body, status in (
        ("/api/v1/islands/quant/settings", {"evolution_enabled": False}, 403),
        ("/api/v1/islands/nowhere/settings", {"evolution_enabled": False}, 404),
        ("/api/v1/islands/cs/settings", {}, 422),
        ("/api/v1/islands/cs/settings", {"evolution_enabled": "sometimes"}, 422),
    ):
        refused = api.http.post(path, json=body, headers=cs)
        assert refused.status_code == status, (path, body)
    quant = api.http.get("/api/v1/islands/quant", headers=cs).json()
    assert quant["evolution_enabled"] is True
