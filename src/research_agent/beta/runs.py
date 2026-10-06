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
import fcntl
import json
import math
import re
import secrets
import sqlite3
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from research_agent.beta.budget import (
    admit_run,
    banded,
    budget_state,
    estimate_tokens,
    fit_run_to_cap,
    price_micros,
)
from research_agent.beta.config import ModelProvider
from research_agent.beta.costs import record_cost_receipt, sum_cost_scope
from research_agent.beta.db import Clock, Json, connect, dumps, iso, loads, new_id
from research_agent.beta.errors import Conflict, Invalid, NotFound, Refusal, Unavailable
from research_agent.beta.ingest import PaperFetcher, SourceFailed
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
from research_agent.beta.papers import (
    decide_paper,
    get_paper,
    index_document,
    load_passages,
    paper_json,
    related_work_shortlist,
    search,
    selected_context,
    upsert_paper,
)
from research_agent.beta.spec import current_spec, find_genome, find_island
from research_agent.beta.text import (
    TextFetcher,
    TextFetchFailed,
    parse_paper_html,
    store_full_text,
)

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
#: The most stored text one paper_text call returns. A full paper is never returned;
#: broad calls return a map and detailed calls read one passage-shaped piece.
TEXT_PER_CALL = 3500
#: The most lines of the passage outline placed in the prompt.
OUTLINE_LINES = 120
#: The least output any model call is given. A model that reasons before it
#: answers spends its reasoning out of the same allowance; at 900 tokens the
#: reasoning alone filled it and the call returned no tool call at all.
STEP_OUTPUT_TOKENS = 2500
#: The least output a submission call is given: the reasoning, then a reading
#: of several hundred tokens of structured JSON that must arrive whole.
SUBMIT_OUTPUT_TOKENS = 4000
#: The fewest extra submission-only calls a run gets when its last submission
#: is cut off, malformed or rejected, with the reason it failed; the budget's
#: band gives more on top.
SUBMIT_RETRIES = 1
#: Stored text up to this many characters is placed in the prompt, so the
#: agent does not spend a model call fetching what it must read anyway.
INLINE_TEXT_LIMIT = 6000
#: Full-text papers above this size get a longer session budget and must read body text.
LONG_TEXT_CHARACTERS = 50_000
ARXIV_ID = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(?:v(\d+))?")

