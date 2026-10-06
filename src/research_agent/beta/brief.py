"""The public brief: the swarm's state told in words and numbers, with a grade.

Everything here is read from stored rows at request time. Nothing calls a
model, so the brief costs nothing and any agent or person may read it. The
grade is computed by fixed rules from the same numbers it prints, and it is
meant to be hard to earn: a criterion with no evidence scores zero, and caps
hold the letter down while a basic duty goes undone.

The public activity feed is the other half: the newest run steps, reduced to
what a viewer needs to see agents at work (who, which paper, which step,
which other papers it looked at), never a prompt or a model's text.
"""

from __future__ import annotations

import html
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from research_agent.beta.budget import BudgetState
from research_agent.beta.db import Json, iso, loads
from research_agent.beta.errors import NotFound
from research_agent.beta.runs import agent_address

#: The sections a caller may ask for, in the order the brief tells them.
SECTIONS = (
    "about",
    "learned",
    "connections",
    "ideas",
    "grade",
    "findings",
    "numbers",
    "islands",
    "agents",
    "claims",
    "papers",
    "evolution",
    "budget",
    "limits",
)

#: What a caller gets without ``include``: what the swarm learned from what it kept.
DEFAULT_SECTIONS = ("about", "learned", "connections", "ideas")

#: An arXiv identifier inside free text, such as a reading's related_papers entry.
_ARXIV_ID = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")

#: Letters from the weighted score, highest first. The bar is high on purpose.
_LETTERS = (
    (97, "A+"),
    (93, "A"),
    (90, "A-"),
    (87, "B+"),
    (83, "B"),
    (80, "B-"),
    (77, "C+"),
    (73, "C"),
    (70, "C-"),
    (60, "D"),
)
_ORDER = ["F", "D", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]

ABOUT = (
    "Atoll is a swarm of AI reading agents. New arXiv papers are ingested every"
    " pass and assigned to islands, each a research group with its own focus."
    " On each island, agents (a prompt, model settings and a set of tools) take"
    " the next unread paper, read it through tools, and submit a reading:"
    " a summary, claims with exact quotes as evidence, objections, related"
    " papers and idea seeds. Every quote is checked against the stored text."
    " Every step is stored as a replayable trace with its cost. Nothing ranks the"
    " agents: evolution mates them across islands and changes one thing, by a"
    " model when the budget allows and by rule otherwise, and people shape the"
    " swarm by archiving agents and selecting or deselecting papers. A month runs"
    " under a fixed budget. Assigned readers select a paper together when all"
    " vote to keep it. A person can select or deselect it for the swarm. Selections"
    " guide future reading until deselected. An unread, unselected paper expires after a fixed"
    " number of days."
)

LIMITS = (
    "A claim is checked once, when it is submitted: each evidence quote is"
    " matched against the paper's stored text and marked verified or not."
    " Nothing later tests whether a claim held up.",
    "Evolution has no fitness function. It mates agents across islands and"
    " changes one thing; nothing it does says an agent is better, only newer.",
    "A claim's stance (positive, neutral or negative toward the paper) is the"
    " reading agent's own label.",
    "Use is counted from public requests for a paper's record; it is shown to"
    " the model that breeds agents, and anyone can make the requests.",
    "A model proposes children when a provider is configured and the budget"
    " admits the call; otherwise a seeded rule does the mating.",
    "Full text comes only from arXiv's HTML versions; a paper without one is"
    " read from its abstract.",
    "This brief is computed from stored rows; it calls no model and costs"
    " nothing to read.",
)


def _ratio(part: float, whole: float) -> float | None:
    return part / whole if whole else None


def _pct(value: float | None) -> str:
    return "none to measure" if value is None else f"{round(value * 100)}%"


def _usd(micros: int | None) -> str:
    return "not reported" if micros is None else f"${micros / 1_000_000:,.4f}"


