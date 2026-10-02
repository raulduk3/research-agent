"""One-paper agent runs: creation, the tool harness and the event trace.

A run is one genome version reading one paper. Creating it fixes the prompt,
the genome copy, the limits and a cost estimate, and passes budget admission
before any model call. Executing it appends one immutable event per step:
the prompt, each model call with its receipt, each tool call (allowed or
refused), each passage read, each note, the submitted reading and how the
run ended. Every event is committed as it happens, so a run that stops
half-way keeps its trace and its cost, and the run page replays the events
in order. What the page says a run did comes from these events alone.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from research_agent.beta.budget import (
    admit_run,
    budget_state,
    estimate_tokens,
    fit_run_to_cap,
    price_micros,
)
from research_agent.beta.config import ModelProvider
from research_agent.beta.costs import record_cost_receipt, sum_cost_scope
from research_agent.beta.db import Clock, Json, connect, dumps, iso, loads, new_id
from research_agent.beta.errors import Conflict, Invalid, Refusal, Unavailable
from research_agent.beta.models import (
    Message,
    ModelCallFailed,
    ModelClient,
    ModelResponse,
    ToolCall,
    ToolSchema,
    assistant_message,
    tool_schema,
)
from research_agent.beta.papers import get_paper, index_document, load_passages, search
from research_agent.beta.spec import find_genome, find_island

EVENT_KINDS = (
    "run_started",
    "prompt",
    "model_call",
    "tool_call",
    "paper_read",
    "note",
    "reading_submitted",
    "run_completed",
    "run_failed",
)
#: The most text one tool result or event payload carries.
RESULT_LIMIT = 6000
#: The least output any model call is given. A model that reasons before it
#: answers spends its reasoning out of the same allowance; at 900 tokens the
#: reasoning alone filled it and the call returned no tool call at all.
STEP_OUTPUT_TOKENS = 2500
#: The least output a submission call is given: the reasoning, then a reading
#: of several hundred tokens of structured JSON that must arrive whole.
SUBMIT_OUTPUT_TOKENS = 4000
#: Extra submission-only calls a run gets when its last submission is cut
#: off, malformed or rejected, with the reason it failed.
SUBMIT_RETRIES = 1
#: Stored text up to this many characters is placed in the prompt, so the
#: agent does not spend a model call fetching what it must read anyway.
INLINE_TEXT_LIMIT = 6000

_TEXT_LIST = {"type": "array", "items": {"type": "string"}}
TOOLS: dict[str, ToolSchema] = {
    "paper_text": tool_schema(
        "paper_text",
        "Return stored text of the paper by passage. Only the passage ids the"
        " prompt lists exist; there are no other sections.",
        {"type": "object", "properties": {"passage_id": {"type": "string"}}},
    ),
    "related_papers": tool_schema(
        "related_papers",
        "Search the stored papers and readings for related work.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    "capture_note": tool_schema(
        "capture_note",
        "Keep a working note. Give an exact quote from the paper when the note rests on one.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["text"],
        },
    ),
    "feedback_context": tool_schema(
        "feedback_context",
        "Show what readers on this island have accepted, passed on or pushed away.",
        {"type": "object", "properties": {}},
    ),
    "cost_state": tool_schema(
        "cost_state",
        "Show what this run has spent and the calls it has left.",
        {"type": "object", "properties": {}},
    ),
    "submit_reading": tool_schema(
        "submit_reading",
        "Submit the final reading and end the run. A claim that depends on the paper"
        " text needs at least one exact quote as evidence.",
        {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "depends_on_paper": {"type": "boolean"},
                            "evidence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "quote": {"type": "string"},
                                        "passage_id": {"type": "string"},
                                    },
                                    "required": ["quote"],
                                },
                            },
                        },
                        "required": ["text"],
                    },
                },
                "objections": _TEXT_LIST,
                "related_papers": _TEXT_LIST,
                "idea_seeds": _TEXT_LIST,
            },
            "required": [
                "summary",
                "claims",
                "objections",
                "related_papers",
                "idea_seeds",
            ],
        },
    ),
}

HARNESS_RULES = (
    "You are one agent reading one paper. Work through the tools you are given."
    " Quote the paper exactly when you cite it; every quote is checked against"
    " the stored text. End the run by calling submit_reading once. Prose outside"
    " a tool call is not kept as the reading."
)


LAST_CALL_NOTICE = "This is the last model call of the run. Call submit_reading now."
NEXT_IS_LAST_NOTICE = (
    "After this call only submit_reading is offered. Finish gathering now."
)
NO_TOOL_NOTICE = "The run continues only through tools. Call submit_reading to finish."
RETRY_NOTICE = (
    "Your reading was not accepted: {problem}. This is one more call to submit"
    " it. Call submit_reading once, with complete JSON arguments and shorter text."
)
ARGUMENTS_NOT_JSON = (
    "The arguments were not complete JSON; they were probably cut off."
    " Send the call again with shorter text."
)


@dataclass(frozen=True)
class Locator:
    """Where in a paper an event points."""

    paper_id: str
    source_kind: str
    passage_id: str | None = None
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    snippet: str | None = None

    def json(self) -> Json:
        return {
            "paper_id": self.paper_id,
            "source_kind": self.source_kind,
            "section": self.passage_id,
            "passage_id": self.passage_id,
            "page": self.page,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "quote": self.snippet,
        }


def append_run_event(
    db: sqlite3.Connection,
    run_id: str,
    kind: str,
    payload: Mapping[str, Any],
    *,
    now: datetime,
    receipt_id: str | None = None,
    cost_state: str = "none",
    locator: Locator | None = None,
) -> int:
    """Append one immutable event to a run's trace and return its sequence.

    A model call is paid work: it must carry its receipt, settled or not.
    """
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown run event kind {kind!r}")
    if kind == "model_call" and (receipt_id is None or cost_state == "none"):
        raise ValueError("a model call event needs its cost receipt")
    seq = int(
        db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM run_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
    )
    spot = locator or Locator("", "")
    db.execute(
        "INSERT INTO run_events(run_id, seq, kind, payload, receipt_id, cost_state,"
        " loc_paper_id, loc_source_kind, loc_page, loc_char_start, loc_char_end,"
        " loc_passage_id, loc_snippet, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            seq,
            kind,
            dumps(payload),
            receipt_id,
            cost_state,
            spot.paper_id or None,
            spot.source_kind or None,
            spot.page,
            spot.char_start,
            spot.char_end,
            spot.passage_id,
            spot.snippet,
            iso(now),
        ),
    )
    return seq


def locate_quote(
    paper_id: str, passages: Sequence[Mapping[str, Any]], quote: str
) -> Locator | None:
    """Find a quote in the stored passages; ``None`` when the text lacks it."""
    wanted = " ".join(quote.split())
    if not wanted:
        return None
    for passage in passages:
        text = str(passage["text"])
        start = text.find(wanted)
        if start < 0:
            start = text.lower().find(wanted.lower())
        if start >= 0:
            offset = int(passage["char_start"]) + start
            return Locator(
                paper_id=paper_id,
                source_kind=str(passage["kind"]),
                passage_id=str(passage["id"]),
                page=passage["page"],
                char_start=offset,
                char_end=offset + len(wanted),
                snippet=text[start : start + len(wanted)][:400],
            )
    return None


def _text_list(value: Any, name: str, most: int) -> list[str]:
    if not isinstance(value, list) or len(value) > most:
        raise Invalid(f"{name} is a list of at most {most} entries", name)
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 600:
            raise Invalid(f"{name} entries are text of at most 600 characters", name)
    return [item.strip() for item in value]


def validate_reading_submission(
    arguments: Mapping[str, Any], paper_id: str, passages: Sequence[Mapping[str, Any]]
) -> Json:
    """Check a submitted reading and return it with each quote verified.

    Every field must be present. A claim that depends on the paper text must
    cite a quote; a quote the stored text does not contain is kept and marked
    unverified, never accepted as evidence.
    """
    for name in ("summary", "claims", "objections", "related_papers", "idea_seeds"):
        if name not in arguments:
            raise Invalid(f"a reading must contain {name}", name)
    summary = arguments["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise Invalid("summary is text of at most 2000 characters", "summary")
    raw_claims = arguments["claims"]
    if not isinstance(raw_claims, list) or not 1 <= len(raw_claims) <= 8:
        raise Invalid("claims is a list of one to eight claims", "claims")
    claims: list[Json] = []
    for index, raw in enumerate(raw_claims):
        where = f"claims[{index}]"
        if not isinstance(raw, Mapping) or not isinstance(raw.get("text"), str):
            raise Invalid("a claim is an object with text", where)
        text = raw["text"].strip()
        if not text or len(text) > 600:
            raise Invalid("claim text is at most 600 characters", f"{where}.text")
        depends = raw.get("depends_on_paper", True)
        if not isinstance(depends, bool):
            raise Invalid(
                "depends_on_paper is true or false", f"{where}.depends_on_paper"
            )
        raw_evidence = raw.get("evidence", [])
        if not isinstance(raw_evidence, list) or len(raw_evidence) > 4:
            raise Invalid(
                "evidence is a list of at most four quotes", f"{where}.evidence"
            )
        evidence: list[Json] = []
        for item in raw_evidence:
            quote = item.get("quote") if isinstance(item, Mapping) else item
            if not isinstance(quote, str) or not quote.strip():
                raise Invalid("an evidence entry carries a quote", f"{where}.evidence")
            found = locate_quote(paper_id, passages, quote)
            evidence.append(
                {
                    "quote": quote.strip()[:600],
                    "verified": found is not None,
                    "locator": found.json() if found else None,
                }
            )
        if depends and not evidence:
            raise Invalid(
                "a claim that depends on the paper text needs an evidence quote",
                f"{where}.evidence",
            )
        claims.append(
            {
                "text": text,
                "depends_on_paper": depends,
                "evidence": evidence,
                "cited": any(item["verified"] for item in evidence),
            }
        )
    return {
        "summary": summary.strip(),
        "claims": claims,
        "objections": _text_list(arguments["objections"], "objections", 6),
        "related_papers": _text_list(arguments["related_papers"], "related_papers", 8),
        "idea_seeds": _text_list(arguments["idea_seeds"], "idea_seeds", 6),
    }


def build_prompt(
    genome: Mapping[str, Any],
    island: Mapping[str, Any],
    paper: sqlite3.Row,
    passages: Sequence[Mapping[str, Any]],
    reading_mode: str,
    limits: Mapping[str, Any],
) -> tuple[str, str]:
    """The system and user text a run starts from."""
    system = "\n\n".join(
        (
            str(genome["prompt"]),
            f"Reading strategy: {genome['reading_strategy']}",
            f"Island: {island['name']}. Focus: {island['focus']}.",
            HARNESS_RULES,
            f"Limits: {limits['max_model_calls']} model calls, {limits['max_tool_calls']}"
            f" tool calls, {limits['max_output_tokens']} output tokens per call.",
        )
    )
    lines = [
        f"Paper {paper['id']} (version {paper['version']})",
        f"Title: {paper['title']}",
        f"Authors: {', '.join(loads(paper['authors']))}",
        f"Categories: {', '.join(loads(paper['categories']))}",
        f"Published: {paper['published_at']}",
    ]
    if not passages:
        lines.append("No text is stored for this paper; read from the metadata alone.")
    elif text_is_inline(passages):
        lines.append(
            "Stored text. This is everything stored for this paper; no other"
            " section exists:"
        )
        lines += [
            f"Passage {passage['id']} ({passage['kind']}): {passage['text']}"
            for passage in passages
        ]
    else:
        lines.append("Stored passages, to be read with paper_text; no others exist:")
        lines += [
            f"- {passage['id']} ({passage['kind']}, {len(passage['text'])} characters)"
            for passage in passages
        ]
    if reading_mode == "metadata":
        lines.append("Submit the reading now with submit_reading.")
    else:
        lines.append(
            "Capture notes or look for related stored papers if that helps, then"
            " call submit_reading. The last model call can only submit."
        )
    return system, "\n".join(lines)


def text_is_inline(passages: Sequence[Mapping[str, Any]]) -> bool:
    """Whether a paper's stored text is short enough to sit in the prompt."""
    return sum(len(str(passage["text"])) for passage in passages) <= INLINE_TEXT_LIMIT


