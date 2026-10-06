"""Research methods upgrades preserve authored behavior and historical runs."""

from __future__ import annotations

import copy
import sqlite3

import pytest

from research_agent.beta import spec as specs
from research_agent.beta.db import connect, loads
from research_agent.beta.config import BetaConfig
from research_agent.beta.evolution import maybe_run_evolution
from research_agent.beta.methods import CATALOG, methods_profile
from tests.beta.helpers import FakeClock
from tests.beta.test_runs import _create, _store


def test_all_founders_have_domain_sources_and_distinct_postures() -> None:
    doc = specs.default_spec()
    for island in doc["islands"]:
        prompts = [g["prompt"] for g in island["genomes"]]
        methods = [g["research_methods"] for g in island["genomes"]]
        assert len(set(prompts)) == 3
        for profile in methods:
            assert CATALOG[island["id"]].label in profile["instructions"]
            assert [source["url"] for source in profile["sources"]] == [
                url for _, url in CATALOG[island["id"]].sources
            ]
            assert "cannot execute experiments" in profile["instructions"]
            assert "mark checks as unresolved" in profile["instructions"]
            assert "http" not in profile["instructions"]
    assert (
        "component ablation"
        in doc["islands"][0]["genomes"][2]["research_methods"]["instructions"]
    )
    assert (
        "certification assumptions"
        in doc["islands"][1]["genomes"][1]["research_methods"]["instructions"]
    )
    assert (
        "controlled perturbation"
        in doc["islands"][2]["genomes"][2]["research_methods"]["instructions"]
    )
    assert (
        "stopping criterion"
        in doc["islands"][3]["genomes"][2]["research_methods"]["instructions"]
    )


