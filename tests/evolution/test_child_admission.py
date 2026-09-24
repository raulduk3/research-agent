from __future__ import annotations

from research_agent.evolution.admission import admit_child
from tests.evolution.genome_fixtures import PROFILE_HASH, genome


def test_admission_is_disabled_before_the_third_cycle() -> None:
    child = genome(lineage_id="child")
    result = admit_child(
        child=child,
        active_genomes=(),
        archived_genomes=(),
        completed_weekly_cycles=0,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "disabled_by_profile"


def test_admission_refuses_a_child_equal_to_an_active_genome() -> None:
    # Same prompt/infra_hash/island -> same configuration hash, regardless
    # of the two genomes' different lineage_id (AG-21 compares content).
    active = genome(lineage_id="active-1", prompt="evidence-first")
    child = genome(lineage_id="child", prompt="evidence-first")
    result = admit_child(
        child=child,
        active_genomes=(active,),
        archived_genomes=(),
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.matched_hash == active.configuration_hash


def test_admission_refuses_a_child_equal_to_an_archived_genome() -> None:
    archived = genome(lineage_id="archived-1", prompt="evidence-first")
    child = genome(lineage_id="child", prompt="evidence-first")
    result = admit_child(
        child=child,
        active_genomes=(),
        archived_genomes=(archived,),
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.matched_hash == archived.configuration_hash


def test_admission_accepts_a_child_differing_in_one_part() -> None:
    active = genome(lineage_id="active-1", prompt="evidence-first")
    child = genome(lineage_id="child", prompt="methods-scrutiny")
    result = admit_child(
        child=child,
        active_genomes=(active,),
        archived_genomes=(),
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "accepted"
    assert result.matched_hash is None