def create_run(
    db: sqlite3.Connection,
    *,
    spec: Mapping[str, Any],
    revision: int,
    provider: ModelProvider | None,
    clock: Clock,
    paper_id: str,
    island_id: str,
    genome_id: str | None = None,
    seed: int | None = None,
) -> str:
    """Create one queued run for one paper under one genome version.

    Refuses before any model call when the paper or genome does not exist,
    when the genome is not this island's or is switched off, or when the
    budget, a pause or the island's share forbids the run.
    """
    now = clock()
    paper = get_paper(db, paper_id)
    island = find_island(spec, island_id)
    if genome_id is None:
        genome_id = next_genome(db, island)
    home, genome = find_genome(spec, genome_id)
    if home["id"] != island_id:
        raise Invalid(f"genome {genome_id} belongs to island {home['id']}", "genome_id")
    if not genome["active"]:
        raise Conflict(f"genome_inactive: genome {genome_id} is switched off")
    if provider is None:
        raise Unavailable(
            "model_provider_not_configured: no model endpoint is configured"
        )

    state = budget_state(db, spec, now, provider_configured=True)
    plan = state.plan
    passages = load_passages(db, paper_id)
    mode = str(island["reading_mode"])
    # A metadata reading is one call; a second is kept for a rejected submission.
    max_calls = (
        min(2, plan.max_model_calls) if mode == "metadata" else plan.max_model_calls
    )
    while True:
        if max_calls == 1:
            # One call cannot use tools first, so the stored text goes in the prompt.
            mode = "metadata"
        limits: Json = {
            "max_model_calls": max_calls,
            "max_tool_calls": 1 if mode == "metadata" else plan.max_tool_calls,
            # The genome and the budget lever set the output; the floor keeps room
            # for the reasoning the model does before it answers.
            "max_output_tokens": max(
                min(
                    int(genome["model_settings"]["max_output_tokens"]),
                    plan.max_output_tokens,
                ),
                STEP_OUTPUT_TOKENS,
            ),
            "per_run_max_micros": state.levers.per_run_max_micros,
            "budget_mode": plan.mode,
            "submit_retries": SUBMIT_RETRIES,
        }
        limits["submit_output_tokens"] = max(
            limits["max_output_tokens"], SUBMIT_OUTPUT_TOKENS
        )
        system, user = build_prompt(genome, island, paper, passages, mode, limits)
        fitted, estimate = fit_run_to_cap(
            provider,
            estimate_tokens(system + user),
            max_calls,
            # In a metadata reading every call is a submission.
            limits["submit_output_tokens"]
            if mode == "metadata"
            else limits["max_output_tokens"],
            state.levers.per_run_max_micros,
            limits["submit_output_tokens"],
            # The estimate holds room for the submission retry too.
            1 + SUBMIT_RETRIES,
        )
        if fitted == max_calls:
            break
        # Fewer calls fit the per-run cap; the prompt is rebuilt to say so.
        max_calls = fitted
    admit_run(state, island, estimate)

    db.execute(
        "INSERT OR IGNORE INTO assignments(paper_id, island_id, reasons, created_at)"
        " VALUES (?, ?, ?, ?)",
        (paper_id, island_id, dumps(["requested_run"]), iso(now)),
    )
    run_id = new_id("R")
    db.execute(
        "INSERT INTO runs(id, paper_id, island_id, genome_id, genome_version,"
        " spec_revision, genome, seed, status, reading_mode, prompt_system, prompt_user,"
        " prompt_hash, model, limits, estimate_micros, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            paper_id,
            island_id,
            genome_id,
            genome["version"],
            revision,
            dumps(genome),
            secrets.randbelow(2**31) if seed is None else seed,
            mode,
            system,
            user,
            hashlib.sha256(f"{system}\n\n{user}".encode()).hexdigest(),
            provider.model,
            dumps(limits),
            estimate,
            iso(now),
        ),
    )
    return run_id


