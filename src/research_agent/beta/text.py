"""A paper's full text, from arXiv's HTML version of it.

arXiv publishes most new papers as HTML converted from their LaTeX source.
That page carries the paper's own sections and subsections, so the text can
be stored by section without parsing a PDF: each section becomes a passage
an agent can ask for by id, with its title, in reading order after the
abstract. Mathematics is kept as its LaTeX source; the bibliography, page
furniture and footnote markers are left out. A paper without an HTML
version keeps its abstract, and the reason is recorded on the paper.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser

import httpx

from research_agent.beta.costs import record_cost_receipt
from research_agent.beta.db import Clock, Json, iso

#: Fetches a paper's HTML version by canonical id and version; ``None`` when
#: arXiv has none.
TextFetcher = Callable[[str, int], "str | None"]

#: The most text one passage holds. A longer section is split at paragraph
#: boundaries, so one tool call returns a readable piece rather than a part
#: cut off mid-way.
PASSAGE_CHARS = 3500
#: The largest page read; anything bigger is refused rather than held in memory.
MAX_HTML_BYTES = 30_000_000

_BLOCKS = frozenset(
    "p div li figcaption h2 h3 h4 h5 h6 tr blockquote dd dt table".split()
)
_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_SKIP_TAGS = frozenset(
    "script style nav header footer button svg annotation annotation-xml".split()
)
_SKIP_CLASSES = frozenset(
    {
        "ltx_bibliography",
        "ltx_note",
        "ltx_page_header",
        "ltx_page_footer",
        "ltx_abstract",
        "ltx_authors",
        "ltx_dates",
        "ltx_TOC",
        "ltx_role_footnote",
    }
)
#: The section levels that become passages of their own; deeper levels stay
#: inside their parent's passage.
_SECTION_CLASSES = frozenset({"ltx_section", "ltx_subsection", "ltx_appendix"})


class TextFetchFailed(Exception):
    """arXiv's HTML page could not be read."""


@dataclass
class Section:
    id: str
    title: str = ""
    paragraphs: list[str] = field(default_factory=list)


