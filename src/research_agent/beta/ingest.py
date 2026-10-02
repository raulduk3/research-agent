"""Current arXiv ingestion: fetch, parse, store, assign.

One pass asks the arXiv API for the newest submissions in each category the
islands watch, stores metadata and the abstract, and assigns each new paper
to islands. A category that fails is recorded on the pass and the others
still commit. Storing is an upsert by canonical arXiv id, so a pass may be
run again, or resumed after a stop, without making a second record.
"""

from __future__ import annotations

import math
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

import httpx

from research_agent.beta.budget import Plan
from research_agent.beta.costs import record_cost_receipt
from research_agent.beta.db import Clock, Json, dumps, iso, new_id
from research_agent.beta.islands import assign_paper
from research_agent.beta.papers import PaperEntry, prune_unread_papers, upsert_paper
from research_agent.beta.text import TextFetcher, fetch_full_texts

#: Fetches one category's newest entries as Atom text: (category, max_results).
Fetcher = Callable[[str, int], str]

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_ABS_ID = re.compile(r"arxiv\.org/abs/(?P<id>[^\s]+?)(?:v(?P<version>\d+))?$")


class SourceFailed(Exception):
    """A source could not be fetched or its answer could not be read."""


def _squash(text: str | None) -> str:
    return " ".join((text or "").split())


def parse_arxiv_feed(xml_text: str) -> tuple[list[PaperEntry], list[Json]]:
    """Read an arXiv Atom feed into paper entries.

    Returns the entries and, separately, the entries set aside because their
    identity could not be read; those are never stored or assigned.
    """
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise SourceFailed("the feed declares a document type")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceFailed(f"the feed is not well-formed XML: {exc}") from exc
    entries: list[PaperEntry] = []
    quarantined: list[Json] = []
    for node in root.findall(f"{_ATOM}entry"):
        raw_id = _squash(node.findtext(f"{_ATOM}id"))
        title = _squash(node.findtext(f"{_ATOM}title"))
        match = _ABS_ID.search(raw_id)
        if match is None or not title:
            quarantined.append({"source_id": raw_id, "reason": "ambiguous_identity"})
            continue
        categories = tuple(
            term
            for item in node.findall(f"{_ATOM}category")
            if (term := item.get("term"))
        )
        primary_node = node.find(f"{_ARXIV}primary_category")
        primary = (primary_node.get("term") if primary_node is not None else None) or (
            categories[0] if categories else ""
        )
        links = {
            (link.get("title") or link.get("rel") or ""): link.get("href") or ""
            for link in node.findall(f"{_ATOM}link")
        }
        paper_id = match.group("id")
        published = _squash(node.findtext(f"{_ATOM}published"))
        entries.append(
            PaperEntry(
                id=paper_id,
                version=int(match.group("version") or 1),
                title=title,
                abstract=_squash(node.findtext(f"{_ATOM}summary")),
                authors=tuple(
                    name
                    for author in node.findall(f"{_ATOM}author")
                    if (name := _squash(author.findtext(f"{_ATOM}name")))
                ),
                primary_category=primary,
                categories=categories,
                published_at=published,
                updated_at=_squash(node.findtext(f"{_ATOM}updated")) or published,
                abs_url=links.get("alternate") or f"https://arxiv.org/abs/{paper_id}",
                pdf_url=links.get("pdf") or f"https://arxiv.org/pdf/{paper_id}",
            )
        )
    return entries, quarantined


def arxiv_fetcher(api: str, attempts: int = 2) -> Fetcher:
    """The network fetcher: newest submissions first, one retry on a failure."""

    def fetch(category: str, max_results: int) -> str:
        error: Exception | None = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(3.0)
            try:
                reply = httpx.get(
                    api,
                    params={
                        "search_query": f"cat:{category}",
                        "start": "0",
                        "max_results": str(max_results),
                        "sortBy": "submittedDate",
                        "sortOrder": "descending",
                    },
                    headers={"User-Agent": "research-agent-swarm-beta"},
                    timeout=40.0,
                    follow_redirects=True,
                )
                reply.raise_for_status()
                return reply.text
            except httpx.HTTPError as exc:
                error = exc
        raise SourceFailed(f"arXiv did not answer: {type(error).__name__}")

    return fetch


def watched_categories(spec: Mapping[str, Any]) -> list[str]:
    """Every category an open island watches, without repeats."""
    seen: list[str] = []
    for island in spec["islands"]:
        if island["archived"]:
            continue
        for category in island["categories"]:
            if category not in seen:
                seen.append(category)
    return seen