def _numbers(db: sqlite3.Connection, island_id: str | None) -> Json:
    """Every count the grade and the findings are made of."""
    where = "" if island_id is None else " WHERE island_id = :i"
    and_ = "" if island_id is None else " AND island_id = :i"
    p: dict[str, Any] = {"i": island_id}
    runs = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(status = 'completed'), 0),"
        " COALESCE(SUM(status = 'failed'), 0),"
        " COALESCE(SUM(status IN ('queued', 'running')), 0) FROM runs" + where,
        p,
    ).fetchone()
    failures = db.execute(
        "SELECT COALESCE(failure, 'unknown') AS reason, COUNT(*) AS n FROM runs"
        " WHERE status = 'failed'" + and_ + " GROUP BY reason ORDER BY n DESC LIMIT 5",
        p,
    ).fetchall()
    claims = depends = cited = with_objection = readings = 0
    stances = {"positive": 0, "neutral": 0, "negative": 0}
    for row in db.execute("SELECT claims, objections FROM readings" + where, p):
        readings += 1
        listed = loads(row["claims"])
        claims += len(listed)
        for claim in listed:
            if claim.get("stance") in stances:
                stances[claim["stance"]] += 1
            if claim.get("depends_on_paper", True):
                depends += 1
                cited += bool(claim.get("cited"))
        with_objection += bool(loads(row["objections"]))
    if island_id is None:
        papers = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(text_status = 'full_text'), 0) FROM papers"
        ).fetchone()
    else:
        papers = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(p.text_status = 'full_text'), 0)"
            " FROM papers p JOIN assignments a ON a.paper_id = p.id"
            " WHERE a.island_id = :i",
            p,
        ).fetchone()
    read = db.execute(
        "SELECT COUNT(DISTINCT paper_id) FROM readings" + where, p
    ).fetchone()[0]
    generations = dict(
        db.execute(
            "SELECT status, COUNT(*) FROM generations" + where + " GROUP BY status", p
        ).fetchall()
    )
    cost = db.execute(
        "SELECT COALESCE(SUM(amount_micros), 0) FROM cost_receipts"
        " WHERE settlement = 'settled'" + and_,
        p,
    ).fetchone()[0]
    likes = db.execute("SELECT COUNT(*) FROM likes" + where, p).fetchone()[0]
    liked_readings = db.execute(
        "SELECT COUNT(*) FROM readings d WHERE EXISTS (SELECT 1 FROM likes l"
        " WHERE l.run_id = d.run_id OR (l.target_kind = 'paper' AND l.target_id = d.paper_id))"
        + ("" if island_id is None else " AND d.island_id = :i"),
        p,
    ).fetchone()[0]
    return {
        "runs": runs[0],
        "completed_runs": runs[1],
        "failed_runs": runs[2],
        "open_runs": runs[3],
        "failure_reasons": [dict(row) for row in failures],
        "readings": readings,
        "claims": claims,
        "paper_claims": depends,
        "verified_claims": cited,
        "positive_claims": stances["positive"],
        "neutral_claims": stances["neutral"],
        "negative_claims": stances["negative"],
        "readings_with_objections": with_objection,
        "papers": papers[0],
        "full_text_papers": papers[1],
        "papers_read": read,
        "generations_committed": generations.get("committed", 0),
        "generations_skipped": generations.get("skipped", 0),
        "cost_micros": cost,
        "likes": int(likes),
        "liked_readings": int(liked_readings),
    }


def _criteria(n: Mapping[str, Any], per_run_max_micros: int) -> list[Json]:
    """Each criterion scored 0 to 100. No evidence scores zero, never a pass."""
    finished = n["completed_runs"] + n["failed_runs"]
    generations = n["generations_committed"] + n["generations_skipped"]
    mean_cost = n["cost_micros"] / n["completed_runs"] if n["completed_runs"] else None

    def score(value: float | None) -> int:
        return 0 if value is None else max(0, min(100, round(value * 100)))

    rows = [
        (
            "evidence",
            25,
            _ratio(n["verified_claims"], n["paper_claims"]),
            f"{n['verified_claims']} of {n['paper_claims']} paper claims carry a"
            " quote found in the stored text",
        ),
        (
            "reliability",
            15,
            _ratio(n["completed_runs"], finished),
            f"{n['completed_runs']} of {finished} finished runs ended with a reading",
        ),
        (
            "coverage",
            15,
            _ratio(n["papers_read"], n["papers"]),
            f"{n['papers_read']} of {n['papers']} stored papers have a reading",
        ),
        (
            "reception",
            10,
            _ratio(n["liked_readings"], n["readings"]),
            f"{n['liked_readings']} of {n['readings']} readings, or their papers, drew a like",
        ),
        (
            "criticism",
            10,
            _ratio(n["readings_with_objections"], n["readings"]),
            f"{n['readings_with_objections']} of {n['readings']} readings raise an"
            " objection",
        ),
        (
            "evolution",
            10,
            None
            if not generations
            else min(1.0, n["generations_committed"] / 4)
            * (n["generations_committed"] / generations),
            f"{n['generations_committed']} generations committed,"
            f" {n['generations_skipped']} skipped",
        ),
        (
            "full_text",
            5,
            _ratio(n["full_text_papers"], n["papers"]),
            f"{n['full_text_papers']} of {n['papers']} papers have full text",
        ),
        (
            "economy",
            10,
            None
            if mean_cost is None or per_run_max_micros <= 0
            else 1 - mean_cost / per_run_max_micros,
            f"{_usd(None if mean_cost is None else round(mean_cost))} per completed"
            f" run against a {_usd(per_run_max_micros)} cap",
        ),
    ]
    return [
        {
            "criterion": name,
            "weight": weight,
            "score": score(value),
            "measured": value is not None,
            "evidence": evidence,
        }
        for name, weight, value, evidence in rows
    ]


def _letter(score: float) -> str:
    for floor, letter in _LETTERS:
        if score >= floor:
            return letter
    return "F"


def grade(n: Mapping[str, Any], per_run_max_micros: int) -> Json:
    """The swarm's grade: a weighted score, a letter, and the caps holding it down."""
    criteria = _criteria(n, per_run_max_micros)
    score = sum(c["score"] * c["weight"] for c in criteria) / sum(
        c["weight"] for c in criteria
    )
    letter = _letter(score)
    caps: list[Json] = []

    def cap(ceiling: str, reason: str) -> None:
        caps.append({"ceiling": ceiling, "reason": reason})

    if n["readings"] == 0:
        cap("F", "no agent has produced a single reading")
    if n["readings"] < 25:
        cap("D", f"{n['readings']} readings is too few to judge anything")
    paper_claims = n["paper_claims"]
    if paper_claims and n["verified_claims"] / paper_claims < 0.6:
        cap("D", "fewer than 60% of paper claims carry a verified quote")
    if n["generations_committed"] == 0:
        cap("B-", "evolution has not committed a generation")
    cap("A-", "no claim is ever checked again after submission")
    for held in caps:
        if _ORDER.index(held["ceiling"]) < _ORDER.index(letter):
            letter = held["ceiling"]
    return {
        "letter": letter,
        "score": round(score, 1),
        "criteria": criteria,
        "caps": caps,
        "rule": (
            "The score weighs each criterion by its weight. A criterion with"
            " nothing to measure scores 0. Each cap is a ceiling on the letter."
        ),
    }