_TEXT_LIST = {"type": "array", "items": {"type": "string"}}
#: Every claim carries the reading agent's stance toward the paper.
STANCES = ("positive", "neutral", "negative")
TOOLS: dict[str, ToolSchema] = {
    "paper_text": tool_schema(
        "paper_text",
        "Return a map of stored passages, or one bounded passage by id. A call without"
        " passage_id never returns paper text; use the returned ids for follow-up.",
        {"type": "object", "properties": {"passage_id": {"type": "string"}}},
    ),
    "related_papers": tool_schema(
        "related_papers",
        "Search the stored papers and readings for related work. Use it for follow-up;"
        " the prompt already includes an initial related-work shortlist.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    "cited_paper_text": tool_schema(
        "cited_paper_text",
        "Read one bounded passage from a cited or related arXiv paper. Give an arXiv"
        " id, arXiv link, or reference text; omit passage_id to get only an outline.",
        {
            "type": "object",
            "properties": {
                "reference": {"type": "string"},
                "passage_id": {"type": "string"},
            },
            "required": ["reference"],
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
        "Show what this island's other agents concluded lately: their newest readings' summaries.",
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
        " text needs at least one exact quote as evidence. Say whether the island"
        " should keep this paper as reference: it is held only if every reader says so.",
        {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "keep": {
                    "type": "boolean",
                    "description": "Should the island hold onto this paper as reference?",
                },
                "thesis_quote": {"type": "string"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "stance": {
                                "type": "string",
                                "enum": list(STANCES),
                                "description": "positive: the claim credits the"
                                " paper's contribution; neutral: it describes;"
                                " negative: it doubts or limits it.",
                            },
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
                        "required": ["text", "stance"],
                    },
                },
                "objections": _TEXT_LIST,
                "related_papers": _TEXT_LIST,
                "idea_seeds": _TEXT_LIST,
            },
            "required": [
                "summary",
                "keep",
                "thesis_quote",
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
    " the stored text. The submitted thesis_quote must be one exact sentence"
    " from the abstract. Label every claim's stance toward the paper: positive,"
    " neutral or negative. End the run by calling submit_reading once. Prose outside"
    " a tool call is not kept as the reading."
)


LAST_CALL_NOTICE = "This is the last model call of the run. Call submit_reading now."
COST_NOTICE = (
    "The run has spent its cost allowance. This is the last model call of the"
    " run. Call submit_reading now, from what has been read so far."
)
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
    if not isinstance(value, list):
        raise Invalid(f"{name} is a list", name)
    kept: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise Invalid(f"{name} entries are text", name)
        kept.append(item.strip()[:600])
        if len(kept) == most:
            break
    return kept


def validate_reading_submission(
    arguments: Mapping[str, Any], paper_id: str, passages: Sequence[Mapping[str, Any]]
) -> Json:
    """Check a submitted reading and return it with each quote verified.

    Every field must be present. A claim that depends on the paper text must
    cite a quote; a quote the stored text does not contain is kept and marked
    unverified, never accepted as evidence.
    """
    for name in (
        "summary",
        "thesis_quote",
        "claims",
        "objections",
        "related_papers",
        "idea_seeds",
    ):
        if name not in arguments:
            raise Invalid(f"a reading must contain {name}", name)
    summary = arguments["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise Invalid("summary is text of at most 2000 characters", "summary")
    thesis_quote = arguments["thesis_quote"]
    if (
        not isinstance(thesis_quote, str)
        or not thesis_quote.strip()
        or len(thesis_quote) > 1000
    ):
        raise Invalid(
            "thesis_quote is one exact sentence of at most 1000 characters",
            "thesis_quote",
        )
    abstract = next((p for p in passages if p.get("kind") == "abstract"), None)
    abstract_text = "" if abstract is None else str(abstract["text"])
    thesis_start = abstract_text.find(thesis_quote.strip())
    if thesis_start < 0:
        raise Invalid(
            "thesis_quote must be an exact sentence from the abstract", "thesis_quote"
        )
    thesis_end = thesis_start + len(thesis_quote.strip())
    keep = arguments.get("keep")
    if not isinstance(keep, bool):
        raise Invalid("keep says whether the island should hold the paper", "keep")
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
        stance = raw.get("stance")
        if stance not in STANCES:
            raise Invalid(
                "each claim's stance is positive, neutral or negative",
                f"{where}.stance",
            )
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
                "stance": stance,
                "depends_on_paper": depends,
                "evidence": evidence,
                "cited": any(item["verified"] for item in evidence),
            }
        )
    return {
        "summary": summary.strip(),
        "keep": keep,
        "thesis_quote": thesis_quote.strip(),
        "thesis_char_start": thesis_start,
        "thesis_char_end": thesis_end,
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
    related_work: Sequence[Mapping[str, Any]],
    reading_mode: str,
    limits: Mapping[str, Any],
    selected_papers: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, str]:
    """The system and user text a run starts from."""
    system = "\n\n".join(
        (
            str(genome["prompt"]),
            str(genome.get("research_methods", {}).get("instructions", "")),
            f"Reading strategy: {genome['reading_strategy']}",
            f"Island: {island['name']}. Focus: {island['focus']}.",
            HARNESS_RULES,
            (
                f"Limits: {limits['max_model_calls']} model calls, {limits['max_tool_calls']}"
                f" tool calls, {limits['max_output_tokens']} output tokens per call."
            ),
        )
    )
    lines = [
        f"Paper {paper['id']} (version {paper['version']})",
        f"Title: {paper['title']}",
        f"Authors: {', '.join(loads(paper['authors']))}",
        f"Categories: {', '.join(loads(paper['categories']))}",
        f"Published: {paper['published_at']}",
    ]
    if reading_mode == "metadata":
        passages = [passage for passage in passages if passage["kind"] == "abstract"]
    if not passages:
        lines.append("No text is stored for this paper; read from the metadata alone.")
    elif reading_mode == "metadata" or text_is_inline(passages):
        lines.append(
            "Stored abstract for this metadata reading:"
            if reading_mode == "metadata"
            else "Stored text. This is everything stored for this paper; no other"
            " section exists:"
        )
        lines += [
            f"Passage {passage['id']} ({passage['kind']}): {passage['text']}"
            for passage in passages
        ]
    else:
        full = any(passage["kind"] == "section" for passage in passages)
        total = sum(len(str(passage["text"])) for passage in passages)
        required = int(limits.get("required_full_text_reads") or 0)
        lines.append(
            (
                f"The full text is stored, {total:,} characters in"
                f" {len(passages)} passages."
                if full
                else "Stored passages:"
            )
            + " Read a map first with paper_text, then call paper_text with one"
            f" passage_id for at most {TEXT_PER_CALL:,} characters."
            " No other passages exist:"
        )
        if required:
            lines.append(
                f"This is not an abstract-only job: before submit_reading, read at"
                f" least {required} non-abstract passage ids from different parts of"
                " the paper, such as methods, results, experiments or discussion."
            )
        lines += passage_outline(passages)
    if related_work:
        lines.append(
            "Related-work shortlist from the stored corpus. Prefer these before"
            " spending a tool call on related_papers; use the tool only for follow-up."
            " When you submit related_papers, say why each one matters: adapted_method,"
            " supporting_evidence, idea_in_new_setting, or motivating_limitation."
        )
        for index, item in enumerate(related_work, 1):
            lines.append(
                f"{index}. [{item['source']}] {item['title']} ({item['paper_id']}):"
                f" {item['snippet']}"
            )
    elif loads(paper["cited_papers"]):
        lines.append(
            "This paper's bibliography was extracted, but no cited stored paper matched it yet."
        )
    if selected_papers:
        lines.append(
            "Papers selected on this island by its readers or a person. Use these"
            " interests to guide comparisons, questions and useful connections."
            " Evaluate this paper independently; selection is context, not evidence."
        )
        for selected in selected_papers:
            lines.append(
                f"- {selected['title']} ({selected['paper_id']}), selected by"
                f" {selected['selected_by']}: {selected['summary']}"
            )
    if reading_mode == "metadata":
        lines.append("Submit the reading now with submit_reading.")
    else:
        lines.append(
            "Capture notes or look for related stored papers if that helps, then"
            " call submit_reading. The last model call can only submit."
        )
    return system, "\n".join(lines)


def _base(passage: Mapping[str, Any]) -> tuple[str, str]:
    """A passage's section, without the part number a long section was split into."""
    pid, title = str(passage["id"]), str(passage.get("title") or passage["kind"])
    head, _, tail = pid.rpartition("-")
    if head and tail.isdigit():
        pid = head
    return pid, re.sub(r" \(part \d+ of \d+\)$", "", title)


def passage_outline(passages: Sequence[Mapping[str, Any]]) -> list[str]:
    """The stored passages as an outline: one line per section, its parts folded in."""
    groups: list[list[Mapping[str, Any]]] = []
    for passage in passages:
        if groups and _base(groups[-1][0]) == _base(passage):
            groups[-1].append(passage)
        else:
            groups.append([passage])
    lines = []
    for group in groups:
        _, title = _base(group[0])
        size = sum(len(str(passage["text"])) for passage in group)
        if len(group) == 1:
            lines.append(f"- {group[0]['id']}: {title} ({size:,} characters)")
        else:
            lines.append(
                f"- {group[0]['id']} to {group[-1]['id']}: {title},"
                f" {len(group)} parts ({size:,} characters)"
            )
    if len(lines) > OUTLINE_LINES:
        rest = len(lines) - OUTLINE_LINES
        lines = lines[:OUTLINE_LINES] + [f"- and {rest} more sections, in order"]
    return lines


def text_is_inline(passages: Sequence[Mapping[str, Any]]) -> bool:
    """Whether a paper's stored text is short enough to sit in the prompt."""
    return sum(len(str(passage["text"])) for passage in passages) <= INLINE_TEXT_LIMIT


def full_text_size(passages: Sequence[Mapping[str, Any]]) -> int:
    """Characters of stored body text, excluding the abstract."""
    return sum(
        len(str(passage["text"]))
        for passage in passages
        if passage.get("kind") == "section"
    )


def long_paper_scale(passages: Sequence[Mapping[str, Any]]) -> int:
    """How much longer a full-text run should be allowed to work."""
    body = full_text_size(passages)
    if body < LONG_TEXT_CHARACTERS:
        return 1
    return min(6, max(2, body // LONG_TEXT_CHARACTERS + 1))


def required_full_text_reads(passages: Sequence[Mapping[str, Any]]) -> int:
    """Minimum non-abstract passages a full-text reading must inspect."""
    sections = sum(1 for passage in passages if passage.get("kind") == "section")
    if full_text_size(passages) < LONG_TEXT_CHARACTERS:
        return 0
    return min(3, max(1, sections))


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
    band = state.levers.band_percent
    passages = load_passages(db, paper_id)
    mode = str(island["reading_mode"])
    required_reads = required_full_text_reads(passages) if mode != "metadata" else 0
    scale = long_paper_scale(passages) if required_reads else 1
    # A metadata reading is one call; a second is kept for a rejected submission.
    # Long full-text papers need enough turns to get a map, read body sections,
    # optionally check related work, then submit.
    max_calls = (
        min(2, plan.max_model_calls)
        if mode == "metadata"
        else (
            max(plan.max_model_calls, 3 + required_reads + min(scale, 3))
            if required_reads
            else plan.max_model_calls
        )
    )
    while True:
        if max_calls == 1:
            # One call cannot use tools first, so the stored text goes in the prompt.
            mode = "metadata"
            required_reads = 0
        # A map, the body reads and the submission each take a call; fewer calls
        # than that require fewer body reads, so the cap never makes a reading
        # impossible to submit.
        required_reads = min(required_reads, max(0, max_calls - 3))
        # The band buys more submission retries on a longer run.
        retries = max(SUBMIT_RETRIES, math.ceil(max_calls * band / 100))
        limits: Json = {
            "agents_per_paper": min(
                plan.agents_per_paper,
                sum(bool(item["active"]) for item in island["genomes"]),
            ),
            "max_model_calls": max_calls,
            "max_tool_calls": 1
            if mode == "metadata"
            else (
                max(plan.max_tool_calls, 2 + required_reads + scale)
                if required_reads
                else plan.max_tool_calls
            ),
            # The genome and the budget lever set the output; the floor keeps room
            # for the reasoning the model does before it answers.
            "max_output_tokens": max(
                min(
                    int(genome["model_settings"]["max_output_tokens"]),
                    plan.max_output_tokens,
                ),
                STEP_OUTPUT_TOKENS,
            ),
            "per_run_max_micros": max(
                state.levers.per_run_max_micros,
                state.levers.per_run_max_micros * scale,
            ),
            "budget_mode": plan.mode,
            "submit_retries": retries,
            "band_percent": band,
            "required_full_text_reads": required_reads,
        }
        limits["submit_output_tokens"] = max(
            limits["max_output_tokens"], SUBMIT_OUTPUT_TOKENS
        )
        related_work = related_work_shortlist(db, paper_id, 20, island_id)
        system, user = build_prompt(
            genome,
            island,
            paper,
            passages,
            related_work,
            mode,
            limits,
            selected_context(db, island_id, paper_id),
        )
        fitted, estimate = fit_run_to_cap(
            provider,
            estimate_tokens(system + user),
            max_calls,
            # In a metadata reading every call is a submission.
            limits["submit_output_tokens"]
            if mode == "metadata"
            else limits["max_output_tokens"],
            # The calls are fitted to the cap with its band, and the run is
            # asked to submit once it has spent the cap itself.
            banded(int(limits["per_run_max_micros"]), band),
            limits["submit_output_tokens"],
            # The estimate holds room for the submission retries too.
            1 + retries,
        )
        if fitted == max_calls:
            break
        # Fewer calls fit the per-run cap; the prompt is rebuilt to say so.
        max_calls = fitted
    admit_run(state, island)

    db.execute(
        "INSERT OR IGNORE INTO assignments(paper_id, island_id, reasons, created_at, kept)"
        " VALUES (?, ?, ?, ?, (SELECT selected FROM paper_selections WHERE paper_id = ?))",
        (paper_id, island_id, dumps(["requested_run"]), iso(now), paper_id),
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
    """The island's active genome with the fewest runs so far, first listed on a tie."""
    active = [str(genome["id"]) for genome in island["genomes"] if genome["active"]]
    if not active:
        raise Conflict(f"no_active_genome: island {island['id']} has no active genome")
    counts = dict(
        db.execute(
            "SELECT genome_id, COUNT(*) FROM runs WHERE island_id = ? GROUP BY genome_id",
            (island["id"],),
        ).fetchall()
    )
    return min(active, key=lambda genome_id: counts.get(genome_id, 0))


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
    picks the newest paper assigned to its island that it has not completed
    and that fewer than ``agents_per_paper`` of the island's agents have
    taken. Every agent that starts nothing is named with the reason.
    """
    started: list[Json] = []
    waiting: list[Json] = []
    now = clock()
    plan = budget_state(db, spec, now, provider is not None).plan
    # The swarm's pace: so many runs a day for all, and so many an hour per island.
    today = db.execute(
        "SELECT COUNT(*) FROM runs WHERE created_at >= ?",
        (iso(now)[:10] + "T00:00:00Z",),
    ).fetchone()[0]
    hour_ago = iso(now - timedelta(hours=1))
    island_runs = dict(
        db.execute(
            "SELECT island_id, COUNT(*) FROM runs WHERE created_at >= ? GROUP BY island_id",
            (iso(now)[:10] + "T00:00:00Z",),
        ).fetchall()
    )
    for island in sorted(
        spec["islands"], key=lambda item: island_runs.get(item["id"], 0)
    ):
        if island["archived"]:
            continue
        island_id = str(island["id"])
        if today + len(started) >= plan.max_runs_per_day:
            waiting.append({"agent": f"*@{island_id}", "reason": "daily_run_cap"})
            continue
        recent = db.execute(
            "SELECT COUNT(*) FROM runs WHERE island_id = ? AND created_at > ?",
            (island_id, hour_ago),
        ).fetchone()[0]
        if recent >= plan.runs_per_island_per_hour:
            waiting.append({"agent": f"*@{island_id}", "reason": "hourly_pace"})
            continue
        started_here = 0
        # Least-used agents get a turn, including newly bred children.
        counts = dict(
            db.execute(
                "SELECT genome_id, COUNT(*) FROM runs WHERE island_id = ? GROUP BY genome_id",
                (island_id,),
            ).fetchall()
        )
        for genome in sorted(
            island["genomes"], key=lambda item: counts.get(item["id"], 0)
        ):
            if today + len(started) >= plan.max_runs_per_day:
                waiting.append({"agent": f"*@{island_id}", "reason": "daily_run_cap"})
                break
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
                " AND r.genome_id = ? AND r.status = 'completed')"
                " AND (SELECT COUNT(*) FROM runs r WHERE r.paper_id = a.paper_id"
                " AND r.genome_id = ? AND r.genome_version = ? AND r.created_at >= ?) < 3"
                " AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.paper_id = a.paper_id"
                " AND r.genome_id = ? AND r.status = 'failed' AND r.finished_at > ?)"
                " AND NOT EXISTS (SELECT 1 FROM paper_releases rl"
                " WHERE rl.paper_id = a.paper_id)"
                " AND ((SELECT COUNT(DISTINCT r.genome_id) FROM runs r"
                " WHERE r.paper_id = a.paper_id AND r.island_id = a.island_id) <"
                " COALESCE((SELECT json_extract(r.limits, '$.agents_per_paper')"
                " FROM runs r WHERE r.paper_id = a.paper_id AND r.island_id = a.island_id"
                " ORDER BY r.rowid LIMIT 1), ?)"
                " OR EXISTS (SELECT 1 FROM runs r WHERE r.paper_id = a.paper_id"
                " AND r.island_id = a.island_id AND r.genome_id = ?))"
                " ORDER BY EXISTS (SELECT 1 FROM runs r WHERE r.paper_id = a.paper_id"
                " AND r.island_id = a.island_id) DESC, a.created_at DESC, a.paper_id LIMIT 1",
                (
                    island_id,
                    genome_id,
                    genome_id,
                    genome["version"],
                    iso(now)[:10] + "T00:00:00Z",
                    genome_id,
                    iso(now - timedelta(minutes=15)),
                    plan.agents_per_paper,
                    genome_id,
                ),
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
            started_here += 1
            if recent + started_here >= plan.runs_per_island_per_hour:
                break
    return {"started": started, "waiting": waiting}


@contextmanager
def _run_ownership(database: Path, run_id: str) -> Iterator[bool]:
    directory = database.resolve().with_suffix(database.suffix + ".run-locks")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = hashlib.sha256(run_id.encode()).hexdigest()
    with (directory / filename).open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def sweep_interrupted_runs(db: sqlite3.Connection, now: datetime) -> int:
    """Close abandoned running work without disturbing a live executor or queue."""
    filename = str(db.execute("PRAGMA database_list").fetchone()[2])
    if not filename:
        raise ValueError("run ownership requires a file-backed SQLite database")
    database = Path(filename)
    rows = db.execute("SELECT id FROM runs WHERE status = 'running'").fetchall()
    recovered = 0
    for row in rows:
        with _run_ownership(database, row["id"]) as owned:
            if not owned:
                continue
            changed = db.execute(
                "UPDATE runs SET status = 'failed', failure = 'interrupted_by_restart',"
                " finished_at = ? WHERE id = ? AND status = 'running'",
                (iso(now), row["id"]),
            ).rowcount
            if changed:
                append_run_event(
                    db,
                    row["id"],
                    "run_failed",
                    {"reason": "interrupted_by_restart"},
                    now=now,
                )
                db.commit()
                recovered += 1
    return recovered


@dataclass
class _Context:
    db: sqlite3.Connection
    run: sqlite3.Row
    genome: Json
    limits: Json
    passages: list[Json]
    provider: ModelProvider
    clock: Clock
    fetch_paper: PaperFetcher | None = None
    fetch_text: TextFetcher | None = None
    model_calls: int = 0
    tool_calls: int = 0
    notes: list[str] = field(default_factory=list)
    read_passage_ids: set[str] = field(default_factory=set)
    #: The run spent its cost allowance before its body reads: a submission
    #: from what was read is accepted rather than paid for and refused.
    required_reads_waived: bool = False

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


def _arxiv_id(text: str) -> str | None:
    match = ARXIV_ID.search(text)
    return match.group(1) if match else None


def _reference_to_paper_id(ctx: _Context, reference: str) -> tuple[str | None, str]:
    direct = _arxiv_id(reference)
    if direct is not None:
        return direct, "argument"
    source = get_paper(ctx.db, ctx.paper_id)
    for item in loads(source["cited_papers"]):
        ref = str(item)
        if reference.lower() in ref.lower() or ref.lower() in reference.lower():
            found = _arxiv_id(ref)
            if found is not None:
                return found, "bibliography"
    hit = search(
        ctx.db,
        reference,
        1,
        exclude_paper=ctx.paper_id,
        island_id=ctx.run["island_id"],
    )
    if hit:
        return str(hit[0]["paper_id"]), "stored_text_search"
    return None, "unresolved"


def _bring_into_island(ctx: _Context, paper_id: str) -> None:
    """A cited paper an agent reads joins its island's pool, so the island can find it."""
    ctx.db.execute(
        "INSERT OR IGNORE INTO assignments(paper_id, island_id, reasons, created_at, kept)"
        " VALUES (?, ?, ?, ?, (SELECT selected FROM paper_selections WHERE paper_id = ?))",
        (
            paper_id,
            ctx.run["island_id"],
            dumps(["cited_by_run"]),
            iso(ctx.clock()),
            paper_id,
        ),
    )


def _ensure_related_paper(
    ctx: _Context, paper_id: str
) -> tuple[sqlite3.Row | None, str]:
    try:
        stored = get_paper(ctx.db, paper_id)
    except NotFound:
        stored = None
    if stored is not None:
        _bring_into_island(ctx, paper_id)
        ctx.db.commit()
        return stored, "stored"
    if ctx.fetch_paper is None:
        return None, "not_stored"
    try:
        entry = ctx.fetch_paper(paper_id)
    except SourceFailed:
        return None, "metadata_fetch_failed"
    if entry is None:
        return None, "not_found"
    receipt_id = record_cost_receipt(
        ctx.db,
        action="ingest",
        owner_kind="run",
        owner_id=ctx.run_id,
        parent_kind="source",
        parent_id=f"arxiv:{paper_id}",
        unit_type="arxiv_request",
        quantity=1,
        amount_micros=0,
        provider="arxiv",
        island_id=ctx.run["island_id"],
        paper_id=entry.id,
        run_id=ctx.run_id,
        now=ctx.clock(),
    )
    upsert_status = upsert_paper(ctx.db, entry, receipt_id, ctx.clock())
    if ctx.fetch_text is not None:
        try:
            html = ctx.fetch_text(entry.id, entry.version)
        except TextFetchFailed:
            html = None
        if html:
            sections = parse_paper_html(html)
            if sections:
                store_full_text(ctx.db, entry.id, sections, ctx.clock())
    _bring_into_island(ctx, entry.id)
    ctx.db.commit()
    return get_paper(ctx.db, entry.id), upsert_status


def _read_related_paper(ctx: _Context, arguments: Mapping[str, Any]) -> Json:
    reference = arguments.get("reference")
    if not isinstance(reference, str) or not reference.strip():
        raise Invalid("a cited paper reference needs text", "reference")
    paper_id, source = _reference_to_paper_id(ctx, reference.strip())
    if paper_id is None:
        return {"error": "unresolved_reference"}
    paper, status = _ensure_related_paper(ctx, paper_id)
    if paper is None:
        return {"error": status, "paper_id": paper_id}
    passages = load_passages(ctx.db, str(paper["id"]))
    wanted = arguments.get("passage_id") or None
    if wanted is None:
        return {
            "paper": paper_json(paper),
            "source": source,
            "status": status,
            "outline": passage_outline(passages)[:40],
            "note": "No paper text was returned. Ask for one passage_id to read a bounded passage.",
        }
    chosen = [p for p in passages if _passage_matches(p, wanted)]
    if not chosen:
        return {
            "error": "unknown_passage",
            "paper_id": paper["id"],
            "available_passages": [p["id"] for p in passages[:40]],
        }
    passage = chosen[0]
    text = str(passage["text"])
    returned = {**passage, "paper_id": paper["id"], "text": text[:TEXT_PER_CALL]}
    result: Json = {
        "paper": paper_json(paper),
        "source": source,
        "status": status,
        "passage": returned,
    }
    if len(text) > TEXT_PER_CALL:
        result["note"] = "The passage was trimmed to the per-call text limit."
    return result


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
        if wanted is None:
            return {
                "passages": [],
                "available_passages": available[:80],
                "outline": passage_outline(ctx.passages),
                "note": "This is the paper map only. Ask for one passage_id to read bounded text.",
            }
        chosen = [p for p in ctx.passages if _passage_matches(p, wanted)]
        if not chosen:
            # The agent asked for a section that was never stored: say what exists.
            return {
                "error": "unknown_passage",
                "passages": [],
                "available_passages": available[:40],
                "note": "Only the passages in the prompt's outline are stored.",
            }
        returned: list[Json] = []
        used = 0
        for passage in chosen:
            if returned:
                break
            text = str(passage["text"])
            returned.append({**passage, "text": text[:TEXT_PER_CALL]})
            used += min(len(text), TEXT_PER_CALL)
        left = [p["id"] for p in chosen[len(returned) :]]
        result: Json = {
            "passages": [
                {
                    "passage_id": p["id"],
                    "title": p.get("title") or p["kind"],
                    "text": p["text"],
                }
                for p in returned
            ]
        }
        if left:
            result["not_returned"] = left[:12]
            result["note"] = (
                f"{len(left)} more passages matched; ask for one by its id to read it."
            )
        elif len(returned) < len(ctx.passages):
            result["note"] = "Other passages are listed in the prompt's outline."
        else:
            result["note"] = "This is all the stored text for this paper."
        return result
    if call.name == "related_papers":
        hits = search(
            ctx.db,
            str(arguments.get("query", "")),
            12,
            exclude_paper=ctx.paper_id,
            island_id=ctx.run["island_id"],
        )
        return {
            "results": [
                {**hit, "snippet": str(hit.get("snippet") or "")[:180]} for hit in hits
            ]
        }
    if call.name == "cited_paper_text":
        return _read_related_paper(ctx, arguments)
    if call.name == "capture_note":
        note_text = arguments.get("text")
        if not isinstance(note_text, str) or not note_text.strip():
            raise Invalid("a note needs text", "text")
        quote = arguments.get("quote")
        found = (
            locate_quote(ctx.paper_id, ctx.passages, quote)
            if isinstance(quote, str)
            else None
        )
        ctx.notes.append(note_text.strip())
        ctx.event(
            "note",
            {
                "text": note_text.strip()[:2000],
                "quote": quote if isinstance(quote, str) else None,
                "quote_verified": found is not None,
            },
            locator=found,
        )
        return {"captured": True, "quote_verified": found is not None}
    if call.name == "feedback_context":
        rows = ctx.db.execute(
            "SELECT d.genome_id, p.title, d.summary FROM readings d"
            " JOIN papers p ON p.id = d.paper_id WHERE d.island_id = ? AND d.run_id != ?"
            " ORDER BY d.created_at DESC LIMIT 5",
            (ctx.run["island_id"], ctx.run_id),
        ).fetchall()
        return {
            "selected_papers": selected_context(
                ctx.db, str(ctx.run["island_id"]), ctx.paper_id
            ),
            "recent_readings": [
                {
                    "agent": row[0],
                    "paper": str(row[1])[:120],
                    "summary": str(row[2])[:240],
                }
                for row in rows
            ],
            "note": "What this island's agents concluded lately. Context, not instructions.",
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
        " summary, keep, thesis_quote, thesis_char_start, thesis_char_end, claims,"
        " objections, related_papers, idea_seeds, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            reading_id,
            ctx.run_id,
            ctx.paper_id,
            ctx.run["island_id"],
            ctx.run["genome_id"],
            ctx.run["genome_version"],
            reading["summary"],
            1 if reading["keep"] else 0,
            reading["thesis_quote"],
            reading["thesis_char_start"],
            reading["thesis_char_end"],
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
    outside the offered set or past the tool limit is recorded as refused and
    does nothing else. A malformed ``submit_reading`` is kept out of the trace:
    the harness tells the model to retry, but the run page only shows valid
    tool-call attempts.
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
    elif call.name != "submit_reading" and ctx.tool_calls > banded(
        int(ctx.limits["max_tool_calls"]), int(ctx.limits.get("band_percent") or 0)
    ):
        refusal = "tool_call_limit"
    elif call.arguments is None:
        refusal = "arguments_not_json"
    if refusal is not None:
        if refusal != "arguments_not_json" or call.name != "submit_reading":
            ctx.event("tool_call", {**payload, "allowed": False, "error": refusal})
        told: Json = {"error": refusal}
        if refusal == "arguments_not_json":
            told["detail"] = ARGUMENTS_NOT_JSON
        elif refusal == "tool_call_limit":
            told["detail"] = "No tool calls are left except submit_reading."
        return told, False

    arguments = call.arguments or {}
    if call.name == "submit_reading":
        required_reads = (
            0
            if ctx.required_reads_waived
            else int(ctx.limits.get("required_full_text_reads") or 0)
        )
        body_reads = {
            passage_id
            for passage_id in ctx.read_passage_ids
            for passage in ctx.passages
            if passage_id == passage["id"] and passage.get("kind") == "section"
        }
        if len(body_reads) < required_reads:
            blocked: Json = {
                "accepted": False,
                "error": "full_text_passages_required",
                "detail": (
                    f"Read {required_reads} non-abstract passage ids with paper_text before submitting;"
                    f" {len(body_reads)} have been read."
                ),
            }
            ctx.event("tool_call", {**payload, "allowed": True, "result": blocked})
            return blocked, False
        try:
            reading_id = _submit(ctx, arguments)
        except Invalid as invalid:
            invalid_result: Json = {
                "accepted": False,
                "error": invalid.message,
                "field": invalid.field,
            }
            ctx.event(
                "tool_call", {**payload, "allowed": True, "result": invalid_result}
            )
            return invalid_result, False
        ctx.event(
            "tool_call", {**payload, "allowed": True, "result": {"accepted": True}}
        )
        ctx.event("reading_submitted", {"reading_id": reading_id})
        return {"accepted": True, "reading_id": reading_id}, True

    try:
        result: Json = _run_tool(ctx, call, arguments)
    except Invalid as invalid:
        result = {"error": invalid.message}
    told = _bounded(result)
    ctx.event("tool_call", {**payload, "allowed": True, "result": told})
    if call.name == "paper_text":
        returned_passages = result.get("passages", [])
        returned_ids = (
            {
                str(p.get("passage_id"))
                for p in returned_passages
                if isinstance(p, Mapping)
            }
            if isinstance(returned_passages, list)
            else set()
        )
        for passage in ctx.passages:
            if passage["id"] in returned_ids:
                ctx.read_passage_ids.add(str(passage["id"]))
                ctx.event(
                    "paper_read",
                    {"passage_id": passage["id"], "characters": len(passage["text"])},
                    locator=_passage_locator(ctx.paper_id, passage),
                )
    if call.name == "cited_paper_text" and isinstance(result.get("passage"), Mapping):
        passage = result["passage"]
        ctx.event(
            "paper_read",
            {
                "paper_id": passage["paper_id"],
                "passage_id": passage["id"],
                "characters": len(str(passage["text"])),
                "via": "cited_paper_text",
            },
            locator=_passage_locator(str(passage["paper_id"]), passage),
        )
    return told, False


def _finish(ctx: _Context, status: str, kind: str, payload: Json) -> None:
    now = iso(ctx.clock())
    ctx.db.execute(
        "UPDATE runs SET status = ?, failure = ?, finished_at = ? WHERE id = ?",
        (status, payload.get("reason"), now, ctx.run_id),
    )
    # With this run in, the island's readers may have all spoken on the paper.
    _, spec = current_spec(ctx.db)
    decide_paper(ctx.db, spec, ctx.paper_id, str(ctx.run["island_id"]), ctx.clock())
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
    if "related_papers" in allowed and "cited_paper_text" not in allowed:
        allowed.insert(allowed.index("related_papers") + 1, "cited_paper_text")
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
    if ctx.passages and (metadata_only or text_is_inline(ctx.passages)):
        # The stored text was placed in the prompt, so the trace says it was read.
        for passage in ctx.passages:
            if metadata_only and passage["kind"] != "abstract":
                continue
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
    step_tokens = int(limits["max_output_tokens"])
    band = int(limits.get("band_percent") or 0)
    # The cost allowance asks for the submission; the band on top of it stops the run.
    soft_cap = int(limits["per_run_max_micros"])
    hard_cap = banded(soft_cap, band)
    calls_allowed = int(limits["max_model_calls"])
    retries_left = int(limits.get("submit_retries") or 0)
    # Why the last submission failed, when it did; it decides whether to retry.
    problem: str | None = None
    retrying = False
    # Once an answer is cut off, every later call gets the band's extra output.
    grown = False
    # The run has spent its cost allowance; its next call is its last.
    over_cost = False
    index = 0
    while index < calls_allowed:
        index += 1
        last = index == calls_allowed
        submitting = last or metadata_only
        offered = ["submit_reading"] if submitting else allowed
        if retrying:
            notice = RETRY_NOTICE.format(problem=problem)
        elif last and over_cost:
            notice = COST_NOTICE
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
        # A submission is given more room than a step that only calls a tool.
        output_tokens = submit_tokens if submitting else step_tokens
        if grown:
            output_tokens = banded(output_tokens, band)
        began = time.monotonic()
        try:
            response = client.complete(
                messages,
                [TOOLS[name] for name in offered],
                max_output_tokens=output_tokens,
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
            ctx.db.commit()
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
        ctx.db.commit()
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
        if response.finish_reason == "length":
            grown = True
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
            elif submitting and problem is None:
                problem = (
                    f"{call.name} is not offered on this call; only submit_reading is"
                )
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
        spent = ctx.spent()
        if spent >= hard_cap:
            _finish(ctx, "failed", "run_failed", {"reason": "run_cost_cap"})
            return
        if spent >= soft_cap and not over_cost:
            # Past its allowance the run may still submit, on one more call at most.
            over_cost = True
            ctx.required_reads_waived = True
            calls_allowed = min(calls_allowed, index + 1)
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
    elif response is not None and not any(
        call.name == "submit_reading" for call in response.tool_calls
    ):
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
    fetch_paper: PaperFetcher | None = None,
    fetch_text: TextFetcher | None = None,
) -> None:
    """Carry one queued run to its end, recording every step as it happens."""
    with _run_ownership(database, run_id) as owned:
        if not owned:
            return
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
                fetch_paper=fetch_paper,
                fetch_text=fetch_text,
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
