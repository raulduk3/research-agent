"""Feedback: one stored shape for every page that accepts it.

A visitor accepts, passes on or pushes away a paper, a reading, a run, an
idea seed or a chat answer. The target must exist; the signal is stored with
the island it came from and the paper and run it traces to, so totals and
cost-per-useful-feedback need no second lookup.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from research_agent.beta.db import Json, iso, new_id
from research_agent.beta.errors import Invalid, NotFound

SIGNALS = ("accept", "pass", "push_away")
TARGET_KINDS = ("paper", "reading", "run", "idea", "chat")


def _resolve(
    db: sqlite3.Connection, kind: str, target_id: str
) -> tuple[str | None, str | None]:
    """The paper and run a target traces to; refuses a target that is not stored."""
    if kind == "paper":
        row = db.execute(
            "SELECT id, NULL FROM papers WHERE id = ?", (target_id,)
        ).fetchone()
    elif kind == "run":
        row = db.execute(
            "SELECT paper_id, id FROM runs WHERE id = ?", (target_id,)
        ).fetchone()
    elif kind == "reading":
        row = db.execute(
            "SELECT paper_id, run_id FROM readings WHERE id = ?", (target_id,)
        ).fetchone()
    elif kind == "idea":
        # An idea seed is addressed as "<reading id>#<index>".
        reading_id, _, index = target_id.partition("#")
        row = db.execute(
            "SELECT paper_id, run_id, json_array_length(idea_seeds) FROM readings WHERE id = ?",
            (reading_id,),
        ).fetchone()
        if row is not None and not (index.isdigit() and int(index) < row[2]):
            row = None
    else:
        # A chat answer is addressed by the receipt of its retrieval; no transcript exists.
        row = db.execute(
            "SELECT NULL, NULL FROM cost_receipts WHERE id = ? AND owner_kind = 'chat'",
            (target_id,),
        ).fetchone()
    if row is None:
        raise NotFound(f"no {kind} {target_id}")
    return row[0], row[1]


def record_feedback(
    db: sqlite3.Connection,
    *,
    island_id: str,
    target_kind: str,
    target_id: str,
    signal: str,
    note: str,
    now: datetime,
) -> Json:
    """Validate and store one feedback signal."""
    if target_kind not in TARGET_KINDS:
        raise Invalid(f"target_kind is one of {', '.join(TARGET_KINDS)}", "target_kind")
    if signal not in SIGNALS:
        raise Invalid(f"signal is one of {', '.join(SIGNALS)}", "signal")
    if len(note) > 2000:
        raise Invalid("a note is at most 2000 characters", "note")
    paper_id, run_id = _resolve(db, target_kind, target_id)
    feedback_id = new_id("F")
    db.execute(
        "INSERT INTO feedback(id, island_id, target_kind, target_id, signal, note,"
        " paper_id, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            feedback_id,
            island_id,
            target_kind,
            target_id,
            signal,
            note.strip(),
            paper_id,
            run_id,
            iso(now),
        ),
    )
    return {
        "id": feedback_id,
        "island_id": island_id,
        "target_kind": target_kind,
        "target_id": target_id,
        "signal": signal,
        "note": note.strip(),
        "created_at": iso(now),
    }


def feedback_rows(
    db: sqlite3.Connection, column: str, value: str, limit: int = 100
) -> Json:
    """Feedback for one paper, run or island: totals by signal and the rows."""
    if column not in ("paper_id", "run_id", "island_id"):
        raise ValueError(f"unknown feedback scope {column!r}")
    totals = db.execute(
        f"SELECT signal, COUNT(*) FROM feedback WHERE {column} = ? GROUP BY signal",
        (value,),
    ).fetchall()
    rows = db.execute(
        "SELECT id, island_id, target_kind, target_id, signal, note, created_at"
        f" FROM feedback WHERE {column} = ? ORDER BY created_at DESC, id LIMIT ?",
        (value, limit),
    ).fetchall()
    return {
        "totals": {signal: 0 for signal in SIGNALS}
        | {row[0]: row[1] for row in totals},
        "items": [dict(row) for row in rows],
    }


def feedback_for_evolution(db: sqlite3.Connection, island_id: str) -> list[Json]:
    """Accepted feedback rows as evolution reads them, joined to the genome that ran."""
    rows = db.execute(
        "SELECT f.id, f.signal, f.target_kind, f.target_id, f.created_at,"
        " r.genome_id, r.genome_version FROM feedback f"
        " LEFT JOIN runs r ON r.id = f.run_id WHERE f.island_id = ? ORDER BY f.created_at",
        (island_id,),
    ).fetchall()
    return [dict(row) for row in rows]
