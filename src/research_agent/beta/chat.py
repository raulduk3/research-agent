"""Chat over stored swarm data.

An answer is built from what the store holds: matching papers and readings,
a named run or paper, the island's activity and its costs. Every part of an
answer links back to the object it came from, and a question the store
cannot support is answered with exactly that. The question is never stored:
chat keeps no transcript, only the receipt of its retrieval.

Retrieval is free. A model-written answer is paid work and is attempted only
when asked for and the budget admits it; otherwise the retrieval answer is
returned with the reason the paid one was refused.
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
from research_agent.beta.db import Clock, Json, new_id
from research_agent.beta.errors import Invalid
from research_agent.beta.models import ModelCallFailed, ModelClient
from research_agent.beta.papers import search

MESSAGE_LIMIT = 2000
ANSWER_TOKENS = 400

_RUN_ID = re.compile(r"\bR-[0-9a-f]{10}\b")
_PAPER_ID = re.compile(r"\b\d{4}\.\d{4,5}\b")
_COST_WORDS = frozenset("cost costs spend spent spending budget money price".split())
_ACTIVITY_WORDS = frozenset(
    "island storm swarm activity happening today status".split()
)

NO_SUPPORT = "Nothing stored in the swarm supports an answer to that."
_SYSTEM = (
    "Answer the question using only the numbered stored records. Cite each record"
    " you rely on as [n]. If the records do not answer the question, say so."
)


def _link(kind: str, ref: str, title: str, snippet: str) -> Json:
    path = {"paper": "/papers/", "run": "/runs/", "island": "/islands/"}[kind]
    return {
        "kind": kind,
        "id": ref,
        "href": path + ref,
        "title": title,
        "snippet": snippet,
    }


def _retrieve(
    db: sqlite3.Connection, island: Mapping[str, Any], message: str
) -> list[Json]:
    """Every stored record the question touches, as links."""
    links: list[Json] = []
    words = set(re.findall(r"[a-z]+", message.lower()))
    island_id = str(island["id"])
    for run_id in _RUN_ID.findall(message):
        row = db.execute(
            "SELECT r.id, r.status, r.genome_id, p.title FROM runs r JOIN papers p"
            " ON p.id = r.paper_id WHERE r.id = ?",
            (run_id,),
        ).fetchone()
        if row is not None:
            detail = f"run by genome {row['genome_id']}, status {row['status']}"
            links.append(_link("run", row["id"], row["title"], detail))
    for paper_id in _PAPER_ID.findall(message):
        row = db.execute(
            "SELECT id, title FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if row is not None:
            links.append(
                _link("paper", row["id"], row["title"], "named in the question")
            )
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
        links.append(
            _link(
                "island",
                island_id,
                f"{island['name']} activity",
                f"{row[0]} papers assigned, {row[1]} runs, {row[2]} readings",
            )
        )
    for hit in search(db, message, 8):
        kind = "run" if hit["kind"] == "reading" else "paper"
        link = _link(kind, hit["ref_id"], hit["title"], hit["snippet"])
        if not any(seen["kind"] == kind and seen["id"] == link["id"] for seen in links):
            links.append(link)
    return links


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
    lines = [
        f"[{n}] {link['title']}: {link['snippet']}" for n, link in enumerate(links, 1)
    ]
    answer = "\n".join(lines) if links else NO_SUPPORT
    mode, refused = "retrieval", None
    if synthesize and links:
        prompt = f"Question: {message}\n\nStored records:\n" + "\n".join(lines)
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
        "links": links,
        "paid": {
            "requested": synthesize,
            "used": mode == "synthesized",
            "refused": refused,
        },
        "cost": {"receipt_ids": receipts, "amount_micros": amount},
    }
