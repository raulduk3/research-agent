"""The store migrates once, whole, and keeps its append-only tables intact."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research_agent.beta import db as store
from research_agent.beta.costs import record_cost_receipt
from tests.beta.helpers import FakeClock

TABLES = {
    "spec_revisions",
    "papers",
    "paper_passages",
    "assignments",
    "ingest_passes",
    "source_cursors",
    "runs",
    "run_events",
    "readings",
    "cost_receipts",
    "feedback",
    "idempotency",
    "search_index",
}


def _tables(path: Path) -> set[str]:
    with store.connect(path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {row[0] for row in rows}


def test_migration_creates_the_schema_and_is_applied_once(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "swarm.sqlite3"

    assert store.migrate(path) == [1]
    assert TABLES <= _tables(path)
    # A second start finds the version recorded and applies nothing again.
    assert store.migrate(path) == []
    with store.connect(path) as connection:
        assert store.schema_version(connection) == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_a_failed_migration_leaves_no_half_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "swarm.sqlite3"
    broken = "CREATE TABLE first_half (id TEXT); CREATE TABLE second_half (id TEXT;"
    monkeypatch.setattr(store, "MIGRATIONS", ((1, broken),))

    with pytest.raises(sqlite3.Error):
        store.migrate(path)

    assert "first_half" not in _tables(path)
    with store.connect(path) as connection:
        assert store.schema_version(connection) == 0


def test_run_events_and_receipts_cannot_be_rewritten(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    receipt_id = record_cost_receipt(
        db,
        action="ingest",
        owner_kind="ingest_pass",
        owner_id="IP-1",
        parent_kind="source",
        parent_id="arxiv:cs.AI",
        unit_type="arxiv_request",
        quantity=1,
        amount_micros=0,
        now=clock(),
    )
    db.commit()

    for statement in (
        "UPDATE cost_receipts SET amount_micros = 5 WHERE id = ?",
        "DELETE FROM cost_receipts WHERE id = ?",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            db.execute(statement, (receipt_id,))
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        db.execute("UPDATE spec_revisions SET body = '{}' WHERE revision = 1")
    assert db.execute("SELECT amount_micros FROM cost_receipts").fetchone()[0] == 0
