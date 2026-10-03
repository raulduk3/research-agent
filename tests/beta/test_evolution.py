"""Evolution: a switch, a cadence, and a generative step with no ranking."""

from __future__ import annotations

import random
import sqlite3
from typing import Any

import pytest

from research_agent.beta import evolution
from research_agent.beta import spec as specs
from research_agent.beta.budget import budget_state
from research_agent.beta.costs import record_cost_receipt
from research_agent.beta.db import dumps, iso
from research_agent.beta.errors import Invalid
from research_agent.beta.models import ModelCallFailed
from research_agent.beta.papers import upsert_paper
from research_agent.beta.projections import build_island_projection
from research_agent.beta.runs import advance_swarm
from tests.beta.helpers import PROVIDER, FakeClock, ScriptedClient, call, entry, reply

PAPER = "2609.00001"
FOUNDERS = [f"cs-{name}" for name, *_ in specs.FOUNDERS]


@pytest.fixture
def paper(db: sqlite3.Connection, clock: FakeClock) -> str:
    receipt = record_cost_receipt(
        db,
        action="ingest",
        owner_kind="ingest_pass",
        owner_id="IP-test",
        parent_kind="source",
        parent_id="arxiv:cs.AI",
        unit_type="arxiv_request",
        quantity=1,
        amount_micros=0,
        now=clock(),
    )
    upsert_paper(db, entry(PAPER), receipt, clock())
    return PAPER


def _run(
    db: sqlite3.Connection,
    clock: FakeClock,
    genome_id: str,
    *,
    island: str = "cs",
    version: int = 1,
    status: str = "completed",
    cost: int = 2_000,
) -> None:
    """One finished run by an agent, with its cost."""
    clock.advance(seconds=1)
    stamp = clock().strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"R-{db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]:010d}"
    db.execute(
        "INSERT INTO runs(id, paper_id, island_id, genome_id, genome_version,"
        " spec_revision, genome, seed, status, reading_mode, prompt_system,"
        " prompt_user, prompt_hash, model, limits, estimate_micros, created_at,"
        " finished_at) VALUES (?, ?, ?, ?, ?, 1, '{}', 1, ?, 'abstract', 's', 'u', 'h',"
        " 'm', '{}', 0, ?, ?)",
        (run_id, PAPER, island, genome_id, version, status, stamp, stamp),
    )
    record_cost_receipt(
        db,
        action="model_call",
        owner_kind="run",
        owner_id=run_id,
        parent_kind="paper",
        parent_id=PAPER,
        unit_type="tokens",
        quantity=1,
        amount_micros=cost,
        now=clock(),
        island_id=island,
        paper_id=PAPER,
        run_id=run_id,
    )


def _edit(db: sqlite3.Connection, clock: FakeClock, proposed: Any) -> None:
    specs.apply_spec(db, proposed, actor="operator", now=clock())


def _add_agent(
    db: sqlite3.Connection, clock: FakeClock, genome_id: str, **changes: Any
):
    _, spec = specs.current_spec(db)
    reader = specs.find_genome(spec, "cs-reader")[1]
    content = {name: reader[name] for name in specs.GENOME_CONTENT}
    content.update(changes)
    _edit(db, clock, specs.patch_genome(spec, "cs", genome_id, content))


def _cycle(db: sqlite3.Connection, clock: FakeClock, **kwargs: Any):
    clock.advance(seconds=1)
    return evolution.maybe_run_evolution(db, "cs", clock(), **kwargs)


def _content(genome: dict[str, Any]) -> dict[str, Any]:
    return {name: genome[name] for name in specs.GENOME_CONTENT}


def _decisions(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["genome_id"]: item for item in record["decisions"]}


def test_every_island_starts_with_the_three_founders(db: sqlite3.Connection) -> None:
    _, spec = specs.current_spec(db)
    for island in spec["islands"]:
        ids = [g["id"] for g in island["genomes"]]
        assert ids == [f"{island['id']}-{name}" for name, *_ in specs.FOUNDERS]
        assert island["focus"] in island["genomes"][0]["prompt"]
    # Kin across islands: the same posture, told each island's focus.
    cs = specs.find_genome(spec, "cs-skeptic")[1]
    bio = specs.find_genome(spec, "bio-skeptic")[1]
    assert cs["reading_strategy"] == bio["reading_strategy"]
    assert cs["prompt"] != bio["prompt"]