def next_genome(db: sqlite3.Connection, island: Mapping[str, Any]) -> str:
    """The island's active genome with the fewest runs so far."""
    active = [str(genome["id"]) for genome in island["genomes"] if genome["active"]]
    if not active:
        raise Conflict(f"no_active_genome: island {island['id']} has no active genome")
    counts = dict(
        db.execute(
            "SELECT genome_id, COUNT(*) FROM runs WHERE island_id = ? GROUP BY genome_id",
            (island["id"],),
        ).fetchall()
    )
    return min(active, key=lambda genome_id: (counts.get(genome_id, 0), genome_id))


def agent_address(genome_id: str, island_id: str) -> str:
    """An agent is a genome seated on an island: ``genome@island``."""
    return f"{genome_id}@{island_id}"


def advance_swarm(
    db: sqlite3.Connection,
    *,
    spec: Mapping[str, Any],
    revision: int,
    provider: ModelProvider | None,
    clock: Clock,
) -> Json:
    """Let every idle agent take the next unread paper from its island's queue.

    Nobody starts this work by hand: an agent that is not already reading
    picks the newest paper assigned to its island that it has not attempted
    and that fewer than ``agents_per_paper`` of the island's agents have
    taken. Every agent that starts nothing is named with the reason.
    """
    started: list[Json] = []
    waiting: list[Json] = []
    plan = budget_state(db, spec, clock(), provider is not None).plan
    for island in spec["islands"]:
        if island["archived"]:
            continue
        island_id = str(island["id"])
        for genome in sorted(island["genomes"], key=lambda item: str(item["id"])):
            if not genome["active"]:
                continue
            genome_id = str(genome["id"])
            agent = agent_address(genome_id, island_id)
            if db.execute(
                "SELECT 1 FROM runs WHERE genome_id = ? AND status IN ('queued', 'running')",
                (genome_id,),
            ).fetchone():
                waiting.append({"agent": agent, "reason": "working"})
                continue
            paper = db.execute(
                "SELECT a.paper_id FROM assignments a WHERE a.island_id = ?"
                " AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.paper_id = a.paper_id"
                " AND r.genome_id = ?)"
                " AND (SELECT COUNT(DISTINCT r.genome_id) FROM runs r"
                " WHERE r.paper_id = a.paper_id AND r.island_id = a.island_id) < ?"
                " ORDER BY a.created_at DESC, a.paper_id LIMIT 1",
                (island_id, genome_id, plan.agents_per_paper),
            ).fetchone()
            if paper is None:
                waiting.append({"agent": agent, "reason": "queue_empty"})
                continue
            try:
                run_id = create_run(
                    db,
                    spec=spec,
                    revision=revision,
                    provider=provider,
                    clock=clock,
                    paper_id=paper["paper_id"],
                    island_id=island_id,
                    genome_id=genome_id,
                )
            except Refusal as refusal:
                waiting.append(
                    {"agent": agent, "reason": refusal.message.split(":", 1)[0]}
                )
                continue
            started.append(
                {"agent": agent, "run_id": run_id, "paper_id": paper["paper_id"]}
            )
    return {"started": started, "waiting": waiting}


