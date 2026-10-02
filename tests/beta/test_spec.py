"""Editing the swarm spec: every edit is a revision, nothing is lost."""

from __future__ import annotations

import copy
import sqlite3

import pytest

from research_agent.beta import spec as specs
from research_agent.beta.errors import Invalid
from tests.beta.helpers import FakeClock


def _apply(db: sqlite3.Connection, clock: FakeClock, proposed, **kwargs):
    return specs.apply_spec(db, proposed, actor="operator", now=clock(), **kwargs)


def _genome(spec, genome_id: str):
    return specs.find_genome(spec, genome_id)[1]


def test_a_fresh_store_is_seeded_as_revision_one(db: sqlite3.Connection) -> None:
    revision, spec = specs.current_spec(db)

    assert revision == 1
    assert [island["id"] for island in spec["islands"]] == [
        "cs",
        "quant",
        "bio",
        "general",
    ]
    founder = _genome(spec, "cs-reader")
    assert founder["version"] == 1
    assert founder["lineage"] == {"origin": "founder", "parent": None, "revision": 1}


def test_editing_an_agent_makes_a_new_version_and_leaves_the_others_alone(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)
    proposed = specs.patch_genome(
        spec, "cs", "cs-reader", {"prompt": "Read for flaws."}
    )

    record = _apply(db, clock, proposed, note="sharper")

    assert record["applied"] and record["revision"] == 2
    assert record["changes"] == [
        {
            "kind": "genome",
            "id": "cs-reader",
            "island_id": "cs",
            "fields": ["prompt"],
            "created": False,
        }
    ]
    _, after = specs.current_spec(db)
    edited = _genome(after, "cs-reader")
    assert edited["version"] == 2
    assert edited["lineage"] == {
        "origin": "edit",
        "parent": {"genome_id": "cs-reader", "version": 1},
        "revision": 2,
    }
    assert _genome(after, "quant-reader")["version"] == 1
    # The first revision is still stored exactly as it was.
    assert _genome(specs.get_revision(db, 1)["spec"], "cs-reader")["version"] == 1


def test_an_edit_that_changes_nothing_writes_no_revision(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)

    record = _apply(db, clock, copy.deepcopy(spec))

    assert record["applied"] is False and record["changes"] == []
    assert db.execute("SELECT COUNT(*) FROM spec_revisions").fetchone()[0] == 1


def test_a_dry_run_reports_the_changes_and_writes_nothing(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)

    record = _apply(
        db, clock, specs.patch_island(spec, "cs", {"paused": True}), dry_run=True
    )

    assert record["applied"] is False
    assert record["changes"][0]["fields"] == ["paused"]
    assert specs.current_spec(db)[0] == 1


def test_islands_and_agents_are_switched_off_never_removed(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)
    without_island = copy.deepcopy(spec)
    without_island["islands"] = [
        island for island in without_island["islands"] if island["id"] != "bio"
    ]
    without_agent = copy.deepcopy(spec)
    specs.find_island(without_agent, "cs")["genomes"] = []

    with pytest.raises(Invalid, match="cannot be removed; set archived"):
        _apply(db, clock, without_island)
    with pytest.raises(Invalid, match="cannot be removed; set active"):
        _apply(db, clock, without_agent)


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"allowed_tools": ["paper_text"]}, "allowed_tools"),
        ({"allowed_tools": ["submit_reading", "shell"]}, "allowed_tools"),
        ({"prompt": "  "}, "prompt"),
        (
            {"model_settings": {"temperature": 3, "max_output_tokens": 900}},
            "model_settings.temperature",
        ),
    ],
)
def test_an_invalid_agent_is_refused_with_the_field_named(
    db: sqlite3.Connection, clock: FakeClock, fields, field: str
) -> None:
    _, spec = specs.current_spec(db)

    with pytest.raises(Invalid) as refused:
        _apply(db, clock, specs.patch_genome(spec, "cs", "cs-reader", fields))

    assert refused.value.field is not None and refused.value.field.endswith(field)
    assert specs.current_spec(db)[0] == 1


def test_a_new_agent_must_declare_every_field(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)
    partial = specs.patch_genome(spec, "cs", "cs-skeptic", {"prompt": "Doubt."})

    with pytest.raises(Invalid, match="must declare model_settings"):
        _apply(db, clock, partial)

    complete = {
        name: specs.find_genome(spec, "cs-reader")[1][name]
        for name in specs.GENOME_CONTENT
    }
    record = _apply(
        db, clock, specs.patch_genome(spec, "cs", "cs-skeptic", complete)
    )
    created = _genome(record["spec"], "cs-skeptic")
    assert created["version"] == 1 and created["lineage"]["origin"] == "created"


def test_restoring_a_revision_appends_one_and_keeps_later_agents_switched_off(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)
    reader = specs.find_genome(spec, "cs-reader")[1]
    edited = specs.patch_genome(spec, "cs", "cs-reader", {"prompt": "Read for flaws."})
    edited = specs.patch_genome(
        edited,
        "cs",
        "cs-skeptic",
        {name: reader[name] for name in specs.GENOME_CONTENT},
    )
    edited = specs.patch_budget(edited, {"agents_per_paper": 2})
    _apply(db, clock, edited)

    record = specs.restore_revision(db, 1, actor="operator", now=clock())

    assert record["applied"] and record["revision"] == 3
    assert record["restored_from"] == 1
    _, after = specs.current_spec(db)
    restored = _genome(after, "cs-reader")
    assert restored["prompt"] == reader["prompt"]
    # Versions only move forward: the old content comes back as version 3.
    assert restored["version"] == 3
    assert restored["lineage"]["origin"] == "restore"
    assert _genome(after, "cs-skeptic")["active"] is False
    assert after["budget"] == {}
    revisions = [item["revision"] for item in specs.list_revisions(db)]
    assert revisions == [3, 2, 1]
    history = specs.genome_versions(db, "cs-reader")
    assert [(item["version"], item["revision"]) for item in history] == [
        (1, 1),
        (2, 2),
        (3, 3),
    ]


def test_the_general_island_cannot_be_closed(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)

    with pytest.raises(Invalid, match="general island must exist"):
        _apply(db, clock, specs.patch_island(spec, "general", {"archived": True}))
