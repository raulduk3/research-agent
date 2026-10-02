"""SQLite storage: connections, numbered migrations and small shared helpers.

One file holds every durable record. Timestamps are UTC ISO-8601 text with a
fixed width, so comparing them as strings orders them in time. Money is whole
micro-dollars. Run events and cost receipts are append-only: a trigger refuses
any update or delete, so a replay or a total can never be rewritten.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Clock = Callable[[], datetime]
Json = dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(5)}"


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def loads(text: str | None) -> Any:
    return None if text is None else json.loads(text)


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open one connection; commit on a clean exit, roll back on an error."""
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


_IMMUTABLE = """
CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table}
BEGIN SELECT RAISE(ABORT, '{table} rows are immutable'); END;
CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
BEGIN SELECT RAISE(ABORT, '{table} rows are immutable'); END;
"""

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
CREATE TABLE spec_revisions (
  revision INTEGER PRIMARY KEY,
  body TEXT NOT NULL,
  changes TEXT NOT NULL,
  actor TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  restored_from INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE papers (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  version INTEGER NOT NULL,
  title TEXT NOT NULL,
  abstract TEXT NOT NULL,
  authors TEXT NOT NULL,
  primary_category TEXT NOT NULL,
  categories TEXT NOT NULL,
  published_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  abs_url TEXT NOT NULL,
  pdf_url TEXT NOT NULL,
  text_status TEXT NOT NULL CHECK (text_status IN ('abstract_only', 'failed')),
  text_failure TEXT,
  ingest_receipt_id TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE paper_passages (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL REFERENCES papers(id),
  kind TEXT NOT NULL
    CHECK (kind IN ('abstract', 'section', 'page', 'passage')),
  ordinal INTEGER NOT NULL,
  page INTEGER,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  text TEXT NOT NULL
);
CREATE INDEX paper_passages_paper ON paper_passages(paper_id, ordinal);
CREATE TABLE assignments (
  paper_id TEXT NOT NULL REFERENCES papers(id),
  island_id TEXT NOT NULL,
  reasons TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (paper_id, island_id)
);
CREATE INDEX assignments_island ON assignments(island_id, created_at);
CREATE TABLE ingest_passes (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  categories TEXT NOT NULL,
  status TEXT NOT NULL,
  mode TEXT NOT NULL,
  stored INTEGER NOT NULL DEFAULT 0,
  updated INTEGER NOT NULL DEFAULT 0,
  unchanged INTEGER NOT NULL DEFAULT 0,
  failures TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE source_cursors (
  source TEXT NOT NULL,
  category TEXT NOT NULL,
  last_published TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (source, category)
);
CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL REFERENCES papers(id),
  island_id TEXT NOT NULL,
  genome_id TEXT NOT NULL,
  genome_version INTEGER NOT NULL,
  spec_revision INTEGER NOT NULL REFERENCES spec_revisions(revision),
  genome TEXT NOT NULL,
  seed INTEGER NOT NULL,
  status TEXT NOT NULL
    CHECK (status IN ('queued', 'running', 'completed', 'failed')),
  reading_mode TEXT NOT NULL,
  prompt_system TEXT NOT NULL,
  prompt_user TEXT NOT NULL,
  prompt_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  limits TEXT NOT NULL,
  estimate_micros INTEGER NOT NULL,
  failure TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX runs_paper ON runs(paper_id, created_at);
CREATE INDEX runs_island ON runs(island_id, created_at);
CREATE TABLE run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id),
  seq INTEGER NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  receipt_id TEXT,
  cost_state TEXT NOT NULL DEFAULT 'none'
    CHECK (cost_state IN ('none', 'settled', 'unsettled')),
  loc_paper_id TEXT,
  loc_source_kind TEXT CHECK (loc_source_kind IS NULL OR loc_source_kind IN
    ('abstract', 'section', 'page', 'passage', 'metadata')),
  loc_page INTEGER,
  loc_char_start INTEGER,
  loc_char_end INTEGER,
  loc_passage_id TEXT,
  loc_snippet TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (run_id, seq)
);
CREATE TABLE readings (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
  paper_id TEXT NOT NULL REFERENCES papers(id),
  island_id TEXT NOT NULL,
  genome_id TEXT NOT NULL,
  genome_version INTEGER NOT NULL,
  summary TEXT NOT NULL,
  claims TEXT NOT NULL,
  objections TEXT NOT NULL,
  related_papers TEXT NOT NULL,
  idea_seeds TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX readings_paper ON readings(paper_id);
CREATE TABLE cost_receipts (
  id TEXT PRIMARY KEY,
  action TEXT NOT NULL,
  owner_kind TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  parent_kind TEXT NOT NULL,
  parent_id TEXT NOT NULL,
  unit_type TEXT NOT NULL,
  quantity REAL NOT NULL,
  amount_micros INTEGER NOT NULL CHECK (amount_micros >= 0),
  currency TEXT NOT NULL DEFAULT 'USD',
  provider TEXT,
  estimated INTEGER NOT NULL CHECK (estimated IN (0, 1)),
  settlement TEXT NOT NULL CHECK (settlement IN ('settled', 'unsettled')),
  island_id TEXT,
  paper_id TEXT,
  run_id TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX cost_receipts_time ON cost_receipts(created_at);
CREATE INDEX cost_receipts_run ON cost_receipts(run_id);
CREATE INDEX cost_receipts_paper ON cost_receipts(paper_id);
CREATE INDEX cost_receipts_island ON cost_receipts(island_id, created_at);
CREATE TABLE feedback (
  id TEXT PRIMARY KEY,
  island_id TEXT NOT NULL,
  target_kind TEXT NOT NULL,
  target_id TEXT NOT NULL,
  signal TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  paper_id TEXT,
  run_id TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX feedback_target ON feedback(target_kind, target_id);
CREATE INDEX feedback_island ON feedback(island_id, created_at);
CREATE TABLE generations (
  id TEXT PRIMARY KEY,
  island_id TEXT NOT NULL,
  number INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('committed', 'skipped')),
  reason TEXT,
  revision INTEGER REFERENCES spec_revisions(revision),
  decisions TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (island_id, number)
);
CREATE TABLE idempotency (
  key TEXT NOT NULL,
  scope TEXT NOT NULL,
  response TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (key, scope)
);
CREATE VIRTUAL TABLE search_index USING fts5(
  kind UNINDEXED, ref_id UNINDEXED, paper_id UNINDEXED, title, body
);
"""
        + _IMMUTABLE.format(table="run_events")
        + _IMMUTABLE.format(table="cost_receipts")
        + _IMMUTABLE.format(table="spec_revisions"),
    ),
    (
        2,
        # A paper's full text: a status for it, when it was last looked for, and
        # a title on each stored passage. SQLite cannot widen a CHECK in place,
        # so the papers table is rebuilt with every row copied across.
        """
CREATE TABLE papers_next (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  version INTEGER NOT NULL,
  title TEXT NOT NULL,
  abstract TEXT NOT NULL,
  authors TEXT NOT NULL,
  primary_category TEXT NOT NULL,
  categories TEXT NOT NULL,
  published_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  abs_url TEXT NOT NULL,
  pdf_url TEXT NOT NULL,
  text_status TEXT NOT NULL
    CHECK (text_status IN ('abstract_only', 'full_text', 'failed')),
  text_failure TEXT,
  text_checked_at TEXT,
  ingest_receipt_id TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
INSERT INTO papers_next(id, source, version, title, abstract, authors,
  primary_category, categories, published_at, updated_at, abs_url, pdf_url,
  text_status, text_failure, text_checked_at, ingest_receipt_id, first_seen_at,
  fetched_at)
SELECT id, source, version, title, abstract, authors, primary_category,
  categories, published_at, updated_at, abs_url, pdf_url, text_status,
  text_failure, NULL, ingest_receipt_id, first_seen_at, fetched_at FROM papers;
DROP TABLE papers;
ALTER TABLE papers_next RENAME TO papers;
CREATE INDEX papers_first_seen ON papers(first_seen_at);
ALTER TABLE paper_passages ADD COLUMN title TEXT;
UPDATE paper_passages SET title = 'Abstract' WHERE kind = 'abstract';
""",
    ),
)


def migrate(path: Path) -> list[int]:
    """Apply every migration not yet recorded; return the versions applied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    applied: list[int] = []
    connection = sqlite3.connect(path, timeout=10.0)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.commit()
        done = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        for version, script in MIGRATIONS:
            if version in done:
                continue
            # One script, one transaction: a failed migration leaves no half schema.
            connection.executescript(
                "BEGIN;\n"
                + script
                + "\nINSERT INTO schema_migrations(version, applied_at) "
                + f"VALUES ({version}, '{iso(utc_now())}');\nCOMMIT;"
            )
            applied.append(version)
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    return applied


def schema_version(db: sqlite3.Connection) -> int:
    row = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)