def sweep_interrupted_runs(db: sqlite3.Connection, now: datetime) -> int:
    """Close every run a stopped process left open; its trace is kept as is."""
    rows = db.execute(
        "SELECT id FROM runs WHERE status IN ('queued', 'running')"
    ).fetchall()
    for row in rows:
        append_run_event(
            db, row["id"], "run_failed", {"reason": "interrupted_by_restart"}, now=now
        )
        db.execute(
            "UPDATE runs SET status = 'failed', failure = 'interrupted_by_restart',"
            " finished_at = ? WHERE id = ?",
            (iso(now), row["id"]),
        )
    return len(rows)


@dataclass
class _Context:
    db: sqlite3.Connection
    run: sqlite3.Row
    genome: Json
    limits: Json
    passages: list[Json]
    provider: ModelProvider
    clock: Clock
    model_calls: int = 0
    tool_calls: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def run_id(self) -> str:
        return str(self.run["id"])

    @property
    def paper_id(self) -> str:
        return str(self.run["paper_id"])

    def event(self, kind: str, payload: Mapping[str, Any], **extra: Any) -> None:
        append_run_event(self.db, self.run_id, kind, payload, now=self.clock(), **extra)
        # Each event is durable on its own: a later failure cannot lose it.
        self.db.commit()

    def spent(self) -> int:
        totals = sum_cost_scope(self.db, "run_id", self.run_id)
        return int(totals["settled_micros"]) + int(totals["unsettled_micros"])


