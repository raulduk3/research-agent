"""Paper records, their stored passages and the search index over them.

A paper exists only because an ingestion pass stored it, and it keeps the
receipt of that pass. Its stored text starts as the abstract, one passage
with character offsets so a run event can point at the words it read; when
arXiv has an HTML version of the paper, its sections are added as further
passages (``text.py``). A paper whose abstract is missing stays visible with
``text_status`` failed and no text is invented for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from research_agent.beta.budget import levers_from
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


def prune_failed_runs(db: sqlite3.Connection, now: datetime) -> int:
    """Remove failed attempts after one day, retaining their spending receipts."""
    stale = db.execute(
        "SELECT r.id FROM runs r WHERE r.status = 'failed' AND r.finished_at < ?"
        " AND NOT EXISTS (SELECT 1 FROM readings d WHERE d.run_id = r.id)",
        (iso(now - timedelta(hours=24)),),
    ).fetchall()
    for row in stale:
        run_id = row[0]
        db.execute("DELETE FROM run_events WHERE run_id = ?", (run_id,))
        db.execute("DELETE FROM likes WHERE run_id = ?", (run_id,))
        db.execute("DELETE FROM search_index WHERE ref_id = ?", (run_id,))
        db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    return len(stale)


def prune_unread_papers(db: sqlite3.Connection, now: datetime, days: int) -> int:
    """Forget old unread papers unless selected; retain run and reading history.

    A paper is kept once any run or reading names it: that
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
            " AND NOT EXISTS (SELECT 1 FROM paper_selections s WHERE s.paper_id = p.id"
            " AND s.selected = 1)"
            " AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.paper_id = p.id"
            " AND a.kept = 1 AND NOT EXISTS (SELECT 1 FROM paper_releases r"
            " WHERE r.paper_id = p.id))",
            (cutoff,),
        )
    ]
    for paper_id in stale:
        db.execute("DELETE FROM paper_passages WHERE paper_id = ?", (paper_id,))
        db.execute("DELETE FROM assignments WHERE paper_id = ?", (paper_id,))
        db.execute("DELETE FROM paper_selections WHERE paper_id = ?", (paper_id,))
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
    if actor != "readers":
        db.execute("UPDATE assignments SET kept = 0 WHERE paper_id = ?", (paper_id,))
        db.execute(
            "INSERT INTO paper_selections(paper_id, selected, actor, note, created_at)"
            " VALUES (?, 0, ?, ?, ?) ON CONFLICT(paper_id) DO UPDATE SET"
            " selected = 0, actor = excluded.actor, note = excluded.note,"
            " created_at = excluded.created_at",
            (paper_id, actor, note, iso(now)),
        )
    db.commit()
    return {"paper_id": paper_id, "held": False, "selected": False}


