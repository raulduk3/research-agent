"""Paper records, their stored passages and the search index over them.

A paper exists only because an ingestion pass stored it, and it keeps the
receipt of that pass. Its stored text starts as the abstract, one passage
with character offsets so a run event can point at the words it read; when
arXiv has an HTML version of the paper, its sections are added as further
passages (``text.py``). A paper whose abstract is missing stays visible with
``text_status`` failed and no text is invented for it.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

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
            # A new version is a new text: look for it again.
            " text_failure = ?, fetched_at = ?, text_checked_at = NULL WHERE id = ?",
            (*values, entry.id),
        )
    db.execute("DELETE FROM paper_passages WHERE paper_id = ?", (entry.id,))
    if entry.abstract:
        db.execute(
            "INSERT INTO paper_passages(id, paper_id, kind, ordinal, page, char_start,"
            " char_end, text, title) VALUES (?, ?, 'abstract', 0, NULL, 0, ?, ?,"
            " 'Abstract')",
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
        "text_checked_at": row["text_checked_at"],
        "cited_papers": loads(row["cited_papers"]),
        "ingest_receipt_id": row["ingest_receipt_id"],
        "first_seen_at": row["first_seen_at"],
        "fetched_at": row["fetched_at"],
    }


def prune_unread_papers(db: sqlite3.Connection, now: datetime, days: int) -> int:
    """Forget papers no agent has touched once they are older than ``days``.

    A paper is kept for good once any run, reading or feedback names it: that
    record is the swarm's history and its cost ledger. Returns how many went.
    """
    cutoff = iso(now - timedelta(days=days))
    # A paper the swarm let go is forgotten at once, if untouched.
    stale = [
        row[0]
        for row in db.execute(
            "SELECT p.id FROM papers p WHERE (p.first_seen_at < ?"
            " OR EXISTS (SELECT 1 FROM paper_releases rl WHERE rl.paper_id = p.id))"
            " AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.paper_id = p.id)"
            " AND NOT EXISTS (SELECT 1 FROM readings d WHERE d.paper_id = p.id)"
            " AND NOT EXISTS (SELECT 1 FROM feedback f WHERE f.paper_id = p.id"
            " OR (f.target_kind = 'paper' AND f.target_id = p.id))",
            (cutoff,),
        )
    ]
    for paper_id in stale:
        db.execute("DELETE FROM paper_passages WHERE paper_id = ?", (paper_id,))
        db.execute("DELETE FROM assignments WHERE paper_id = ?", (paper_id,))
        db.execute("DELETE FROM paper_releases WHERE paper_id = ?", (paper_id,))
        db.execute("DELETE FROM paper_traffic WHERE paper_id = ?", (paper_id,))
        db.execute("DELETE FROM search_index WHERE paper_id = ?", (paper_id,))
        db.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    return len(stale)


def release_paper(
    db: sqlite3.Connection, paper_id: str, *, actor: str, note: str, now: datetime
) -> Json:
    """Let the swarm go of a paper: no island queues it and no agent finds it.

    Runs, readings and receipts that name the paper stay; they are the ledger.
    Letting go twice is the same as once.
    """
    get_paper(db, paper_id)
    db.execute(
        "INSERT OR IGNORE INTO paper_releases(paper_id, actor, note, created_at)"
        " VALUES (?, ?, ?, ?)",
        (paper_id, actor, note, iso(now)),
    )
    db.commit()
    return {"paper_id": paper_id, "held": False}


def hold_paper(db: sqlite3.Connection, paper_id: str) -> Json:
    """Take a let-go paper back: it returns to every island's queue and search."""
    get_paper(db, paper_id)
    db.execute("DELETE FROM paper_releases WHERE paper_id = ?", (paper_id,))
    db.commit()
    return {"paper_id": paper_id, "held": True}


def count_paper_use(db: sqlite3.Connection, paper_id: str, now: datetime) -> None:
    """Count one public request for a paper's record, on the day it came."""
    db.execute(
        "INSERT INTO paper_traffic(paper_id, day, hits) VALUES (?, ?, 1)"
        " ON CONFLICT(paper_id, day) DO UPDATE SET hits = hits + 1",
        (paper_id, iso(now)[:10]),
    )
    db.commit()