def _bounded(value: Any) -> Any:
    text = json.dumps(value)
    return value if len(text) <= RESULT_LIMIT else {"truncated": text[:RESULT_LIMIT]}


def _passage_locator(paper_id: str, passage: Mapping[str, Any]) -> Locator:
    return Locator(
        paper_id=paper_id,
        source_kind=str(passage["kind"]),
        passage_id=str(passage["id"]),
        page=passage["page"],
        char_start=int(passage["char_start"]),
        char_end=int(passage["char_end"]),
        snippet=str(passage["text"])[:240],
    )


def _run_tool(ctx: _Context, call: ToolCall, arguments: Mapping[str, Any]) -> Json:
    """Do one allowed tool's work and return what the model is told."""
    if call.name == "paper_text":
        wanted = arguments.get("passage_id") or None
        available = [p["id"] for p in ctx.passages]
        if not ctx.passages:
            return {
                "passages": [],
                "available_passages": [],
                "note": "No text is stored for this paper.",
            }
        chosen = [p for p in ctx.passages if _passage_matches(p, wanted)]
        if not chosen:
            # The agent asked for a section that was never stored: say what exists.
            return {
                "error": "unknown_passage",
                "passages": [],
                "available_passages": available,
                "note": "Only the listed passages are stored for this paper.",
            }
        return {
            "passages": [
                {"passage_id": p["id"], "kind": p["kind"], "text": p["text"]}
                for p in chosen
            ],
            "available_passages": available,
            "note": "This is all the stored text for this paper.",
        }
    if call.name == "related_papers":
        hits = search(
            ctx.db, str(arguments.get("query", "")), 5, exclude_paper=ctx.paper_id
        )
        return {"results": hits}
    if call.name == "capture_note":
        text = arguments.get("text")
        if not isinstance(text, str) or not text.strip():
            raise Invalid("a note needs text", "text")
        quote = arguments.get("quote")
        found = (
            locate_quote(ctx.paper_id, ctx.passages, quote)
            if isinstance(quote, str)
            else None
        )
        ctx.notes.append(text.strip())
        ctx.event(
            "note",
            {
                "text": text.strip()[:2000],
                "quote": quote if isinstance(quote, str) else None,
                "quote_verified": found is not None,
            },
            locator=found,
        )
        return {"captured": True, "quote_verified": found is not None}
    if call.name == "feedback_context":
        island = ctx.run["island_id"]
        totals = ctx.db.execute(
            "SELECT signal, COUNT(*) FROM feedback WHERE island_id = ? GROUP BY signal",
            (island,),
        ).fetchall()
        notes = ctx.db.execute(
            "SELECT signal, note FROM feedback WHERE island_id = ? AND note != ''"
            " ORDER BY created_at DESC LIMIT 5",
            (island,),
        ).fetchall()
        return {
            "island_totals": {row[0]: row[1] for row in totals},
            "recent_notes": [dict(row) for row in notes],
        }
    if call.name == "cost_state":
        return {
            "spent_micros": ctx.spent(),
            "per_run_max_micros": ctx.limits["per_run_max_micros"],
            "model_calls": [ctx.model_calls, ctx.limits["max_model_calls"]],
            "tool_calls": [ctx.tool_calls, ctx.limits["max_tool_calls"]],
            "budget_mode": ctx.limits["budget_mode"],
        }
    raise Invalid(f"no handler for tool {call.name}")


