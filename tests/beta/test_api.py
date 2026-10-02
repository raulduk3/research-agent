"""The HTTP surface: envelope, sessions, edit scope and the front-end routes."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from research_agent.beta.app import create_app
from research_agent.beta.db import connect
from research_agent.beta.ingest import SourceFailed
from tests.beta.helpers import (
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
                fetch=self._fetch,
                sleep=lambda _: None,
            )
        )
        # The test client keeps cookies; drop them so each call states its own auth.
        self.http.cookies.clear()

    def _fetch(self, category: str, limit: int) -> str:
        if category not in self.feeds:
            raise SourceFailed(f"no answer for {category}")
        return self.feeds[category]

    def bearer(self, credential: str) -> dict[str, str]:
        reply_ = self.http.post("/api/v1/login", json={"credential": credential})
        self.http.cookies.clear()
        assert reply_.status_code == 200, reply_.text
        return {"Authorization": f"Bearer {reply_.json()['data']['token']}"}

    def rows(self, sql: str) -> list[sqlite3.Row]:
        with connect(self.cfg.database) as db:
            return db.execute(sql).fetchall()


@pytest.fixture
def api(tmp_path: Path) -> Api:
    return Api(tmp_path)


@pytest.fixture
def cs(api: Api) -> dict[str, str]:
    return api.bearer("cs-pass")


@pytest.fixture
def operator(api: Api) -> dict[str, str]:
    return {"Authorization": "Bearer operator-pass"}


def _ingest(api: Api, operator: dict[str, str], **body: Any) -> dict[str, Any]:
    reply_ = api.http.post(
        "/api/v1/ingest/arxiv",
        json={"category": "cs.AI", "advance": False, **body},
        headers=operator,
    )
    assert reply_.status_code == 200, reply_.text
    return reply_.json()["data"]


def test_health_and_the_public_storm_need_no_session(api: Api) -> None:
    health = api.http.get("/health")
    assert health.json() == {
        "status": "ok",
        "schema_version": 1,
        "provider_configured": True,
    }

    storm = api.http.get("/api/v1/public/storm")

    assert storm.status_code == 200 and storm.json()["contract"] == "1"
    data = storm.json()["data"]
    assert [island["id"] for island in data["islands"]] == [
        "cs",
        "quant",
        "bio",
        "general",
    ]
    assert data["budget"]["monthly_budget_micros"] == 50_000_000
    assert data["agents"]["items"][0]["address"] == "cs-reader@cs"
    # The public view shows activity, never a prompt or a session token.
    assert "prompt" not in storm.text and "csrf_token" not in data


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
            "contract": "1",
            "error": {
                "code": "unauthenticated",
                "message": "sign in to an island first",
                "field": None,
            },
        }


def test_login_binds_a_credential_to_its_island_and_stores_nothing(api: Api) -> None:
    wrong = api.http.post("/api/v1/login", json={"credential": "not-a-password"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthenticated"

    opened = api.http.post("/api/v1/login", json={"credential": "quant-pass"})

    data = opened.json()["data"]
    assert (data["role"], data["island"]) == ("island", "quant")
    assert data["csrf_token"] and data["token"].startswith("v1.")
    assert "HttpOnly" in opened.headers["set-cookie"]
    assert data["budget"]["island"]["island_id"] == "quant"
    # No session row, no transcript row: the only stored rows are the seeded spec.
    counts = api.rows(
        "SELECT (SELECT COUNT(*) FROM spec_revisions), (SELECT COUNT(*) FROM feedback),"
        " (SELECT COUNT(*) FROM cost_receipts), (SELECT COUNT(*) FROM idempotency)"
    )[0]
    assert tuple(counts) == (1, 0, 0, 0)


def test_a_cookie_session_must_prove_its_posts_with_the_csrf_token(api: Api) -> None:
    opened = api.http.post("/api/v1/login", json={"credential": "cs-pass"})
    csrf = opened.json()["data"]["csrf_token"]
    # The cookie is marked Secure; over the test transport it is sent by hand.
    cookie = {"Cookie": f"swarm_session={opened.json()['data']['token']}"}
    api.http.cookies.clear()
    body = {"message": "what is happening on the island?"}

    assert api.http.get("/api/v1/session", headers=cookie).status_code == 200
    bare = api.http.post("/api/v1/chat", json=body, headers=cookie)
    assert bare.status_code == 403
    assert bare.json()["error"]["field"] == "X-CSRF-Token"
    proven = api.http.post(
        "/api/v1/chat", json=body, headers={**cookie, "X-CSRF-Token": csrf}
    )
    assert proven.status_code == 200


def test_a_session_expires_and_a_tampered_token_is_refused(
    api: Api, cs: dict[str, str]
) -> None:
    forged = {"Authorization": cs["Authorization"][:-1] + "0"}
    if forged == cs:
        forged = {"Authorization": cs["Authorization"][:-1] + "1"}
    assert api.http.get("/api/v1/session", headers=forged).status_code == 401

    assert api.http.get("/api/v1/session", headers=cs).status_code == 200
    api.clock.advance(days=31)
    expired = api.http.get("/api/v1/session", headers=cs)
    assert expired.status_code == 401
    assert expired.json()["error"]["message"] == "the session has expired"


def test_cors_admits_the_configured_origin_only(api: Api) -> None:
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,x-csrf-token",
    }

    allowed = api.http.options("/api/v1/chat", headers={"Origin": ORIGIN, **preflight})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert allowed.headers["access-control-allow-credentials"] == "true"

    other = api.http.options(
        "/api/v1/chat", headers={"Origin": "https://elsewhere.example", **preflight}
    )
    assert "access-control-allow-origin" not in other.headers


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
    run = api.http.get(f"/api/v1/runs/{started['run_id']}", headers=cs).json()["data"]
    assert run["run"]["status"] == "completed"
    assert run["budget"]["month_to_date_micros"] == 4_000


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
    run_id = accepted.json()["data"]["run_id"]
    # The same request sent again answers with the same run and starts nothing.
    again = api.http.post(
        "/api/v1/runs", json={"paper_id": PAPER}, headers={**cs, **key}
    )
    assert again.json()["data"]["run_id"] == run_id
    assert api.rows("SELECT COUNT(*) FROM runs")[0][0] == 1

    view = api.http.get(f"/api/v1/runs/{run_id}", headers=cs).json()["data"]
    assert view["run"]["status"] == "completed"
    assert [event["seq"] for event in view["events"]] == list(range(1, 10))
    assert view["events"][1]["kind"] == "prompt"
    assert view["budget"]["island"]["island_id"] == "cs"
    tail = api.http.get(f"/api/v1/runs/{run_id}?after=7", headers=cs).json()["data"]
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
    assert refused.json()["error"]["code"] == "state_conflict"
    assert refused.json()["error"]["message"].startswith("runs_paused:")
    # Browsing stays up while runs are stopped.
    assert api.http.get(f"/api/v1/papers/{PAPER}", headers=cs).status_code == 200


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
    assert refused.json()["error"]["code"] == "unavailable"
    assert api.rows("SELECT COUNT(*) FROM runs")[0][0] == 0
    assert api.rows("SELECT COUNT(*) FROM readings")[0][0] == 0


def test_the_island_paper_and_agent_views_carry_the_cascade_and_the_budget(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    api.model.script = [reply(call("submit_reading", reading()))]
    run_id = _ingest(api, operator, advance=True)["advance"]["started"][0]["run_id"]

    island = api.http.get("/api/v1/islands/cs", headers=cs).json()["data"]
    assert island["island"]["state"] == "idle"
    assert island["papers"]["items"][0]["id"] == PAPER
    assert island["queue"]["state"] == "empty"
    assert island["runs"]["items"][0]["id"] == run_id
    assert island["readings"]["count"] == 1
    assert island["island"]["cost"]["settled_micros"] == 2_000
    assert island["budget"]["island"]["today_micros"] == 2_000

    paper = api.http.get(f"/api/v1/papers/{PAPER}", headers=cs).json()["data"]
    assert list(paper)[:6] == [
        "paper",
        "assignments",
        "readings",
        "runs",
        "feedback",
        "cost",
    ]
    assert paper["assignments"]["items"][0]["reasons"] == [
        "primary_category:cs.AI",
        "focus_keyword:agents",
    ]
    assert paper["readings"]["items"][0]["run_id"] == run_id
    assert paper["runs"]["items"][0]["tool_call_count"] == 1
    assert paper["cost"]["settled_micros"] == 2_000

    listed = api.http.get("/api/v1/agents?island=cs", headers=cs).json()["data"]
    assert [agent["address"] for agent in listed["agents"]] == ["cs-reader@cs"]
    agent = api.http.get("/api/v1/agents/cs-reader@cs", headers=cs).json()["data"]
    assert agent["agent"]["state"] == "idle"
    assert agent["agent"]["stats"]["completed"] == 1
    assert agent["runs"]["items"][0]["id"] == run_id
    assert agent["cost"]["settled_micros"] == 2_000
    assert agent["versions"]["count"] == 1


def test_an_island_session_edits_its_own_agents_and_nothing_beyond(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    edited = api.http.post(
        "/api/v1/agents/cs-reader",
        json={"fields": {"prompt": "Read for flaws."}, "note": "sharper"},
        headers=cs,
    )
    assert edited.status_code == 200
    assert (edited.json()["data"]["revision"], edited.json()["data"]["applied"]) == (
        2,
        True,
    )

    for path, fields in (
        ("/api/v1/agents/quant-reader", {"prompt": "Not mine."}),
        ("/api/v1/islands/quant", {"focus": "Not mine."}),
        ("/api/v1/islands/cs", {"budget_share": 0.9}),
        ("/api/v1/costs/budget", {"monthly_budget_micros": 900_000_000}),
    ):
        refused = api.http.post(path, json={"fields": fields}, headers=cs)
        assert refused.status_code == 403, path
    spec = api.http.get("/api/v1/swarm/spec", headers=cs).json()["data"]
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
    assert raised.json()["data"]["changes"][0]["kind"] == "budget"


def test_an_edit_can_be_previewed_guarded_and_undone(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    preview = api.http.post(
        "/api/v1/agents/cs-reader",
        json={"fields": {"prompt": "Read for flaws."}, "dry_run": True},
        headers=cs,
    ).json()["data"]
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
    assert stale.json()["error"]["message"].startswith("spec_changed:")

    undone = api.http.post(
        "/api/v1/agents/cs-reader/versions/1/restore", json={}, headers=cs
    ).json()["data"]
    assert undone["applied"] and undone["restored_from"] == 1
    agent = api.http.get("/api/v1/agents/cs-reader", headers=cs).json()["data"]
    assert agent["genome"]["version"] == 3
    assert agent["genome"]["lineage"]["origin"] == "restore"
    assert [item["version"] for item in agent["versions"]["items"]] == [1, 2, 3]
    assert agent["versions"]["items"][0]["prompt"] == agent["genome"]["prompt"]

    whole = api.http.post(
        "/api/v1/swarm/revisions/2/restore", json={}, headers=operator
    ).json()["data"]
    assert whole["revision"] == 4
    log = api.http.get("/api/v1/swarm/revisions", headers=cs).json()["data"]
    assert [item["revision"] for item in log["revisions"]] == [4, 3, 2, 1]
    assert (
        api.http.post(
            "/api/v1/swarm/revisions/1/restore", json={}, headers=cs
        ).status_code
        == 403
    )


def test_an_invalid_edit_names_the_field_and_changes_nothing(
    api: Api, cs: dict[str, str]
) -> None:
    refused = api.http.post(
        "/api/v1/agents/cs-reader",
        json={"fields": {"allowed_tools": ["paper_text"]}},
        headers=cs,
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "invalid_request"
    assert refused.json()["error"]["field"] == "islands[0].genomes[0].allowed_tools"
    assert api.rows("SELECT COUNT(*) FROM spec_revisions")[0][0] == 1


def test_feedback_is_accepted_on_every_target_kind_and_scoped_to_the_island(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    api.model.script = [reply(call("submit_reading", reading()))]
    run_id = _ingest(api, operator, advance=True)["advance"]["started"][0]["run_id"]
    reading_id = api.rows("SELECT id FROM readings")[0][0]
    answer = api.http.post(
        "/api/v1/chat", json={"message": "visible traces"}, headers=cs
    ).json()["data"]

    targets = [
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
        assert stored.json()["data"]["feedback"]["island_id"] == "cs"

    for body, status in (
        ({"target_kind": "run", "target_id": "R-missing", "signal": "accept"}, 404),
        (
            {"target_kind": "idea", "target_id": f"{reading_id}#9", "signal": "accept"},
            404,
        ),
        ({"target_kind": "paper", "target_id": PAPER, "signal": "adore"}, 422),
        ({"target_kind": "genome", "target_id": "cs-reader", "signal": "accept"}, 422),
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
        assert (
            api.http.post("/api/v1/feedback", json=body, headers=cs).status_code
            == status
        )

    island = api.http.get("/api/v1/islands/cs", headers=cs).json()["data"]
    assert island["feedback"]["totals"] == {"accept": 5, "pass": 0, "push_away": 0}
    run = api.http.get(f"/api/v1/runs/{run_id}", headers=cs).json()["data"]
    # Paper feedback does not name the run; the run, reading and idea signals do.
    assert run["feedback"]["totals"]["accept"] == 3
    assert run["cost"]["cost_per_useful_feedback_micros"] == 2_000 // 3


def test_chat_answers_through_the_api_with_links_cost_and_budget(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    _ingest(api, operator)

    answer = api.http.post(
        "/api/v1/chat", json={"message": "visible traces"}, headers=cs
    ).json()["data"]

    assert answer["supported"] and answer["links"][0]["href"] == f"/papers/{PAPER}"
    assert answer["cost"]["amount_micros"] == 0
    assert answer["budget"]["paid_chat_allowed"] is True
    unknown = api.http.post(
        "/api/v1/chat", json={"message": "medieval bookbinding"}, headers=cs
    ).json()["data"]
    assert unknown["supported"] is False


def test_the_budget_view_states_every_tracked_figure_and_lever(
    api: Api, cs: dict[str, str]
) -> None:
    state = api.http.get("/api/v1/costs/budget", headers=cs).json()["data"]["state"]

    for figure in (
        "monthly_budget_micros",
        "month_to_date_micros",
        "projected_month_end_micros",
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


def test_an_unknown_route_and_a_malformed_body_wear_the_error_envelope(
    api: Api, cs: dict[str, str]
) -> None:
    missing = api.http.get("/api/v1/nowhere", headers=cs)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    malformed = api.http.post("/api/v1/feedback", json={"signal": "accept"}, headers=cs)
    assert malformed.status_code == 422
    assert malformed.json()["error"] == {
        "code": "invalid_request",
        "message": "Field required",
        "field": "target_kind",
    }


def test_a_restart_closes_open_runs_and_keeps_the_stored_swarm(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    _ingest(api, operator)
    # A queued run with no model answer stays open, as after a crash.
    with connect(api.cfg.database) as db:
        db.execute(
            "INSERT INTO runs(id, paper_id, island_id, genome_id, genome_version,"
            " spec_revision, genome, seed, status, reading_mode, prompt_system,"
            " prompt_user, prompt_hash, model, limits, estimate_micros, created_at)"
            " VALUES ('R-crashed000', ?, 'cs', 'cs-reader', 1, 1, '{}', 1, 'running',"
            " 'abstract', 's', 'u', 'h', 'm', '{}', 0, '2026-09-10T12:00:00Z')",
            (PAPER,),
        )

    create_app(api.cfg, model_client=api.model, clock=api.clock, fetch=api._fetch)

    status = api.rows("SELECT status, failure FROM runs")[0]
    assert tuple(status) == ("failed", "interrupted_by_restart")
    assert api.rows("SELECT COUNT(*) FROM papers")[0][0] == 1
    assert api.rows("SELECT COUNT(*) FROM spec_revisions")[0][0] == 1


def test_evolution_is_toggled_by_the_operator_and_per_island_by_the_island(
    api: Api, cs: dict[str, str], operator: dict[str, str]
) -> None:
    spec = api.http.get("/api/v1/swarm/spec", headers=cs).json()["data"]["spec"]
    assert spec["evolution"] == {} and spec["islands"][0]["evolve"] is True

    refused = api.http.post(
        "/api/v1/swarm/evolution", json={"fields": {"enabled": False}}, headers=cs
    )
    assert refused.status_code == 403
    off = api.http.post(
        "/api/v1/swarm/evolution",
        json={"fields": {"enabled": False}},
        headers=operator,
    ).json()["data"]
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
    ).json()["data"]
    assert forced["generations"] == []

    own = api.http.post(
        "/api/v1/islands/cs", json={"fields": {"evolve": False}}, headers=cs
    )
    assert own.status_code == 200
    island = api.http.get("/api/v1/islands/cs", headers=cs).json()["data"]
    assert island["evolve"] is False and island["generations"]["state"] == "empty"
    assert api.http.post("/api/v1/swarm/evolve", json={}, headers=cs).status_code == 403


def test_finished_runs_and_feedback_evolve_an_island_through_the_api(
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
        assert len(advanced.json()["data"]["started"]) == 1

    island = api.http.get("/api/v1/islands/cs", headers=cs).json()["data"]

    [generation] = island["generations"]["items"]
    assert generation["status"] == "committed"
    addresses = [agent["address"] for agent in island["agents"]["items"]]
    assert addresses == ["cs-reader@cs", "cs-gen1@cs"]
    child = api.http.get("/api/v1/agents/cs-gen1", headers=cs).json()["data"]
    assert child["genome"]["lineage"]["origin"] == "mutation"
    assert child["genome"]["lineage"]["parent"]["genome_id"] == "cs-reader"
