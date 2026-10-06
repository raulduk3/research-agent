"""The swarm spec: one editable document, kept as an append-only revision log.

Islands, their genomes, the budget levers and the evolution settings are
declared in one JSON document. Every edit validates the whole document and writes a new revision;
nothing is updated in place and nothing is deleted. That is what makes
editing safe:

- a run records the revision and the genome version it ran under and keeps a
  copy of that genome, so a later edit cannot change what a past run was;
- any earlier revision can be restored, which writes a new revision with the
  old content rather than rewinding the log;
- an island or genome is switched off (``archived``, ``active: false``),
  never removed, so every stored run still resolves.

A genome's ``version`` and ``lineage`` are managed here: a change to its
prompt, model settings, tools, reading strategy or scoring preferences makes
the next version, whose lineage names its parent.
"""

from __future__ import annotations

import copy
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from datetime import datetime
from typing import Any

from research_agent.beta.budget import PRIORITIES, levers_from
from research_agent.beta.db import Json, dumps, iso, loads
from research_agent.beta.errors import Invalid, NotFound
from research_agent.beta.methods import (
    island_methods,
    methods_profile,
    unique_instructions,
)

#: The harness tools a genome may allow. ``submit_reading`` is how a run ends.
TOOL_NAMES = (
    "paper_text",
    "related_papers",
    "cited_paper_text",
    "capture_note",
    "feedback_context",
    "cost_state",
    "submit_reading",
)
READING_MODES = ("abstract", "metadata")
#: The island a paper falls to when nothing else claims it.
FALLBACK_ISLAND = "general"

ISLAND_FIELDS = (
    "name",
    "focus",
    "categories",
    "keywords",
    "priority",
    "reading_mode",
    "paused",
    "archived",
    "budget_share",
    "evolve",
    "mutate",
)
GENOME_CONTENT = (
    "prompt",
    "research_methods",
    "model_settings",
    "allowed_tools",
    "reading_strategy",
    "scoring_preferences",
)


@dataclass(frozen=True)
class EvolutionSettings:
    """The evolution block of the spec. Every field is editable."""

    enabled: bool = True
    #: Completed runs on an island since its last generation that start a cycle.
    runs_threshold: int = 6
    #: Active agents an island may hold; past it, the least-run agent is archived.
    max_agents_per_island: int = 6


#: Settings from before evolution stopped ranking; read and dropped.
_RETIRED_EVOLUTION_SETTINGS = (
    "feedback_threshold",
    "verdict_threshold",
    "min_runs_to_judge",
)


def evolution_settings_from(doc: Mapping[str, Any]) -> EvolutionSettings:
    """Validate the evolution block; absent settings take the defaults."""
    known = {item.name for item in dataclass_fields(EvolutionSettings)}
    doc = {k: v for k, v in doc.items() if k not in _RETIRED_EVOLUTION_SETTINGS}
    unknown = sorted(set(doc) - known)
    if unknown:
        raise Invalid(
            f"unknown evolution setting {unknown[0]}", f"evolution.{unknown[0]}"
        )
    for name, value in doc.items():
        where = f"evolution.{name}"
        if name == "enabled":
            if not isinstance(value, bool):
                raise Invalid("enabled must be true or false", where)
        elif isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise Invalid(f"{name} must be a whole number of at least 1", where)
    return EvolutionSettings(**doc)


_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_CATEGORY = re.compile(r"^[a-z-]+(\.([A-Za-z-]+|\*))?$")


