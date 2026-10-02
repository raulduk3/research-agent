"""The views the pages read: storm, island, paper and run.

Each view is assembled from stored rows at request time. A group of rows is
a section that says whether it is ``available``, ``empty`` or
``unavailable``, so a failed query never looks like "nothing here". Cost
stands beside activity in every view and is always summed from receipts.
"""

from __future__ import annotations

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
from research_agent.beta.papers import get_paper, paper_json
from research_agent.beta.runs import agent_address
from research_agent.beta.spec import find_genome, find_island, genome_versions

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
    " d.genome_version, d.summary, d.claims, d.objections, d.related_papers, d.idea_seeds,"
    " d.created_at FROM readings d JOIN papers p ON p.id = d.paper_id"
)


def section(build: Callable[[], Sequence[Json]]) -> Json:
    """Run one group's query and label the result with its availability."""
    try:
        items = list(build())
    except sqlite3.Error:
        return {"state": "unavailable", "count": None, "items": []}
    return {
        "state": "available" if items else "empty",
        "count": len(items),
        "items": items,
    }


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


def _event_json(row: sqlite3.Row) -> Json:
    locator = None
    if row["loc_paper_id"] is not None:
        locator = {
            "paper_id": row["loc_paper_id"],
            "source_kind": row["loc_source_kind"],
            "passage_id": row["loc_passage_id"],
            "page": row["loc_page"],
            "char_start": row["loc_char_start"],
            "char_end": row["loc_char_end"],
            "snippet": row["loc_snippet"],
        }
    return {
        "seq": row["seq"],
        "kind": row["kind"],
        "at": row["created_at"],
        "payload": loads(row["payload"]),
        "receipt_id": row["receipt_id"],
        "cost_state": row["cost_state"],
        "locator": locator,
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
        "started_at": events[0]["at"] if events else None,
        "ended_at": events[-1]["at"] if events else None,
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
    rows = db.execute(
        "SELECT * FROM run_events WHERE run_id = ? ORDER BY seq", (run_id,)
    ).fetchall()
    events = [_event_json(row) for row in rows]
    genome = loads(run["genome"])
    found = readings(db, "d.run_id = ?", (run_id,), 1)
    paper = get_paper(db, run["paper_id"])
    return {
        "run": {
            "id": run["id"],
            "status": run["status"],
            "failure": run["failure"],
            "paper": {"id": paper["id"], "title": paper["title"]},
            "island_id": run["island_id"],
            "genome": {
                "id": run["genome_id"],
                "version": run["genome_version"],
                "spec_revision": run["spec_revision"],
                "reading_strategy": genome["reading_strategy"],
                "model_settings": genome["model_settings"],
                "allowed_tools": genome["allowed_tools"],
                "lineage": genome["lineage"],
            },
            "prompt": {
                "system": run["prompt_system"],
                "user": run["prompt_user"],
                "hash": run["prompt_hash"],
            },
            "model": run["model"],
            "seed": run["seed"],
            "reading_mode": run["reading_mode"],
            "limits": loads(run["limits"]),
            "estimate_micros": run["estimate_micros"],
            "created_at": run["created_at"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
        },
        "events": [event for event in events if event["seq"] > after_seq],
        "last_seq": events[-1]["seq"] if events else 0,
        "conduct": trace_authority_view(events),
        "reading": found[0] if found else None,
        "feedback": feedback_rows(db, "run_id", run_id),
        "cost": attach_cost_summary(db, "run_id", run_id),
        "receipts": receipts_for(db, "run_id", run_id),
    }


def build_paper_projection(db: sqlite3.Connection, paper_id: str) -> Json:
    """One paper and its cascade: islands, readings, runs, feedback, cost."""
    paper = get_paper(db, paper_id)

    def assignments() -> list[Json]:
        rows = db.execute(
            "SELECT island_id, reasons, created_at FROM assignments WHERE paper_id = ?"
            " ORDER BY created_at, island_id",
            (paper_id,),
        ).fetchall()
        return [
            {"island_id": row[0], "reasons": loads(row[1]), "created_at": row[2]}
            for row in rows
        ]

    def feedback() -> list[Json]:
        items: list[Json] = feedback_rows(db, "paper_id", paper_id)["items"]
        return items

    return {
        "paper": paper_json(paper),
        "assignments": section(assignments),
        "readings": section(lambda: readings(db, "d.paper_id = ?", (paper_id,), 50)),
        "runs": section(lambda: run_briefs(db, "r.paper_id = ?", (paper_id,), 100)),
        "feedback": {
            **section(feedback),
            "totals": feedback_rows(db, "paper_id", paper_id)["totals"],
        },
        "cost": attach_cost_summary(db, "paper_id", paper_id),
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
    """Every agent as a row: where it sits, what it is doing, what it has done.

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
            agents.append(
                {
                    "id": genome["id"],
                    "address": agent_address(genome["id"], island["id"]),
                    "island_id": island["id"],
                    "state": state,
                    "blocked_reason": reason,
                    "version": genome["version"],
                    "active": genome["active"],
                    "current": current,
                    "stats": stats.get(genome["id"], empty),
                }
            )
    return agents


def build_agent_projection(
    db: sqlite3.Connection, spec: Mapping[str, Any], genome_id: str, budget: BudgetState
) -> Json:
    """One agent's page: its genome, what it is reading now and what it has read."""
    island, genome = find_genome(spec, genome_id)
    brief = agent_briefs(db, spec, budget, island["id"])
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

    return {
        "agent": next(item for item in brief if item["id"] == genome_id),
        "genome": genome,
        "versions": section(lambda: genome_versions(db, genome_id)),
        "runs": section(lambda: run_briefs(db, "r.genome_id = ?", (genome_id,), 100)),
        "readings": section(lambda: readings(db, "d.genome_id = ?", (genome_id,), 50)),
        "feedback": section(feedback),
        "cost": {
            "state": "available",
            "settled_micros": int(cost[0]),
            "unsettled_count": int(cost[1]),
            "receipt_count": int(cost[2]),
        },
    }


def island_brief(
    db: sqlite3.Connection, island: Mapping[str, Any], budget: BudgetState
) -> Json:
    """One island as a list or storm row: identity, state, counts and cost."""
    island_id = str(island["id"])
    counts = db.execute(
        "SELECT (SELECT COUNT(*) FROM assignments WHERE island_id = :i),"
        " (SELECT COUNT(*) FROM runs WHERE island_id = :i),"
        " (SELECT COUNT(*) FROM runs WHERE island_id = :i AND status IN ('queued', 'running')),"
        " (SELECT COUNT(*) FROM readings WHERE island_id = :i)",
        {"i": island_id},
    ).fetchone()
    state, reason = island_state(island, int(counts[2]), budget)
    return {
        "id": island_id,
        "name": island["name"],
        "focus": island["focus"],
        "priority": island["priority"],
        "reading_mode": island["reading_mode"],
        "paused": island["paused"],
        "archived": island["archived"],
        "state": state,
        "blocked_reason": reason,
        "paper_count": counts[0],
        "run_count": counts[1],
        "active_run_count": counts[2],
        "reading_count": counts[3],
        "agent_count": sum(1 for genome in island["genomes"] if genome["active"]),
        "cost": attach_cost_summary(db, "island_id", island_id),
    }


def build_island_projection(
    db: sqlite3.Connection, spec: Mapping[str, Any], island_id: str, budget: BudgetState
) -> Json:
    """One island's page: queue, papers, agents, runs, readings, feedback, edits."""
    island = find_island(spec, island_id)

    def papers(queue_only: bool) -> list[Json]:
        waiting = (
            " AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.paper_id = p.id"
            " AND r.island_id = a.island_id AND r.status != 'failed')"
            if queue_only
            else ""
        )
        rows = db.execute(
            "SELECT p.id, p.title, p.primary_category, p.published_at, p.text_status,"
            " a.reasons, a.created_at AS assigned_at,"
            " (SELECT COUNT(*) FROM runs r WHERE r.paper_id = p.id"
            " AND r.island_id = a.island_id) AS run_count"
            " FROM assignments a JOIN papers p ON p.id = a.paper_id"
            f" WHERE a.island_id = ?{waiting} ORDER BY a.created_at DESC, p.id LIMIT 100",
            (island_id,),
        ).fetchall()
        return [{**dict(row), "reasons": loads(row["reasons"])} for row in rows]

    def feedback() -> list[Json]:
        items: list[Json] = feedback_rows(db, "island_id", island_id)["items"]
        return items

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

    return {
        "island": island_brief(db, island, budget),
        "categories": island["categories"],
        "keywords": island["keywords"],
        "budget_share": island["budget_share"],
        "queue": section(lambda: papers(queue_only=True)),
        "papers": section(lambda: papers(queue_only=False)),
        "agents": section(lambda: agent_briefs(db, spec, budget, island_id)),
        "runs": section(lambda: run_briefs(db, "r.island_id = ?", (island_id,), 100)),
        "readings": section(lambda: readings(db, "d.island_id = ?", (island_id,), 50)),
        "feedback": {
            **section(feedback),
            "totals": feedback_rows(db, "island_id", island_id)["totals"],
        },
        "evolve": island["evolve"],
        "generations": section(lambda: build_generation_activity(db, island_id)),
        "edits": section(edits),
    }


def build_storm(
    db: sqlite3.Connection, spec: Mapping[str, Any], budget: BudgetState
) -> Json:
    """The public view: islands at a glance and the newest papers and runs."""
    totals = db.execute(
        "SELECT (SELECT COUNT(*) FROM papers), (SELECT COUNT(*) FROM runs),"
        " (SELECT COUNT(*) FROM readings), (SELECT COUNT(*) FROM feedback),"
        " (SELECT COALESCE(SUM(amount_micros), 0) FROM cost_receipts"
        " WHERE settlement = 'settled')"
    ).fetchone()

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

    return {
        "islands": [
            island_brief(db, island, budget)
            for island in spec["islands"]
            if not island["archived"]
        ],
        "totals": {
            "papers": totals[0],
            "runs": totals[1],
            "readings": totals[2],
            "feedback": totals[3],
            "settled_cost_micros": totals[4],
        },
        "recent_papers": section(recent_papers),
        "agents": section(
            lambda: [
                {
                    key: agent[key]
                    for key in (
                        "id",
                        "address",
                        "island_id",
                        "state",
                        "blocked_reason",
                        "current",
                    )
                }
                for agent in agent_briefs(db, spec, budget)
                if agent["active"]
            ]
        ),
        "recent_runs": section(lambda: run_briefs(db, "1 = 1", (), 20)),
    }
