"""Chat over stored swarm data.

An answer is built from what the store holds: matching papers and readings,
a named run or paper, the island's activity and its costs. Every part of an
answer links back to the object it came from, and a question the store
cannot support is answered with exactly that. The question is never stored:
chat keeps no transcript, only the receipt of its retrieval.

Retrieval is free. A model-written answer is paid work and is attempted only
when asked for and the budget admits it; otherwise a short answer is built
from the retrieved records, and the reason the paid one was refused is given.
The model is shown each record's stored text (the abstract, or the agent's
reading), not the search fragment, so it can answer from what was stored.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from typing import Any

from research_agent.beta.budget import (
    BudgetState,
    admit_paid_chat,
    estimate_tokens,
    price_micros,
)
from research_agent.beta.config import ModelProvider
from research_agent.beta.costs import record_cost_receipt, sum_cost_scope
from research_agent.beta.db import Clock, Json, loads, new_id
from research_agent.beta.errors import Invalid
from research_agent.beta.models import ModelCallFailed, ModelClient
from research_agent.beta.papers import search

MESSAGE_LIMIT = 2000
#: Output allowed for a written answer. The model reasons out of the same
#: allowance before it writes, so a small one returns no text at all.
ANSWER_TOKENS = 2500
#: How much of each record's stored text the model is shown.
RECORD_CHARACTERS = 900

_RUN_ID = re.compile(r"\bR-[0-9a-f]{10}\b")
_PAPER_ID = re.compile(r"\b\d{4}\.\d{4,5}\b")
_COST_WORDS = frozenset("cost costs spend spent spending budget money price".split())
_ACTIVITY_WORDS = frozenset(
    "island storm swarm activity happening today status you your yours yourself my mine here".split()
)

NO_SUPPORT = "Nothing stored in the swarm supports an answer to that."
_SYSTEM = (
    "You answer questions about a research swarm's stored papers and the agents'"
    " readings of them. Use only the numbered stored records. Answer in a few"
    " plain sentences, cite each record you rely on as [n], and say plainly when"
    " the records do not answer the question."
)


def _link(kind: str, ref: str, title: str, snippet: str, record: str = "") -> Json:
    """One retrieved object; ``record`` is the stored text the model may read."""
    path = {"paper": "/papers/", "run": "/runs/", "island": "/islands/"}[kind]
    return {
        "kind": kind,
        "id": ref,
        "href": path + ref,
        "title": title,
        "snippet": snippet,
        "record": record or snippet,
    }


def _clip(text: str, limit: int) -> str:
    """Text cut at a word boundary near ``limit``, marked when it was cut."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " …"