def _submit(ctx: _Context, arguments: Mapping[str, Any]) -> str:
    reading = validate_reading_submission(arguments, ctx.paper_id, ctx.passages)
    reading_id = new_id("RD")
    ctx.db.execute(
        "INSERT INTO readings(id, run_id, paper_id, island_id, genome_id, genome_version,"
        " summary, claims, objections, related_papers, idea_seeds, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            reading_id,
            ctx.run_id,
            ctx.paper_id,
            ctx.run["island_id"],
            ctx.run["genome_id"],
            ctx.run["genome_version"],
            reading["summary"],
            dumps(reading["claims"]),
            dumps(reading["objections"]),
            dumps(reading["related_papers"]),
            dumps(reading["idea_seeds"]),
            iso(ctx.clock()),
        ),
    )
    title = ctx.db.execute(
        "SELECT title FROM papers WHERE id = ?", (ctx.paper_id,)
    ).fetchone()
    body = " ".join(
        [reading["summary"], *(claim["text"] for claim in reading["claims"])]
        + reading["objections"]
        + reading["idea_seeds"]
    )
    index_document(ctx.db, "reading", ctx.run_id, ctx.paper_id, str(title[0]), body)
    return reading_id


def _passage_matches(passage: Mapping[str, Any], wanted: Any) -> bool:
    """Whether a requested passage names this one: by full id, by kind, or by the id's tail."""
    if wanted is None:
        return True
    if not isinstance(wanted, str):
        return False
    pid = str(passage["id"])
    return wanted in (pid, passage["kind"], pid.rsplit(":", 1)[-1])


def dispatch_tool_call(
    ctx: _Context, call: ToolCall, offered: Sequence[str]
) -> tuple[Json, bool]:
    """Run one tool call under the genome's policy and record it.

    Returns what the model is told and whether the run is finished. A call
    outside the offered set, past the tool limit or with unreadable arguments
    is recorded as refused and does nothing else.
    """
    ctx.tool_calls += 1
    payload: Json = {
        "call_id": call.id,
        "name": call.name,
        "arguments": call.arguments
        if call.arguments is not None
        else call.raw_arguments,
    }
    refusal: str | None = None
    if call.name not in offered:
        refusal = "tool_not_allowed"
    elif (
        call.name != "submit_reading" and ctx.tool_calls > ctx.limits["max_tool_calls"]
    ):
        refusal = "tool_call_limit"
    elif call.arguments is None:
        refusal = "arguments_not_json"
    if refusal is not None:
        ctx.event("tool_call", {**payload, "allowed": False, "error": refusal})
        told: Json = {"error": refusal}
        if refusal == "arguments_not_json":
            told["detail"] = ARGUMENTS_NOT_JSON
        elif refusal == "tool_call_limit":
            told["detail"] = "No tool calls are left except submit_reading."
        return told, False

    arguments = call.arguments or {}
    if call.name == "submit_reading":
        try:
            reading_id = _submit(ctx, arguments)
        except Invalid as invalid:
            result: Json = {
                "accepted": False,
                "error": invalid.message,
                "field": invalid.field,
            }
            ctx.event("tool_call", {**payload, "allowed": True, "result": result})
            return result, False
        ctx.event(
            "tool_call", {**payload, "allowed": True, "result": {"accepted": True}}
        )
        ctx.event("reading_submitted", {"reading_id": reading_id})
        return {"accepted": True, "reading_id": reading_id}, True

    try:
        result = _run_tool(ctx, call, arguments)
    except Invalid as invalid:
        result = {"error": invalid.message}
    ctx.event("tool_call", {**payload, "allowed": True, "result": _bounded(result)})
    if call.name == "paper_text":
        for passage in ctx.passages:
            if any(
                p["passage_id"] == passage["id"] for p in result.get("passages", [])
            ):
                ctx.event(
                    "paper_read",
                    {"passage_id": passage["id"], "characters": len(passage["text"])},
                    locator=_passage_locator(ctx.paper_id, passage),
                )
    return result, False


