"""Evolution: a switch, a cadence, and a generative step with no fitness function.

Nothing here ranks agents. When an island has finished enough runs since its
last generation, a child is made for it by mating: a parent from the island
and a mate from another island are combined, then one thing is changed. A
model proposes the child from the whole swarm's state when a provider is
configured and the budget admits the call; otherwise a seeded rule does the
mating, so a cycle always produces something and a test can repeat it.

People shape the population two ways only: by archiving agents (switching
them off) and by letting go of papers. When an island is over its cap, the
agent with the fewest runs that is not a parent of the new child is archived,
so the population keeps turning over toward new things.

A generation is one spec revision together with its record, so it appears
whole or not at all, and shows on the island page with each decision.
"""

from __future__ import annotations

import copy
import json
import random
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from research_agent.beta.budget import (
    BudgetState,
    admit_paid,
    budget_state,
    estimate_tokens,
    levers_from,
    price_micros,
)
from research_agent.beta.config import ModelProvider
from research_agent.beta.costs import record_cost_receipt
from research_agent.beta.db import Json, dumps, iso, loads, new_id
from research_agent.beta.errors import Invalid
from research_agent.beta.likes import points_of
from research_agent.beta.models import ModelCallFailed, ModelClient
from research_agent.beta.spec import (
    GENOME_CONTENT,
    TOOL_NAMES,
    apply_spec,
    current_spec,
    evolution_of,
    find_island,
    validate_genome,
)

EMPHASES = (
    "Weigh the method before the result.",
    "Look first for what the evidence does not show.",
    "Name the single claim the paper cannot do without.",
    "Prefer what a practitioner could use this month.",
    "Ask what earlier work this quietly depends on.",
)
STRATEGIES = (
    "Read the stored text first, capture a note on the central claim, look for"
    " related stored papers, then submit the reading.",
    "Look for related stored papers before reading, then read the stored text"
    " against them and submit the reading.",
    "Read the stored text once, write the objections as notes first, then the"
    " claims, then submit the reading.",
)
OPTIONAL_TOOLS = ("related_papers", "capture_note", "feedback_context", "cost_state")
_EMPHASIS = "\n\nEmphasis: "
#: Output the proposing model is given to answer with.
PROPOSAL_TOKENS = 1200

PROPOSE_TOOL: Json = {
    "type": "function",
    "function": {
        "name": "propose_child",
        "description": (
            "Propose one new agent for the island by mating existing agents,"
            " from this island and from others, and changing something."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "parents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ids of the agents mated, at least one of this island's.",
                },
                "prompt": {"type": "string"},
                "reading_strategy": {"type": "string"},
                "temperature": {"type": "number"},
                "max_output_tokens": {"type": "integer"},
                "allowed_tools": {"type": "array", "items": {"type": "string"}},
                "why": {"type": "string", "description": "One sentence on the idea."},
                "archive": {
                    "type": "string",
                    "description": "An agent of this island to fail out, when one is"
                    " plainly not working: a lemon. Leave it out otherwise.",
                },
                "why_archive": {"type": "string"},
            },
            "required": ["parents", "prompt", "reading_strategy", "temperature", "why"],
        },
    },
}

_SYSTEM = (
    "You breed reading agents for a swarm that reads new arXiv papers. Each"
    " agent is a prompt, a reading strategy, a temperature, an output budget and"
    " a set of tools. There is no score to optimize: the point is variety that"
    " reads papers in ways the swarm has not tried, built from what works in"
    " other agents, on this island and across the others. Mate two or more"
    " agents, keep what is distinctive in each, change one thing, and keep the"
    " prompt under 900 characters. People give likes; an agent's points are the"
    " likes on its work and on papers it voted to keep, and they tell you what"
    " people enjoyed, not what is right. If one of the island's agents is plainly"
    " a lemon, name it in archive with a reason. Answer only by calling"
    " propose_child."
)