def decide_paper(
    db: sqlite3.Connection,
    spec: Mapping[str, Any],
    paper_id: str,
    island_id: str,
    now: datetime,
) -> str | None:
    """Apply human selection first, otherwise wait for the completed reader cohort.

    An island cannot hold every paper. The planned cohort of agents reads it and says
    whether to keep it; the paper is kept only when all of them say so, and a
    reader whose run failed has not voted. Until every reader has submitted
    a reading the paper is undecided. A paper no island keeps, once every island that has
    it has decided, is let go for the swarm. Returns ``kept``, ``rejected``
    or ``None`` while undecided.
    """
    island = next((i for i in spec["islands"] if i["id"] == island_id), None)
    if island is None:
        return None
    if not db.execute(
        "SELECT 1 FROM assignments WHERE paper_id = ? AND island_id = ?",
        (paper_id, island_id),
    ).fetchone():
        return None
    manual = db.execute(
        "SELECT selected FROM paper_selections WHERE paper_id = ?", (paper_id,)
    ).fetchone()
    if manual is not None:
        selected = bool(manual[0])
        db.execute(
            "UPDATE assignments SET kept = ? WHERE paper_id = ? AND island_id = ?",
            (int(selected), paper_id, island_id),
        )
        db.commit()
        return "kept" if selected else "rejected"
    # The cohort is the readers who took this paper, bounded by the plan.
    # Evolution must not add voters to papers already being decided.
    first = db.execute(
        "SELECT limits FROM runs WHERE paper_id = ? AND island_id = ? ORDER BY rowid LIMIT 1",
        (paper_id, island_id),
    ).fetchone()
    fallback_count = min(
        levers_from(spec.get("budget", {})).agents_per_paper,
        sum(bool(g["active"]) for g in island["genomes"]),
    )
    count = (
        int(loads(first[0]).get("agents_per_paper", fallback_count))
        if first
        else fallback_count
    )
    readers = db.execute(
        "SELECT genome_id FROM runs WHERE paper_id = ? AND island_id = ?"
        " GROUP BY genome_id ORDER BY MIN(rowid) LIMIT ?",
        (paper_id, island_id, count),
    ).fetchall()
    if not count or len(readers) < count:
        return None
    votes: dict[str, int | None] = {}
    for reader in readers:
        genome_id = str(reader[0])
        row = db.execute(
            "SELECT r.status, (SELECT d.keep FROM readings d WHERE d.run_id = r.id)"
            " FROM runs r WHERE r.paper_id = ? AND r.genome_id = ?"
            " ORDER BY r.rowid DESC LIMIT 1",
            (paper_id, genome_id),
        ).fetchone()
        if row is None or row[0] != "completed" or row[1] is None:
            return None
        votes[genome_id] = int(row[1])
    kept = all(vote == 1 for vote in votes.values()) if votes else False
    db.execute(
        "UPDATE assignments SET kept = ? WHERE paper_id = ? AND island_id = ?",
        (1 if kept else 0, paper_id, island_id),
    )
    undecided, kept_anywhere = db.execute(
        "SELECT COALESCE(SUM(kept IS NULL), 0), COALESCE(SUM(kept = 1), 0)"
        " FROM assignments WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    if not undecided and not kept_anywhere:
        db.execute(
            "INSERT OR IGNORE INTO paper_releases(paper_id, actor, note, created_at)"
            " VALUES (?, 'readers', 'no island kept it', ?)",
            (paper_id, iso(now)),
        )
    db.commit()
    return "kept" if kept else "rejected"


def recover_failed_decisions(
    db: sqlite3.Connection, spec: Mapping[str, Any], now: datetime
) -> int:
    """Reopen automatic rejections that mistook a failed run for a negative vote.

    Human releases remain authoritative and completed votes are preserved.
    Past runs and readings are never rewritten.
    """
    rows = db.execute(
        "SELECT DISTINCT a.paper_id, a.island_id FROM assignments a"
        " WHERE a.kept = 0 AND EXISTS (SELECT 1 FROM runs r"
        " WHERE r.paper_id = a.paper_id AND r.island_id = a.island_id"
        " AND r.status = 'failed' AND NOT EXISTS (SELECT 1 FROM runs newer"
        " WHERE newer.paper_id = r.paper_id AND newer.genome_id = r.genome_id"
        " AND newer.rowid > r.rowid))"
    ).fetchall()
    changed = 0
    for row in rows:
        # A release by a person remains authoritative.
        if db.execute(
            "SELECT 1 FROM paper_releases WHERE paper_id = ? AND actor != 'readers'",
            (row["paper_id"],),
        ).fetchone():
            continue
        # Only the failed cohort's old automatic decision needs reopening.
        if decide_paper(db, spec, row["paper_id"], row["island_id"], now) is not None:
            continue
        db.execute(
            "UPDATE assignments SET kept = NULL WHERE paper_id = ? AND island_id = ?",
            (row["paper_id"], row["island_id"]),
        )
        db.execute(
            "DELETE FROM paper_releases WHERE paper_id = ? AND actor = 'readers'",
            (row["paper_id"],),
        )
        changed += 1
    db.commit()
    return changed


def hold_paper(
    db: sqlite3.Connection, paper_id: str, *, actor: str, note: str, now: datetime
) -> Json:
    """Select a paper for every assigned island, overriding automatic votes."""
    get_paper(db, paper_id)
    db.execute("DELETE FROM paper_releases WHERE paper_id = ?", (paper_id,))
    db.execute(
        "INSERT INTO paper_selections(paper_id, selected, actor, note, created_at)"
        " VALUES (?, 1, ?, ?, ?) ON CONFLICT(paper_id) DO UPDATE SET"
        " selected = 1, actor = excluded.actor, note = excluded.note,"
        " created_at = excluded.created_at",
        (paper_id, actor, note, iso(now)),
    )
    db.execute("UPDATE assignments SET kept = 1 WHERE paper_id = ?", (paper_id,))
    db.commit()
    return {"paper_id": paper_id, "held": True, "selected": True}


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


def selected_context(
    db: sqlite3.Connection, island_id: str, paper_id: str, limit: int = 5
) -> list[Json]:
    """Bounded reading context from this island's current selections."""
    rows = db.execute(
        "SELECT p.id, p.title, p.abstract, s.actor,"
        " (SELECT d.summary FROM readings d WHERE d.paper_id = p.id"
        " AND d.island_id = a.island_id ORDER BY d.rowid DESC LIMIT 1) AS summary"
        " FROM assignments a JOIN papers p ON p.id = a.paper_id"
        " LEFT JOIN paper_selections s ON s.paper_id = p.id"
        " WHERE a.island_id = ? AND COALESCE(s.selected, a.kept) = 1 AND p.id != ?"
        " AND NOT EXISTS (SELECT 1 FROM paper_releases r WHERE r.paper_id = p.id)"
        " ORDER BY a.created_at DESC, p.id LIMIT ?",
        (island_id, paper_id, limit),
    ).fetchall()
    return [
        {
            "paper_id": row["id"],
            "title": str(row["title"])[:160],
            "summary": str(row["summary"] or row["abstract"])[:600],
            "selected_by": row["actor"] or "readers",
        }
        for row in rows
    ]
