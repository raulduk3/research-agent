"""Research methods upgrades preserve authored behavior and historical runs."""

from __future__ import annotations

import copy
import sqlite3

import pytest

from research_agent.beta import spec as specs
from research_agent.beta.db import connect, loads
from research_agent.beta.config import BetaConfig
from research_agent.beta.evolution import maybe_run_evolution
from research_agent.beta.methods import CATALOG
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


def test_evolution_child_mixes_parent_domains_after_mating(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    result = maybe_run_evolution(db, "bio", clock(), force=True)
    assert result is not None and result["status"] == "committed"
    _, doc = specs.current_spec(db)
    child = specs.find_island(doc, "bio")["genomes"][-1]
    assert "Biology: mechanisms" in child["research_methods"]["instructions"]
    assert "Also, from" not in child["prompt"]
    assert "http" not in child["prompt"]
    assert "Computer science: empirical" in child["research_methods"]["instructions"]


def test_oversized_mating_records_refusal_and_preserves_population(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, doc = specs.current_spec(db)
    for island in doc["islands"]:
        for genome in island["genomes"]:
            genome["prompt"] = "Long custom posture. " + genome["id"] * (
                7800 // len(genome["id"])
            )
    specs.apply_spec(db, doc, actor="operator", now=clock())
    before = specs.current_spec(db)
    result = maybe_run_evolution(db, "cs", clock(), force=True)
    assert result is not None
    assert result["reason"] == "invalid_child"
    assert result["decisions"][0]["why"] == "must be at most 8000 characters"
    assert specs.current_spec(db) == before


def test_source_metadata_does_not_make_a_duplicate_mutation_novel() -> None:
    from research_agent.beta.evolution import _mutations, mutate_genome
    import random

    genome = specs.default_spec()["islands"][0]["genomes"][0]
    offers = _mutations(genome, random.Random("seed"))
    existing = [
        {**content, "research_methods": {**genome["research_methods"], "version": 2}}
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


def test_mating_keeps_both_method_contributions_once() -> None:
    from research_agent.beta.evolution import mate_genomes

    doc = specs.default_spec()
    parent = copy.deepcopy(doc["islands"][0]["genomes"][0])
    mate = copy.deepcopy(doc["islands"][1]["genomes"][0])
    parent["research_methods"]["instructions"] = (
        "Shared method. Compare matched baselines."
    )
    mate["research_methods"]["instructions"] = (
        "Shared method. Check certification assumptions."
    )
    parent["prompt"] = "Read stored evidence. Check claims."
    mate["prompt"] = "Read stored evidence. Check claims."
    result = mate_genomes(parent, mate, [parent, mate], "method-mating")
    assert result is not None
    child = result[0]
    assert child["research_methods"]["instructions"] == (
        "Shared method. Compare matched baselines.\n\nCheck certification assumptions."
    )
    assert child["prompt"].count("Check claims.") == 1
    assert {source["url"] for source in child["research_methods"]["sources"]} == {
        source["url"]
        for genome in (parent, mate)
        for source in genome["research_methods"]["sources"]
    }


def test_new_agent_prompt_removes_repeated_instructions() -> None:
    genome = copy.deepcopy(specs.default_spec()["islands"][0]["genomes"][0])
    genome["prompt"] = (
        "Read stored evidence. Read stored evidence.\n\nKeep both X and x."
    )
    checked = specs.validate_genome(genome, "agent")
    assert checked["prompt"] == "Read stored evidence.\n\nKeep both X and x."


def test_persisted_evolution_keeps_actual_parent_methods(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, doc = specs.current_spec(db)
    for island in doc["islands"]:
        for genome in island["genomes"]:
            genome["research_methods"]["instructions"] += (
                f"\nProcedure for {genome['id']}."
            )
    specs.apply_spec(db, doc, actor="operator", now=clock())
    result = maybe_run_evolution(db, "cs", clock(), force=True)
    assert result is not None and result["status"] == "committed"
    _, evolved = specs.current_spec(db)
    child = specs.find_genome(evolved, "cs-gen1")[1]
    assert len(child["lineage"]["parents"]) == 2
    for parent_id in child["lineage"]["parents"]:
        assert (
            f"Procedure for {parent_id}." in child["research_methods"]["instructions"]
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Read evidence.\nRead evidence.", "Read evidence."),
        ("Read evidence\nRead evidence", "Read evidence"),
        (
            "Check assumptions.\n\nAdditional reading emphasis: Additional reading emphasis: Check assumptions.",
            "Check assumptions.",
        ),
        (
            "Additional reading emphasis: Additional reading emphasis: Check assumptions.",
            "Additional reading emphasis: Check assumptions.",
        ),
        ("Use e.g. controls. Use e.g. controls.", "Use e.g. controls."),
        ("Estimate 0.05. Estimate 0.05.", "Estimate 0.05."),
        ("Estimate X. Estimate x.", "Estimate X. Estimate x."),
        (
            "Read https://example.test/data. Read https://example.test/data.",
            "Read https://example.test/data.",
        ),
        ("Read stored\n evidence. Read stored evidence.", "Read stored\n evidence."),
        (
            "Check assumptions.\n\nAdditional reading emphasis: Check assumptions.",
            "Check assumptions.",
        ),
        (
            "- Read evidence\n- Read evidence\n- Check claims",
            "- Read evidence\n- Check claims",
        ),
        ("```python\nx = 1\nx = 1\n```", "```python\nx = 1\nx = 1\n```"),
        ('Repeat "A. A. A. A." exactly.', 'Repeat "A. A. A. A." exactly.'),
        ("Repeat ‘A. A. A. A.’ exactly.", "Repeat ‘A. A. A. A.’ exactly."),
        ("Spend $5. Spend $5.", "Spend $5."),
        ("Use $x. x. x.$ literally.", "Use $x. x. x.$ literally."),
    ],
)
def test_instruction_normalization_preserves_scientific_text(
    text: str, expected: str
) -> None:
    from research_agent.beta.methods import unique_instructions

    assert unique_instructions(text) == expected
    assert unique_instructions(expected) == expected


def test_run_prompt_removes_duplicates_across_instruction_fields(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, doc = specs.current_spec(db)
    genome = specs.find_genome(doc, "cs-reader")[1]
    genome["prompt"] = "Read stored evidence. Check matched controls."
    genome["research_methods"]["instructions"] = (
        "Check matched controls. Check assumptions."
    )
    specs.apply_spec(db, doc, actor="operator", now=clock())
    _store(db, clock)
    run_id = _create(db, clock)
    row = db.execute(
        "SELECT prompt_system,prompt_user FROM runs WHERE id=?", (run_id,)
    ).fetchone()
    assert row["prompt_system"].count("Check matched controls.") == 1
    assert "Check assumptions." in row["prompt_system"]
    assert "Paper 2609.00001" in row["prompt_user"]


def test_legacy_queued_prompt_is_normalized_at_execution(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    import hashlib
    from tests.beta.helpers import call, reading, reply
    from tests.beta.test_runs import _execute

    _store(db, clock)
    run_id = _create(db, clock)
    db.execute(
        "UPDATE runs SET prompt_system = ? WHERE id = ?",
        ("Check evidence. Check evidence.", run_id),
    )
    db.commit()
    captured = dict(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
    client = _execute(cfg, clock, run_id, [reply(call("submit_reading", reading()))])
    assert client.requests[0]["messages"][0]["content"] == "Check evidence."
    event = db.execute(
        "SELECT payload FROM run_events WHERE run_id=? AND kind='prompt'", (run_id,)
    ).fetchone()
    payload = loads(event["payload"])
    assert payload["system"] == "Check evidence."
    assert (
        payload["prompt_hash"]
        == hashlib.sha256(
            f"Check evidence.\n\n{captured['prompt_user']}".encode()
        ).hexdigest()
    )
    after = db.execute(
        "SELECT prompt_system,prompt_hash FROM runs WHERE id=?", (run_id,)
    ).fetchone()
    assert after["prompt_system"] == captured["prompt_system"]
    assert after["prompt_hash"] == captured["prompt_hash"]
    from research_agent.beta.projections import build_run_projection

    view = build_run_projection(db, run_id)
    assert view["run"]["prompt"] == {
        "system": payload["system"],
        "user": payload["user"],
        "hash": payload["prompt_hash"],
    }


def test_existing_archived_agents_upgrade_without_losing_custom_methods(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    from research_agent.beta.db import dumps, iso

    revision, legacy = specs.current_spec(db)
    legacy["islands"][0]["archived"] = True
    agent = legacy["islands"][0]["genomes"][0]
    agent["active"] = False
    agent["prompt"] = "Keep uncertainty. Keep uncertainty."
    agent["research_methods"]["instructions"] = "Custom control. Custom control."
    # Append a pre-normalization revision, as an existing database would contain.
    db.execute(
        "INSERT INTO spec_revisions(revision,body,changes,actor,created_at) VALUES (?,?,?,?,?)",
        (revision + 1, dumps(legacy), "[]", "operator", iso(clock())),
    )
    preview = specs.upgrade_methods(db, now=clock(), dry_run=True)
    assert not preview["applied"]
    assert specs.current_spec(db)[1] == legacy
    updated = specs.upgrade_methods(db, now=clock())
    current = specs.find_genome(updated["spec"], agent["id"])[1]
    assert current["prompt"] == "Keep uncertainty."
    assert current["research_methods"]["instructions"] == "Custom control."
    assert (
        current["research_methods"]["sources"] == agent["research_methods"]["sources"]
    )
    assert not current["active"] and updated["spec"]["islands"][0]["archived"]
    assert current["version"] == agent["version"] + 1
    assert specs.get_revision(db, revision + 1)["spec"] == legacy
    assert specs.upgrade_methods(db, now=clock())["changes"] == []