def _digest_genome(
    db: sqlite3.Connection, island_id: str, genome: Mapping[str, Any]
) -> str:
    row = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(status = 'completed'), 0),"
        " COALESCE((SELECT SUM(c.amount_micros) FROM cost_receipts c"
        " JOIN runs r2 ON r2.id = c.run_id WHERE r2.genome_id = ?), 0)"
        " FROM runs r WHERE r.genome_id = ?",
        (genome["id"], genome["id"]),
    ).fetchone()
    runs, completed, cost = int(row[0]), int(row[1]), int(row[2])
    points = points_of(db, str(genome["id"]))
    summaries = [
        str(item[0])[:160]
        for item in db.execute(
            "SELECT summary FROM readings WHERE genome_id = ?"
            " ORDER BY created_at DESC LIMIT 2",
            (genome["id"],),
        )
    ]
    settings = genome["model_settings"]
    lines = [
        f"- {genome['id']}@{island_id} (v{genome['version']},"
        f" gen {genome['lineage'].get('generation', 0)}): temperature"
        f" {settings['temperature']}, {settings['max_output_tokens']} tokens, tools"
        f" {', '.join(genome['allowed_tools'])}; {completed} of {runs} runs completed,"
        f" {cost // runs if runs else 0} micros per run, {points} points",
        f"  prompt: {str(genome['prompt'])[:400]}",
        f"  strategy: {str(genome['reading_strategy'])[:200]}",
    ]
    lines += [f"  recent reading: {text}" for text in summaries]
    return "\n".join(lines)


def swarm_digest(
    db: sqlite3.Connection, spec: Mapping[str, Any], island_id: str
) -> str:
    """The whole swarm as the proposing model sees it, this island first."""
    islands = sorted(spec["islands"], key=lambda item: item["id"] != island_id)
    parts: list[str] = []
    for island in islands:
        if island["archived"]:
            continue
        parts.append(f"## {island['name']} ({island['id']}): {island['focus']}")
        parts += [
            _digest_genome(db, str(island["id"]), g)
            for g in island["genomes"]
            if g["active"]
        ]
        archived = [g["id"] for g in island["genomes"] if not g["active"]]
        if archived:
            parts.append(f"  archived: {', '.join(archived)}")
    used = db.execute(
        "SELECT p.title, SUM(t.hits) AS hits FROM paper_traffic t"
        " JOIN papers p ON p.id = t.paper_id GROUP BY p.id ORDER BY hits DESC LIMIT 5"
    ).fetchall()
    if used:
        parts.append("## Papers people asked for most")
        parts += [f"- {row[0]} ({row[1]} requests)" for row in used]
    return "\n".join(parts)


def _mutations(
    genome: Mapping[str, Any], rng: random.Random
) -> list[tuple[Json, Json]]:
    """Every single-field change on offer, shuffled: (new content, description)."""
    content = {name: copy.deepcopy(genome[name]) for name in GENOME_CONTENT}
    offers: list[tuple[Json, Json]] = []

    def offer(field: str, value: Any, operator: str) -> None:
        if value != content[field]:
            description = {"operator": operator, "field": field}
            offers.append(({**content, field: value}, description))

    base = str(content["prompt"]).split(_EMPHASIS)[0]
    for emphasis in EMPHASES:
        offer("prompt", f"{base}{_EMPHASIS}{emphasis}", "emphasis")
    for strategy in STRATEGIES:
        offer("reading_strategy", strategy, "strategy")
    settings = content["model_settings"]
    for step in (-0.15, 0.15):
        temperature = round(min(1.2, max(0.1, settings["temperature"] + step)), 2)
        offer("model_settings", {**settings, "temperature": temperature}, "temperature")
    for factor in (0.8, 1.25):
        tokens = int(min(2000, max(256, settings["max_output_tokens"] * factor)))
        offer(
            "model_settings", {**settings, "max_output_tokens": tokens}, "output_tokens"
        )
    for tool in OPTIONAL_TOOLS:
        tools = list(content["allowed_tools"])
        if tool in tools:
            tools.remove(tool)
        else:
            tools.append(tool)
        offer("allowed_tools", tools, "tool")
    rng.shuffle(offers)
    return offers


