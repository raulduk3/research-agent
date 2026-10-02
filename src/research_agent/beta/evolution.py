"""Simple evolution: score an island's agents, keep the best, mutate one child.

Evolution is a switch in the swarm spec (``evolution.enabled``) and a flag on
each island (``evolve``); both must be on. When an island has finished enough
runs or received enough feedback since its last generation, one cycle runs:

1. each active agent with enough runs is scored on usefulness (accepted minus
   pushed-away feedback per completed run, plus how often it completes);
2. agents are ranked by usefulness band, and cost per run only breaks a tie
   within a band; an agent whose runs cost more than the per-run cap is not
   eligible to parent;
3. the best is retained and one child is made from it by exactly one
   field-level mutation that no agent on the island already has;
4. when that puts the island over its agent cap, the worst judged agent is
   retired, which switches it off and removes nothing.

A generation is written as one spec revision together with its record, so it
appears whole or not at all and can be restored like any other edit. Mutation
is rule-based: it calls no model and costs nothing.
"""

from __future__ import annotations

import copy
import math
import random
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from research_agent.beta.budget import levers_from
from research_agent.beta.db import Json, dumps, iso, loads, new_id
from research_agent.beta.spec import (
    GENOME_CONTENT,
    EvolutionSettings,
    apply_spec,
    current_spec,
    evolution_of,
    find_island,
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
#: Usefulness is compared in bands this wide; cost decides inside a band.
BAND = 0.2


def score_genomes(
    db: sqlite3.Connection, island: Mapping[str, Any], settings: EvolutionSettings
) -> list[Json]:
    """Score each active agent of an island on the runs of its current version."""
    scored: list[Json] = []
    for genome in island["genomes"]:
        if not genome["active"]:
            continue
        row = db.execute(
            "SELECT COUNT(*) AS runs, COALESCE(SUM(r.status = 'completed'), 0) AS completed,"
            " COALESCE(SUM((SELECT SUM(c.amount_micros) FROM cost_receipts c"
            " WHERE c.run_id = r.id)), 0) AS cost,"
            " COALESCE(SUM((SELECT COUNT(*) FROM feedback f WHERE f.run_id = r.id"
            " AND f.signal = 'accept')), 0) AS accepted,"
            " COALESCE(SUM((SELECT COUNT(*) FROM feedback f WHERE f.run_id = r.id"
            " AND f.signal = 'push_away')), 0) AS pushed"
            " FROM runs r WHERE r.genome_id = ? AND r.genome_version = ?"
            " AND r.status IN ('completed', 'failed')",
            (genome["id"], genome["version"]),
        ).fetchone()
        runs, completed = int(row["runs"]), int(row["completed"])
        usefulness = (
            (row["accepted"] - row["pushed"]) / max(1, completed)
            + 0.5 * completed / runs
            if runs
            else 0.0
        )
        scored.append(
            {
                "genome_id": genome["id"],
                "version": genome["version"],
                "runs": runs,
                "completed": completed,
                "accepted": int(row["accepted"]),
                "pushed_away": int(row["pushed"]),
                "usefulness": round(usefulness, 3),
                "band": math.floor(usefulness / BAND + 1e-9),
                "mean_cost_micros": int(row["cost"]) // runs if runs else 0,
                "judged": runs >= settings.min_runs_to_judge,
            }
        )
    return scored


def select_survivors(scores: list[Json], per_run_max_micros: int) -> list[Json]:
    """Rank judged agents: usefulness band first, cost only inside a band.

    Returns the eligible agents best first. An agent whose mean run cost is
    above the per-run cap is marked ``over_budget`` and left out.
    """
    eligible = []
    for score in scores:
        score["over_budget"] = score["mean_cost_micros"] > per_run_max_micros
        if score["judged"] and not score["over_budget"]:
            eligible.append(score)
    return sorted(
        eligible,
        key=lambda item: (-item["band"], item["mean_cost_micros"], item["genome_id"]),
    )


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


def mutate_genome(
    genome: Mapping[str, Any], existing: list[Mapping[str, Any]], seed: str
) -> tuple[Json, Json] | None:
    """One field-level change to a parent that no existing agent already is.

    The same seed gives the same child. Returns the child's content and what
    was changed, or ``None`` when every offered change repeats an agent.
    """

    def same(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        return all(
            (sorted(a[name]) if name == "allowed_tools" else a[name])
            == (sorted(b[name]) if name == "allowed_tools" else b[name])
            for name in GENOME_CONTENT
        )

    for content, description in _mutations(genome, random.Random(seed)):
        if not any(same(content, other) for other in existing):
            return content, description
    return None


def _since_last(db: sqlite3.Connection, island_id: str) -> tuple[int, int, int]:
    """Generations so far, and runs and feedback since the last one."""
    last = db.execute(
        "SELECT COUNT(*), COALESCE(MAX(created_at), '') FROM generations WHERE island_id = ?",
        (island_id,),
    ).fetchone()
    runs = db.execute(
        "SELECT COUNT(*) FROM runs WHERE island_id = ? AND status = 'completed'"
        " AND finished_at > ?",
        (island_id, last[1]),
    ).fetchone()[0]
    feedback = db.execute(
        "SELECT COUNT(*) FROM feedback WHERE island_id = ? AND created_at > ?",
        (island_id, last[1]),
    ).fetchone()[0]
    return int(last[0]), int(runs), int(feedback)


def maybe_run_evolution(
    db: sqlite3.Connection, island_id: str, now: datetime, force: bool = False
) -> Json | None:
    """Run one evolution cycle for an island when it is due.

    Returns the generation record, committed or skipped with its reason, or
    ``None`` when evolution is off for the island or no threshold is crossed.
    ``force`` runs a cycle now regardless of the thresholds, never of the
    switches.
    """
    revision, spec = current_spec(db)
    settings = evolution_of(spec)
    island = find_island(spec, island_id)
    if not settings.enabled or not island["evolve"] or island["archived"]:
        return None
    count, runs, feedback = _since_last(db, island_id)
    due = runs >= settings.runs_threshold or feedback >= settings.feedback_threshold
    if not (due or force):
        return None

    number = count + 1
    scores = score_genomes(db, island, settings)
    ranked = select_survivors(scores, levers_from(spec["budget"]).per_run_max_micros)
    record: Json = {
        "id": new_id("G"),
        "island_id": island_id,
        "number": number,
        "status": "skipped",
        "reason": None,
        "revision": None,
        "decisions": [],
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

    def decide(score: Mapping[str, Any], decision: str, reason: str) -> None:
        record["decisions"].append({**score, "decision": decision, "reason": reason})

    if not ranked:
        for score in scores:
            reason = "over_budget" if score["over_budget"] else "too_few_runs"
            decide(score, "unjudged", reason)
        record["reason"] = "no_judged_agent"
        return close()

    parent_score = ranked[0]
    proposed = copy.deepcopy(spec)
    target = find_island(proposed, island_id)
    parent = next(g for g in target["genomes"] if g["id"] == parent_score["genome_id"])
    mutated = mutate_genome(parent, target["genomes"], f"{island_id}:{number}")
    if mutated is None:
        record["reason"] = "no_novel_mutation"
        return close()
    content, mutation = mutated

    retire: Mapping[str, Any] | None = None
    if len(scores) + 1 > settings.max_agents_per_island:
        worst = [score for score in reversed(ranked) if score is not parent_score]
        over = [score for score in scores if score["judged"] and score["over_budget"]]
        candidates = over + worst
        if not candidates:
            # Every other agent is too new to judge; nothing is retired on no evidence.
            record["reason"] = "population_full_awaiting_evidence"
            return close()
        retire = candidates[0]

    child_id = f"{island_id}-gen{number}"
    suffix = 1
    taken = {genome["id"] for item in proposed["islands"] for genome in item["genomes"]}
    while child_id in taken:
        suffix += 1
        child_id = f"{island_id}-gen{number}-{suffix}"
    target["genomes"].append({"id": child_id, "active": True, **content})
    for genome in target["genomes"]:
        if retire is not None and genome["id"] == retire["genome_id"]:
            genome["active"] = False
    lineage = {
        child_id: {
            "origin": "mutation",
            "parent": {"genome_id": parent["id"], "version": parent["version"]},
            "generation": number,
            "mutation": mutation,
        }
    }
    applied = apply_spec(
        db,
        proposed,
        actor="evolution",
        now=now,
        note=f"generation {number} on {island_id}",
        lineage=lineage,
    )

    for score in scores:
        if score is parent_score:
            decide(score, "retained", "best_usefulness_band")
        elif retire is not None and score is retire:
            reason = "over_budget" if score["over_budget"] else "lowest_usefulness_band"
            decide(score, "retired", reason)
        elif not score["judged"]:
            decide(score, "retained", "too_few_runs_to_judge")
        else:
            decide(score, "retained", "within_population_cap")
    record["decisions"].append(
        {
            "genome_id": child_id,
            "version": 1,
            "decision": "created",
            "reason": "mutation_of_best",
            "parent": lineage[child_id]["parent"],
            "mutation": mutation,
        }
    )
    record.update(status="committed", revision=applied["revision"])
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