def _finish(ctx: _Context, status: str, kind: str, payload: Json) -> None:
    now = iso(ctx.clock())
    ctx.db.execute(
        "UPDATE runs SET status = ?, failure = ?, finished_at = ? WHERE id = ?",
        (status, payload.get("reason"), now, ctx.run_id),
    )
    ctx.event(
        kind,
        {
            **payload,
            "model_calls": ctx.model_calls,
            "tool_calls": ctx.tool_calls,
            "spent_micros": ctx.spent(),
        },
    )


def _drive(ctx: _Context, client: ModelClient) -> None:
    run, limits = ctx.run, ctx.limits
    metadata_only = run["reading_mode"] == "metadata"
    ctx.db.execute(
        "UPDATE runs SET status = 'running', started_at = ? WHERE id = ?",
        (iso(ctx.clock()), ctx.run_id),
    )
    allowed = [name for name in ctx.genome["allowed_tools"] if name in TOOLS]
    ctx.event(
        "run_started",
        {
            "paper_id": ctx.paper_id,
            "island_id": run["island_id"],
            "genome": {"id": run["genome_id"], "version": run["genome_version"]},
            "spec_revision": run["spec_revision"],
            "seed": run["seed"],
            "reading_mode": run["reading_mode"],
            "model": run["model"],
            "limits": limits,
            "allowed_tools": allowed,
        },
    )
    ctx.event(
        "prompt",
        {
            "system": run["prompt_system"],
            "user": run["prompt_user"],
            "prompt_hash": run["prompt_hash"],
        },
        locator=Locator(ctx.paper_id, "metadata"),
    )
    if ctx.passages and text_is_inline(ctx.passages):
        # The stored text was placed in the prompt, so the trace says it was read.
        for passage in ctx.passages:
            ctx.event(
                "paper_read",
                {
                    "passage_id": passage["id"],
                    "characters": len(passage["text"]),
                    "placed_in_prompt": True,
                },
                locator=_passage_locator(ctx.paper_id, passage),
            )

    messages: list[Message] = [
        {"role": "system", "content": run["prompt_system"]},
        {"role": "user", "content": run["prompt_user"]},
    ]
    temperature = float(ctx.genome["model_settings"]["temperature"])
    # What the harness tells the model between calls; kept on the next call's event.
    notice: str | None = None
    response: ModelResponse | None = None
    submit_tokens = int(
        limits.get("submit_output_tokens") or limits["max_output_tokens"]
    )
    calls_allowed = int(limits["max_model_calls"])
    retries_left = int(limits.get("submit_retries") or 0)
    # Why the last submission failed, when it did; it decides whether to retry.
    problem: str | None = None
    retrying = False
    index = 0
    while index < calls_allowed:
        index += 1
        last = index == calls_allowed
        submitting = last or metadata_only
        offered = ["submit_reading"] if submitting else allowed
        if retrying:
            notice = RETRY_NOTICE.format(problem=problem)
        elif last and index > 1:
            notice = LAST_CALL_NOTICE
        elif index == calls_allowed - 1 and not metadata_only:
            notice = (
                f"{notice} {NEXT_IS_LAST_NOTICE}" if notice else NEXT_IS_LAST_NOTICE
            )
        if notice is not None:
            messages.append({"role": "user", "content": notice})
        ctx.model_calls = index
        common: dict[str, Any] = {
            "owner_kind": "run",
            "owner_id": ctx.run_id,
            "parent_kind": "paper",
            "parent_id": ctx.paper_id,
            "unit_type": "tokens",
            "provider": ctx.provider.name,
            "island_id": run["island_id"],
            "paper_id": ctx.paper_id,
            "run_id": ctx.run_id,
        }
        began = time.monotonic()
        try:
            response = client.complete(
                messages,
                [TOOLS[name] for name in offered],
                # A submission is given more room than a step that only calls a tool.
                max_output_tokens=submit_tokens
                if submitting
                else int(limits["max_output_tokens"]),
                temperature=temperature,
            )
        except ModelCallFailed as failure:
            # The request left and no usage came back: charge the input estimate, unsettled.
            sent = estimate_tokens(json.dumps(messages))
            receipt_id = record_cost_receipt(
                ctx.db,
                action="model_call",
                quantity=sent,
                amount_micros=price_micros(ctx.provider, sent, 0),
                now=ctx.clock(),
                estimated=True,
                settled=False,
                **common,
            )
            ctx.event(
                "model_call",
                {"index": index, "error": str(failure), "harness_notice": notice},
                receipt_id=receipt_id,
                cost_state="unsettled",
            )
            _finish(ctx, "failed", "run_failed", {"reason": "model_call_failed"})
            return
        receipt_id = record_cost_receipt(
            ctx.db,
            action="model_call",
            quantity=response.input_tokens + response.output_tokens,
            amount_micros=price_micros(
                ctx.provider, response.input_tokens, response.output_tokens
            ),
            now=ctx.clock(),
            estimated=not response.usage_reported,
            **common,
        )
        ctx.event(
            "model_call",
            {
                "index": index,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "usage_reported": response.usage_reported,
                "finish_reason": response.finish_reason,
                "text": response.text[:RESULT_LIMIT],
                "reasoning": response.reasoning[:RESULT_LIMIT],
                "tool_calls": [
                    {"id": call.id, "name": call.name} for call in response.tool_calls
                ],
                "offered_tools": offered,
                "harness_notice": notice,
                "latency_ms": int((time.monotonic() - began) * 1000),
            },
            receipt_id=receipt_id,
            cost_state="settled",
        )
        messages.append(assistant_message(response))
        notice = None if response.tool_calls else NO_TOOL_NOTICE
        problem = None
        if submitting and not response.tool_calls:
            problem = (
                "the answer was cut off before any tool call"
                if response.finish_reason == "length"
                else "no tool call was made"
            )
        for call in response.tool_calls:
            result, finished = dispatch_tool_call(ctx, call, offered)
            if call.name == "submit_reading" and not finished:
                problem = str(result.get("detail") or result.get("error"))
                if result.get("field"):
                    problem += f" (field {result['field']})"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(_bounded(result)),
                }
            )
            if finished:
                _finish(
                    ctx,
                    "completed",
                    "run_completed",
                    {"reading_id": result["reading_id"]},
                )
                return
        if ctx.spent() >= limits["per_run_max_micros"]:
            _finish(ctx, "failed", "run_failed", {"reason": "run_cost_cap"})
            return
        retrying = False
        if last and problem is not None and retries_left > 0:
            # The last submission failed: one more call to submit it, told why.
            retries_left -= 1
            calls_allowed += 1
            retrying = True
    # Say why no reading came out of the last call, as far as the trace shows.
    reason = "model_call_limit"
    if response is not None and response.finish_reason == "length":
        reason = "output_truncated"
    elif response is not None and not response.tool_calls:
        reason = "no_reading_submitted"
    elif problem is not None:
        reason = "submission_rejected"
    _finish(ctx, "failed", "run_failed", {"reason": reason})


def execute_run(
    database: Path,
    run_id: str,
    *,
    client: ModelClient,
    provider: ModelProvider,
    clock: Clock,
) -> None:
    """Carry one queued run to its end, recording every step as it happens."""
    with connect(database) as db:
        run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None or run["status"] != "queued":
            return
        ctx = _Context(
            db=db,
            run=run,
            genome=loads(run["genome"]),
            limits=loads(run["limits"]),
            passages=load_passages(db, run["paper_id"]),
            provider=provider,
            clock=clock,
        )
        try:
            _drive(ctx, client)
        except Exception as error:
            # Whatever broke, the trace keeps every committed event and says why it stopped.
            db.rollback()
            _finish(
                ctx,
                "failed",
                "run_failed",
                {"reason": "harness_error", "detail": type(error).__name__},
            )