def _same(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return all(
        (sorted(a[name]) if name == "allowed_tools" else a[name])
        == (sorted(b[name]) if name == "allowed_tools" else b[name])
        for name in GENOME_CONTENT
    )


def mutate_genome(
    genome: Mapping[str, Any], existing: Sequence[Mapping[str, Any]], seed: str
) -> tuple[Json, Json] | None:
    """One field-level change to a genome that no existing agent already is.

    The same seed gives the same child. Returns the child's content and what
    was changed, or ``None`` when every offered change repeats an agent.
    """
    for content, description in _mutations(genome, random.Random(seed)):
        if not any(_same(content, other) for other in existing):
            return content, description
    return None


def _bent(prompt: str) -> str:
    """The part of a prompt after its first sentence: what makes the agent itself."""
    head, _, rest = prompt.partition(". ")
    return rest.strip() if rest.strip() else head.strip()


def mate_genomes(
    parent: Mapping[str, Any],
    mate: Mapping[str, Any],
    existing: Sequence[Mapping[str, Any]],
    seed: str,
) -> tuple[Json, Json] | None:
    """Cross two agents by rule, then change one thing.

    The child keeps the parent's prompt and takes the mate's bent as a second
    paragraph, the mate's reading strategy, the mean temperature and the
    union of tools. The same seed gives the same child; ``None`` when every
    offered change repeats an agent already on the island.
    """
    base = str(parent["prompt"]).split(_EMPHASIS)[0]
    bent = _bent(str(mate["prompt"]).split(_EMPHASIS)[0])
    mean = (
        float(parent["model_settings"]["temperature"])
        + float(mate["model_settings"]["temperature"])
    ) / 2
    crossed: Json = {
        "prompt": f"{base}\n\nAlso, from {mate['id']}: {bent}"[:1800],
        "model_settings": {**parent["model_settings"], "temperature": round(mean, 2)},
        "allowed_tools": sorted(
            set(parent["allowed_tools"]) | set(mate["allowed_tools"])
        ),
        "reading_strategy": mate["reading_strategy"],
        "scoring_preferences": parent["scoring_preferences"],
    }
    for content, description in _mutations(crossed, random.Random(seed)):
        if not any(_same(content, other) for other in existing):
            return content, {**description, "crossed_with": mate["id"]}
    return None


def _runs_of(db: sqlite3.Connection, genome_id: str) -> int:
    return int(
        db.execute(
            "SELECT COUNT(*) FROM runs WHERE genome_id = ? AND status = 'completed'",
            (genome_id,),
        ).fetchone()[0]
    )


def _since_last(db: sqlite3.Connection, island_id: str) -> tuple[int, int]:
    """Generations so far, and completed runs since the last one."""
    last = db.execute(
        "SELECT COUNT(*), COALESCE(MAX(created_at), '') FROM generations WHERE island_id = ?",
        (island_id,),
    ).fetchone()
    runs = db.execute(
        "SELECT COUNT(*) FROM runs WHERE island_id = ? AND status = 'completed'"
        " AND finished_at > ?",
        (island_id, last[1]),
    ).fetchone()[0]
    return int(last[0]), int(runs)


def _proposal_from_model(
    db: sqlite3.Connection,
    *,
    spec: Mapping[str, Any],
    island: Mapping[str, Any],
    state: BudgetState,
    provider: ModelProvider,
    client: ModelClient,
    generation_id: str,
    now: datetime,
) -> tuple[Json | None, Json]:
    """Ask the model for a child. Returns (content or None, what happened)."""
    island_id = str(island["id"])
    user = (
        f"Make one new agent for {island['name']} ({island_id}), whose focus is"
        f" {island['focus']}.\n\n{swarm_digest(db, spec, island_id)}"
    )
    estimate = price_micros(provider, estimate_tokens(_SYSTEM + user), PROPOSAL_TOKENS)
    refused = admit_paid(
        state, estimate, state.levers.per_evolution_max_micros, "evolution"
    )
    if refused is not None:
        return None, {"model": "refused", "reason": refused}
    common: dict[str, Any] = {
        "owner_kind": "generation",
        "owner_id": generation_id,
        "parent_kind": "island",
        "parent_id": island_id,
        "island_id": island_id,
        "provider": provider.name,
    }
    try:
        reply = client.complete(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            [PROPOSE_TOOL],
            max_output_tokens=PROPOSAL_TOKENS,
            temperature=0.9,
        )
    except ModelCallFailed as exc:
        record_cost_receipt(
            db,
            action="evolution",
            unit_type="tokens",
            quantity=estimate_tokens(user),
            amount_micros=estimate,
            now=now,
            estimated=True,
            settled=False,
            **common,
        )
        return None, {"model": "failed", "reason": str(exc)[:200]}
    amount = price_micros(provider, reply.input_tokens, reply.output_tokens)
    record_cost_receipt(
        db,
        action="evolution",
        unit_type="tokens",
        quantity=reply.input_tokens + reply.output_tokens,
        amount_micros=amount,
        now=now,
        estimated=not reply.usage_reported,
        **common,
    )
    call = next((c for c in reply.tool_calls if c.name == "propose_child"), None)
    if call is None:
        return None, {"model": "no_proposal", "cost_micros": amount}
    arguments = call.arguments
    if arguments is None:
        try:
            arguments = json.loads(call.raw_arguments)
        except (TypeError, ValueError):
            return None, {"model": "malformed_proposal", "cost_micros": amount}
    if not isinstance(arguments, Mapping):
        return None, {"model": "malformed_proposal", "cost_micros": amount}
    known = {g["id"]: g for item in spec["islands"] for g in item["genomes"]}
    parents = [
        p for p in arguments.get("parents", []) if isinstance(p, str) and p in known
    ]
    own = [p for p in parents if any(g["id"] == p for g in island["genomes"])]
    if not own:
        return None, {"model": "no_parent_on_island", "cost_micros": amount}
    first = known[own[0]]
    tools = [
        t
        for t in (arguments.get("allowed_tools") or first["allowed_tools"])
        if t in TOOL_NAMES
    ]
    if "submit_reading" not in tools:
        tools.append("submit_reading")
    try:
        temperature = float(arguments.get("temperature", 0.7))
        tokens = int(
            arguments.get("max_output_tokens")
            or first["model_settings"]["max_output_tokens"]
        )
    except (TypeError, ValueError):
        return None, {"model": "malformed_proposal", "cost_micros": amount}
    content: Json = {
        "prompt": str(arguments.get("prompt", ""))[:1800],
        "model_settings": {
            "temperature": round(min(1.2, max(0.1, temperature)), 2),
            "max_output_tokens": int(min(2000, max(256, tokens))),
        },
        "allowed_tools": sorted(set(tools)),
        "reading_strategy": str(arguments.get("reading_strategy", ""))[:600],
        "scoring_preferences": first["scoring_preferences"],
    }
    try:
        validate_genome({"id": "child", **content}, "child")
    except Invalid as exc:
        return None, {
            "model": "invalid_proposal",
            "reason": exc.message,
            "cost_micros": amount,
        }
    if any(_same(content, g) for g in island["genomes"]):
        return None, {"model": "repeats_an_agent", "cost_micros": amount}
    lemon = arguments.get("archive")
    on_island = {str(g["id"]) for g in island["genomes"] if g["active"]}
    return content, {
        "model": "proposed",
        "parents": parents,
        "why": str(arguments.get("why", ""))[:300],
        "archive": lemon
        if isinstance(lemon, str) and lemon in on_island and lemon not in parents
        else None,
        "why_archive": str(arguments.get("why_archive", ""))[:300],
        "cost_micros": amount,
    }


def _version_of(spec: Mapping[str, Any], genome_id: str) -> int:
    for island in spec["islands"]:
        for genome in island["genomes"]:
            if genome["id"] == genome_id:
                return int(genome["version"])
    return 1


def _unfinished_readers(
    db: sqlite3.Connection, island: Mapping[str, Any], count: int
) -> set[str]:
    protected: set[str] = set()
    fallback = min(count, sum(bool(g["active"]) for g in island["genomes"]))
    papers = db.execute(
        "SELECT a.paper_id FROM assignments a WHERE a.island_id = ? AND a.kept IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM paper_releases r WHERE r.paper_id = a.paper_id)"
        " AND NOT EXISTS (SELECT 1 FROM paper_selections s WHERE s.paper_id = a.paper_id)",
        (island["id"],),
    ).fetchall()
    for paper in papers:
        first = db.execute(
            "SELECT limits FROM runs WHERE paper_id = ? AND island_id = ? ORDER BY rowid LIMIT 1",
            (paper[0], island["id"]),
        ).fetchone()
        size = (
            int(loads(first[0]).get("agents_per_paper", fallback))
            if first
            else fallback
        )
        readers = db.execute(
            "SELECT genome_id FROM runs WHERE paper_id = ? AND island_id = ?"
            " GROUP BY genome_id ORDER BY MIN(rowid) LIMIT ?",
            (paper[0], island["id"], size),
        ).fetchall()
        for reader in readers:
            vote = db.execute(
                "SELECT r.status, (SELECT d.keep FROM readings d WHERE d.run_id = r.id)"
                " FROM runs r WHERE r.paper_id = ? AND r.genome_id = ? ORDER BY r.rowid DESC LIMIT 1",
                (paper[0], reader[0]),
            ).fetchone()
            if vote is None or vote[0] != "completed" or vote[1] is None:
                protected.add(str(reader[0]))
    return protected


def maybe_run_evolution(
    db: sqlite3.Connection,
    island_id: str,
    now: datetime,
    force: bool = False,
    *,
    provider: ModelProvider | None = None,
    client: ModelClient | None = None,
) -> Json | None:
    """Run one evolution cycle for an island when it is due.

    Returns the generation record, committed or skipped with its reason, or
    ``None`` when evolution is off for the island or no threshold is crossed.
    ``force`` runs a cycle now regardless of the threshold, never of the
    switches.
    """
    _, spec = current_spec(db)
    settings = evolution_of(spec)
    island = find_island(spec, island_id)
    if not settings.enabled or not island["evolve"] or island["archived"]:
        return None
    count, runs = _since_last(db, island_id)
    if not (runs >= settings.runs_threshold or force):
        return None

    number = count + 1
    record: Json = {
        "id": new_id("G"),
        "island_id": island_id,
        "number": number,
        "status": "skipped",
        "reason": None,
        "revision": None,
        "decisions": [],
        "cost_micros": 0,
        "created_at": iso(now),
    }

    def close() -> Json:
        db.execute(
            "INSERT INTO generations(id, island_id, number, status, reason, revision,"
            " decisions, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record["id"],
                island_id,
                number,
                record["status"],
                record["reason"],
                record["revision"],
                dumps(record["decisions"]),
                record["created_at"],
            ),
        )
        return record

    def decide(genome_id: str, decision: str, reason: str, **more: Any) -> None:
        record["decisions"].append(
            {"genome_id": genome_id, "decision": decision, "reason": reason, **more}
        )

    active = [g for g in island["genomes"] if g["active"]]
    if not active:
        record["reason"] = "no_active_agent"
        return close()
    # The parent is the island's most liked agent, then its most experienced; the
    # mate comes from another island, chosen by the generation's seed so the
    # pairing repeats.
    parent = max(
        active,
        key=lambda g: (
            points_of(db, str(g["id"])),
            _runs_of(db, str(g["id"])),
            str(g["id"]),
        ),
    )
    rng = random.Random(f"{island_id}:{number}")
    elsewhere = [
        (str(other["id"]), g)
        for other in spec["islands"]
        if other["id"] != island_id and not other["archived"]
        for g in other["genomes"]
        if g["active"]
    ]
    mate_island, mate = rng.choice(elsewhere) if elsewhere else (None, None)

    child: Json | None = None
    how: Json = {}
    if island["mutate"]:
        if provider is not None and client is not None:
            state = budget_state(db, spec, now, True)
            child, how = _proposal_from_model(
                db,
                spec=spec,
                island=island,
                state=state,
                provider=provider,
                client=client,
                generation_id=str(record["id"]),
                now=now,
            )
            record["cost_micros"] = int(how.get("cost_micros", 0))
        if child is None:
            seed = f"{island_id}:{number}"
            bred = (
                mate_genomes(parent, mate, island["genomes"], seed)
                if mate is not None
                else mutate_genome(parent, island["genomes"], seed)
            )
            if bred is None:
                record["reason"] = "no_novel_child"
                record["decisions"].append(
                    {
                        "genome_id": None,
                        "decision": "none",
                        "reason": "no_novel_child",
                        **how,
                    }
                )
                return close()
            child = bred[0]
            how = {
                **how,
                "rule": bred[1],
                "parents": [parent["id"]] + ([mate["id"]] if mate is not None else []),
            }

    parents: list[str] = (
        list(how.get("parents", [parent["id"]])) if child is not None else []
    )
    protected = _unfinished_readers(
        db,
        island,
        levers_from(spec.get("budget", {})).agents_per_paper,
    )
    candidates = [
        g for g in active if g["id"] not in parents and g["id"] not in protected
    ]
    archived: str | None = None
    archive_reason = "population_cap"
    lemon = how.get("archive")
    if isinstance(lemon, str) and any(g["id"] == lemon for g in candidates):
        archived, archive_reason = lemon, "breeder_lemon"
    elif child is not None and len(active) + 1 > settings.max_agents_per_island:
        if not candidates:
            record["reason"] = "pending_reading_cohort"
            return close()
        victim = min(
            candidates, key=lambda g: (_runs_of(db, str(g["id"])), str(g["id"]))
        )
        archived = str(victim["id"])

    proposed = copy.deepcopy(spec)
    target = find_island(proposed, island_id)
    lineage: dict[str, Json] = {}
    child_id: str | None = None
    if child is not None:
        child_id = f"{island_id}-gen{number}"
        suffix = 1
        taken = {g["id"] for item in proposed["islands"] for g in item["genomes"]}
        while child_id in taken:
            suffix += 1
            child_id = f"{island_id}-gen{number}-{suffix}"
        target["genomes"].append({"id": child_id, "active": True, **child})
        lineage[child_id] = {
            "origin": "mating" if len(parents) > 1 else "mutation",
            "parent": {
                "genome_id": parents[0],
                "version": _version_of(spec, parents[0]),
            },
            "parents": parents,
            "generation": number,
            "mutation": how.get("rule"),
            "proposed_by": "model" if how.get("model") == "proposed" else "rule",
            "why": how.get("why"),
        }

    if archived is not None:
        for genome in target["genomes"]:
            if genome["id"] == archived:
                genome["active"] = False

    applied = apply_spec(
        db,
        proposed,
        actor="evolution",
        now=now,
        note=f"generation {number} on {island_id}",
        lineage=lineage,
    )
    for genome in active:
        if genome["id"] == archived:
            decide(
                str(genome["id"]),
                "archived",
                archive_reason,
                why=how.get("why_archive")
                if archive_reason == "breeder_lemon"
                else None,
            )
        elif genome["id"] in parents:
            decide(str(genome["id"]), "parent", "mated")
        else:
            decide(str(genome["id"]), "kept", "no_ranking")
    if mate is not None and mate["id"] in parents:
        decide(str(mate["id"]), "mate", "from_another_island", island_id=mate_island)
    if child_id is not None:
        decide(
            child_id,
            "created",
            "model_mating" if how.get("model") == "proposed" else "rule_mating",
            parents=parents,
            mutation=how.get("rule"),
            why=how.get("why"),
        )
    record.update(
        status="committed", revision=applied["revision"] if applied["applied"] else None
    )
    return close()


def build_generation_activity(
    db: sqlite3.Connection, island_id: str, limit: int = 20
) -> list[Json]:
    """An island's recent generations, newest first, with every decision."""
    rows = db.execute(
        "SELECT id, island_id, number, status, reason, revision, decisions, created_at"
        " FROM generations WHERE island_id = ? ORDER BY number DESC LIMIT ?",
        (island_id, limit),
    ).fetchall()
    return [{**dict(row), "decisions": loads(row["decisions"])} for row in rows]