#: The three agents every island starts with, carried over from the first research
#: agent's launch procedures and said in this version's terms: a name, a
#: temperature, the procedure, and how to read. Three postures, so the readers
#: who decide a paper together disagree in useful ways: one reads for the
#: evidence, one for what could be wrong, one for what can be built on.
FOUNDERS: tuple[tuple[str, float, str, str], ...] = (
    (
        "reader",
        0.7,
        "Locate the paper's central result and the evidence offered for it before"
        " anything else. Identify the main claim, read the section that carries its"
        " evidence, and judge whether that evidence is direct, indirect or absent."
        " Only then look outward at related work. Quote the words that carry each"
        " claim, say what a skeptical reviewer would object to, and leave idea seeds"
        " the group could act on. Keep the paper only if its evidence is direct.",
        "Read the abstract, then the passage that holds the central result: results,"
        " experiments or the main theorem. Read a second passage only if the first"
        " was partial. Look for related stored papers only after the evidence is read."
        " Then submit the reading.",
    ),
    (
        "skeptic",
        0.4,
        "Look for what could make the conclusion wrong. Scrutinize how the result was"
        " obtained: the method, the data or setting, and every assumption the"
        " conclusion needs, recording whether the paper states it, tests it or leaves"
        " it implicit. Then list the alternative explanations of the main result the"
        " paper does not rule out. Be sparing with praise. Keep the paper only if its"
        " conclusion survives the untested assumptions.",
        "Read the methods, setup or proofs passages before the results, then the"
        " limitations or discussion. Capture each open alternative as a note. Then"
        " submit the reading.",
    ),
    (
        "builder",
        0.9,
        "Read for what can be built on. Place the paper against the stored papers"
        " near it and say what is new; state its central claim in one sentence and"
        " chain its consequences forward, what else must hold if it is true and what"
        " later work it would make possible; quote the passage that makes a method"
        " or result reusable, and seed concrete next experiments. Keep the paper only"
        " if the group could act on it this month.",
        "Look for related stored papers first and read their abstracts. Read the"
        " abstract, then the one passage that makes the contribution usable. Then"
        " submit the reading.",
    ),
)


def founders(
    island_id: str, focus: str, categories: list[str] | None = None
) -> list[Json]:
    """The island's starting agents, one per posture in ``FOUNDERS``."""
    return [
        {
            "id": f"{island_id}-{name}",
            "prompt": (
                f"You read one new paper for a research group whose focus is {focus}. "
                + procedure
            ),
            "research_methods": methods_profile(island_id, focus, categories or []),
            "model_settings": {"temperature": temperature, "max_output_tokens": 900},
            "allowed_tools": list(TOOL_NAMES),
            "reading_strategy": strategy,
            "scoring_preferences": {"novelty": 0.4, "rigor": 0.4, "usefulness": 0.2},
            "active": True,
        }
        for name, temperature, procedure, strategy in FOUNDERS
    ]


def default_spec() -> Json:
    """The spec a fresh store starts from; every part of it is editable."""
    seeds: tuple[tuple[str, str, str, list[str]], ...] = (
        (
            "cs",
            "CS island",
            "agents, memory, evaluation",
            ["cs.AI", "cs.LG", "cs.CL", "cs.MA"],
        ),
        (
            "quant",
            "Quant island",
            "optimization, simulation, quantum methods",
            ["quant-ph"],
        ),
        ("bio", "Bio island", "mechanisms, methods, biological systems", ["q-bio.*"]),
        (
            FALLBACK_ISLAND,
            "General island",
            "statistics, optimization, complex systems and unclaimed papers",
            ["stat.ML", "math.OC", "physics.soc-ph"],
        ),
    )
    shares = {"cs": 0.4, "quant": 0.25, "bio": 0.25, FALLBACK_ISLAND: 0.1}
    return {
        "islands": [
            {
                "id": island_id,
                "name": name,
                "focus": focus,
                "categories": categories,
                "keywords": [word.strip() for word in focus.split(",")]
                if island_id != FALLBACK_ISLAND
                else [],
                "priority": "low" if island_id == FALLBACK_ISLAND else "normal",
                "reading_mode": "abstract",
                "paused": False,
                "archived": False,
                "budget_share": shares[island_id],
                "evolve": True,
                "mutate": True,
                "genomes": founders(island_id, focus, categories),
            }
            for island_id, name, focus, categories in seeds
        ],
        "budget": {},
        "evolution": {},
    }


