"""The views the pages read: storm, island, agent, paper and run.

Each view is assembled from stored rows at request time. A group of rows is a
plain list; a group whose query fails is named in the view's ``unavailable``
list, so a failed query never looks like "nothing here". Cost stands beside
activity in every view and is always summed from receipts.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from research_agent.beta.budget import BudgetState
from research_agent.beta.costs import attach_cost_summary, receipts_for
from research_agent.beta.db import Json, loads
from research_agent.beta.errors import NotFound
from research_agent.beta.evolution import build_generation_activity
from research_agent.beta.feedback import feedback_rows
from research_agent.beta.islands import island_state
from research_agent.beta.papers import get_paper, load_passages, paper_json
from research_agent.beta.runs import agent_address
from research_agent.beta.spec import (
    evolution_of,
    find_genome,
    find_island,
    genome_versions,
)

#: How many papers and runs an island's page lists, newest first; the island's
#: counts say how many there are in all.
ISLAND_WINDOW = 30

_RUN_BRIEF = (
    "SELECT r.id, r.paper_id, p.title AS paper_title, r.island_id, r.genome_id,"
    " r.genome_version, r.status, r.reading_mode, r.failure, r.created_at, r.finished_at,"
    " (SELECT COALESCE(SUM(c.amount_micros), 0) FROM cost_receipts c WHERE c.run_id = r.id)"
    " AS cost_micros,"
    " (SELECT COUNT(*) FROM run_events e WHERE e.run_id = r.id) AS event_count,"
    " (SELECT COUNT(*) FROM run_events e WHERE e.run_id = r.id AND e.kind = 'tool_call')"
    " AS tool_call_count"
    " FROM runs r JOIN papers p ON p.id = r.paper_id"
)
_READING = (
    "SELECT d.id, d.run_id, d.paper_id, p.title AS paper_title, d.island_id, d.genome_id,"
    " d.genome_version, d.summary, d.thesis_quote, d.thesis_char_start, d.thesis_char_end,"
    " d.claims, d.objections, d.related_papers, d.idea_seeds,"
    " d.created_at FROM readings d JOIN papers p ON p.id = d.paper_id"
)


class Groups:
    """Collects a view's groups of rows and names the ones that could not be read."""

    def __init__(self) -> None:
        self.unavailable: list[str] = []

    def rows(self, name: str, build: Callable[[], Sequence[Json]]) -> list[Json]:
        try:
            return list(build())
        except sqlite3.Error:
            self.unavailable.append(name)
            return []


