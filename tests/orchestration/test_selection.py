from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.admission import admit_child
from research_agent.evolution.genome import Lineage
from research_agent.orchestration.selection import (
    archive_lineage,
    exempt_founders,
    record_selection_stage,
    select_population,
)
from selection_fixtures import PROFILE_HASH, genome, standing


def _lineage(
    lineage_id: str, *, founder: bool = False, skills: tuple[float, ...] = (0.5,)
) -> Lineage:
    return Lineage(
        lineage_id=lineage_id,
        island="cs",
        founder=founder,
        history=tuple(
            standing(
                genome_=genome(
                    lineage_id=lineage_id,
                    founder=founder,
                    prompt=f"{lineage_id}-generation-{index}",
                ),
                skill=skill,
            )
            for index, skill in enumerate(skills)
        ),
    )


# -- exempt_founders (AG-38) -------------------------------------------------


def test_exempt_founders_refuses_an_island_with_no_founder() -> None:
    with pytest.raises(ContractValidationError):
        exempt_founders([_lineage("a"), _lineage("b")])


def test_exempt_founders_refuses_an_island_with_two_founders() -> None:
    with pytest.raises(ContractValidationError):
        exempt_founders([_lineage("a", founder=True), _lineage("b", founder=True)])


def test_exempt_founders_separates_the_one_founder() -> None:
    founder, others = exempt_founders(
        [_lineage("founder", founder=True), _lineage("a"), _lineage("b")]
    )
    assert founder.lineage_id == "founder"
    assert {lineage.lineage_id for lineage in others} == {"a", "b"}


# -- select_population (FT-14, AG-38) ----------------------------------------


def test_select_population_is_disabled_through_the_first_two_cycles() -> None:
    lineages = [
        _lineage("founder", founder=True, skills=(0.01,)),
        _lineage("a", skills=(0.9,)),
    ]
    for cycle in (0, 1):
        result = select_population(
            island="cs",
            lineages=lineages,
            ceiling=0,
            completed_weekly_cycles=cycle,
            profile_hash=PROFILE_HASH,
        )
        assert result.disposition == "selection_disabled"
        assert set(result.survivors) == {"founder", "a"}


def test_select_population_ranks_by_skill_and_breaks_ties_on_skill_per_dollar() -> None:
    founder = _lineage("founder", founder=True, skills=(0.5,))
    cheap = Lineage(
        lineage_id="cheap",
        island="cs",
        founder=False,
        history=(
            standing(
                genome_=genome(lineage_id="cheap"), skill=0.5, skill_per_dollar=10.0
            ),
        ),
    )
    expensive = Lineage(
        lineage_id="expensive",
        island="cs",
        founder=False,
        history=(
            standing(
                genome_=genome(lineage_id="expensive"), skill=0.5, skill_per_dollar=1.0
            ),
        ),
    )
    low = Lineage(
        lineage_id="low",
        island="cs",
        founder=False,
        history=(standing(genome_=genome(lineage_id="low"), skill=0.1),),
    )
    result = select_population(
        island="cs",
        lineages=[founder, cheap, expensive, low],
        ceiling=1,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
        floor=2,
    )
    assert result.ranked_support[0] == "cheap"
    assert result.survivors == ("founder", "cheap")


def test_select_population_keeps_the_founder_even_when_it_would_rank_last() -> None:
    founder = _lineage("founder", founder=True, skills=(0.01,))
    strong = _lineage("strong", skills=(0.9,))
    result = select_population(
        island="cs",
        lineages=[founder, strong],
        ceiling=1,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
        floor=2,
    )
    assert "founder" in result.survivors


def test_select_population_refuses_to_drop_the_island_below_the_floor() -> None:
    founder = _lineage("founder", founder=True, skills=(0.5,))
    others = [_lineage(f"member-{i}", skills=(0.1 * i,)) for i in range(1, 5)]
    result = select_population(
        island="cs",
        lineages=[founder, *others],
        ceiling=1,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
        floor=4,
    )
    assert len(result.survivors) == 4


def test_select_population_refuses_a_lineage_of_another_island() -> None:
    foreign = Lineage(
        lineage_id="foreign",
        island="quant-ph",
        founder=False,
        history=(standing(genome_=genome(island="quant-ph", lineage_id="foreign")),),
    )
    with pytest.raises(ContractValidationError):
        select_population(
            island="cs",
            lineages=[_lineage("founder", founder=True), foreign],
            ceiling=1,
            completed_weekly_cycles=2,
            profile_hash=PROFILE_HASH,
        )


# -- archive_lineage (FT-15) --------------------------------------------------


def test_archive_lineage_is_disabled_through_the_first_two_cycles() -> None:
    lineage = _lineage("retiring", skills=(0.1, 0.5, 0.2))
    result = archive_lineage(
        lineage=lineage, completed_weekly_cycles=1, profile_hash=PROFILE_HASH
    )
    assert result.disposition == "disabled_by_profile"
    assert result.archived is None


def test_archive_lineage_archives_exactly_the_highest_skill_member() -> None:
    lineage = _lineage("retiring", skills=(0.1, 0.5, 0.2))
    result = archive_lineage(
        lineage=lineage, completed_weekly_cycles=2, profile_hash=PROFILE_HASH
    )
    assert result.disposition == "archived"
    archived = result.archived
    assert archived is not None
    assert archived.skill == 0.5
    assert archived.genome_hash == lineage.history[1].genome.configuration_hash


def test_an_archived_genome_refuses_an_identical_child_under_admission() -> None:
    lineage = _lineage("retiring", skills=(0.1, 0.5, 0.2))
    archived = archive_lineage(
        lineage=lineage, completed_weekly_cycles=2, profile_hash=PROFILE_HASH
    ).archived
    assert archived is not None
    identical_child = lineage.history[1].genome
    result = admit_child(
        child=identical_child,
        active_genomes=(),
        archived_genomes=(lineage.history[1].genome,),
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.matched_hash == archived.genome_hash


# -- record_selection_stage (FT-13) ------------------------------------------


def test_record_selection_stage_archives_every_retired_lineage_in_one_event() -> None:
    founder = _lineage("founder", founder=True, skills=(0.5,))
    survivor = _lineage("survivor", skills=(0.9,))
    mid = _lineage("mid", skills=(0.5,))
    low = _lineage("low", skills=(0.3,))
    retiring = _lineage("retiring", skills=(0.1, 0.6, 0.2))
    event = record_selection_stage(
        cycle_id="cycle-3",
        profile_hash=PROFILE_HASH,
        completed_weekly_cycles=2,
        islands={"cs": [founder, survivor, mid, low, retiring]},
        ceilings={"cs": 1},
    )
    assert event.disposition == "selected"
    result = event.results["cs"]
    assert {c.lineage_id for c in result.retired} == {"retiring"}
    assert len(result.survivors) == 4
    assert len(event.archived) == 1
    assert event.archived[0].lineage_id == "retiring"
    assert event.archived[0].skill == 0.6