def test_upgrade_versions_every_agent_without_changing_history(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _, current = specs.current_spec(db)
    old = copy.deepcopy(current)
    for island in old["islands"]:
        for genome in island["genomes"]:
            genome["prompt"] += " Custom hypothesis."
            genome.pop("research_methods", None)
    old["islands"][2]["archived"] = True
    old["islands"][2]["genomes"][0]["active"] = False
    specs.apply_spec(db, old, actor="operator", now=clock())
    custom = copy.deepcopy(old["islands"][0])
    custom.update(
        id="ecology", focus="river ecosystem resilience", categories=["q-bio.PE"]
    )
    for genome in custom["genomes"]:
        genome["id"] = "ecology-" + genome["id"].split("-")[1]
    old["islands"].append(custom)
    record = specs.apply_spec(db, old, actor="operator", now=clock())
    before_revision, before = specs.current_spec(db)
    assert before_revision == record["revision"]
    _store(db, clock)
    run_id = _create(db, clock)
    run_before = dict(
        db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    )

    preview = specs.upgrade_methods(db, now=clock(), dry_run=True)
    assert not preview["applied"]
    assert specs.current_spec(db)[0] == before_revision
    assert len(preview["changes"]) == 15
    applied = specs.upgrade_methods(db, now=clock())
    assert applied["applied"]
    for island in applied["spec"]["islands"]:
        old_island = specs.find_island(before, island["id"])
        for genome in island["genomes"]:
            prior = next(g for g in old_island["genomes"] if g["id"] == genome["id"])
            assert genome["prompt"] == prior["prompt"]
            assert genome["version"] == prior["version"] + 1
            assert genome["lineage"]["previous_version"] == {
                "genome_id": prior["id"],
                "version": prior["version"],
            }
            for field in specs.GENOME_CONTENT:
                if field != "research_methods":
                    assert genome[field] == prior[field]
            assert genome["active"] == prior["active"]
        assert island["archived"] == old_island["archived"]
    profile = applied["spec"]["islands"][-1]["genomes"][0]["research_methods"]
    assert not profile["specialist"]
    assert "river ecosystem resilience" in profile["instructions"]
    assert specs.get_revision(db, before_revision)["spec"] == before
    assert (
        dict(db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())
        == run_before
    )
    db.commit()
    with connect(cfg.database) as reopened:
        assert specs.current_spec(reopened)[0] == applied["revision"]
        assert specs.upgrade_methods(reopened, now=clock())["changes"] == []

    _store(db, clock, "2609.00002")
    newer_run = _create(db, clock, paper_id="2609.00002")
    row = db.execute(
        "SELECT genome, prompt_system FROM runs WHERE id = ?", (newer_run,)
    ).fetchone()
    assert "empirical evaluation and reproducibility" in row["prompt_system"]
    assert "http" not in row["prompt_system"]
    assert (
        loads(row["genome"])["research_methods"]["sources"][0]["url"]
        == "https://jmlr.org/papers/volume22/20-303/20-303.pdf"
    )
    assert (
        loads(row["genome"])["version"]
        == specs.find_genome(applied["spec"], "cs-reader")[1]["version"]
    )


def test_evolution_child_retains_target_domain_after_mating(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    result = maybe_run_evolution(db, "bio", clock(), force=True)
    assert result is not None and result["status"] == "committed"
    _, doc = specs.current_spec(db)
    child = specs.find_island(doc, "bio")["genomes"][-1]
    assert "Biology: mechanisms" in child["research_methods"]["instructions"]
    assert "Also, from" not in child["prompt"]
    assert "http" not in child["prompt"]
    assert (
        "Computer science: empirical" not in child["research_methods"]["instructions"]
    )


def test_oversized_mating_records_refusal_and_preserves_population(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, doc = specs.current_spec(db)
    for island in doc["islands"]:
        for genome in island["genomes"]:
            genome["prompt"] = "Long custom posture. " + "x" * 7800
    specs.apply_spec(db, doc, actor="operator", now=clock())
    before = specs.current_spec(db)
    result = maybe_run_evolution(db, "cs", clock(), force=True)
    assert result is not None
    assert result["reason"] == "invalid_child"
    assert result["decisions"][0]["why"] == "must be at most 8000 characters"
    assert specs.current_spec(db) == before


def test_managed_guidance_does_not_make_a_duplicate_mutation_novel() -> None:
    from research_agent.beta.evolution import _mutations, mutate_genome
    import random

    genome = specs.default_spec()["islands"][0]["genomes"][0]
    offers = _mutations(genome, random.Random("seed"))
    existing = [
        {**content, "research_methods": methods_profile("cs", "agents")}
        for content, _ in offers
    ]
    assert mutate_genome(genome, existing, "seed") is None


def test_cli_dry_run_does_not_prepare_or_modify_store(
    db: sqlite3.Connection,
    cfg: BetaConfig,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json
    from research_agent.beta import __main__ as cli

    _, doc = specs.current_spec(db)
    doc["islands"][0]["genomes"][0].pop("research_methods")
    specs.apply_spec(db, doc, actor="operator", now=clock())
    db.commit()
    before = specs.current_spec(db)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(
        cli.Swarm, "prepare", lambda self: pytest.fail("dry run prepared store")
    )
    assert cli.main(["upgrade-methods", "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["applied"] and len(result["changes"]) == 1
    assert specs.current_spec(db) == before
    assert cli.main(["upgrade-methods"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["applied"]
    assert cli.main(["upgrade-methods"]) == 0
    assert json.loads(capsys.readouterr().out)["changes"] == []


def test_upgrade_restores_evolved_genealogy_and_version_edits_keep_it(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    maybe_run_evolution(db, "cs", clock(), force=True)
    _, before = specs.current_spec(db)
    child = specs.find_genome(before, "cs-gen1")[1]
    genealogy = copy.deepcopy(child["lineage"])
    legacy = copy.deepcopy(before)
    old_child = specs.find_genome(legacy, "cs-gen1")[1]
    old_child["prompt"] += " Extra custom strategy."
    old_child.pop("research_methods")
    edited = specs.apply_spec(db, legacy, actor="operator", now=clock())
    updated = specs.find_genome(edited["spec"], "cs-gen1")[1]
    assert updated["lineage"]["parent"] == genealogy["parent"]
    assert updated["lineage"]["parents"] == genealogy["parents"]
    assert updated["lineage"]["generation"] == genealogy["generation"]
    # Reproduce the current-state damage older edits wrote, without changing the historic creation record.
    damaged = copy.deepcopy(edited["spec"])
    current_child = specs.find_genome(damaged, "cs-gen1")[1]
    current_child["lineage"] = {
        "origin": "edit",
        "parent": {"genome_id": "cs-gen1", "version": 1},
        "revision": edited["revision"],
    }
    from research_agent.beta.db import dumps, iso

    db.execute(
        "INSERT INTO spec_revisions(revision, body, changes, actor, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            edited["revision"] + 1,
            dumps(damaged),
            "[]",
            "operator",
            "legacy edit",
            iso(clock()),
        ),
    )
    upgraded = specs.upgrade_methods(db, now=clock())
    repaired = specs.find_genome(upgraded["spec"], "cs-gen1")[1]
    assert repaired["lineage"]["parent"] == genealogy["parent"]
    assert repaired["lineage"]["parents"] == genealogy["parents"]
    assert repaired["lineage"]["generation"] == genealogy["generation"]
    assert repaired["prompt"] == updated["prompt"]


def test_upgrade_removes_only_known_legacy_mating_attribution(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    maybe_run_evolution(db, "cs", clock(), force=True)
    revision, doc = specs.current_spec(db)
    child = specs.find_genome(doc, "cs-gen1")[1]
    donor = child["lineage"]["parents"][1]
    child["prompt"] = (
        f"Custom reader.\n\nAlso, from {donor}: Keep this inherited strategy."
        "\n\nAlso, from custom-explanation: Keep this user-authored text."
    )
    child.pop("research_methods")
    record = specs.apply_spec(db, doc, actor="operator", now=clock())
    historic = specs.get_revision(db, record["revision"])["spec"]
    result = specs.upgrade_methods(db, now=clock())
    upgraded = specs.find_genome(result["spec"], "cs-gen1")[1]
    assert upgraded["prompt"] == (
        "Custom reader.\n\nAdditional reading emphasis: Keep this inherited strategy."
        "\n\nAlso, from custom-explanation: Keep this user-authored text."
    )
    assert specs.get_revision(db, record["revision"])["spec"] == historic
    _store(db, clock)
    run_id = _create(db, clock, genome_id="cs-gen1")
    row = db.execute(
        "SELECT prompt_system FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert donor not in row["prompt_system"]
    assert "Keep this inherited strategy." in row["prompt_system"]
    assert specs.upgrade_methods(db, now=clock())["changes"] == []


def test_upgrade_cleans_nested_mating_labels_from_recorded_ancestors(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    maybe_run_evolution(db, "cs", clock(), force=True)
    _, doc = specs.current_spec(db)
    first = specs.find_genome(doc, "cs-gen1")[1]
    older_donor = first["lineage"]["parents"][1]
    child = copy.deepcopy(first)
    child.update(
        id="cs-gen2",
        research_methods={},
        prompt=f"Nested custom strategy.\n\nAlso, from cs-gen1: First generation procedure."
        f"\n\nAlso, from {older_donor}: Older inherited procedure."
        "\n\nAlso, from custom-explanation: Authored reasoning.",
    )
    specs.find_island(doc, "cs")["genomes"].append(child)
    record = specs.apply_spec(
        db,
        doc,
        actor="evolution",
        now=clock(),
        lineage={
            "cs-gen2": {
                "origin": "mating",
                "parents": ["cs-gen1", "quant-builder"],
                "parent": {"genome_id": "cs-gen1", "version": 1},
                "generation": 2,
            }
        },
    )
    historic = specs.get_revision(db, record["revision"])["spec"]
    result = specs.upgrade_methods(db, now=clock())
    updated = specs.find_genome(result["spec"], "cs-gen2")[1]
    assert "cs-gen1" not in updated["prompt"]
    assert older_donor not in updated["prompt"]
    assert "First generation procedure." in updated["prompt"]
    assert "Older inherited procedure." in updated["prompt"]
    assert "Also, from custom-explanation: Authored reasoning." in updated["prompt"]
    assert updated["lineage"]["parents"] == ["cs-gen1", "quant-builder"]
    assert specs.get_revision(db, record["revision"])["spec"] == historic
    _store(db, clock)
    run_id = _create(db, clock, genome_id="cs-gen2")
    system = db.execute(
        "SELECT prompt_system FROM runs WHERE id = ?", (run_id,)
    ).fetchone()[0]
    assert older_donor not in system and "cs-gen1" not in system
