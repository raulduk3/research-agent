"""Evolution: a switch, a ranking, one mutation, one whole generation."""

from __future__ import annotations

import random
import sqlite3
from typing import Any

import pytest

from research_agent.beta import evolution
from research_agent.beta import spec as specs
from research_agent.beta.costs import record_cost_receipt
from research_agent.beta.errors import Invalid
from research_agent.beta.papers import upsert_paper
from research_agent.beta.projections import build_island_projection
from research_agent.beta.budget import budget_state
from research_agent.beta.runs import advance_swarm
from tests.beta.helpers import PROVIDER, FakeClock, entry

PAPER = "2609.00001"


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
    accept: int = 0,
    push_away: int = 0,
) -> None:
    """One finished run by an agent, with its cost and the feedback it drew."""
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
    for signal, count in (("accept", accept), ("push_away", push_away)):
        for _ in range(count):
            number = db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            db.execute(
                "INSERT INTO feedback(id, island_id, target_kind, target_id, signal,"
                " paper_id, run_id, created_at) VALUES (?, ?, 'run', ?, ?, ?, ?, ?)",
                (f"F-{number}", island, run_id, signal, PAPER, run_id, stamp),
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


def test_no_cycle_runs_below_the_thresholds(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(5):
        _run(db, clock, "cs-reader")

    assert _cycle(db, clock) is None
    assert db.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0


def test_the_run_threshold_starts_a_generation_with_one_mutated_child(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader", accept=1)

    record = _cycle(db, clock)

    assert record is not None and record["status"] == "committed"
    assert (record["number"], record["revision"]) == (1, 2)
    decisions = {item["genome_id"]: item for item in record["decisions"]}
    assert decisions["cs-reader"]["decision"] == "retained"
    assert decisions["cs-gen1"]["decision"] == "created"

    _, spec = specs.current_spec(db)
    parent = specs.find_genome(spec, "cs-reader")[1]
    child = specs.find_genome(spec, "cs-gen1")[1]
    # Exactly one field differs from the parent, and the lineage names it.
    changed = [name for name in specs.GENOME_CONTENT if child[name] != parent[name]]
    assert changed == [child["lineage"]["mutation"]["field"]]
    assert child["lineage"]["origin"] == "mutation"
    assert child["lineage"]["parent"] == {"genome_id": "cs-reader", "version": 1}
    assert (child["lineage"]["generation"], child["lineage"]["revision"]) == (1, 2)
    assert child["active"] and parent["version"] == 1
    assert specs.get_revision(db, 2)["actor"] == "evolution"
    # The counters start again from this generation.
    assert _cycle(db, clock) is None


def test_feedback_alone_can_start_a_generation(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _run(db, clock, "cs-reader", accept=2)
    _run(db, clock, "cs-reader", accept=1)

    record = _cycle(db, clock)

    assert record is not None and record["status"] == "committed"


def test_evolution_is_switched_off_for_the_swarm_or_for_one_island(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader", accept=1)
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


def test_a_useful_costly_agent_parents_over_a_cheap_useless_one(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _add_agent(db, clock, "cs-cheap", prompt="Skim.")
    for _ in range(3):
        _run(db, clock, "cs-reader", accept=1, cost=40_000)
        _run(db, clock, "cs-cheap", accept=0, cost=500)

    record = _cycle(db, clock)

    child = next(item for item in record["decisions"] if item["decision"] == "created")
    assert child["parent"]["genome_id"] == "cs-reader"
    scores = {item["genome_id"]: item for item in record["decisions"]}
    assert scores["cs-reader"]["band"] > scores["cs-cheap"]["band"]
    assert (
        scores["cs-reader"]["mean_cost_micros"] > scores["cs-cheap"]["mean_cost_micros"]
    )


def test_cost_decides_only_between_agents_in_the_same_usefulness_band(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _add_agent(db, clock, "cs-thrifty", prompt="Read briefly.")
    for _ in range(3):
        _run(db, clock, "cs-reader", accept=1, cost=9_000)
        _run(db, clock, "cs-thrifty", accept=1, cost=1_000)

    record = _cycle(db, clock)

    child = next(item for item in record["decisions"] if item["decision"] == "created")
    assert child["parent"]["genome_id"] == "cs-thrifty"


def test_an_agent_over_the_run_cap_cannot_parent(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _add_agent(db, clock, "cs-modest", prompt="Read plainly.")
    for _ in range(3):
        _run(db, clock, "cs-reader", accept=3, cost=60_000)
        _run(db, clock, "cs-modest", accept=0, cost=1_000)

    record = _cycle(db, clock)

    child = next(item for item in record["decisions"] if item["decision"] == "created")
    assert child["parent"]["genome_id"] == "cs-modest"


def test_a_full_island_retires_its_worst_judged_agent_without_removing_it(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _add_agent(db, clock, "cs-middling", prompt="Read evenly.")
    _add_agent(db, clock, "cs-poor", prompt="Guess.")
    for _ in range(2):
        _run(db, clock, "cs-reader", accept=2)
        _run(db, clock, "cs-middling", accept=1)
        _run(db, clock, "cs-poor", push_away=1)

    record = _cycle(db, clock)

    decisions = {item["genome_id"]: item["decision"] for item in record["decisions"]}
    assert decisions == {
        "cs-reader": "retained",
        "cs-middling": "retained",
        "cs-poor": "retired",
        "cs-gen1": "created",
    }
    _, spec = specs.current_spec(db)
    retired = specs.find_genome(spec, "cs-poor")[1]
    assert retired["active"] is False and retired["prompt"] == "Guess."
    active = [g["id"] for g in specs.find_island(spec, "cs")["genomes"] if g["active"]]
    assert active == ["cs-reader", "cs-middling", "cs-gen1"]
    # The retired agent takes no more papers; the child does.
    result = advance_swarm(db, spec=spec, revision=3, provider=PROVIDER, clock=clock)
    agents = {item["agent"] for item in result["started"] + result["waiting"]}
    assert "cs-poor@cs" not in agents and "cs-gen1@cs" in agents


def test_nothing_is_retired_on_no_evidence(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _add_agent(db, clock, "cs-new-a", prompt="Untested a.")
    _add_agent(db, clock, "cs-new-b", prompt="Untested b.")
    for _ in range(6):
        _run(db, clock, "cs-reader", accept=1)

    record = _cycle(db, clock)

    assert (record["status"], record["reason"]) == (
        "skipped",
        "population_full_awaiting_evidence",
    )
    assert specs.current_spec(db)[0] == 3
    # The skip is recorded and resets the counters, so it is not retried each beat.
    assert _cycle(db, clock) is None


def test_a_cycle_with_no_judged_agent_is_recorded_as_skipped(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    _run(db, clock, "cs-reader", accept=3)

    record = _cycle(db, clock)

    assert (record["status"], record["reason"]) == ("skipped", "no_judged_agent")
    assert record["decisions"][0]["reason"] == "too_few_runs"
    assert specs.current_spec(db)[0] == 1


def test_a_generation_is_written_whole_or_not_at_all(
    db: sqlite3.Connection,
    clock: FakeClock,
    paper: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader", accept=1)
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


def test_mutation_is_repeatable_and_never_repeats_an_existing_agent(
    db: sqlite3.Connection,
) -> None:
    _, spec = specs.current_spec(db)
    parent = specs.find_genome(spec, "cs-reader")[1]

    first = evolution.mutate_genome(parent, [parent], "cs:1")
    again = evolution.mutate_genome(parent, [parent], "cs:1")
    other = evolution.mutate_genome(parent, [parent], "cs:2")

    assert first == again
    assert first is not None and other is not None
    assert first[0] != _content(parent)
    # With the first child already on the island, the same seed must find another.
    sibling = evolution.mutate_genome(parent, [parent, first[0]], "cs:1")
    assert sibling is not None and sibling[0] not in (first[0], _content(parent))
    # A child is still a valid genome.
    specs.validate_genome({"id": "child", **first[0]}, "child")
    every = [content for content, _ in evolution._mutations(parent, random.Random(0))]
    assert evolution.mutate_genome(parent, [parent, *every], "cs:1") is None


def test_the_island_page_shows_generations_and_the_settings_are_validated(
    db: sqlite3.Connection, clock: FakeClock, paper: str
) -> None:
    for _ in range(6):
        _run(db, clock, "cs-reader", accept=1)
    _cycle(db, clock)
    _, spec = specs.current_spec(db)

    view = build_island_projection(
        db, spec, "cs", budget_state(db, spec, clock(), True)
    )

    assert view["evolve"] is True
    [generation] = view["generations"]["items"]
    assert generation["number"] == 1 and generation["status"] == "committed"
    assert {agent["id"] for agent in view["agents"]["items"]} == {
        "cs-reader",
        "cs-gen1",
    }
    assert view["edits"]["items"][0]["actor"] == "evolution"

    for fields, where in (
        ({"enabled": "yes"}, "evolution.enabled"),
        ({"runs_threshold": 0}, "evolution.runs_threshold"),
        ({"mutation_rate": 2}, "evolution.mutation_rate"),
    ):
        with pytest.raises(Invalid) as refused:
            specs.validate_spec(specs.patch_evolution(spec, fields))
        assert refused.value.field == where