class _PaperParser(HTMLParser):
    """Collects section titles and paragraph text from arXiv's converted HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[Section] = []
        self._stack: list[tuple[str, str]] = []
        self._open_sections: list[Section] = []
        self._skipping = 0
        self._heading: list[str] | None = None
        self._buffer: list[str] = []

    @property
    def _current(self) -> Section | None:
        return self._open_sections[-1] if self._open_sections else None

    def _flush(self) -> None:
        text = " ".join("".join(self._buffer).split())
        self._buffer = []
        current = self._current
        if text and current is not None:
            if current not in self.sections:
                self.sections.append(current)
            current.paragraphs.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            if tag == "br" and not self._skipping:
                self._buffer.append(" ")
            return
        found = dict(attrs)
        classes = set((found.get("class") or "").split())
        if self._skipping:
            self._stack.append((tag, "skip"))
            self._skipping += 1
            return
        if tag == "math":
            # Mathematics is kept as the LaTeX it was written in.
            source = found.get("alttext")
            if source and self._heading is None:
                self._buffer.append(f" ${source}$ ")
            elif source and self._heading is not None:
                self._heading.append(f" ${source}$ ")
            self._stack.append((tag, "skip"))
            self._skipping += 1
            return
        if tag in _SKIP_TAGS or classes & _SKIP_CLASSES:
            self._stack.append((tag, "skip"))
            self._skipping += 1
            return
        if tag == "section" and classes & _SECTION_CLASSES:
            self._flush()
            parent = self._current
            section_id = found.get("id") or f"part{len(self.sections) + 1}"
            self._open_sections.append(Section(section_id))
            if parent is not None:
                # Text of the parent after this child continues in a new passage.
                parent.paragraphs.append("")
            self._stack.append((tag, "section"))
            return
        if (
            tag in ("h2", "h3", "h4", "h5", "h6")
            and "ltx_title" in classes
            and self._current is not None
            and not self._current.title
            and self._heading is None
        ):
            self._flush()
            self._heading = []
            self._stack.append((tag, "heading"))
            return
        self._stack.append((tag, "plain"))

    def handle_endtag(self, tag: str) -> None:
        if not any(open_tag == tag for open_tag, _ in self._stack):
            return
        while self._stack:
            open_tag, kind = self._stack.pop()
            if kind == "skip":
                self._skipping -= 1
            elif kind == "heading" and self._heading is not None:
                current = self._current
                if current is not None:
                    current.title = " ".join("".join(self._heading).split())
                self._heading = None
            elif kind == "section":
                self._flush()
                if self._open_sections:
                    self._open_sections.pop()
            elif open_tag in _BLOCKS and not self._skipping:
                self._flush()
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._skipping:
            return
        if self._heading is not None:
            self._heading.append(data)
        elif self._current is not None:
            self._buffer.append(data)


def parse_paper_html(html: str) -> list[Section]:
    """The sections of an arXiv HTML paper, in reading order, empty ones left out."""
    parser = _PaperParser()
    parser.feed(html)
    parser.close()
    return [section for section in parser.sections if any(section.paragraphs)]


def split_section(
    section: Section, limit: int = PASSAGE_CHARS
) -> list[tuple[str, str, str]]:
    """A section as passages of at most ``limit`` characters: (id, title, text).

    Paragraphs stay whole where they fit; a single paragraph longer than the
    limit is cut at a word boundary.
    """
    pieces: list[str] = []
    for paragraph in section.paragraphs:
        while len(paragraph) > limit:
            cut = paragraph.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            pieces.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        pieces.append(paragraph)
    parts: list[list[str]] = [[]]
    size = 0
    for piece in pieces:
        if piece == "":
            # The parent's text resumed after a subsection: start a new passage.
            if parts[-1]:
                parts.append([])
                size = 0
            continue
        if parts[-1] and size + len(piece) + 2 > limit:
            parts.append([])
            size = 0
        parts[-1].append(piece)
        size += len(piece) + 2
    parts = [part for part in parts if part]
    title = section.title or section.id
    passages: list[tuple[str, str, str]] = []
    for number, part in enumerate(parts, 1):
        suffix = "" if number == 1 else f"-{number}"
        label = title if len(parts) == 1 else f"{title} (part {number} of {len(parts)})"
        passages.append((f"{section.id}{suffix}", label, "\n\n".join(part)))
    return passages


def arxiv_html_fetcher(base: str = "https://arxiv.org/html/") -> TextFetcher:
    """The network fetcher for arXiv's HTML versions."""

    def fetch(paper_id: str, version: int) -> str | None:
        try:
            reply = httpx.get(
                f"{base}{paper_id}v{version}",
                headers={"User-Agent": "research-agent-swarm-beta"},
                timeout=60.0,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise TextFetchFailed(
                f"arXiv did not answer: {type(exc).__name__}"
            ) from exc
        if reply.status_code == 404:
            return None
        if reply.status_code >= 400:
            raise TextFetchFailed(f"arXiv answered {reply.status_code}")
        if len(reply.content) > MAX_HTML_BYTES:
            raise TextFetchFailed("the HTML page is larger than this server reads")
        return reply.text

    return fetch


def store_full_text(
    db: sqlite3.Connection, paper_id: str, sections: list[Section], now: datetime
) -> int:
    """Store a paper's sections as passages after its abstract; return how many."""
    abstract = db.execute(
        "SELECT char_end FROM paper_passages WHERE paper_id = ? AND kind = 'abstract'",
        (paper_id,),
    ).fetchone()
    offset = (int(abstract[0]) + 2) if abstract is not None else 0
    db.execute(
        "DELETE FROM paper_passages WHERE paper_id = ? AND kind != 'abstract'",
        (paper_id,),
    )
    ordinal = 0
    seen: set[str] = set()
    for section in sections:
        for local_id, title, text in split_section(section):
            ordinal += 1
            passage_id = f"{paper_id}:{local_id}"
            if passage_id in seen:
                passage_id = f"{passage_id}-{ordinal}"
            seen.add(passage_id)
            db.execute(
                "INSERT INTO paper_passages(id, paper_id, kind, ordinal, page,"
                " char_start, char_end, text, title)"
                " VALUES (?, ?, 'section', ?, NULL, ?, ?, ?, ?)",
                (
                    passage_id,
                    paper_id,
                    ordinal,
                    offset,
                    offset + len(text),
                    text,
                    title,
                ),
            )
            offset += len(text) + 2
    db.execute(
        "UPDATE papers SET text_status = 'full_text', text_failure = NULL,"
        " text_checked_at = ? WHERE id = ?",
        (iso(now), paper_id),
    )
    return ordinal


def _record_missing(
    db: sqlite3.Connection, paper_id: str, reason: str, now: datetime
) -> None:
    db.execute(
        "UPDATE papers SET text_failure = ?, text_checked_at = ? WHERE id = ?",
        (reason, iso(now), paper_id),
    )


def fetch_full_texts(
    db: sqlite3.Connection,
    *,
    fetch: TextFetcher,
    clock: Clock,
    owner_id: str,
    limit: int,
    delay_seconds: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Json:
    """Look for the full text of papers not yet looked for, newest first.

    Each request to arXiv is a scarce action and leaves a zero-cost receipt.
    A paper is looked for once per version: a missing or unreadable HTML
    page is recorded on the paper and not asked for again.
    """
    rows = db.execute(
        "SELECT id, version FROM papers WHERE text_checked_at IS NULL"
        " ORDER BY first_seen_at DESC, id LIMIT ?",
        (limit,),
    ).fetchall()
    counts = {"full_text": 0, "no_html_version": 0, "failed": 0, "passages": 0}
    for index, row in enumerate(rows):
        if index:
            sleep(delay_seconds)
        now = clock()
        record_cost_receipt(
            db,
            action="ingest",
            owner_kind="ingest_pass",
            owner_id=owner_id,
            parent_kind="source",
            parent_id=f"arxiv-html:{row['id']}",
            unit_type="arxiv_request",
            quantity=1,
            amount_micros=0,
            provider="arxiv",
            now=now,
        )
        try:
            html = fetch(row["id"], int(row["version"]))
        except TextFetchFailed as exc:
            _record_missing(db, row["id"], f"html_fetch_failed: {exc}", now)
            counts["failed"] += 1
            db.commit()
            continue
        sections = parse_paper_html(html) if html else []
        if not sections:
            reason = "no_html_version" if html is None else "html_without_sections"
            _record_missing(db, row["id"], reason, now)
            counts["no_html_version"] += 1
        else:
            counts["passages"] += store_full_text(db, row["id"], sections, now)
            counts["full_text"] += 1
        db.commit()
    return counts
