"""Cost receipts: the one ledger every total is summed from.

Each paid or scarce action writes one receipt. A receipt is a leaf charge:
its parent names the object the work was for, never another receipt, so a
scope total is a plain sum and nothing is counted twice. Events and pages
link to receipts; none of them keeps a cost counter of its own.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from research_agent.beta.db import Json, iso, new_id

#: What a receipt may be for. Free but rate-limited work (an arXiv request,
#: a stored-data retrieval) is recorded at amount zero.
ACTIONS = ("ingest", "model_call", "chat_retrieval", "chat_answer", "evolution")

#: The columns a scope total may be taken over.
SCOPES = ("run_id", "paper_id", "island_id")

#: Feedback signals that count as useful when cost is put beside feedback.
HELD = "holds"


def record_cost_receipt(
    db: sqlite3.Connection,
    *,
    action: str,
    owner_kind: str,
    owner_id: str,
    parent_kind: str,
    parent_id: str,
    unit_type: str,
    quantity: float,
    amount_micros: int,
    now: datetime,
    provider: str | None = None,
    estimated: bool = False,
    settled: bool = True,
    island_id: str | None = None,
    paper_id: str | None = None,
    run_id: str | None = None,
) -> str:
    """Write one receipt and return its id.

    ``settled`` is false when the charge could not be confirmed, for example
    a model call that failed after the request left: the amount is then the
    estimate, kept out of settled totals and still counted against budgets.
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown cost action {action!r}")
    receipt_id = new_id("C")
    db.execute(
        "INSERT INTO cost_receipts(id, action, owner_kind, owner_id, parent_kind,"
        " parent_id, unit_type, quantity, amount_micros, provider, estimated,"
        " settlement, island_id, paper_id, run_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            receipt_id,
            action,
            owner_kind,
            owner_id,
            parent_kind,
            parent_id,
            unit_type,
            quantity,
            amount_micros,
            provider,
            int(estimated),
            "settled" if settled else "unsettled",
            island_id,
            paper_id,
            run_id,
            iso(now),
        ),
    )
    return receipt_id


def sum_cost_scope(db: sqlite3.Connection, scope: str, value: str) -> Json:
    """Total the receipts of one run, paper or island, each counted once."""
    if scope not in SCOPES:
        raise ValueError(f"unknown cost scope {scope!r}")
    row = db.execute(
        "SELECT COALESCE(SUM(CASE WHEN settlement = 'settled' THEN amount_micros END), 0),"
        " COALESCE(SUM(CASE WHEN settlement = 'unsettled' THEN amount_micros END), 0),"
        " COALESCE(SUM(settlement = 'unsettled'), 0), COUNT(*),"
        " COALESCE(SUM(estimated), 0)"
        f" FROM cost_receipts WHERE {scope} = ?",
        (value,),
    ).fetchone()
    return {
        "settled_micros": int(row[0]),
        "unsettled_micros": int(row[1]),
        "unsettled_count": int(row[2]),
        "receipt_count": int(row[3]),
        "estimated_count": int(row[4]),
    }


def attach_cost_summary(db: sqlite3.Connection, scope: str, value: str) -> Json:
    """The cost block a view shows beside its activity.

    Settled total and unsettled count. A failed query yields ``unavailable``
    rather than a zero.
    """
    try:
        summary = sum_cost_scope(db, scope, value)
    except sqlite3.Error:
        return {"state": "unavailable"}
    return {"state": "available", **summary}


def receipts_for(
    db: sqlite3.Connection, scope: str, value: str, limit: int = 200
) -> list[Json]:
    if scope not in SCOPES:
        raise ValueError(f"unknown cost scope {scope!r}")
    rows = db.execute(
        "SELECT id, action, owner_kind, owner_id, unit_type, quantity, amount_micros,"
        " provider, estimated, settlement, created_at FROM cost_receipts"
        f" WHERE {scope} = ? ORDER BY created_at, id LIMIT ?",
        (value, limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "action": row["action"],
            "owner": {"kind": row["owner_kind"], "id": row["owner_id"]},
            "unit_type": row["unit_type"],
            "quantity": row["quantity"],
            "amount_micros": row["amount_micros"],
            "provider": row["provider"],
            "estimated": bool(row["estimated"]),
            "settlement": row["settlement"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
