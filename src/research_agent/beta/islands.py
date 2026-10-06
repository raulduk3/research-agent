"""Islands: which papers they take and what state each is in.

Assignment reads a paper's categories against each open island's categories,
with the island's keywords in the title and abstract as extra weight, and
stores the chosen islands with the reasons. A paper nothing claims goes to the general
island marked ``assignment_uncertain``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime
from fnmatch import fnmatchcase
from typing import Any

from research_agent.beta.budget import BudgetState
from research_agent.beta.db import dumps, iso
from research_agent.beta.papers import PaperEntry
from research_agent.beta.spec import FALLBACK_ISLAND


def score_islands(
    spec: Mapping[str, Any], entry: PaperEntry
) -> list[tuple[int, str, list[str]]]:
    """Score each open island for a paper; best first, with reason codes."""
    text = f"{entry.title} {entry.abstract}".lower()
    scored: list[tuple[int, str, list[str]]] = []
    for island in spec["islands"]:
        if island["archived"]:
            continue
        score = 0
        reasons: list[str] = []
        patterns = island["categories"]
        if any(fnmatchcase(entry.primary_category, pattern) for pattern in patterns):
            score += 2
            reasons.append(f"primary_category:{entry.primary_category}")
        crossed = [
            category
            for category in entry.categories
            if category != entry.primary_category
            and any(fnmatchcase(category, pattern) for pattern in patterns)
        ]
        for category in crossed[:2]:
            score += 1
            reasons.append(f"cross_list:{category}")
        in_category = bool(score)
        for keyword in [word for word in island["keywords"] if word in text][:2]:
            score += 1
            reasons.append(f"focus_keyword:{keyword}")
        # A keyword strengthens a category match; alone it claims a paper only
        # for an island that watches no category at all.
        if in_category or (score and not patterns):
            scored.append((score, island["id"], reasons))
    return sorted(scored, key=lambda item: (-item[0], item[1]))


def assign_paper(
    db: sqlite3.Connection,
    spec: Mapping[str, Any],
    entry: PaperEntry,
    islands_per_paper: int,
    now: datetime,
) -> list[str]:
    """Assign a paper to islands; return the islands newly given it."""
    chosen = [(island, reasons) for _, island, reasons in score_islands(spec, entry)]
    chosen = chosen[:islands_per_paper] or [(FALLBACK_ISLAND, ["assignment_uncertain"])]
    added: list[str] = []
    for island_id, reasons in chosen:
        cursor = db.execute(
            "INSERT OR IGNORE INTO assignments(paper_id, island_id, reasons, created_at, kept)"
            " VALUES (?, ?, ?, ?, (SELECT selected FROM paper_selections WHERE paper_id = ?))",
            (entry.id, island_id, dumps(reasons), iso(now), entry.id),
        )
        if cursor.rowcount:
            added.append(island_id)
    return added


def island_state(
    island: Mapping[str, Any], active_runs: int, budget: BudgetState
) -> tuple[str, str | None]:
    """What an island is doing now: working, blocked (with why) or idle."""
    if active_runs:
        return "working", None
    if island["archived"]:
        return "blocked", "archived"
    if island["paused"]:
        return "blocked", "paused"
    if budget.plan.runs_refusal is not None:
        return "blocked", budget.plan.runs_refusal
    if island["priority"] in budget.plan.paused_priorities:
        return "blocked", "paused_by_budget"
    share = budget.islands.get(str(island["id"]))
    if share is not None and share.over_share:
        return "blocked", "island_over_share"
    return "idle", None
