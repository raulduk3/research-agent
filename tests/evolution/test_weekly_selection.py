from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.orchestration.selection import (
    cycle_guard,
    record_selection_stage,
)
from research_agent.evolution.genome import Lineage
from tests.evolution.genome_fixtures import PROFILE_HASH, genome, standing


def _lineage(lineage_id: str, *, founder: bool = False, skill: float = 0.5) -> Lineage:
    return Lineage(
        lineage_id=lineage_id,
        island="cs",
        founder=founder,
        history=(
            standing(
                genome_=genome(lineage_id=lineage_id, founder=founder),
                skill=skill,
            ),
        ),
    )


def test_cycle_guard_rejects_a_missing_profile() -> None:
    with pytest.raises(ContractValidationError):
        cycle_guard(profile_hash=None, completed_weekly_cycles=3)


def test_cycle_guard_rejects_an_unreadable_cycle_count() -> None:
    with pytest.raises(ContractValidationError):
        cycle_guard(profile_hash=PROFILE_HASH, completed_weekly_cycles=None)


def test_cycle_guard_disabled_through_the_first_two_cycles() -> None:
    for cycle in (0, 1):
        result = cycle_guard(profile_hash=PROFILE_HASH, completed_weekly_cycles=cycle)
        assert result.disposition == "disabled_by_profile"


def test_cycle_guard_enabled_from_the_third_cycle() -> None:
    result = cycle_guard(profile_hash=PROFILE_HASH, completed_weekly_cycles=2)
    assert result.disposition == "enabled"


def test_successive_weeks_change_no_active_hash_before_the_third_cycle() -> None:
    lineages = [
        _lineage("founder", founder=True),
        _lineage("a", skill=0.1),
        _lineage("b", skill=0.9),
    ]
    islands = {"cs": lineages}
    ceilings = {"cs": 4}
    for cycle_index, cycle in enumerate((0, 1)):
        event = record_selection_stage(
            cycle_id=f"cycle-{cycle_index}",
            profile_hash=PROFILE_HASH,
            completed_weekly_cycles=cycle,
            islands=islands,
            ceilings=ceilings,
        )
        assert event.disposition == "selection_disabled"
        assert set(event.results["cs"].survivors) == {"founder", "a", "b"}
        assert event.archived == ()


def test_a_third_cycle_resolves_to_one_committed_event() -> None:
    lineages = [
        _lineage("founder", founder=True),
        _lineage("a", skill=0.1),
        _lineage("b", skill=0.9),
    ]
    islands = {"cs": lineages}
    ceilings = {"cs": 1}
    event = record_selection_stage(
        cycle_id="cycle-3",
        profile_hash=PROFILE_HASH,
        completed_weekly_cycles=2,
        islands=islands,
        ceilings=ceilings,
    )
    assert event.disposition == "selected"
    assert "b" in event.results["cs"].survivors
    assert "founder" in event.results["cs"].survivors


def test_an_interrupted_checkpoint_resumes_idempotently() -> None:
    lineages = [
        _lineage("founder", founder=True),
        _lineage("a", skill=0.1),
        _lineage("b", skill=0.9),
    ]
    islands = {"cs": lineages}
    ceilings = {"cs": 1}
    first = record_selection_stage(
        cycle_id="cycle-3",
        profile_hash=PROFILE_HASH,
        completed_weekly_cycles=2,
        islands=islands,
        ceilings=ceilings,
    )
    replay = record_selection_stage(
        cycle_id="cycle-3",
        profile_hash=PROFILE_HASH,
        completed_weekly_cycles=2,
        islands=islands,
        ceilings=ceilings,
        previous_event=first,
    )
    assert replay is first