def run_briefs(
    db: sqlite3.Connection, where: str, params: Sequence[Any], limit: int
) -> list[Json]:
    rows = db.execute(
        f"{_RUN_BRIEF} WHERE {where} ORDER BY r.created_at DESC, r.id LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _reading_json(row: sqlite3.Row) -> Json:
    reading = dict(row)
    for name in ("claims", "objections", "related_papers", "idea_seeds"):
        reading[name] = loads(reading[name])
    return reading


def readings(
    db: sqlite3.Connection, where: str, params: Sequence[Any], limit: int
) -> list[Json]:
    rows = db.execute(
        f"{_READING} WHERE {where} ORDER BY d.created_at DESC, d.id LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [_reading_json(row) for row in rows]


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _display(kind: str, payload: Mapping[str, Any]) -> Json:
    """How a step reads on the replay: a line, and what went in and came out.

    These are a rendering of the stored payload for the page; the payload
    itself stays the record.
    """
    shown: Json = {
        "body": kind,
        "tool": None,
        "model": None,
        "input": None,
        "output": None,
    }
    if kind == "run_started":
        genome = payload.get("genome", {})
        shown["body"] = (
            f"Agent {genome.get('id')} version {genome.get('version')} starts"
            f" reading paper {payload.get('paper_id')}"
        )
    elif kind == "prompt":
        shown["body"] = "Prompt sent to the model"
        shown["input"] = f"{payload['system']}\n\n{payload['user']}"
    elif kind == "model_call":
        shown["model"] = payload.get("model")
        shown["input"] = payload.get("harness_notice")
        if "error" in payload:
            shown["body"] = f"Model call {payload['index']} failed: {payload['error']}"
        else:
            shown["body"] = (
                f"Model call {payload['index']}: {payload['input_tokens']} tokens in,"
                f" {payload['output_tokens']} out"
            )
            asked = ", ".join(call["name"] for call in payload["tool_calls"])
            shown["output"] = payload["text"] or (f"asked for {asked}" if asked else "")
    elif kind == "tool_call":
        shown["tool"] = payload["name"]
        shown["input"] = _text(payload["arguments"])
        if payload["allowed"]:
            shown["body"] = f"Tool {payload['name']}"
            shown["output"] = _text(payload["result"])
        else:
            shown["body"] = f"Tool {payload['name']} refused: {payload['error']}"
    elif kind == "paper_read":
        shown["body"] = (
            f"Read passage {payload['passage_id']} ({payload['characters']} characters)"
        )
    elif kind == "note":
        shown["body"] = payload["text"]
        shown["input"] = payload.get("quote")
    elif kind == "reading_submitted":
        shown["body"] = "Final reading submitted"
    elif kind == "run_completed":
        shown["body"] = "Run completed"
    elif kind == "run_failed":
        shown["body"] = f"Run failed: {payload.get('reason')}"
    return shown


def _event_json(row: sqlite3.Row, amounts: Mapping[str, int]) -> Json:
    locator = None
    if row["loc_paper_id"] is not None:
        locator = {
            "paper_id": row["loc_paper_id"],
            "source_kind": row["loc_source_kind"],
            # The section a viewer opens is the stored passage.
            "section": row["loc_passage_id"],
            "passage_id": row["loc_passage_id"],
            "page": row["loc_page"],
            "char_start": row["loc_char_start"],
            "char_end": row["loc_char_end"],
            "quote": row["loc_snippet"],
        }
    payload = loads(row["payload"])
    return {
        "id": row["seq"],
        "seq": row["seq"],
        "run_id": row["run_id"],
        "kind": row["kind"],
        "created_at": row["created_at"],
        **_display(row["kind"], payload),
        "cost_micros": amounts.get(row["receipt_id"], 0),
        "receipt_id": row["receipt_id"],
        "cost_state": row["cost_state"],
        "locator": locator,
        "payload": payload,
    }


def trace_authority_view(events: Sequence[Mapping[str, Any]]) -> Json:
    """What the run did, counted from harness events and nothing the agent wrote."""
    tool_calls = [event["payload"] for event in events if event["kind"] == "tool_call"]
    return {
        "model_calls": sum(event["kind"] == "model_call" for event in events),
        "tool_calls": [call["name"] for call in tool_calls if call["allowed"]],
        "refused_tool_calls": [
            {"name": call["name"], "error": call["error"]}
            for call in tool_calls
            if not call["allowed"]
        ],
        "passages_read": [
            event["payload"]["passage_id"]
            for event in events
            if event["kind"] == "paper_read"
        ],
        "notes": sum(event["kind"] == "note" for event in events),
        "started_at": events[0]["created_at"] if events else None,
        "ended_at": events[-1]["created_at"] if events else None,
    }


def _paper_view(db: sqlite3.Connection, paper: sqlite3.Row) -> Json:
    """A paper row with its stored text as sections, in reading order."""
    return {
        **paper_json(paper),
        "sections": [
            {
                "id": passage["id"],
                "title": passage.get("title") or str(passage["kind"]).capitalize(),
                "kind": passage["kind"],
                "page": passage["page"],
                "char_start": passage["char_start"],
                "char_end": passage["char_end"],
                "text": passage["text"],
            }
            for passage in load_passages(db, paper["id"])
        ],
    }


def build_run_projection(
    db: sqlite3.Connection, run_id: str, after_seq: int = 0
) -> Json:
    """One run with its replay: every event in sequence order.

    ``after_seq`` returns only later events, so a page watching a live run
    asks for what it has not seen. Conduct is always counted over the whole
    trace.
    """
    run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise NotFound(f"no run {run_id}")
    amounts = dict(
        db.execute(
            "SELECT id, amount_micros FROM cost_receipts WHERE run_id = ?", (run_id,)
        ).fetchall()
    )
    rows = db.execute(
        "SELECT * FROM run_events WHERE run_id = ? ORDER BY seq", (run_id,)
    ).fetchall()
    events = [_event_json(row, amounts) for row in rows]
    found = readings(db, "d.run_id = ?", (run_id,), 1)
    feedback = feedback_rows(db, "run_id", run_id)
    cost = attach_cost_summary(db, "run_id", run_id)
    return {
        "run": {
            "id": run["id"],
            "paper_id": run["paper_id"],
            "island_id": run["island_id"],
            "genome_id": run["genome_id"],
            "genome_version": run["genome_version"],
            "agent": agent_address(run["genome_id"], run["island_id"]),
            "spec_revision": run["spec_revision"],
            "status": run["status"],
            "failure": run["failure"],
            "reading_mode": run["reading_mode"],
            "model": run["model"],
            "seed": run["seed"],
            "limits": loads(run["limits"]),
            "estimate_micros": run["estimate_micros"],
            "prompt": {
                "system": run["prompt_system"],
                "user": run["prompt_user"],
                "hash": run["prompt_hash"],
            },
            "created_at": run["created_at"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "cost_micros": sum(amounts.values()),
        },
        # The genome exactly as this run used it, whatever has been edited since.
        "genome": {**loads(run["genome"]), "island_id": run["island_id"]},
        "paper": _paper_view(db, get_paper(db, run["paper_id"])),
        "events": [event for event in events if event["seq"] > after_seq],
        "last_seq": events[-1]["seq"] if events else 0,
        "conduct": trace_authority_view(events),
        "reading": found[0] if found else None,
        "feedback": feedback["items"],
        "feedback_totals": feedback["totals"],
        "cost_micros": sum(amounts.values()),
        "cost": cost,
        "receipts": receipts_for(db, "run_id", run_id),
    }


def build_paper_projection(db: sqlite3.Connection, paper_id: str) -> Json:
    """One paper and its cascade: islands, readings, runs, feedback, cost."""
    paper = get_paper(db, paper_id)
    groups = Groups()

    def assignments() -> list[Json]:
        rows = db.execute(
            "SELECT paper_id, island_id, reasons, created_at FROM assignments"
            " WHERE paper_id = ? ORDER BY created_at, island_id",
            (paper_id,),
        ).fetchall()
        return [
            {
                "paper_id": row["paper_id"],
                "island_id": row["island_id"],
                "reasons": loads(row["reasons"]),
                "reason": ", ".join(loads(row["reasons"])),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def cost_by_island() -> list[Json]:
        rows = db.execute(
            "SELECT island_id, SUM(amount_micros) AS cost_micros FROM cost_receipts"
            " WHERE paper_id = ? AND island_id IS NOT NULL GROUP BY island_id",
            (paper_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    feedback = groups.rows(
        "feedback", lambda: [feedback_rows(db, "paper_id", paper_id)]
    )
    cost = attach_cost_summary(db, "paper_id", paper_id)
    return {
        "paper": _paper_view(db, paper),
        "assignments": groups.rows("assignments", assignments),
        "readings": groups.rows(
            "readings", lambda: readings(db, "d.paper_id = ?", (paper_id,), 50)
        ),
        "runs": groups.rows(
            "runs", lambda: run_briefs(db, "r.paper_id = ?", (paper_id,), 100)
        ),
        "feedback": feedback[0]["items"] if feedback else [],
        "feedback_totals": feedback[0]["totals"] if feedback else None,
        "cost_micros": cost.get("settled_micros"),
        "cost_by_island": {
            row["island_id"]: row["cost_micros"]
            for row in groups.rows("cost_by_island", cost_by_island)
        },
        "cost": cost,
        "unavailable": groups.unavailable,
    }


def _agent_stats(db: sqlite3.Connection) -> dict[str, Json]:
    stats: dict[str, Json] = {}
    for row in db.execute(
        "SELECT r.genome_id, COUNT(*) AS runs, SUM(r.status = 'completed') AS completed,"
        " SUM(r.status = 'failed') AS failed,"
        " COALESCE(SUM((SELECT SUM(c.amount_micros) FROM cost_receipts c"
        " WHERE c.run_id = r.id)), 0) AS cost_micros,"
        " COALESCE(SUM((SELECT COUNT(*) FROM feedback f WHERE f.run_id = r.id"
        " AND f.signal = 'accept')), 0) AS accepted,"
        " MAX(r.created_at) AS last_run_at"
        " FROM runs r GROUP BY r.genome_id"
    ):
        stats[str(row["genome_id"])] = dict(row)
    return stats


def _current_run(db: sqlite3.Connection, genome_id: str) -> Json | None:
    """The run an agent is on now, with the step it last recorded."""
    row = db.execute(
        "SELECT r.id AS run_id, r.paper_id, p.title AS paper_title, r.status, r.started_at,"
        " (SELECT e.kind FROM run_events e WHERE e.run_id = r.id ORDER BY e.seq DESC LIMIT 1)"
        " AS last_event_kind,"
        " (SELECT COALESCE(MAX(e.seq), 0) FROM run_events e WHERE e.run_id = r.id) AS last_seq"
        " FROM runs r JOIN papers p ON p.id = r.paper_id"
        " WHERE r.genome_id = ? AND r.status IN ('queued', 'running')"
        " ORDER BY r.created_at LIMIT 1",
        (genome_id,),
    ).fetchone()
    return None if row is None else dict(row)


def agent_briefs(
    db: sqlite3.Connection,
    spec: Mapping[str, Any],
    budget: BudgetState,
    island_id: str | None = None,
) -> list[Json]:
    """Every agent as a row: its genome, where it sits, what it is doing and has done.

    An agent is a genome seated on an island. Its state is ``working`` while
    it has a run open, ``retired`` when switched off, ``blocked`` with the
    reason when its island may not start work, and ``idle`` otherwise.
    """
    stats = _agent_stats(db)
    empty = {
        "runs": 0,
        "completed": 0,
        "failed": 0,
        "cost_micros": 0,
        "accepted": 0,
        "last_run_at": None,
    }
    agents: list[Json] = []
    for island in spec["islands"]:
        if island_id is not None and island["id"] != island_id:
            continue
        for genome in island["genomes"]:
            current = _current_run(db, genome["id"])
            if not genome["active"]:
                state, reason = "retired", None
            else:
                state, reason = island_state(island, 1 if current else 0, budget)
            numbers = stats.get(genome["id"], empty)
            parent = genome["lineage"].get("parent") or {}
            agents.append(
                {
                    **genome,
                    "address": agent_address(genome["id"], island["id"]),
                    "island_id": island["id"],
                    "state": state,
                    "blocked_reason": reason,
                    "parent_id": parent.get("genome_id"),
                    "generation": genome["lineage"].get("generation", 0),
                    "current": current,
                    "stats": numbers,
                    "cost_micros": numbers["cost_micros"],
                }
            )
    return agents


def build_agent_projection(
    db: sqlite3.Connection, spec: Mapping[str, Any], genome_id: str, budget: BudgetState
) -> Json:
    """One agent's page: its genome, what it is reading now and what it has read."""
    island, _ = find_genome(spec, genome_id)
    groups = Groups()
    cost = db.execute(
        "SELECT COALESCE(SUM(CASE WHEN c.settlement = 'settled' THEN c.amount_micros END), 0),"
        " COALESCE(SUM(c.settlement = 'unsettled'), 0), COUNT(*)"
        " FROM cost_receipts c JOIN runs r ON r.id = c.run_id WHERE r.genome_id = ?",
        (genome_id,),
    ).fetchone()

    def feedback() -> list[Json]:
        rows = db.execute(
            "SELECT f.id, f.target_kind, f.target_id, f.signal, f.note, f.created_at, f.run_id"
            " FROM feedback f JOIN runs r ON r.id = f.run_id WHERE r.genome_id = ?"
            " ORDER BY f.created_at DESC, f.id LIMIT 100",
            (genome_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    briefs = agent_briefs(db, spec, budget, island["id"])
    return {
        "agent": next(item for item in briefs if item["id"] == genome_id),
        "versions": groups.rows("versions", lambda: genome_versions(db, genome_id)),
        "runs": groups.rows(
            "runs", lambda: run_briefs(db, "r.genome_id = ?", (genome_id,), 100)
        ),
        "readings": groups.rows(
            "readings", lambda: readings(db, "d.genome_id = ?", (genome_id,), 50)
        ),
        "feedback": groups.rows("feedback", feedback),
        "cost_micros": int(cost[0]),
        "cost": {
            "state": "available",
            "settled_micros": int(cost[0]),
            "unsettled_count": int(cost[1]),
            "receipt_count": int(cost[2]),
        },
        "unavailable": groups.unavailable,
    }


def island_brief(
    db: sqlite3.Connection, island: Mapping[str, Any], budget: BudgetState
) -> Json:
    """One island as a list or storm row: identity, state, counts, cost and share."""
    island_id = str(island["id"])
    counts = db.execute(
        "SELECT (SELECT COUNT(*) FROM assignments WHERE island_id = :i),"
        " (SELECT COUNT(*) FROM runs WHERE island_id = :i),"
        " (SELECT COUNT(*) FROM runs WHERE island_id = :i AND status IN ('queued', 'running')),"
        " (SELECT COUNT(*) FROM readings WHERE island_id = :i)",
        {"i": island_id},
    ).fetchone()
    state, reason = island_state(island, int(counts[2]), budget)
    cost = attach_cost_summary(db, "island_id", island_id)
    share = budget.islands.get(island_id)
    return {
        "id": island_id,
        "name": island["name"],
        "focus": island["focus"],
        "priority": island["priority"],
        "reading_mode": island["reading_mode"],
        "paused": island["paused"],
        "archived": island["archived"],
        "evolve": island["evolve"],
        "mutate": island["mutate"],
        "state": state,
        "blocked_reason": reason,
        "paper_count": counts[0],
        "run_count": counts[1],
        "active_run_count": counts[2],
        "reading_count": counts[3],
        "agent_count": sum(1 for genome in island["genomes"] if genome["active"]),
        "cost_micros": cost.get("settled_micros"),
        "month_cost_micros": share.month_micros if share else None,
        "budget_share": share.share if share else None,
        # A blocked island starts nothing, whatever room its share has left.
        "runs_remaining_today": 0
        if state == "blocked"
        else budget.runs_remaining_today(island_id),
        "cost": cost,
    }


def _evolution_steps(db: sqlite3.Connection, island_id: str) -> list[Json]:
    """An island's evolution as one flat list: a row per decision, newest first."""
    steps: list[Json] = []
    for generation in build_generation_activity(db, island_id):
        common = {
            "generation": generation["number"],
            "status": generation["status"],
            "revision": generation["revision"],
            "created_at": generation["created_at"],
        }
        if generation["status"] == "skipped":
            reason = generation["reason"]
            steps.append(
                {**common, "genome_id": None, "decision": "skipped", "reason": reason}
            )
        steps.extend({**common, **decision} for decision in generation["decisions"])
    return steps


def build_island_projection(
    db: sqlite3.Connection, spec: Mapping[str, Any], island_id: str, budget: BudgetState
) -> Json:
    """One island's page: agents, queue, papers, runs, readings, feedback, evolution."""
    island = find_island(spec, island_id)
    groups = Groups()

    def papers(queue_only: bool) -> list[Json]:
        waiting = (
            " AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.paper_id = p.id"
            " AND r.island_id = a.island_id AND r.status != 'failed')"
            if queue_only
            else ""
        )
        rows = db.execute(
            "SELECT p.id, p.title, p.abstract AS summary, p.abs_url AS url, p.pdf_url,"
            " p.primary_category, p.published_at, p.text_status, p.fetched_at,"
            " a.reasons, a.created_at AS assigned_at,"
            " (SELECT COUNT(*) FROM runs r WHERE r.paper_id = p.id"
            " AND r.island_id = a.island_id) AS run_count,"
            " (SELECT COALESCE(SUM(c.amount_micros), 0) FROM cost_receipts c"
            " WHERE c.paper_id = p.id AND c.island_id = a.island_id) AS cost_micros"
            " FROM assignments a JOIN papers p ON p.id = a.paper_id"
            f" WHERE a.island_id = ?{waiting} ORDER BY a.created_at DESC, p.id"
            f" LIMIT {ISLAND_WINDOW}",
            (island_id,),
        ).fetchall()
        return [{**dict(row), "reasons": loads(row["reasons"])} for row in rows]

    def edits() -> list[Json]:
        rows = db.execute(
            "SELECT revision, actor, note, restored_from, changes, created_at"
            " FROM spec_revisions ORDER BY revision DESC LIMIT 200"
        ).fetchall()
        items = []
        for row in rows:
            touched = [c for c in loads(row["changes"]) if c["island_id"] == island_id]
            if touched:
                items.append({**dict(row), "changes": touched})
        return items[:20]

    brief = island_brief(db, island, budget)
    feedback = groups.rows(
        "feedback", lambda: [feedback_rows(db, "island_id", island_id)]
    )
    return {
        "island": brief,
        "cost_micros": brief["cost_micros"],
        "month_cost_micros": brief["month_cost_micros"],
        "budget_share": brief["budget_share"],
        "runs_remaining_today": brief["runs_remaining_today"],
        # The island's own switches. Evolution also needs the swarm's switch on.
        "evolution_enabled": island["evolve"],
        "mutation_enabled": island["mutate"],
        "swarm_evolution_enabled": evolution_of(spec).enabled,
        "categories": island["categories"],
        "keywords": island["keywords"],
        "agents": groups.rows(
            "agents", lambda: agent_briefs(db, spec, budget, island_id)
        ),
        "queue": groups.rows("queue", lambda: papers(queue_only=True)),
        "papers": groups.rows("papers", lambda: papers(queue_only=False)),
        "runs": groups.rows(
            "runs",
            lambda: run_briefs(db, "r.island_id = ?", (island_id,), ISLAND_WINDOW),
        ),
        "readings": groups.rows(
            "readings", lambda: readings(db, "d.island_id = ?", (island_id,), 50)
        ),
        "feedback": feedback[0]["items"] if feedback else [],
        "feedback_totals": feedback[0]["totals"] if feedback else None,
        "evolution": groups.rows("evolution", lambda: _evolution_steps(db, island_id)),
        "edits": groups.rows("edits", edits),
        "unavailable": groups.unavailable,
    }


def build_storm(
    db: sqlite3.Connection, spec: Mapping[str, Any], budget: BudgetState
) -> Json:
    """The public view: islands at a glance, agents, the newest papers and runs."""
    totals = db.execute(
        "SELECT (SELECT COUNT(*) FROM papers), (SELECT COUNT(*) FROM runs),"
        " (SELECT COUNT(*) FROM readings), (SELECT COUNT(*) FROM feedback),"
        " (SELECT COALESCE(SUM(amount_micros), 0) FROM cost_receipts"
        " WHERE settlement = 'settled')"
    ).fetchone()
    groups = Groups()

    def recent_papers() -> list[Json]:
        rows = db.execute(
            "SELECT p.id, p.title, p.primary_category, p.published_at, p.first_seen_at,"
            " (SELECT group_concat(a.island_id) FROM assignments a WHERE a.paper_id = p.id)"
            " AS islands FROM papers p ORDER BY p.first_seen_at DESC, p.id LIMIT 20"
        ).fetchall()
        return [
            {
                **dict(row),
                "islands": row["islands"].split(",") if row["islands"] else [],
            }
            for row in rows
        ]

    # The public view names agents and what they are reading, never a prompt.
    shown = ("id", "address", "island_id", "state", "blocked_reason", "current")
    return {
        "islands": [
            island_brief(db, island, budget)
            for island in spec["islands"]
            if not island["archived"]
        ],
        "papers": totals[0],
        "runs": totals[1],
        "readings": totals[2],
        "feedback": totals[3],
        "cost_micros": totals[4],
        "agents": groups.rows(
            "agents",
            lambda: [
                {key: agent[key] for key in shown}
                for agent in agent_briefs(db, spec, budget)
                if agent["active"]
            ],
        ),
        "recent_papers": groups.rows("recent_papers", recent_papers),
        "recent_runs": groups.rows(
            "recent_runs", lambda: run_briefs(db, "1 = 1", (), 20)
        ),
        "unavailable": groups.unavailable,
    }