def test_a_store_from_before_the_founders_is_given_them(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    # A store written before the founders existed: one agent per island, put in
    # place as a revision by hand since a spec edit may not remove genomes.
    _, spec = specs.current_spec(db)
    thin = {
        **spec,
        "islands": [
            {**island, "genomes": island["genomes"][:1]} for island in spec["islands"]
        ],
    }
    db.execute(
        "INSERT INTO spec_revisions(revision, body, changes, actor, note, restored_from,"
        " created_at) VALUES (2, ?, '[]', 'test', '', NULL, ?)",
        (dumps(thin), iso(clock())),
    )
    assert len(specs.find_island(specs.current_spec(db)[1], "cs")["genomes"]) == 1

    specs.ensure_seed(db, clock())

    revision, after = specs.current_spec(db)
    assert len(specs.find_island(after, "cs")["genomes"]) == 3
    assert specs.get_revision(db, revision)["actor"] == "seed"
    # Done once: a second call changes nothing.
    specs.ensure_seed(db, clock())
    assert specs.current_spec(db)[0] == revision


def test_no_cycle_runs_below_the_threshold(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(5):
        _run(db, clock, "cs-reader")

    assert _cycle(db, clock) is None
    assert db.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0


def test_the_run_threshold_breeds_a_child_from_the_island_and_another(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader")

    record = _cycle(db, clock)

    assert record is not None and record["status"] == "committed"
    assert (record["number"], record["revision"]) == (1, 2)
    decisions = _decisions(record)
    assert decisions["cs-reader"]["decision"] == "parent"
    mates = [d for d in record["decisions"] if d["decision"] == "mate"]
    assert len(mates) == 1 and mates[0]["island_id"] != "cs"
    child = decisions["cs-gen1"]
    assert (child["decision"], child["reason"]) == ("created", "rule_mating")
    assert child["parents"] == ["cs-reader", mates[0]["genome_id"]]
    # Nothing is ranked: every other agent is simply kept.
    assert {d["decision"] for d in record["decisions"]} == {
        "parent",
        "mate",
        "created",
        "kept",
    }

    _, spec = specs.current_spec(db)
    parent = specs.find_genome(spec, "cs-reader")[1]
    mate = specs.find_genome(spec, mates[0]["genome_id"])[1]
    bred = specs.find_genome(spec, "cs-gen1")[1]
    assert bred["lineage"]["origin"] == "mating"
    assert bred["lineage"]["parents"] == ["cs-reader", mate["id"]]
    assert bred["lineage"]["proposed_by"] == "rule"
    assert (bred["lineage"]["generation"], bred["lineage"]["revision"]) == (1, 2)
    assert bred["prompt"].startswith(parent["prompt"].split("\n\n")[0])
    assert f"from {mate['id']}" in bred["prompt"]
    assert bred["active"] and parent["version"] == 1
    assert specs.get_revision(db, 2)["actor"] == "evolution"
    # The counters start again from this generation.
    assert _cycle(db, clock) is None


def test_mating_is_repeatable_and_never_repeats_an_existing_agent(
    db: sqlite3.Connection,
) -> None:
    _, spec = specs.current_spec(db)
    parent = specs.find_genome(spec, "cs-reader")[1]
    mate = specs.find_genome(spec, "quant-builder")[1]
    existing = specs.find_island(spec, "cs")["genomes"]

    first = evolution.mate_genomes(parent, mate, existing, "cs:1")
    again = evolution.mate_genomes(parent, mate, existing, "cs:1")
    other = evolution.mate_genomes(parent, mate, existing, "cs:2")

    assert first == again and first is not None and other is not None
    assert first[0] != _content(parent) and first[0] != _content(mate)
    assert first[1]["crossed_with"] == "quant-builder"
    specs.validate_genome({"id": "child", **first[0]}, "child")
    # Plain mutation still works the same way for an island with no neighbor.
    mutated = evolution.mutate_genome(parent, [parent], "cs:1")
    assert mutated == evolution.mutate_genome(parent, [parent], "cs:1")
    every = [content for content, _ in evolution._mutations(parent, random.Random(0))]
    assert evolution.mutate_genome(parent, [parent, *every], "cs:1") is None


def test_the_model_proposes_the_child_when_it_is_configured(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader")
    client = ScriptedClient(
        [
            reply(
                call(
                    "propose_child",
                    {
                        "parents": ["cs-reader", "bio-builder"],
                        "prompt": "Read for the central result, then simulate it forward.",
                        "reading_strategy": "Read the result, chain its consequences, submit.",
                        "temperature": 0.75,
                        "why": "Evidence-first reading with the simulator's forward chaining.",
                    },
                )
            )
        ]
    )

    record = _cycle(db, clock, provider=PROVIDER, client=client)

    assert record["status"] == "committed" and record["cost_micros"] == 500
    child = _decisions(record)["cs-gen1"]
    assert (child["reason"], child["parents"]) == (
        "model_mating",
        ["cs-reader", "bio-builder"],
    )
    assert child["why"].startswith("Evidence-first")
    _, spec = specs.current_spec(db)
    bred = specs.find_genome(spec, "cs-gen1")[1]
    assert bred["lineage"]["proposed_by"] == "model"
    assert bred["prompt"].startswith("Read for the central result")
    assert bred["model_settings"]["temperature"] == 0.75
    assert "submit_reading" in bred["allowed_tools"]
    # The model saw the whole swarm, this island first, and the call was paid for.
    sent = client.requests[0]["messages"][1]["content"]
    assert sent.index("## CS island") < sent.index("## Bio island")
    assert "bio-builder@bio" in sent
    receipt = db.execute(
        "SELECT action, amount_micros, settlement FROM cost_receipts"
        " WHERE owner_kind = 'generation'"
    ).fetchone()
    assert tuple(receipt) == ("evolution", 500, "settled")


def test_a_failed_or_useless_proposal_falls_back_to_the_rule(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader")
    failing = ScriptedClient([ModelCallFailed("provider down")])

    record = _cycle(db, clock, provider=PROVIDER, client=failing)

    child = _decisions(record)["cs-gen1"]
    assert child["reason"] == "rule_mating"
    assert (
        db.execute(
            "SELECT settlement FROM cost_receipts WHERE owner_kind = 'generation'"
        ).fetchone()[0]
        == "unsettled"
    )

    for _ in range(6):
        _run(db, clock, "cs-reader")
    elsewhere = ScriptedClient(
        [
            reply(
                call(
                    "propose_child",
                    {
                        "parents": ["bio-reader"],
                        "prompt": "Not this island's.",
                        "reading_strategy": "x",
                        "temperature": 0.5,
                        "why": "wrong island",
                    },
                )
            )
        ]
    )
    second = _cycle(db, clock, provider=PROVIDER, client=elsewhere)
    assert _decisions(second)["cs-gen2"]["reason"] == "rule_mating"


def test_the_budget_decides_whether_the_model_is_asked(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _, spec = specs.current_spec(db)
    _edit(db, clock, specs.patch_budget(spec, {"per_evolution_max_micros": 1}))
    for _ in range(6):
        _run(db, clock, "cs-reader")
    client = ScriptedClient([])

    record = _cycle(db, clock, provider=PROVIDER, client=client)

    assert client.requests == [] and record["cost_micros"] == 0
    assert _decisions(record)["cs-gen1"]["reason"] == "rule_mating"


def test_evolution_is_switched_off_for_the_swarm_or_for_one_island(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader")
    _, spec = specs.current_spec(db)

    _edit(db, clock, specs.patch_evolution(spec, {"enabled": False}))
    assert _cycle(db, clock, force=True) is None

    _, spec = specs.current_spec(db)
    proposed = specs.patch_evolution(spec, {"enabled": True})
    _edit(db, clock, specs.patch_island(proposed, "cs", {"evolve": False}))
    assert _cycle(db, clock, force=True) is None
    assert db.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0

    _, spec = specs.current_spec(db)
    _edit(db, clock, specs.patch_island(spec, "cs", {"evolve": True}))
    assert _cycle(db, clock)["status"] == "committed"


def test_with_mutation_off_a_cycle_is_recorded_and_breeds_nothing(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _, spec = specs.current_spec(db)
    _edit(db, clock, specs.patch_island(spec, "cs", {"mutate": False}))
    for _ in range(6):
        _run(db, clock, "cs-reader")

    record = _cycle(db, clock)

    assert (record["status"], record["revision"]) == ("committed", None)
    assert {d["decision"] for d in record["decisions"]} == {"kept"}
    _, after = specs.current_spec(db)
    assert [g["id"] for g in specs.find_island(after, "cs")["genomes"]] == FOUNDERS


def test_over_its_cap_the_island_archives_its_least_run_agent(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _, spec = specs.current_spec(db)
    _edit(db, clock, specs.patch_evolution(spec, {"max_agents_per_island": 3}))
    for _ in range(6):
        _run(db, clock, "cs-reader")
    for _ in range(2):
        _run(db, clock, "cs-skeptic")
    _run(db, clock, "cs-builder")

    record = _cycle(db, clock)

    decisions = {d["genome_id"]: d["decision"] for d in record["decisions"]}
    assert decisions["cs-builder"] == "archived"
    assert decisions["cs-reader"] == "parent" and decisions["cs-gen1"] == "created"
    _, spec = specs.current_spec(db)
    archived = specs.find_genome(spec, "cs-builder")[1]
    assert archived["active"] is False and "built on" in archived["prompt"]
    active = [g["id"] for g in specs.find_island(spec, "cs")["genomes"] if g["active"]]
    assert active == ["cs-reader", "cs-skeptic", "cs-gen1"]
    # The archived agent takes no more papers.
    clock.advance(hours=2)
    result = advance_swarm(db, spec=spec, revision=3, provider=PROVIDER, clock=clock)
    agents = {item["agent"] for item in result["started"] + result["waiting"]}
    assert "cs-builder@cs" not in agents


def test_the_breeder_may_fail_out_a_lemon_and_likes_pick_the_parent(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader")
    _run(db, clock, "cs-skeptic")
    # One like on the skeptic's work outweighs the reader's experience.
    db.execute(
        "INSERT INTO likes(id, island_id, target_kind, target_id, genome_id, created_at)"
        " VALUES ('L-1', 'cs', 'agent', 'cs-skeptic', 'cs-skeptic', '2026-09-10T12:00:00Z')"
    )
    client = ScriptedClient(
        [
            reply(
                call(
                    "propose_child",
                    {
                        "parents": ["cs-skeptic", "quant-reader"],
                        "prompt": "Doubt first, then read for evidence.",
                        "reading_strategy": "Methods, then results, then submit.",
                        "temperature": 0.5,
                        "why": "The skeptic people liked, with the reader's evidence habit.",
                        "archive": "cs-builder",
                        "why_archive": "It keeps every paper and quotes nothing.",
                    },
                )
            )
        ]
    )

    record = _cycle(db, clock, provider=PROVIDER, client=client)

    decisions = _decisions(record)
    assert decisions["cs-builder"]["decision"] == "archived"
    assert decisions["cs-builder"]["reason"] == "breeder_lemon"
    assert decisions["cs-builder"]["why"].startswith("It keeps")
    assert decisions["cs-gen1"]["parents"] == ["cs-skeptic", "quant-reader"]
    assert "1 points" in client.requests[0]["messages"][1]["content"]
    _, spec = specs.current_spec(db)
    assert specs.find_genome(spec, "cs-builder")[1]["active"] is False
    # By rule the parent is the most liked agent too.
    for _ in range(6):
        _run(db, clock, "cs-reader")
    second = _cycle(db, clock)
    assert _decisions(second)["cs-gen2"]["parents"][0] == "cs-skeptic"


def test_an_archived_agent_can_be_brought_back_by_hand(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)
    _edit(db, clock, specs.patch_genome(spec, "cs", "cs-builder", {"active": False}))
    assert (
        specs.find_genome(specs.current_spec(db)[1], "cs-builder")[1]["active"] is False
    )

    _, spec = specs.current_spec(db)
    _edit(db, clock, specs.patch_genome(spec, "cs", "cs-builder", {"active": True}))

    assert (
        specs.find_genome(specs.current_spec(db)[1], "cs-builder")[1]["active"] is True
    )


def test_a_generation_is_written_whole_or_not_at_all(
    db: sqlite3.Connection,
    clock: FakeClock,
    paper: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader")
    db.commit()

    def broken(*args: Any, **kwargs: Any) -> str:
        raise sqlite3.OperationalError("disk full")

    # The spec revision is written first; the generation record then fails.
    monkeypatch.setattr(evolution, "dumps", broken)
    with pytest.raises(sqlite3.OperationalError):
        _cycle(db, clock)
    db.rollback()

    assert specs.current_spec(db)[0] == 1
    assert db.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0
    with pytest.raises(Exception, match="no genome cs-gen1"):
        specs.find_genome(specs.current_spec(db)[1], "cs-gen1")


def test_the_island_page_shows_generations_and_the_settings_are_validated(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader")
    _cycle(db, clock)
    _, spec = specs.current_spec(db)

    view = build_island_projection(
        db, spec, "cs", budget_state(db, spec, clock(), True)
    )

    assert view["island"]["evolve"] is True
    steps = {step["genome_id"]: step for step in view["evolution"]}
    assert steps["cs-reader"]["decision"] == "parent"
    assert steps["cs-gen1"]["decision"] == "created"
    assert {step["generation"] for step in view["evolution"]} == {1}
    agents = {agent["id"]: agent for agent in view["agents"]}
    assert set(agents) == {*FOUNDERS, "cs-gen1"}
    assert (agents["cs-gen1"]["parent_id"], agents["cs-gen1"]["generation"]) == (
        "cs-reader",
        1,
    )

    # Settings from before the ranking went are read and dropped; unknown ones refused.
    old = specs.evolution_settings_from({"feedback_threshold": 3, "runs_threshold": 2})
    assert old.runs_threshold == 2
    with pytest.raises(Invalid, match="unknown evolution setting"):
        specs.evolution_settings_from({"fitness": 1})
    with pytest.raises(Invalid):
        specs.evolution_settings_from({"max_agents_per_island": 0})
