from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.parents import draw_parents
from genome_fixtures import PROFILE_HASH, genome, standing


def test_draw_parents_is_disabled_before_the_third_cycle() -> None:
    standings = [standing(genome_=genome(lineage_id="a"), skill=0.5)]
    for cycle in (0, 1):
        result = draw_parents(
            island="cs",
            standings=standings,
            count=1,
            completed_weekly_cycles=cycle,
            profile_hash=PROFILE_HASH,
        )
        assert result.disposition == "disabled_by_profile"
        assert result.drawn == ()


def test_draw_parents_excludes_a_genome_below_the_claim_count() -> None:
    eligible = standing(
        genome_=genome(lineage_id="a"), skill=0.5, resolved_claim_count=30
    )
    thin = standing(genome_=genome(lineage_id="b"), skill=0.9, resolved_claim_count=10)
    result = draw_parents(
        island="cs",
        standings=[eligible, thin],
        count=2,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "drawn"
    drawn_hashes = {g.configuration_hash for g in result.drawn}
    assert eligible.genome.configuration_hash in drawn_hashes
    assert thin.genome.configuration_hash not in drawn_hashes
    assert thin.genome.configuration_hash in result.excluded


def test_draw_parents_excludes_a_genome_below_the_grounding_floor() -> None:
    grounded = standing(genome_=genome(lineage_id="a"), skill=0.1, grounding_share=0.99)
    ungrounded = standing(
        genome_=genome(lineage_id="b"), skill=0.9, grounding_share=0.5
    )
    result = draw_parents(
        island="cs",
        standings=[grounded, ungrounded],
        count=2,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    drawn_hashes = {g.configuration_hash for g in result.drawn}
    assert grounded.genome.configuration_hash in drawn_hashes
    assert ungrounded.genome.configuration_hash not in drawn_hashes
    assert ungrounded.genome.configuration_hash in result.excluded


def test_draw_parents_ranks_by_skill_descending() -> None:
    low = standing(genome_=genome(lineage_id="a"), skill=0.1)
    high = standing(genome_=genome(lineage_id="b"), skill=0.8)
    result = draw_parents(
        island="cs",
        standings=[low, high],
        count=1,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.drawn[0].configuration_hash == high.genome.configuration_hash


def test_draw_parents_breaks_equal_skill_ties_on_skill_per_dollar() -> None:
    cheap = standing(genome_=genome(lineage_id="a"), skill=0.5, skill_per_dollar=10.0)
    expensive = standing(
        genome_=genome(lineage_id="b"), skill=0.5, skill_per_dollar=1.0
    )
    # Input order deliberately puts the worse tie-break first, so a pass
    # that fell back to input order would draw the wrong genome.
    result = draw_parents(
        island="cs",
        standings=[expensive, cheap],
        count=1,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.drawn[0].configuration_hash == cheap.genome.configuration_hash


def test_draw_parents_falls_back_to_the_island_proxy_when_skill_is_unavailable() -> (
    None
):
    no_skill = standing(genome_=genome(lineage_id="a"), skill=None, proxy=0.7)
    result = draw_parents(
        island="cs",
        standings=[no_skill],
        count=1,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.drawn[0].configuration_hash == no_skill.genome.configuration_hash


def test_draw_parents_rejects_missing_profile() -> None:
    with pytest.raises(ContractValidationError):
        draw_parents(
            island="cs",
            standings=[standing()],
            count=1,
            completed_weekly_cycles=2,
            profile_hash=None,
        )