def _findings(n: Mapping[str, Any], graded: Mapping[str, Any]) -> list[str]:
    """Plain sentences about the swarm, worst first, each drawn from a number."""
    out: list[str] = []
    for c in sorted(graded["criteria"], key=lambda c: c["score"]):
        if not c["measured"]:
            out.append(
                f"{c['criterion'].capitalize()} cannot be measured yet: {c['evidence']}."
            )
        elif c["score"] < 50:
            out.append(
                f"{c['criterion'].capitalize()} fails at {c['score']}/100: {c['evidence']}."
            )
        elif c["score"] < 80:
            out.append(
                f"{c['criterion'].capitalize()} is middling at {c['score']}/100: {c['evidence']}."
            )
        else:
            out.append(
                f"{c['criterion'].capitalize()} holds at {c['score']}/100: {c['evidence']}."
            )
    for reason in n["failure_reasons"]:
        out.append(f"{reason['n']} runs failed with {reason['reason']}.")
    if n["open_runs"]:
        out.append(f"{n['open_runs']} runs are open right now.")
    if n["claims"]:
        out.append(
            f"The swarm has made {n['claims']} claims across {n['readings']} readings,"
            f" {n['claims'] / max(1, n['readings']):.1f} per reading."
        )
    return out


def _claims(
    db: sqlite3.Connection, island_id: str | None, paper_id: str | None, limit: int
) -> list[Json]:
    """The newest claims, each with its paper, agent and whether its quote was found."""
    clauses, params = [], []
    if island_id is not None:
        clauses.append("d.island_id = ?")
        params.append(island_id)
    if paper_id is not None:
        clauses.append("d.paper_id = ?")
        params.append(paper_id)
    rows = db.execute(
        "SELECT d.id, d.paper_id, p.title, d.island_id, d.genome_id, d.claims,"
        " d.objections, d.created_at FROM readings d JOIN papers p ON p.id = d.paper_id"
        + (" WHERE " + " AND ".join(clauses) if clauses else "")
        + " ORDER BY d.created_at DESC, d.id LIMIT ?",
        (*params, limit),
    ).fetchall()
    out: list[Json] = []
    for row in rows:
        for claim in loads(row["claims"]):
            evidence = claim.get("evidence") or []
            out.append(
                {
                    "text": claim["text"],
                    "paper_id": row["paper_id"],
                    "paper_title": row["title"],
                    "agent": agent_address(row["genome_id"], row["island_id"]),
                    "island_id": row["island_id"],
                    "reading_id": row["id"],
                    "depends_on_paper": claim.get("depends_on_paper", True),
                    "stance": claim.get("stance"),
                    "verified": bool(claim.get("cited")),
                    "quote": evidence[0]["quote"] if evidence else None,
                    "created_at": row["created_at"],
                }
            )
            if len(out) >= limit:
                return out
    return out


def _ranked_claims(claims: Sequence[Mapping[str, Any]]) -> list[Json]:
    """A reading's claims, those with a verified quote first."""
    ranked = sorted(claims, key=lambda claim: not claim.get("cited"))
    return [
        {
            "text": claim["text"],
            "stance": claim.get("stance"),
            "verified": bool(claim.get("cited")),
            "quote": (claim.get("evidence") or [{}])[0].get("quote"),
        }
        for claim in ranked
    ]


def _takeaways(db: sqlite3.Connection, paper_id: str) -> Json:
    """The newest reading's thesis, summary and three biggest takeaways."""
    row = db.execute(
        "SELECT genome_id, island_id, summary, thesis_quote, claims FROM readings"
        " WHERE paper_id = ? ORDER BY created_at DESC, id LIMIT 1",
        (paper_id,),
    ).fetchone()
    if row is None:
        return {"thesis": None, "summary": None, "takeaways": [], "read_by": None}
    return {
        "thesis": row["thesis_quote"] or None,
        "summary": row["summary"],
        "takeaways": _ranked_claims(loads(row["claims"]))[:3],
        "read_by": agent_address(row["genome_id"], row["island_id"]),
    }


