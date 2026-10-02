"""Cost receipts: one per paid or scarce action, each counted once."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from research_agent.beta.costs import (
    attach_cost_summary,
    record_cost_receipt,
    sum_cost_scope,
)
from tests.beta.helpers import FakeClock


def _receipt(db: sqlite3.Connection, clock: FakeClock, **fields: Any) -> str:
    values: dict[str, Any] = {
        "action": "model_call",
        "owner_kind": "run",
        "owner_id": "R-1",
        "parent_kind": "paper",
        "parent_id": "P-1",
        "unit_type": "tokens",
        "quantity": 1200,
        "amount_micros": 2_000,
        "now": clock(),
        "island_id": "cs",
        "paper_id": "P-1",
        "run_id": "R-1",
    }
    values.update(fields)
    return record_cost_receipt(db, **values)


def test_a_receipt_stores_owner_parent_units_amount_and_settlement(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    receipt_id = _receipt(db, clock, provider="test-provider", estimated=True)

    row = db.execute(
        "SELECT * FROM cost_receipts WHERE id = ?", (receipt_id,)
    ).fetchone()
    assert (row["owner_kind"], row["owner_id"]) == ("run", "R-1")
    assert (row["parent_kind"], row["parent_id"]) == ("paper", "P-1")
    assert (row["unit_type"], row["quantity"], row["amount_micros"]) == (
        "tokens",
        1200,
        2_000,
    )
    assert (row["currency"], row["provider"]) == ("USD", "test-provider")
    assert (row["estimated"], row["settlement"]) == (1, "settled")


def test_an_action_outside_the_ledger_is_refused(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    with pytest.raises(ValueError, match="unknown cost action"):
        _receipt(db, clock, action="model_training")


def test_scope_totals_count_each_receipt_once_and_keep_unsettled_apart(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _receipt(db, clock, amount_micros=2_000)
    _receipt(db, clock, amount_micros=3_000)
    _receipt(db, clock, amount_micros=700, settled=False, estimated=True)
    _receipt(db, clock, amount_micros=5_000, run_id="R-2", owner_id="R-2")
    _receipt(
        db, clock, amount_micros=9_000, run_id="R-3", paper_id="P-2", island_id="quant"
    )

    run = sum_cost_scope(db, "run_id", "R-1")
    assert run == {
        "settled_micros": 5_000,
        "unsettled_micros": 700,
        "unsettled_count": 1,
        "receipt_count": 3,
        "estimated_count": 1,
    }
    # The paper holds both of its runs; the island holds the same receipts once.
    assert sum_cost_scope(db, "paper_id", "P-1")["settled_micros"] == 10_000
    assert sum_cost_scope(db, "island_id", "cs")["settled_micros"] == 10_000
    ledger = db.execute(
        "SELECT SUM(amount_micros) FROM cost_receipts WHERE settlement = 'settled'"
    ).fetchone()[0]
    islands = sum(
        sum_cost_scope(db, "island_id", island)["settled_micros"]
        for island in ("cs", "quant")
    )
    assert islands == ledger == 19_000


def test_cost_stands_beside_useful_feedback(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _receipt(db, clock, amount_micros=6_000)
    for index, signal in enumerate(("accept", "accept", "pass")):
        db.execute(
            "INSERT INTO feedback(id, island_id, target_kind, target_id, signal,"
            " paper_id, run_id, created_at) VALUES (?, 'cs', 'run', 'R-1', ?, 'P-1',"
            " 'R-1', '2026-09-10T12:00:00Z')",
            (f"F-{index}", signal),
        )

    summary = attach_cost_summary(db, "run_id", "R-1")

    assert summary["state"] == "available"
    assert summary["useful_feedback_count"] == 2
    assert summary["cost_per_useful_feedback_micros"] == 3_000
    # With no useful feedback the figure is absent, not zero.
    empty = attach_cost_summary(db, "run_id", "R-none")
    assert empty["cost_per_useful_feedback_micros"] is None


def test_a_cost_that_cannot_be_read_is_unavailable_not_zero(
    db: sqlite3.Connection,
) -> None:
    db.execute("DROP TABLE feedback")

    assert attach_cost_summary(db, "run_id", "R-1") == {"state": "unavailable"}