def get_paper(db: sqlite3.Connection, paper_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        raise NotFound(f"no paper {paper_id}")
    found: sqlite3.Row = row
    return found


def load_passages(db: sqlite3.Connection, paper_id: str) -> list[Json]:
    rows = db.execute(
        "SELECT id, kind, ordinal, page, char_start, char_end, text, title"
        " FROM paper_passages"
        " WHERE paper_id = ? ORDER BY ordinal",
        (paper_id,),
    ).fetchall()
    return [dict(row) for row in rows]


_STOPWORDS = frozenset(
    [
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "say",
        "tell",
        "that",
        "the",
        "their",
        "them",
        "there",
        "these",
        "they",
        "this",
        "to",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
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
    db: sqlite3.Connection,
    text: str,
    limit: int = 8,
    exclude_paper: str | None = None,
    island_id: str | None = None,
) -> list[Json]:
    """Ranked matches over stored papers and readings, best first.

    Papers the swarm has let go are left out. With ``island_id`` only papers
    assigned to that island are found: an island reads within its own pool.
    """
    query = match_query(text)
    if query is None:
        return []
    rows = db.execute(
        "SELECT kind, ref_id, paper_id, title,"
        " snippet(search_index, 4, '', '', ' ... ', 28) AS snippet"
        " FROM search_index WHERE search_index MATCH ? AND paper_id IS NOT ?"
        " AND paper_id NOT IN (SELECT paper_id FROM paper_releases)"
        " AND (? IS NULL OR paper_id IN"
        " (SELECT paper_id FROM assignments WHERE island_id = ?))"
        " ORDER BY bm25(search_index, 0.0, 0.0, 0.0, 4.0, 1.0) LIMIT ?",
        (query, exclude_paper, island_id, island_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _fingerprint(text: str) -> str:
    return " ".join(
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) >= 3 and word not in _STOPWORDS
    )


def related_work_shortlist(
    db: sqlite3.Connection, paper_id: str, limit: int = 20, island_id: str | None = None
) -> list[Json]:
    """Papers to show a run before it searches: bibliography matches, then BM25.

    With ``island_id`` only that island's papers are offered.
    """
    paper = get_paper(db, paper_id)
    cited = loads(paper["cited_papers"])
    candidates: list[Json] = []
    seen: set[tuple[str, str]] = set()

    stored = db.execute(
        "SELECT id, title, abstract FROM papers WHERE id != ?"
        " AND id NOT IN (SELECT paper_id FROM paper_releases)"
        " AND (? IS NULL OR id IN (SELECT paper_id FROM assignments WHERE island_id = ?))"
        " ORDER BY first_seen_at DESC",
        (paper_id, island_id, island_id),
    ).fetchall()
    references = [(ref, _fingerprint(str(ref))) for ref in cited if str(ref).strip()]
    for row in stored:
        title_key = _fingerprint(row["title"])
        if not title_key:
            continue
        for reference, reference_key in references:
            if title_key in reference_key or reference_key in title_key:
                item = {
                    "kind": "paper",
                    "ref_id": row["id"],
                    "paper_id": row["id"],
                    "title": row["title"],
                    "snippet": str(reference)[:280],
                    "source": "bibliography",
                }
                candidates.append(item)
                seen.add(("paper", row["id"]))
                break
        if len(candidates) >= limit:
            return candidates

    query = " ".join(
        [paper["title"], paper["abstract"], *[str(ref) for ref in cited[:20]]]
    )
    for hit in search(
        db, query, limit * 2, exclude_paper=paper_id, island_id=island_id
    ):
        key = (str(hit["kind"]), str(hit["ref_id"]))
        if key in seen:
            continue
        candidates.append({**hit, "source": "stored_text_search"})
        seen.add(key)
        if len(candidates) >= limit:
            break
    return candidates