def build_public_paper(
    db: sqlite3.Connection, paper_id: str, now: datetime, days: int
) -> Json:
    """One paper as the public may read it: its record and every reading of it."""
    paper = db.execute(
        "SELECT id, title, abstract, authors, primary_category, abs_url, text_status,"
        " first_seen_at,"
        " (SELECT group_concat(a.island_id) FROM assignments a WHERE a.paper_id = p.id)"
        " AS islands FROM papers p WHERE p.id = ?",
        (paper_id,),
    ).fetchone()
    if paper is None:
        raise NotFound(f"no paper {paper_id}")
    touched = db.execute(
        "SELECT EXISTS (SELECT 1 FROM assignments WHERE paper_id = :p AND kept = 1)",
        {"p": paper_id},
    ).fetchone()[0]
    kept_by = [
        row[0]
        for row in db.execute(
            "SELECT island_id FROM assignments WHERE paper_id = ? AND kept = 1"
            " ORDER BY island_id",
            (paper_id,),
        )
    ]
    released = db.execute(
        "SELECT created_at FROM paper_releases WHERE paper_id = ?", (paper_id,)
    ).fetchone()
    reached = paper["islands"].split(",") if paper["islands"] else []
    let_go = released is not None
    held = bool(touched) and not let_go
    selection = db.execute(
        "SELECT actor, selected, note, created_at FROM paper_selections WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    seen = datetime.strptime(paper["first_seen_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=now.tzinfo
    )
    rows = db.execute(
        "SELECT id, genome_id, island_id, summary, thesis_quote, claims, objections,"
        " idea_seeds, created_at FROM readings WHERE paper_id = ?"
        " ORDER BY created_at DESC, id",
        (paper_id,),
    ).fetchall()
    return {
        "paper": {
            "id": paper["id"],
            "title": paper["title"],
            "abstract": paper["abstract"],
            "authors": loads(paper["authors"]),
            "primary_category": paper["primary_category"],
            "url": paper["abs_url"],
            "text_status": paper["text_status"],
            "islands": reached,
            "first_seen_at": paper["first_seen_at"],
        },
        "held": held,
        "selected": held,
        "selection": dict(selection) if selection is not None else None,
        "selected_by": (selection["actor"] if selection is not None else "readers")
        if held
        else None,
        "kept_by": kept_by,
        "released": let_go,
        "released_at": released["created_at"] if released else None,
        "used": paper_use(db, paper_id),
        "let_go_after": None if held or let_go else iso(seen + timedelta(days=days)),
        **_takeaways(db, paper_id),
        "readings": [
            {
                "id": row["id"],
                "agent": agent_address(row["genome_id"], row["island_id"]),
                "island_id": row["island_id"],
                "summary": row["summary"],
                "thesis": row["thesis_quote"] or None,
                "claims": _ranked_claims(loads(row["claims"])),
                "objections": loads(row["objections"]),
                "idea_seeds": loads(row["idea_seeds"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


def _takeaway(claim: Mapping[str, Any]) -> str:
    stance = claim.get("stance") or "unlabeled"
    mark = "verified" if claim["verified"] else "UNVERIFIED"
    return f"- [{stance}] {claim['text']} ({mark})"


def paper_use(db: sqlite3.Connection, paper_id: str) -> int:
    """How many times the public has asked for this paper's record."""
    used: int = db.execute(
        "SELECT COALESCE(SUM(hits), 0) FROM paper_traffic WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()[0]
    return used


def render_paper_text(view: Mapping[str, Any]) -> str:
    """One paper and its readings as Markdown."""
    p = view["paper"]
    lines = [f"# {p['title']}", "", f"arXiv {p['id']} · {p['url']}"]
    if view["held"]:
        lines.append(f"Selected by the swarm. Asked for {view['used']} times.")
    elif view["released"]:
        lines.append("Deselected by the swarm.")
    else:
        lines.append(
            f"Waiting: expires after {view['let_go_after']} if unread and unselected."
        )
    if view["thesis"]:
        lines += ["", f"Thesis: {view['thesis']}"]
    if view["takeaways"]:
        lines += ["", "Takeaways:"] + [_takeaway(t) for t in view["takeaways"]]
    lines += ["", "## Abstract", "", p["abstract"]]
    for r in view["readings"]:
        lines += ["", f"## Reading by {r['agent']}", "", r["summary"]]
        lines += [_takeaway(c) for c in r["claims"]]
        for o in r["objections"]:
            lines.append(f"- objection: {o}")
    return "\n".join(lines) + "\n"


def render_island_papers_html(db: sqlite3.Connection, island_id: str) -> str:
    """Web 1.0 HTML index of every paper ever assigned to an island."""
    rows = db.execute(
        "SELECT p.id, p.title, p.abstract, p.abs_url, p.primary_category,"
        " p.first_seen_at, a.kept, a.created_at AS assigned_at,"
        " EXISTS (SELECT 1 FROM paper_releases rl WHERE rl.paper_id = p.id) AS released,"
        " (SELECT COUNT(*) FROM readings r WHERE r.paper_id = p.id AND r.island_id = a.island_id) AS readings,"
        " (SELECT GROUP_CONCAT(pp.text, '\\n\\n') FROM paper_passages pp"
        " WHERE pp.paper_id = p.id ORDER BY pp.ordinal LIMIT 3) AS passages"
        " FROM assignments a JOIN papers p ON p.id = a.paper_id"
        " WHERE a.island_id = ? ORDER BY a.created_at DESC, p.id",
        (island_id,),
    ).fetchall()
    title = f"Atoll {island_id} paper chunks"
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(title)}</title>",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<style>body{font:18px/1.5 Georgia,serif;max-width:900px;margin:2rem auto;padding:0 1rem}article{border-top:1px solid #999;padding:1rem 0}pre{white-space:pre-wrap;font:inherit;background:#f7f7f7;padding:1rem}</style>",
        "</head><body>",
        f"<h1>{html.escape(title)}</h1>",
        "<p>Plain HTML chunks for indexing. Each entry links to the original paper and includes its abstract, newest stored passages and island reading summaries.</p>",
    ]
    for row in rows:
        status = (
            "deselected"
            if row["released"]
            else "selected"
            if row["kept"]
            else "waiting"
        )
        parts += [
            f'<article id="{html.escape(row["id"])}">',
            f"<h2>{html.escape(row['title'])}</h2>",
            f'<p><a href="{html.escape(row["abs_url"])}">{html.escape(row["id"])}</a> · {html.escape(row["primary_category"])} · {status} · {int(row["readings"])} readings</p>',
            f"<p>{html.escape(row['abstract'])}</p>",
        ]
        if row["passages"]:
            parts.append(f"<pre>{html.escape(str(row['passages'])[:6000])}</pre>")
        readings = db.execute(
            "SELECT genome_id, summary, claims, objections, idea_seeds FROM readings"
            " WHERE paper_id = ? AND island_id = ? ORDER BY created_at DESC LIMIT 5",
            (row["id"], island_id),
        ).fetchall()
        for reading in readings:
            claims = "; ".join(
                str(c.get("text", c)) for c in loads(reading["claims"])[:5]
            )
            ideas = "; ".join(str(i) for i in loads(reading["idea_seeds"])[:5])
            parts += [
                f"<h3>Reading by {html.escape(reading['genome_id'])}</h3>",
                f"<p>{html.escape(reading['summary'])}</p>",
                f"<p><b>Claims:</b> {html.escape(claims)}</p>",
                f"<p><b>Ideas:</b> {html.escape(ideas)}</p>",
            ]
        parts.append("</article>")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


def _states(island_id: str | None) -> tuple[str, str]:
    """SQL over ``p``: selection within scope and swarm-wide deselection.

    Letting go is swarm-wide, so it reads the same for every island.
    """
    touched = (
        "EXISTS (SELECT 1 FROM assignments a2 WHERE a2.paper_id = p.id AND a2.kept = 1"
        + (" AND a2.island_id = :i" if island_id is not None else "")
        + ")"
    )
    gone = "EXISTS (SELECT 1 FROM paper_releases rl WHERE rl.paper_id = p.id)"
    return touched, gone


def _scope(island_id: str | None) -> str:
    return (
        ""
        if island_id is None
        else " AND EXISTS (SELECT 1 FROM assignments a WHERE a.paper_id = p.id"
        " AND a.island_id = :i)"
    )


_PAPER_ROW = (
    "SELECT p.id, p.title, p.primary_category, p.text_status, p.first_seen_at,"
    " (SELECT group_concat(a.island_id) FROM assignments a WHERE a.paper_id = p.id)"
    " AS islands,"
    " (SELECT COALESCE(SUM(t.hits), 0) FROM paper_traffic t WHERE t.paper_id = p.id)"
    " AS used,"
    " (SELECT COUNT(*) FROM readings d WHERE d.paper_id = p.id) AS readings,"
    " (SELECT COUNT(*) FROM runs r WHERE r.paper_id = p.id) AS runs"
    " FROM papers p WHERE "
)


def _rows(db: sqlite3.Connection, sql: str, params: Mapping[str, Any]) -> list[Json]:
    listed = []
    for row in db.execute(sql, params).fetchall():
        item = dict(row)
        item["islands"] = row["islands"].split(",") if row["islands"] else []
        item["kept_by"] = [
            selected[0]
            for selected in db.execute(
                "SELECT island_id FROM assignments WHERE paper_id = ? AND kept = 1"
                " ORDER BY island_id",
                (row["id"],),
            )
        ]
        item["href"] = f"/api/v1/public/papers/{row['id']}"
        listed.append(item)
    return listed


def _days_left(item: Json, now: datetime, days: int) -> None:
    seen = datetime.strptime(item["first_seen_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=now.tzinfo
    )
    let_go = seen + timedelta(days=days)
    item["let_go_after"] = iso(let_go)
    item["days_left"] = max(0.0, round((let_go - now).total_seconds() / 86400, 1))


def _papers(
    db: sqlite3.Connection, now: datetime, days: int, island_id: str | None, limit: int
) -> Json:
    """What the swarm holds, what still waits, what it let go, and the newest papers."""
    touched, gone = _states(island_id)
    scope = _scope(island_id)
    params = {"i": island_id, "n": limit}
    held_count, waiting_count, released_count = db.execute(
        f"SELECT COALESCE(SUM({touched} AND NOT {gone}), 0),"
        f" COALESCE(SUM(NOT {touched} AND NOT {gone}), 0), COALESCE(SUM({gone}), 0)"
        " FROM papers p WHERE 1 = 1" + scope,
        params,
    ).fetchone()
    held = _rows(
        db,
        _PAPER_ROW
        + f"{touched} AND NOT {gone}"
        + scope
        + " ORDER BY p.first_seen_at DESC, p.id LIMIT :n",
        params,
    )
    waiting = _rows(
        db,
        _PAPER_ROW
        + f"NOT {touched} AND NOT {gone}"
        + scope
        + " ORDER BY p.first_seen_at, p.id LIMIT :n",
        params,
    )
    recent = _rows(
        db,
        _PAPER_ROW.replace("SELECT p.id,", f"SELECT {touched} AS held, p.id,")
        + f"NOT {gone}"
        + scope
        + " ORDER BY p.first_seen_at DESC, p.id LIMIT :n",
        params,
    )
    for item in held:
        item.update(_takeaways(db, item["id"]))
    for item in waiting:
        _days_left(item, now, days)
    for item in recent:
        item["held"] = bool(item["held"])
        if not item["held"]:
            _days_left(item, now, days)
    return {
        "held": held_count,
        "selected": held_count,
        "waiting": waiting_count,
        "released": released_count,
        "let_go_after_days": days,
        "rule": (
            "A paper is selected when every assigned reader on an island votes to keep it"
            " or a person selects it. Selections guide future reading until"
            " a person deselects it. A paper no island selects is deselected once all"
            " assigned cohorts have voted. An unread, unselected paper expires at"
            f" the first ingestion pass {days} days after it was first seen."
        ),
        "held_papers": held,
        "selected_papers": held,
        "waiting_papers": waiting,
        "recent_papers": recent,
    }


def _kept_readings(
    db: sqlite3.Connection, island_id: str | None, limit: int
) -> list[sqlite3.Row]:
    """The newest reading of each kept paper, newest first."""
    touched, gone = _states(island_id)
    return db.execute(
        "SELECT d.*, p.title FROM readings d JOIN papers p ON p.id = d.paper_id"
        f" WHERE NOT {gone}"
        + _scope(island_id)
        + " AND d.id = (SELECT d2.id FROM readings d2 WHERE d2.paper_id = p.id"
        " ORDER BY d2.created_at DESC, d2.id LIMIT 1)"
        " ORDER BY d.created_at DESC, d.id LIMIT :n",
        {"i": island_id, "n": limit},
    ).fetchall()


def _learned(rows: Sequence[sqlite3.Row], db: sqlite3.Connection) -> list[Json]:
    """What each kept paper taught the swarm: thesis, takeaways and ideas."""
    out = []
    for row in rows:
        islands = db.execute(
            "SELECT a.island_id FROM assignments a WHERE a.paper_id = ?"
            " ORDER BY a.island_id",
            (row["paper_id"],),
        ).fetchall()
        out.append(
            {
                "paper_id": row["paper_id"],
                "title": row["title"],
                "islands": [r[0] for r in islands],
                "thesis": row["thesis_quote"] or None,
                "summary": row["summary"],
                "takeaways": _ranked_claims(loads(row["claims"]))[:3],
                "ideas": loads(row["idea_seeds"]),
                "used": paper_use(db, row["paper_id"]),
                "objections": loads(row["objections"])[:2],
                "read_by": agent_address(row["genome_id"], row["island_id"]),
                "href": f"/api/v1/public/papers/{row['paper_id']}",
            }
        )
    return out


def _connections(rows: Sequence[sqlite3.Row]) -> list[Json]:
    """Links between kept papers, as readings named them, each with its reason."""
    kept = {row["paper_id"]: row["title"] for row in rows}
    edges: list[Json] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        for entry in loads(row["related_papers"]):
            for other in _ARXIV_ID.findall(entry):
                pair = (row["paper_id"], other)
                if other == row["paper_id"] or other not in kept or pair in seen:
                    continue
                seen.add(pair)
                edges.append(
                    {
                        "from": row["paper_id"],
                        "from_title": row["title"],
                        "to": other,
                        "to_title": kept[other],
                        "why": entry,
                    }
                )
    return edges


def _ideas(rows: Sequence[sqlite3.Row], limit: int) -> list[Json]:
    """The idea seeds the kept papers left, newest first, each with its source."""
    out: list[Json] = []
    for row in rows:
        for idea in loads(row["idea_seeds"]):
            out.append(
                {
                    "idea": idea,
                    "paper_id": row["paper_id"],
                    "paper_title": row["title"],
                    "agent": agent_address(row["genome_id"], row["island_id"]),
                }
            )
            if len(out) >= limit:
                return out
    return out


def build_brief(
    db: sqlite3.Connection,
    spec: Mapping[str, Any],
    budget: BudgetState,
    now: datetime,
    *,
    sections: Iterable[str] | None = None,
    island_id: str | None = None,
    paper_id: str | None = None,
    limit: int = 40,
) -> Json:
    """The brief as data: the asked sections, in their fixed order."""
    asked = set(DEFAULT_SECTIONS if sections is None else sections)
    wanted = [s for s in SECTIONS if s in asked]
    kept = (
        _kept_readings(db, island_id, limit)
        if asked & {"learned", "connections", "ideas"}
        else []
    )
    n = _numbers(db, island_id)
    graded = grade(n, budget.levers.per_run_max_micros)
    islands = [i for i in spec["islands"] if not i["archived"]]
    if island_id is not None:
        islands = [i for i in islands if i["id"] == island_id]
    brief: Json = {
        "generated_at": iso(now),
        "scope": {"island": island_id, "paper": paper_id},
        "sections": wanted,
    }
    for name in wanted:
        if name == "about":
            brief["about"] = ABOUT
        elif name == "learned":
            brief["learned"] = _learned(kept, db)
        elif name == "connections":
            brief["connections"] = _connections(kept)
        elif name == "ideas":
            brief["ideas"] = _ideas(kept, limit)
        elif name == "grade":
            brief["grade"] = graded
        elif name == "findings":
            brief["findings"] = _findings(n, graded)
        elif name == "numbers":
            brief["numbers"] = n
        elif name == "islands":
            brief["islands"] = [
                {
                    "id": i["id"],
                    "name": i["name"],
                    "focus": i["focus"],
                    "categories": i["categories"],
                    "agents": sum(1 for g in i["genomes"] if g["active"]),
                    "evolve": i["evolve"],
                    "paused": i["paused"],
                    "numbers": _numbers(db, i["id"]),
                }
                for i in islands
            ]
        elif name == "agents":
            brief["agents"] = _agents(db, islands)
        elif name == "claims":
            brief["claims"] = _claims(db, island_id, paper_id, limit)
        elif name == "papers":
            brief["papers"] = _papers(
                db, now, budget.levers.unread_paper_days, island_id, limit
            )
        elif name == "evolution":
            brief["evolution"] = _evolution(db, island_id, limit)
        elif name == "budget":
            brief["budget_state"] = {
                **budget.compact(),
                "per_run_max_micros": budget.levers.per_run_max_micros,
                "unread_paper_days": budget.levers.unread_paper_days,
            }
        elif name == "limits":
            brief["limits"] = list(LIMITS)
    return brief


def _agents(db: sqlite3.Connection, islands: Sequence[Mapping[str, Any]]) -> list[Json]:
    rows: list[Json] = []
    for island in islands:
        for genome in island["genomes"]:
            if not genome["active"]:
                continue
            stats = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(status = 'completed'), 0),"
                " COALESCE(SUM(status = 'failed'), 0) FROM runs WHERE genome_id = ?",
                (genome["id"],),
            ).fetchone()
            current = db.execute(
                "SELECT r.id, r.paper_id, p.title FROM runs r JOIN papers p"
                " ON p.id = r.paper_id WHERE r.genome_id = ?"
                " AND r.status IN ('queued', 'running') ORDER BY r.created_at LIMIT 1",
                (genome["id"],),
            ).fetchone()
            rows.append(
                {
                    "address": agent_address(genome["id"], island["id"]),
                    "island_id": island["id"],
                    "version": genome["version"],
                    "generation": genome["lineage"].get("generation", 0),
                    "tools": genome.get("allowed_tools", []),
                    "runs": stats[0],
                    "completed": stats[1],
                    "failed": stats[2],
                    "reading_now": None
                    if current is None
                    else {
                        "run_id": current["id"],
                        "paper_id": current["paper_id"],
                        "paper_title": current["title"],
                    },
                }
            )
    return rows


def _evolution(db: sqlite3.Connection, island_id: str | None, limit: int) -> list[Json]:
    rows = db.execute(
        "SELECT island_id, number, status, reason, decisions, created_at FROM generations"
        + ("" if island_id is None else " WHERE island_id = ?")
        + " ORDER BY created_at DESC, number DESC LIMIT ?",
        (limit,) if island_id is None else (island_id, limit),
    ).fetchall()
    out = []
    for row in rows:
        decisions = loads(row["decisions"])
        out.append(
            {
                "island_id": row["island_id"],
                "generation": row["number"],
                "status": row["status"],
                "reason": row["reason"],
                "decisions": [
                    {
                        key: d.get(key)
                        for key in (
                            "genome_id",
                            "decision",
                            "reason",
                            "usefulness",
                            "parents",
                            "why",
                            "why_archive",
                            "mutation",
                        )
                        if key in d
                    }
                    for d in (decisions if isinstance(decisions, list) else [])
                    if isinstance(d, Mapping)
                ],
                "created_at": row["created_at"],
            }
        )
    return out


def render_text(brief: Mapping[str, Any]) -> str:
    """The brief as Markdown, for an agent or a person to read as it is."""
    lines = ["# Atoll swarm brief", "", f"Generated {brief['generated_at']}."]
    scope = brief["scope"]
    if scope["island"] or scope["paper"]:
        lines.append(
            f"Scope: island {scope['island'] or 'all'}, paper {scope['paper'] or 'all'}."
        )
    if "about" in brief:
        lines += ["", "## What this is", "", brief["about"]]
    if "learned" in brief:
        lines += ["", "## What the swarm learned from the papers it keeps", ""]
        for item in brief["learned"]:
            lines.append(f"### {item['title']} (`{item['paper_id']}`)")
            if item["thesis"]:
                lines.append(f"Thesis: {item['thesis']}")
            lines += [_takeaway(t) for t in item["takeaways"]]
            lines += [f"- idea: {i}" for i in item["ideas"]]
            lines += ["", f"Full record: GET {item['href']}?format=text", ""]
    if "connections" in brief:
        lines += ["", "## Between the papers", ""]
        lines += [
            f"- {c['from']} → {c['to']}: {c['why']}" for c in brief["connections"]
        ] or ["- No reading has linked two kept papers yet."]
    if "ideas" in brief:
        lines += ["", "## Ideas", ""]
        lines += [f"- {i['idea']} (from {i['paper_id']})" for i in brief["ideas"]]
    if "grade" in brief:
        g = brief["grade"]
        lines += ["", f"## Grade: {g['letter']} ({g['score']}/100)", "", g["rule"], ""]
        lines += [
            f"- {c['criterion']} ({c['weight']}%): {c['score']}/100. {c['evidence']}."
            for c in g["criteria"]
        ]
        lines += ["", "Caps:"] + [f"- {c['ceiling']}: {c['reason']}" for c in g["caps"]]
    if "findings" in brief:
        lines += ["", "## Findings", ""] + [f"- {f}" for f in brief["findings"]]
    if "numbers" in brief:
        lines += ["", "## Numbers", ""] + [
            f"- {k}: {v}" for k, v in brief["numbers"].items() if k != "failure_reasons"
        ]
    if "islands" in brief:
        lines += ["", "## Islands", ""]
        for i in brief["islands"]:
            n = i["numbers"]
            lines.append(
                f"- **{i['name']}** (`{i['id']}`): {i['focus']} {i['agents']} agents,"
                f" {n['papers']} papers, {n['readings']} readings, {n['claims']} claims,"
                f" {_usd(n['cost_micros'])} spent."
            )
    if "agents" in brief:
        lines += ["", "## Agents", ""]
        for a in brief["agents"]:
            now_ = a["reading_now"]
            doing = (
                f"reading {now_['paper_id']} ({now_['paper_title']})"
                if now_
                else "idle"
            )
            lines.append(
                f"- `{a['address']}` v{a['version']} gen {a['generation']}: {a['runs']} runs,"
                f" {a['completed']} completed, {a['failed']} failed; {doing}."
            )
    if "claims" in brief:
        lines += ["", "## Claims, newest first", ""]
        for c in brief["claims"]:
            mark = ("verified quote" if c["verified"] else "UNVERIFIED") + (
                f", {c['stance']}" if c["stance"] else ""
            )
            lines.append(
                f"- {c['text']} [{mark}; {c['agent']} on {c['paper_id']}: {c['paper_title']}]"
            )
    if "papers" in brief:
        p = brief["papers"]
        lines += ["", "## Papers selected and deselected", "", p["rule"], ""]
        lines.append(
            f"Selected: {p['held']}. Waiting: {p['waiting']}. Deselected: {p['released']}."
        )
        for item in p["held_papers"]:
            lines.append(
                f"- selected `{item['id']}` {item['title']} ({item['readings']} readings)"
            )
            if item.get("thesis"):
                lines.append(f"  - thesis: {item['thesis']}")
            for t in item.get("takeaways") or []:
                lines.append(f"  {_takeaway(t)}")
            lines.append(f"  - full record: GET {item['href']}?format=text")
        for item in p["waiting_papers"]:
            lines.append(
                f"- waiting `{item['id']}` {item['title']} ({item['days_left']} days left)"
            )
    if "evolution" in brief:
        lines += ["", "## Evolution, newest first", ""]
        for e in brief["evolution"]:
            lines.append(
                f"- {e['island_id']} generation {e['generation']}: {e['status']}"
                + (f" ({e['reason']})" if e["reason"] else "")
            )
    if "budget_state" in brief:
        b = brief["budget_state"]
        lines += [
            "",
            "## Budget",
            "",
            f"Mode {b['mode']}. {_usd(b['month_to_date_micros'])} of"
            f" {_usd(b['target_micros'])} this month, projected"
            f" {_usd(b['projected_month_micros'])}. Runs allowed: {b['runs_allowed']}.",
        ]
    if "limits" in brief:
        lines += ["", "## What this brief cannot tell you", ""] + [
            f"- {item}" for item in brief["limits"]
        ]
    return "\n".join(lines) + "\n"


def build_activity(db: sqlite3.Connection, after: int, limit: int) -> Json:
    """The newest run steps, for a viewer that draws agents at work.

    Each step names its run, agent, island, paper, kind and tool, and the other
    papers it looked at (search hits or a cited paper read). No prompt, model
    text or tool output is shown. ``after`` is the last step id already seen.
    """
    rows = db.execute(
        "SELECT e.id, e.run_id, e.kind, e.payload, e.loc_passage_id, e.created_at,"
        " r.paper_id, r.island_id, r.genome_id FROM run_events e"
        " JOIN runs r ON r.id = e.run_id WHERE e.id > ? ORDER BY e.id DESC LIMIT ?",
        (after, limit),
    ).fetchall()
    steps: list[Json] = []
    mentioned: set[str] = set()
    for row in reversed(rows):
        payload = loads(row["payload"])
        tool = payload.get("name") if row["kind"] == "tool_call" else None
        looked_at: list[str] = []
        if tool == "related_papers" and payload.get("allowed"):
            result = payload.get("result") or {}
            for hit in result.get("results", []) if isinstance(result, Mapping) else []:
                pid = hit.get("paper_id") if isinstance(hit, Mapping) else None
                if isinstance(pid, str) and pid not in looked_at:
                    looked_at.append(pid)
        elif tool == "cited_paper_text":
            pid = (payload.get("arguments") or {}).get("paper_id")
            if isinstance(pid, str):
                looked_at.append(pid)
        mentioned.update([row["paper_id"], *looked_at])
        steps.append(
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "agent": agent_address(row["genome_id"], row["island_id"]),
                "island_id": row["island_id"],
                "paper_id": row["paper_id"],
                "kind": row["kind"],
                "tool": tool,
                "passage_id": row["loc_passage_id"],
                "looked_at": looked_at[:8],
                "created_at": row["created_at"],
            }
        )
    papers: dict[str, Json] = {}
    for pid in sorted(mentioned):
        found = db.execute(
            "SELECT p.id, p.title, p.primary_category,"
            " (SELECT group_concat(a.island_id) FROM assignments a WHERE a.paper_id = p.id)"
            " AS islands FROM papers p WHERE p.id = ?",
            (pid,),
        ).fetchone()
        if found is not None:
            papers[pid] = {
                **dict(found),
                "islands": found["islands"].split(",") if found["islands"] else [],
            }
    last = db.execute("SELECT COALESCE(MAX(id), 0) FROM run_events").fetchone()[0]
    return {"steps": steps, "papers": papers, "last_id": last}