def run_ingestion_pass(
    db: sqlite3.Connection,
    spec: Mapping[str, Any],
    plan: Plan,
    *,
    fetch: Fetcher,
    clock: Clock,
    categories: Sequence[str] | None = None,
    limit: int | None = None,
    delay_seconds: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
    fetch_text: TextFetcher | None = None,
    prune_after_days: int | None = None,
) -> Json:
    """Run one ingestion pass and return what it stored, skipped and assigned.

    The pass holds at most ``plan.papers_per_pass`` papers, shared evenly
    between categories. Each category commits on its own, so a stop leaves
    every finished category stored and a rerun picks the rest up. With a
    text fetcher, the pass then looks for the full text of as many papers
    as it may hold. With ``prune_after_days``, it first forgets papers that
    old which no agent has touched.
    """
    wanted = list(categories) if categories else watched_categories(spec)
    cap = (
        plan.papers_per_pass
        if limit is None
        else max(1, min(limit, plan.papers_per_pass))
    )
    per_category = max(1, math.ceil(cap / max(1, len(wanted))))
    started: datetime = clock()
    pass_id = new_id("IP")
    pruned = (
        prune_unread_papers(db, started, prune_after_days)
        if prune_after_days is not None
        else 0
    )
    db.execute(
        "INSERT INTO ingest_passes(id, source, categories, status, mode, started_at)"
        " VALUES (?, 'arxiv', ?, 'running', ?, ?)",
        (pass_id, dumps(wanted), plan.ingest_mode, iso(started)),
    )
    db.commit()

    counts = {"stored": 0, "updated": 0, "unchanged": 0}
    failures: list[Json] = []
    quarantined: list[Json] = []
    assigned: list[Json] = []
    seen: set[str] = set()
    for index, category in enumerate(wanted):
        if len(seen) >= cap:
            break
        if index:
            sleep(delay_seconds)
        now = clock()
        # The request is free and rate limited: a receipt at amount zero.
        receipt_id = record_cost_receipt(
            db,
            action="ingest",
            owner_kind="ingest_pass",
            owner_id=pass_id,
            parent_kind="source",
            parent_id=f"arxiv:{category}",
            unit_type="arxiv_request",
            quantity=1,
            amount_micros=0,
            provider="arxiv",
            now=now,
        )
        try:
            entries, set_aside = parse_arxiv_feed(fetch(category, per_category))
        except SourceFailed as exc:
            failures.append({"category": category, "error": str(exc)})
            db.commit()
            continue
        quarantined.extend({**item, "category": category} for item in set_aside)
        newest = ""
        for entry in entries:
            if entry.id in seen or len(seen) >= cap:
                continue
            seen.add(entry.id)
            outcome = upsert_paper(db, entry, receipt_id, now)
            counts[outcome] += 1
            newest = max(newest, entry.published_at)
            for island_id in assign_paper(db, spec, entry, plan.islands_per_paper, now):
                assigned.append({"paper_id": entry.id, "island_id": island_id})
        if newest:
            db.execute(
                "INSERT INTO source_cursors(source, category, last_published, updated_at)"
                " VALUES ('arxiv', ?, ?, ?) ON CONFLICT(source, category) DO UPDATE SET"
                " last_published = MAX(last_published, excluded.last_published),"
                " updated_at = excluded.updated_at",
                (category, newest, iso(now)),
            )
        db.commit()

    full_text: Json = {}
    if fetch_text is not None:
        full_text = fetch_full_texts(
            db,
            fetch=fetch_text,
            clock=clock,
            owner_id=pass_id,
            limit=cap,
            delay_seconds=delay_seconds,
            sleep=sleep,
        )

    status = "failed" if failures and not seen else "completed"
    problems = failures + quarantined
    db.execute(
        "UPDATE ingest_passes SET status = ?, stored = ?, updated = ?, unchanged = ?,"
        " failures = ?, finished_at = ? WHERE id = ?",
        (
            status,
            counts["stored"],
            counts["updated"],
            counts["unchanged"],
            dumps(problems),
            iso(clock()),
            pass_id,
        ),
    )
    db.commit()
    return {
        "pass_id": pass_id,
        "status": status,
        "mode": plan.ingest_mode,
        "categories": wanted,
        "paper_cap": cap,
        **counts,
        "failures": failures,
        "quarantined": quarantined,
        "assigned": assigned,
        "pruned": pruned,
        "full_text": full_text,
    }
