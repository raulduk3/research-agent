"""Paper records, their stored passages and the search index over them.

A paper exists only because an ingestion pass stored it, and it keeps the
receipt of that pass. The stored text is the abstract, kept as one passage
with character offsets so a run event can point at the words it read. A
paper whose abstract is missing stays visible with ``text_status`` failed
and no text is invented for it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from research_agent.beta.db import Json, dumps, iso, loads
from research_agent.beta.errors import NotFound


@dataclass(frozen=True)
class PaperEntry:
    """One paper as a source reported it, already normalized."""

    id: str
    version: int
    title: str
    abstract: str
    authors: tuple[str, ...]
    primary_category: str
    categories: tuple[str, ...]
    published_at: str
    updated_at: str
    abs_url: str
    pdf_url: str
    source: str = "arxiv"


def index_document(
    db: sqlite3.Connection, kind: str, ref_id: str, paper_id: str, title: str, body: str
) -> None:
    """Replace one document in the search index."""
    db.execute("DELETE FROM search_index WHERE kind = ? AND ref_id = ?", (kind, ref_id))
    db.execute(
        "INSERT INTO search_index(kind, ref_id, paper_id, title, body) VALUES (?, ?, ?, ?, ?)",
        (kind, ref_id, paper_id, title, body),
    )


def upsert_paper(
    db: sqlite3.Connection, entry: PaperEntry, receipt_id: str, now: datetime
) -> str:
    """Store a paper by its canonical id; say whether it is new, newer or known.

    A later version of a stored paper replaces its metadata and abstract and
    never makes a second record.
    """
    stamp = iso(now)
    existing = db.execute(
        "SELECT version FROM papers WHERE id = ?", (entry.id,)
    ).fetchone()
    if existing is not None and int(existing["version"]) >= entry.version:
        db.execute("UPDATE papers SET fetched_at = ? WHERE id = ?", (stamp, entry.id))
        return "unchanged"
    status = "abstract_only" if entry.abstract else "failed"
    failure = None if entry.abstract else "abstract_missing"
    values = (
        entry.source,
        entry.version,
        entry.title,
        entry.abstract,
        dumps(list(entry.authors)),
        entry.primary_category,
        dumps(list(entry.categories)),
        entry.published_at,
        entry.updated_at,
        entry.abs_url,
        entry.pdf_url,
        status,
        failure,
        stamp,
    )
    if existing is None:
        db.execute(
            "INSERT INTO papers(source, version, title, abstract, authors,"
            " primary_category, categories, published_at, updated_at, abs_url, pdf_url,"
            " text_status, text_failure, fetched_at, id, ingest_receipt_id, first_seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*values, entry.id, receipt_id, stamp),
        )
    else:
        db.execute(
            "UPDATE papers SET source = ?, version = ?, title = ?, abstract = ?,"
            " authors = ?, primary_category = ?, categories = ?, published_at = ?,"
            " updated_at = ?, abs_url = ?, pdf_url = ?, text_status = ?,"
            " text_failure = ?, fetched_at = ? WHERE id = ?",
            (*values, entry.id),
        )
    db.execute("DELETE FROM paper_passages WHERE paper_id = ?", (entry.id,))
    if entry.abstract:
        db.execute(
            "INSERT INTO paper_passages(id, paper_id, kind, ordinal, page, char_start,"
            " char_end, text) VALUES (?, ?, 'abstract', 0, NULL, 0, ?, ?)",
            (f"{entry.id}:abstract", entry.id, len(entry.abstract), entry.abstract),
        )
    index_document(db, "paper", entry.id, entry.id, entry.title, entry.abstract)
    return "stored" if existing is None else "updated"


def paper_json(row: sqlite3.Row) -> Json:
    return {
        "id": row["id"],
        "source": row["source"],
        "version": row["version"],
        "title": row["title"],
        # The stored text of a paper is its arXiv abstract.
        "summary": row["abstract"],
        "authors": loads(row["authors"]),
        "primary_category": row["primary_category"],
        "categories": loads(row["categories"]),
        "published_at": row["published_at"],
        "updated_at": row["updated_at"],
        "url": row["abs_url"],
        "pdf_url": row["pdf_url"],
        "text_status": row["text_status"],
        "text_failure": row["text_failure"],
        "ingest_receipt_id": row["ingest_receipt_id"],
        "first_seen_at": row["first_seen_at"],
        "fetched_at": row["fetched_at"],
    }


def get_paper(db: sqlite3.Connection, paper_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        raise NotFound(f"no paper {paper_id}")
    found: sqlite3.Row = row
    return found


def load_passages(db: sqlite3.Connection, paper_id: str) -> list[Json]:
    rows = db.execute(
        "SELECT id, kind, ordinal, page, char_start, char_end, text FROM paper_passages"
        " WHERE paper_id = ? ORDER BY ordinal",
        (paper_id,),
    ).fetchall()
    return [dict(row) for row in rows]


_STOPWORDS = frozenset(
    "a about an and are as at be by can could did do does for from had has have how i in"
    " is it its me my of on or our say tell that the their them there these they this to"
    " us was we were what when where which who why will with would you your".split()
)


def match_query(text: str, limit: int = 12) -> str | None:
    """Turn free text into a full-text query, or ``None`` when no term is left."""
    terms: list[str] = []
    word = ""
    for char in text.lower() + " ":
        if char.isalnum():
            word += char
            continue
        if len(word) >= 3 and word not in _STOPWORDS and word not in terms:
            terms.append(word)
        word = ""
    if not terms:
        return None
    return " OR ".join(f'"{term}"' for term in terms[:limit])


def search(
    db: sqlite3.Connection, text: str, limit: int = 8, exclude_paper: str | None = None
) -> list[Json]:
    """Ranked matches over stored papers and readings, best first."""
    query = match_query(text)
    if query is None:
        return []
    rows = db.execute(
        "SELECT kind, ref_id, paper_id, title,"
        " snippet(search_index, 4, '', '', ' ... ', 28) AS snippet"
        " FROM search_index WHERE search_index MATCH ? AND paper_id IS NOT ?"
        " ORDER BY bm25(search_index, 0.0, 0.0, 0.0, 4.0, 1.0) LIMIT ?",
        (query, exclude_paper, limit),
    ).fetchall()
    return [dict(row) for row in rows]