def _paper_link(
    db: sqlite3.Connection, paper_id: str, why: str = "", island_id: str | None = None
) -> Json | None:
    if island_id is None:
        row = db.execute(
            "SELECT id, title, abstract FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
    else:
        row = db.execute(
            "SELECT p.id, p.title, p.abstract FROM papers p"
            " JOIN assignments a ON a.paper_id = p.id"
            " WHERE p.id = ? AND a.island_id = ?",
            (paper_id, island_id),
        ).fetchone()
    if row is None:
        return None
    return _link(
        "paper",
        row["id"],
        row["title"],
        why or _clip(row["abstract"], 180),
        _clip(row["abstract"], RECORD_CHARACTERS) or "No text is stored.",
    )


def _reading_link(
    db: sqlite3.Connection, run_id: str, island_id: str | None = None
) -> Json | None:
    if island_id is None:
        row = db.execute(
            "SELECT d.run_id, d.summary, d.claims, d.genome_id, p.title FROM readings d"
            " JOIN papers p ON p.id = d.paper_id WHERE d.run_id = ?",
            (run_id,),
        ).fetchone()
    else:
        row = db.execute(
            "SELECT d.run_id, d.summary, d.claims, d.genome_id, p.title FROM readings d"
            " JOIN papers p ON p.id = d.paper_id WHERE d.run_id = ? AND d.island_id = ?",
            (run_id, island_id),
        ).fetchone()
    if row is None:
        return None
    claims = [claim["text"] for claim in loads(row["claims"])][:4]
    record = row["summary"] + (" Claims: " + " ".join(claims) if claims else "")
    return _link(
        "run",
        row["run_id"],
        f"Reading of {row['title']}",
        f"{row['genome_id']}: {_clip(row['summary'], 160)}",
        _clip(record, RECORD_CHARACTERS),
    )


def _island_context(db: sqlite3.Connection, island: Mapping[str, Any]) -> list[Json]:
    """Baseline records that make every chat about this island's swarm."""
    island_id = str(island["id"])
    row = db.execute(
        "SELECT (SELECT COUNT(*) FROM assignments WHERE island_id = :i),"
        " (SELECT COUNT(*) FROM runs WHERE island_id = :i),"
        " (SELECT COUNT(*) FROM readings WHERE island_id = :i)",
        {"i": island_id},
    ).fetchone()
    links = [
        _link(
            "island",
            island_id,
            f"{island['name']} swarm",
            f"{row[0]} papers assigned, {row[1]} runs, {row[2]} readings",
        )
    ]
    for row in db.execute(
        "SELECT p.id, p.title, p.abstract FROM papers p"
        " JOIN assignments a ON a.paper_id = p.id"
        " WHERE a.island_id = ? ORDER BY a.created_at DESC LIMIT 3",
        (island_id,),
    ):
        links.append(
            _link(
                "paper",
                row["id"],
                row["title"],
                _clip(row["abstract"], 180),
                _clip(row["abstract"], RECORD_CHARACTERS) or "No text is stored.",
            )
        )
    for row in db.execute(
        "SELECT d.run_id, d.summary, d.claims, d.genome_id, p.title FROM readings d"
        " JOIN papers p ON p.id = d.paper_id WHERE d.island_id = ?"
        " ORDER BY d.created_at DESC LIMIT 3",
        (island_id,),
    ):
        claims = [claim["text"] for claim in loads(row["claims"])][:4]
        record = row["summary"] + (" Claims: " + " ".join(claims) if claims else "")
        links.append(
            _link(
                "run",
                row["run_id"],
                f"Reading of {row['title']}",
                f"{row['genome_id']}: {_clip(row['summary'], 160)}",
                _clip(record, RECORD_CHARACTERS),
            )
        )
    return links


def _append_unique(links: list[Json], found: Json | None) -> None:
    if found is None:
        return
    if not any(
        seen["kind"] == found["kind"] and seen["id"] == found["id"] for seen in links
    ):
        links.append(found)


def _retrieve(
    db: sqlite3.Connection, island: Mapping[str, Any], message: str
) -> list[Json]:
    """Every stored record the question touches, plus island context."""
    links: list[Json] = _island_context(db, island)
    words = set(re.findall(r"[a-z]+", message.lower()))
    island_id = str(island["id"])
    for run_id in _RUN_ID.findall(message):
        row = db.execute(
            "SELECT r.id, r.status, r.genome_id, p.title FROM runs r JOIN papers p"
            " ON p.id = r.paper_id WHERE r.id = ?",
            (run_id,),
        ).fetchone()
        if row is not None and row["id"] in {
            seen["run_id"]
            for seen in db.execute(
                "SELECT id AS run_id FROM runs WHERE island_id = ?", (island_id,)
            )
        }:
            detail = f"run by genome {row['genome_id']}, status {row['status']}"
            links.append(_link("run", row["id"], row["title"], detail))
    for paper_id in _PAPER_ID.findall(message):
        named = _paper_link(db, paper_id, "named in the question", island_id)
        _append_unique(links, named)
    if words & _COST_WORDS:
        cost = sum_cost_scope(db, "island_id", island_id)
        links.append(
            _link(
                "island",
                island_id,
                f"{island['name']} cost",
                f"settled cost {cost['settled_micros'] / 1_000_000:.4f} USD over"
                f" {cost['receipt_count']} receipts, {cost['unsettled_count']} unsettled",
            )
        )
    if words & _ACTIVITY_WORDS:
        row = db.execute(
            "SELECT (SELECT COUNT(*) FROM assignments WHERE island_id = :i),"
            " (SELECT COUNT(*) FROM runs WHERE island_id = :i),"
            " (SELECT COUNT(*) FROM readings WHERE island_id = :i)",
            {"i": island_id},
        ).fetchone()
        _append_unique(
            links,
            _link(
                "island",
                island_id,
                f"{island['name']} activity",
                f"{row[0]} papers assigned, {row[1]} runs, {row[2]} readings",
            ),
        )
    for hit in search(db, message, 8):
        found = (
            _reading_link(db, hit["ref_id"], island_id)
            if hit["kind"] == "reading"
            else _paper_link(db, hit["ref_id"], island_id=island_id)
        )
        if found is None:
            continue
        _append_unique(links, found)
    return links


def _retrieval_answer(links: list[Json]) -> str:
    """A short answer built from the records alone, for when no model writes one."""
    if not links:
        return NO_SUPPORT
    facts = [link for link in links if link["kind"] == "island"]
    papers = [link for link in links if link["kind"] == "paper"]
    readings = [link for link in links if link["kind"] == "run"]
    parts = [f"{fact['title']}: {fact['snippet']}." for fact in facts]
    if papers or readings:
        found = []
        if papers:
            found.append(f"{len(papers)} paper{'s' if len(papers) != 1 else ''}")
        if readings:
            found.append(f"{len(readings)} reading{'s' if len(readings) != 1 else ''}")
        top = [f"“{link['title']}”" for link in (papers or readings)[:3]]
        parts.append(
            f"The swarm is looking across {' and '.join(found)} for paper claims and patterns. The closest: "
            + "; ".join(top)
            + ". Open one below to see what was stored."
        )
    return " ".join(parts)


def answer_question(
    db: sqlite3.Connection,
    *,
    island: Mapping[str, Any],
    message: str,
    synthesize: bool,
    state: BudgetState,
    provider: ModelProvider | None,
    client: ModelClient | None,
    clock: Clock,
) -> Json:
    """Answer one question from stored data, with links and its cost."""
    if not message.strip():
        raise Invalid("a question needs text", "message")
    if len(message) > MESSAGE_LIMIT:
        raise Invalid(f"a question is at most {MESSAGE_LIMIT} characters", "message")
    island_id = str(island["id"])
    links = _retrieve(db, island, message)
    answer_id = new_id("CH")
    common: dict[str, Any] = {
        "owner_kind": "chat",
        "owner_id": answer_id,
        "parent_kind": "island",
        "parent_id": island_id,
        "island_id": island_id,
    }
    retrieval = record_cost_receipt(
        db,
        action="chat_retrieval",
        unit_type="stored_lookup",
        quantity=1,
        amount_micros=0,
        now=clock(),
        **common,
    )
    receipts, amount = [retrieval], 0
    answer = _retrieval_answer(links)
    mode, refused = "retrieval", None
    if synthesize and links:
        lines = [
            f"[{n}] {link['title']}\n{link['record']}"
            for n, link in enumerate(links, 1)
        ]
        prompt = f"Question: {message}\n\nStored records:\n\n" + "\n\n".join(lines)
        estimate = (
            price_micros(provider, estimate_tokens(_SYSTEM + prompt), ANSWER_TOKENS)
            if provider
            else 0
        )
        refused = admit_paid_chat(state, estimate)
        if refused is None and provider is not None and client is not None:
            try:
                reply = client.complete(
                    [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    [],
                    max_output_tokens=ANSWER_TOKENS,
                    temperature=0.2,
                )
            except ModelCallFailed:
                refused = "model_call_failed"
                receipts.append(
                    record_cost_receipt(
                        db,
                        action="chat_answer",
                        unit_type="tokens",
                        quantity=estimate_tokens(prompt),
                        amount_micros=estimate,
                        now=clock(),
                        provider=provider.name,
                        estimated=True,
                        settled=False,
                        **common,
                    )
                )
            else:
                amount = price_micros(provider, reply.input_tokens, reply.output_tokens)
                receipts.append(
                    record_cost_receipt(
                        db,
                        action="chat_answer",
                        unit_type="tokens",
                        quantity=reply.input_tokens + reply.output_tokens,
                        amount_micros=amount,
                        now=clock(),
                        provider=provider.name,
                        estimated=not reply.usage_reported,
                        **common,
                    )
                )
                if reply.text.strip():
                    answer, mode = reply.text.strip(), "synthesized"
    return {
        # The retrieval receipt is the answer's id: feedback on a chat answer targets it.
        "answer_id": retrieval,
        "answer": answer,
        "supported": bool(links),
        "mode": mode,
        # The stored text shown to the model stays on the server side of the answer.
        "links": [
            {key: value for key, value in link.items() if key != "record"}
            for link in links
        ],
        "paid": {
            "requested": synthesize,
            "used": mode == "synthesized",
            "refused": refused,
        },
        # What this answer cost, not the island's running total.
        "cost_micros": amount,
        "receipt_ids": receipts,
    }
