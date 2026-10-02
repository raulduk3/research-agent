"""Likes: the one simple signal a person gives, on any layer but a tool call.

A like names a paper, a run, a reading, one claim or one idea seed of a
reading, or an agent. An island gives at most one like per thing and may
take it back. Likes become an agent's points: every like on its runs,
readings, claims and ideas, plus every like on a paper it voted to keep.
Points are shown to the model that breeds agents and pick the parent of
the next child; nothing else is computed from them.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from research_agent.beta.db import Json, iso, loads, new_id
from research_agent.beta.errors import Invalid, NotFound

TARGET_KINDS = ("paper", "run", "reading", "claim", "idea", "agent")


def _resolve(
    db: sqlite3.Connection, kind: str, target_id: str
) -> tuple[str | None, str | None, str | None]:
    """The paper, run and agent a target traces to; refuses one that is not stored."""
    if kind == "paper":
        row = db.execute("SELECT 1 FROM papers WHERE id = ?", (target_id,)).fetchone()
        return (target_id, None, None) if row else _missing(kind, target_id)
    if kind == "run":
        row = db.execute(
            "SELECT paper_id, genome_id FROM runs WHERE id = ?", (target_id,)
        ).fetchone()
        return (row[0], target_id, row[1]) if row else _missing(kind, target_id)
    if kind == "agent":
        row = db.execute(
            "SELECT 1 FROM runs WHERE genome_id = ? LIMIT 1", (target_id,)
        ).fetchone()
        # An agent that has not run yet is still an agent; the spec is the authority.
        return (None, None, target_id)
    reading_id, _, index = target_id.partition("#")
    row = db.execute(
        "SELECT paper_id, run_id, genome_id, claims, idea_seeds FROM readings WHERE id = ?",
        (reading_id,),
    ).fetchone()
    if row is None:
        return _missing(kind, target_id)
    if kind in ("claim", "idea"):
        items = loads(row["claims"] if kind == "claim" else row["idea_seeds"])
        if not (index.isdigit() and int(index) < len(items)):
            return _missing(kind, target_id)
    return row["paper_id"], row["run_id"], row["genome_id"]


def _missing(kind: str, target_id: str) -> tuple[str | None, str | None, str | None]:
    raise NotFound(f"no {kind} {target_id}")


def toggle_like(
    db: sqlite3.Connection,
    *,
    island_id: str,
    target_kind: str,
    target_id: str,
    now: datetime,
) -> Json:
    """Give the island's like to a thing, or take it back if it is already there."""
    if target_kind not in TARGET_KINDS:
        raise Invalid(f"target_kind is one of {', '.join(TARGET_KINDS)}", "target_kind")
    paper_id, run_id, genome_id = _resolve(db, target_kind, target_id)
    had = db.execute(
        "SELECT id FROM likes WHERE island_id = ? AND target_kind = ? AND target_id = ?",
        (island_id, target_kind, target_id),
    ).fetchone()
    if had:
        db.execute("DELETE FROM likes WHERE id = ?", (had[0],))
        liked = False
    else:
        db.execute(
            "INSERT INTO likes(id, island_id, target_kind, target_id, paper_id, run_id,"
            " genome_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("L"),
                island_id,
                target_kind,
                target_id,
                paper_id,
                run_id,
                genome_id,
                iso(now),
            ),
        )
        liked = True
    count = db.execute(
        "SELECT COUNT(*) FROM likes WHERE target_kind = ? AND target_id = ?",
        (target_kind, target_id),
    ).fetchone()[0]
    return {
        "target_kind": target_kind,
        "target_id": target_id,
        "island_id": island_id,
        "liked": liked,
        "count": int(count),
    }


def likes_where(db: sqlite3.Connection, where: str, params: tuple[str, ...]) -> Json:
    """Likes within a scope as a map ``kind:id`` -> {count, islands}."""
    rows = db.execute(
        f"SELECT target_kind, target_id, island_id FROM likes WHERE {where}"
        " ORDER BY created_at",
        params,
    ).fetchall()
    out: dict[str, Json] = {}
    for row in rows:
        key = f"{row['target_kind']}:{row['target_id']}"
        entry = out.setdefault(key, {"count": 0, "islands": []})
        entry["count"] += 1
        entry["islands"].append(row["island_id"])
    return out


def points_of(db: sqlite3.Connection, genome_id: str) -> int:
    """An agent's points: likes on its work, and on papers it voted to keep."""
    own = db.execute(
        "SELECT COUNT(*) FROM likes WHERE genome_id = ?", (genome_id,)
    ).fetchone()[0]
    papers = db.execute(
        "SELECT COUNT(*) FROM likes l WHERE l.target_kind = 'paper' AND EXISTS"
        " (SELECT 1 FROM readings d WHERE d.paper_id = l.paper_id"
        " AND d.genome_id = ? AND d.keep = 1)",
        (genome_id,),
    ).fetchone()[0]
    return int(own) + int(papers)


def points_by_agent(db: sqlite3.Connection) -> dict[str, int]:
    """Every agent's points, for the views that list agents."""
    totals: dict[str, int] = {}
    for row in db.execute(
        "SELECT genome_id, COUNT(*) FROM likes WHERE genome_id IS NOT NULL GROUP BY genome_id"
    ):
        totals[str(row[0])] = int(row[1])
    for row in db.execute(
        "SELECT d.genome_id, COUNT(*) FROM likes l JOIN readings d ON d.paper_id = l.paper_id"
        " WHERE l.target_kind = 'paper' AND d.keep = 1 GROUP BY d.genome_id"
    ):
        totals[str(row[0])] = totals.get(str(row[0]), 0) + int(row[1])
    return totals