def _text(value: Any, where: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Invalid("must be non-empty text", where)
    if len(value) > limit:
        raise Invalid(f"must be at most {limit} characters", where)
    return value.strip()


def _words(value: Any, where: str, pattern: re.Pattern[str] | None = None) -> list[str]:
    if not isinstance(value, list) or len(value) > 40:
        raise Invalid("must be a list of at most 40 entries", where)
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 60:
            raise Invalid("entries must be short text", where)
        if pattern is not None and not pattern.match(item):
            raise Invalid(
                f"{item!r} is not an arXiv category such as cs.AI or q-bio.*", where
            )
    return [item.strip() for item in value]


def _validate_methods(value: Any, where: str) -> Json:
    if value == {}:
        return {}
    field = f"{where}.research_methods"
    if not isinstance(value, Mapping) or set(value) != {
        "version",
        "domain",
        "specialist",
        "instructions",
        "sources",
    }:
        raise Invalid(
            "research_methods must declare its version, domain, instructions and sources",
            field,
        )
    version = value["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise Invalid("research_methods version must be a positive integer", field)
    if not isinstance(value["specialist"], bool):
        raise Invalid("research_methods specialist must be boolean", field)
    sources = value["sources"]
    if not isinstance(sources, list) or not sources or len(sources) > 10:
        raise Invalid("research_methods sources must be a non-empty list", field)
    checked = []
    for source in sources:
        if not isinstance(source, Mapping) or set(source) != {"title", "url"}:
            raise Invalid("a research_methods source declares title and url", field)
        checked.append(
            {
                "title": _text(source["title"], field, 500),
                "url": _text(source["url"], field, 1000),
            }
        )
    return {
        "version": version,
        "domain": _text(value["domain"], field, 100),
        "specialist": value["specialist"],
        "instructions": unique_instructions(_text(value["instructions"], field, 4000)),
        "sources": checked,
    }


def validate_genome(genome: Any, where: str) -> Json:
    """Require every field a genome declares and return its normal form."""
    if not isinstance(genome, Mapping):
        raise Invalid("a genome is an object", where)
    for name in ("id", *GENOME_CONTENT):
        if name not in genome and name != "research_methods":
            raise Invalid(f"a genome must declare {name}", f"{where}.{name}")
    genome_id = genome["id"]
    if not isinstance(genome_id, str) or not _SLUG.match(genome_id):
        raise Invalid("an id is lowercase letters, digits and hyphens", f"{where}.id")
    settings = genome["model_settings"]
    if not isinstance(settings, Mapping) or set(settings) != {
        "temperature",
        "max_output_tokens",
    }:
        raise Invalid(
            "model_settings holds temperature and max_output_tokens",
            f"{where}.model_settings",
        )
    temperature, tokens = settings["temperature"], settings["max_output_tokens"]
    if isinstance(temperature, bool) or not isinstance(temperature, int | float):
        raise Invalid("temperature is a number", f"{where}.model_settings.temperature")
    if not 0 <= temperature <= 2:
        raise Invalid(
            "temperature is between 0 and 2", f"{where}.model_settings.temperature"
        )
    if (
        isinstance(tokens, bool)
        or not isinstance(tokens, int)
        or not 64 <= tokens <= 8000
    ):
        raise Invalid(
            "max_output_tokens is a whole number from 64 to 8000",
            f"{where}.model_settings.max_output_tokens",
        )
    tools = genome["allowed_tools"]
    if not isinstance(tools, list) or len(set(tools)) != len(tools):
        raise Invalid(
            "allowed_tools is a list without repeats", f"{where}.allowed_tools"
        )
    for tool in tools:
        if tool not in TOOL_NAMES:
            raise Invalid(f"{tool!r} is not a harness tool", f"{where}.allowed_tools")
    if "submit_reading" not in tools:
        raise Invalid("a genome must allow submit_reading", f"{where}.allowed_tools")
    preferences = genome["scoring_preferences"]
    if not isinstance(preferences, Mapping) or not all(
        isinstance(key, str)
        and isinstance(value, int | float)
        and not isinstance(value, bool)
        for key, value in preferences.items()
    ):
        raise Invalid(
            "scoring_preferences maps names to numbers", f"{where}.scoring_preferences"
        )
    active = genome.get("active", True)
    if not isinstance(active, bool):
        raise Invalid("active must be true or false", f"{where}.active")
    return {
        "id": genome_id,
        "research_methods": _validate_methods(
            genome.get("research_methods", {}), where
        ),
        "prompt": unique_instructions(_text(genome["prompt"], f"{where}.prompt", 8000)),
        "model_settings": {
            "temperature": float(temperature),
            "max_output_tokens": tokens,
        },
        "allowed_tools": [tool for tool in TOOL_NAMES if tool in tools],
        "reading_strategy": unique_instructions(
            _text(genome["reading_strategy"], f"{where}.reading_strategy", 2000)
        ),
        "scoring_preferences": {
            key: float(value) for key, value in preferences.items()
        },
        "active": active,
        # Managed by apply_spec; a caller's values are carried only for comparison.
        "version": genome.get("version", 0),
        "lineage": genome.get("lineage", {}),
    }


def _validate_island(island: Any, where: str) -> Json:
    if not isinstance(island, Mapping):
        raise Invalid("an island is an object", where)
    for name in ("id", "name", "focus"):
        if name not in island:
            raise Invalid(f"an island must declare {name}", f"{where}.{name}")
    island_id = island["id"]
    if not isinstance(island_id, str) or not _SLUG.match(island_id):
        raise Invalid("an id is lowercase letters, digits and hyphens", f"{where}.id")
    priority = island.get("priority", "normal")
    if priority not in PRIORITIES:
        raise Invalid("priority is high, normal or low", f"{where}.priority")
    mode = island.get("reading_mode", "abstract")
    if mode not in READING_MODES:
        raise Invalid("reading_mode is abstract or metadata", f"{where}.reading_mode")
    flags = {}
    for name in ("paused", "archived", "evolve", "mutate"):
        flags[name] = island.get(name, name in ("evolve", "mutate"))
        if not isinstance(flags[name], bool):
            raise Invalid(f"{name} must be true or false", f"{where}.{name}")
    share = island.get("budget_share", 0.0)
    if isinstance(share, bool) or not isinstance(share, int | float) or share < 0:
        raise Invalid("budget_share is a number, zero or more", f"{where}.budget_share")
    genomes = island.get("genomes", [])
    if not isinstance(genomes, list):
        raise Invalid("genomes is a list", f"{where}.genomes")
    return {
        "id": island_id,
        "name": _text(island["name"], f"{where}.name", 80),
        "focus": _text(island["focus"], f"{where}.focus", 400),
        "categories": _words(
            island.get("categories", []), f"{where}.categories", _CATEGORY
        ),
        "keywords": [
            word.lower() for word in _words(island.get("keywords", []), where)
        ],
        "priority": priority,
        "reading_mode": mode,
        "paused": flags["paused"],
        "archived": flags["archived"],
        "budget_share": float(share),
        "evolve": flags["evolve"],
        "mutate": flags["mutate"],
        "genomes": [
            validate_genome(genome, f"{where}.genomes[{index}]")
            for index, genome in enumerate(genomes)
        ],
    }


def validate_spec(doc: Any) -> Json:
    """Check a whole spec and return it in normal form, or refuse with a field."""
    if not isinstance(doc, Mapping) or not isinstance(doc.get("islands"), list):
        raise Invalid("a spec holds an islands list and a budget block", "islands")
    islands = [
        _validate_island(island, f"islands[{index}]")
        for index, island in enumerate(doc["islands"])
    ]
    island_ids = [island["id"] for island in islands]
    if len(set(island_ids)) != len(island_ids):
        raise Invalid("island ids must be unique", "islands")
    genome_ids = [genome["id"] for island in islands for genome in island["genomes"]]
    if len(set(genome_ids)) != len(genome_ids):
        raise Invalid("genome ids must be unique across the swarm", "islands")
    fallback = next(
        (island for island in islands if island["id"] == FALLBACK_ISLAND), None
    )
    if fallback is None or fallback["archived"]:
        raise Invalid(
            f"the {FALLBACK_ISLAND} island must exist and stay open", "islands"
        )
    if not any(
        island["budget_share"] > 0 for island in islands if not island["archived"]
    ):
        raise Invalid("at least one open island needs a budget share", "islands")
    budget = doc.get("budget", {})
    if not isinstance(budget, Mapping):
        raise Invalid("budget is an object of levers", "budget")
    levers_from(budget)
    evolution = doc.get("evolution", {})
    if not isinstance(evolution, Mapping):
        raise Invalid("evolution is an object of settings", "evolution")
    evolution_settings_from(evolution)
    return {"islands": islands, "budget": dict(budget), "evolution": dict(evolution)}


def evolution_of(spec: Mapping[str, Any]) -> EvolutionSettings:
    return evolution_settings_from(spec.get("evolution", {}))


def find_island(spec: Mapping[str, Any], island_id: str) -> Json:
    for island in spec["islands"]:
        if island["id"] == island_id:
            found: Json = island
            return found
    raise NotFound(f"no island {island_id}")


def find_genome(spec: Mapping[str, Any], genome_id: str) -> tuple[Json, Json]:
    for island in spec["islands"]:
        for genome in island["genomes"]:
            if genome["id"] == genome_id:
                return island, genome
    raise NotFound(f"no genome {genome_id}")


def _genome_index(spec: Mapping[str, Any]) -> dict[str, tuple[str, Json]]:
    return {
        genome["id"]: (island["id"], genome)
        for island in spec["islands"]
        for genome in island["genomes"]
    }


def diff_spec(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[Json]:
    """Name what an edit changes: one entry per island, genome or budget block."""
    changes: list[Json] = []
    old_islands = {island["id"]: island for island in old["islands"]}
    for island in new["islands"]:
        before = old_islands.get(island["id"])
        changed = [
            name
            for name in ISLAND_FIELDS
            if before is None or before[name] != island[name]
        ]
        if changed:
            changes.append(
                {
                    "kind": "island",
                    "id": island["id"],
                    "island_id": island["id"],
                    "fields": changed,
                    "created": before is None,
                }
            )
    old_genomes = _genome_index(old)
    for island in new["islands"]:
        for genome in island["genomes"]:
            before_genome = old_genomes.get(genome["id"], (None, None))[1]
            changed = [
                name
                for name in (*GENOME_CONTENT, "active")
                if before_genome is None or before_genome.get(name, {}) != genome[name]
            ]
            if changed:
                changes.append(
                    {
                        "kind": "genome",
                        "id": genome["id"],
                        "island_id": island["id"],
                        "fields": changed,
                        "created": before_genome is None,
                    }
                )
    levers = sorted(
        name
        for name in set(old["budget"]) | set(new["budget"])
        if old["budget"].get(name) != new["budget"].get(name)
    )
    if levers:
        changes.append(
            {"kind": "budget", "id": "budget", "island_id": None, "fields": levers}
        )
    before_evolution = old.get("evolution", {})
    settings = sorted(
        name
        for name in set(before_evolution) | set(new["evolution"])
        if before_evolution.get(name) != new["evolution"].get(name)
    )
    if settings:
        changes.append(
            {
                "kind": "evolution",
                "id": "evolution",
                "island_id": None,
                "fields": settings,
            }
        )
    return changes


def current_spec(db: sqlite3.Connection) -> tuple[int, Json]:
    row = db.execute(
        "SELECT revision, body FROM spec_revisions ORDER BY revision DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("the store has no swarm spec; run the migration first")
    return int(row["revision"]), loads(row["body"])


def _revision_json(row: sqlite3.Row, with_spec: bool = False) -> Json:
    record: Json = {
        "revision": row["revision"],
        "actor": row["actor"],
        "note": row["note"],
        "restored_from": row["restored_from"],
        "changes": loads(row["changes"]),
        "created_at": row["created_at"],
    }
    if with_spec:
        record["spec"] = loads(row["body"])
    return record


def list_revisions(db: sqlite3.Connection, limit: int = 100) -> list[Json]:
    rows = db.execute(
        "SELECT * FROM spec_revisions ORDER BY revision DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_revision_json(row) for row in rows]


def get_revision(db: sqlite3.Connection, revision: int) -> Json:
    row = db.execute(
        "SELECT * FROM spec_revisions WHERE revision = ?", (revision,)
    ).fetchone()
    if row is None:
        raise NotFound(f"no spec revision {revision}")
    return _revision_json(row, with_spec=True)


def apply_spec(
    db: sqlite3.Connection,
    proposed: Any,
    *,
    actor: str,
    now: datetime,
    note: str = "",
    restored_from: int | None = None,
    dry_run: bool = False,
    lineage: Mapping[str, Mapping[str, Any]] | None = None,
) -> Json:
    """Validate a proposed spec and record it as the next revision.

    Returns the revision record with ``applied`` saying whether anything was
    written: a proposal equal to the current spec, or a dry run, writes
    nothing. ``lineage`` gives the origin of genomes this revision creates,
    by id; evolution uses it to name a child's parent and mutation.
    """
    new = validate_spec(proposed)
    first = db.execute("SELECT 1 FROM spec_revisions LIMIT 1").fetchone() is None
    revision = 0
    old: Json = {"islands": [], "budget": {}, "evolution": {}}
    if not first:
        revision, old = current_spec(db)
    old_genomes = _genome_index(old)
    new_island_ids = {island["id"] for island in new["islands"]}
    new_genome_ids = {
        genome["id"] for island in new["islands"] for genome in island["genomes"]
    }
    for island in old["islands"]:
        if island["id"] not in new_island_ids:
            raise Invalid(
                f"island {island['id']} cannot be removed; set archived to true",
                "islands",
            )
    for genome_id in old_genomes:
        if genome_id not in new_genome_ids:
            raise Invalid(
                f"genome {genome_id} cannot be removed; set active to false", "islands"
            )

    next_revision = revision + 1
    for island in new["islands"]:
        for genome in island["genomes"]:
            home, before = old_genomes.get(genome["id"], (None, None))
            if before is None:
                genome["version"] = 1
                genome["lineage"] = {
                    "origin": "founder" if first else "created",
                    "parent": None,
                    **(lineage or {}).get(genome["id"], {}),
                    "revision": next_revision,
                }
            elif home != island["id"]:
                raise Invalid(
                    f"genome {genome['id']} stays on island {home}; copy it instead",
                    "islands",
                )
            elif any(before.get(name, {}) != genome[name] for name in GENOME_CONTENT):
                genome["version"] = before["version"] + 1
                genome["lineage"] = {
                    **before["lineage"],
                    **(lineage or {}).get(genome["id"], {}),
                    "origin": "restore" if restored_from is not None else "edit",
                    "previous_version": {
                        "genome_id": genome["id"],
                        "version": before["version"],
                    },
                    "revision": next_revision,
                }
            else:
                genome["version"] = before["version"]
                genome["lineage"] = before["lineage"]

    changes = diff_spec(old, new)
    record: Json = {
        "revision": next_revision if changes else revision,
        "actor": actor,
        "note": note,
        "restored_from": restored_from,
        "changes": changes,
        "created_at": iso(now),
        "applied": bool(changes) and not dry_run,
        "spec": new,
    }
    if record["applied"]:
        db.execute(
            "INSERT INTO spec_revisions(revision, body, changes, actor, note,"
            " restored_from, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                next_revision,
                dumps(new),
                dumps(changes),
                actor,
                note,
                restored_from,
                iso(now),
            ),
        )
    return record


def ensure_seed(db: sqlite3.Connection, now: datetime) -> None:
    """Write revision 1 from the default spec when the store has none, and give
    every island its founders when a store from before them has fewer."""
    if db.execute("SELECT 1 FROM spec_revisions LIMIT 1").fetchone() is None:
        apply_spec(db, default_spec(), actor="seed", now=now, note="default swarm")
        return
    _, spec = current_spec(db)
    proposed = copy.deepcopy(spec)
    added = False
    for island in proposed["islands"]:
        if island["archived"]:
            continue
        have = {genome["id"] for genome in island["genomes"]}
        for founder in founders(
            str(island["id"]), str(island["focus"]), island["categories"]
        ):
            if founder["id"] not in have:
                island["genomes"].append(founder)
                added = True
    if added:
        apply_spec(
            db, proposed, actor="seed", now=now, note="founders for every island"
        )


def restore_revision(
    db: sqlite3.Connection,
    revision: int,
    *,
    actor: str,
    now: datetime,
    dry_run: bool = False,
) -> Json:
    """Bring back an earlier revision's content as a new revision.

    Islands and genomes created since are kept and switched off, so nothing a
    stored run refers to disappears.
    """
    target = copy.deepcopy(get_revision(db, revision)["spec"])
    _, current = current_spec(db)
    target_islands = {island["id"]: island for island in target["islands"]}
    target_genomes = _genome_index(target)
    for island in current["islands"]:
        if island["id"] not in target_islands:
            kept = copy.deepcopy(island)
            kept["archived"] = True
            target["islands"].append(kept)
            target_islands[kept["id"]] = kept
        for genome in island["genomes"]:
            if genome["id"] not in target_genomes and island["id"] in target_islands:
                if all(
                    g["id"] != genome["id"]
                    for g in target_islands[island["id"]]["genomes"]
                ):
                    target_islands[island["id"]]["genomes"].append(
                        {**copy.deepcopy(genome), "active": False}
                    )
    return apply_spec(
        db,
        target,
        actor=actor,
        now=now,
        note=f"restore revision {revision}",
        restored_from=revision,
        dry_run=dry_run,
    )


def genome_versions(db: sqlite3.Connection, genome_id: str) -> list[Json]:
    """Every version a genome has had, oldest first, with the revision that made it."""
    versions: dict[int, Json] = {}
    for row in db.execute(
        "SELECT revision, body, actor, created_at FROM spec_revisions ORDER BY revision"
    ):
        for island in loads(row["body"])["islands"]:
            for genome in island["genomes"]:
                if genome["id"] == genome_id and genome["version"] not in versions:
                    versions[genome["version"]] = {
                        **genome,
                        "island_id": island["id"],
                        "revision": row["revision"],
                        "actor": row["actor"],
                        "created_at": row["created_at"],
                    }
    if not versions:
        raise NotFound(f"no genome {genome_id}")
    return [versions[number] for number in sorted(versions)]


def patch_island(
    spec: Mapping[str, Any], island_id: str, fields: Mapping[str, Any]
) -> Json:
    """A copy of the spec with some fields of one island replaced."""
    unknown = sorted(set(fields) - set(ISLAND_FIELDS))
    if unknown:
        raise Invalid(f"{unknown[0]} is not an editable island field", unknown[0])
    proposed: Json = copy.deepcopy(dict(spec))
    island = next(
        (item for item in proposed["islands"] if item["id"] == island_id), None
    )
    if island is None:
        proposed["islands"].append({"id": island_id, "genomes": [], **fields})
    else:
        island.update(fields)
    return proposed


def patch_genome(
    spec: Mapping[str, Any], island_id: str, genome_id: str, fields: Mapping[str, Any]
) -> Json:
    """A copy of the spec with one genome edited, or created when new."""
    unknown = sorted(set(fields) - {*GENOME_CONTENT, "active"})
    if unknown:
        raise Invalid(f"{unknown[0]} is not an editable genome field", unknown[0])
    proposed: Json = copy.deepcopy(dict(spec))
    island = find_island(proposed, island_id)
    genome = next((item for item in island["genomes"] if item["id"] == genome_id), None)
    if genome is None:
        island["genomes"].append({"id": genome_id, **fields})
    else:
        genome.update(fields)
    return proposed


def patch_evolution(spec: Mapping[str, Any], fields: Mapping[str, Any]) -> Json:
    """A copy of the spec with some evolution settings replaced."""
    proposed: Json = copy.deepcopy(dict(spec))
    proposed["evolution"] = {**proposed.get("evolution", {}), **fields}
    return proposed


def patch_budget(spec: Mapping[str, Any], fields: Mapping[str, Any]) -> Json:
    """A copy of the spec with some budget levers replaced."""
    proposed: Json = copy.deepcopy(dict(spec))
    proposed["budget"] = {**proposed["budget"], **fields}
    return proposed


def upgrade_methods(
    db: sqlite3.Connection, *, now: datetime, dry_run: bool = False
) -> Json:
    """Version every current genome, including archived islands and agents."""
    _, current = current_spec(db)
    proposed = copy.deepcopy(current)
    genealogy: dict[str, Json] = {}
    for row in db.execute("SELECT body FROM spec_revisions ORDER BY revision"):
        for island in loads(row["body"])["islands"]:
            for genome in island["genomes"]:
                ancestry = genome.get("lineage", {})
                if ancestry.get("origin") in ("mating", "mutation"):
                    genealogy[genome["id"]] = {
                        key: value
                        for key, value in ancestry.items()
                        if key not in ("origin", "revision", "previous_version")
                    }
    for island in proposed["islands"]:
        for genome in island["genomes"]:
            genome["research_methods"] = genome.get(
                "research_methods"
            ) or island_methods(island)
            ancestry = genealogy.get(genome["id"], genome.get("lineage", {}))
            ancestors: set[str] = set()
            pending = list(ancestry.get("parents", []))
            while pending:
                parent_id = pending.pop()
                if parent_id in ancestors:
                    continue
                ancestors.add(parent_id)
                pending.extend(genealogy.get(parent_id, {}).get("parents", []))
            for parent_id in ancestors:
                genome["prompt"] = genome["prompt"].replace(
                    f"\n\nAlso, from {parent_id}: ",
                    "\n\nAdditional reading emphasis: ",
                )
    return apply_spec(
        db,
        proposed,
        actor="operator",
        now=now,
        dry_run=dry_run,
        note="source-grounded island methods v1",
        lineage=genealogy,
    )
