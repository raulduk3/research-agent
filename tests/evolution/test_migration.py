from __future__ import annotations

from research_agent.evolution.mutation import propose_migration
from genome_fixtures import PROFILE_HASH, genome


def test_migration_from_quant_ph_into_cs_is_admitted_and_recorded() -> None:
    source = genome(island="quant-ph", lineage_id="quant-ph-1")
    result = propose_migration(
        destination_island="cs",
        kind="parent",
        source_genome=source,
        field_name="prompt",
        new_value="methods-scrutiny",
        lineage_id="cs-lineage-1",
        cycle_id="cycle-3",
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "accepted"
    assert result.child is not None
    assert result.child.island == "cs"
    assert result.migration is not None
    assert result.migration.source_island == "quant-ph"
    assert result.migration.source_hash == source.configuration_hash
    assert result.migration.kind == "parent"
    assert result.migration.field_name is None
    assert result.migration.child_hash == result.child.configuration_hash


def test_migration_from_cs_into_q_bio_is_refused_whole() -> None:
    source = genome(island="cs", lineage_id="cs-1")
    result = propose_migration(
        destination_island="q-bio",
        kind="parent",
        source_genome=source,
        field_name="prompt",
        new_value="methods-scrutiny",
        lineage_id="q-bio-lineage-1",
        cycle_id="cycle-3",
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.reason == "q_bio_destination_refused"
    assert result.child is None
    assert result.migration is None


def test_migration_from_q_bio_into_cs_is_admitted() -> None:
    source = genome(island="q-bio", lineage_id="q-bio-1", prompt="limitations-scrutiny")
    local_parent = genome(island="cs", lineage_id="cs-1")
    result = propose_migration(
        destination_island="cs",
        kind="field",
        source_genome=source,
        field_name="prompt",
        local_parent=local_parent,
        lineage_id="cs-1",
        cycle_id="cycle-3",
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "accepted"
    assert result.child is not None
    assert result.child.island == "cs"
    assert result.child.emphasis["prompt"] == "limitations-scrutiny"
    assert result.child.infra_hash == local_parent.infra_hash
    assert result.migration is not None
    assert result.migration.kind == "field"
    assert result.migration.field_name == "prompt"
    assert result.migration.source_island == "q-bio"


def test_migration_with_an_unresolvable_source_is_refused() -> None:
    result = propose_migration(
        destination_island="cs",
        kind="parent",
        source_genome=None,
        field_name="prompt",
        new_value="methods-scrutiny",
        lineage_id="cs-lineage-1",
        cycle_id="cycle-3",
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.reason == "unresolvable_source"


def test_proposal_within_the_same_island_is_not_a_migration() -> None:
    source = genome(island="cs", lineage_id="cs-1")
    result = propose_migration(
        destination_island="cs",
        kind="parent",
        source_genome=source,
        field_name="prompt",
        new_value="methods-scrutiny",
        lineage_id="cs-2",
        cycle_id="cycle-3",
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.reason == "not_a_migration"


def test_migration_is_disabled_before_the_third_cycle() -> None:
    source = genome(island="quant-ph", lineage_id="quant-ph-1")
    result = propose_migration(
        destination_island="cs",
        kind="parent",
        source_genome=source,
        field_name="prompt",
        new_value="methods-scrutiny",
        lineage_id="cs-lineage-1",
        cycle_id="cycle-1",
        completed_weekly_cycles=0,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "disabled_by_profile"
