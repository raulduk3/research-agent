from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.mutation import (
    propose_mutation,
    propose_performance_mutation,
)
from genome_fixtures import PROFILE_HASH, genome


# -- propose_mutation (AG-20) -----------------------------------------------


def test_propose_mutation_is_disabled_before_the_third_cycle() -> None:
    parent = genome()
    for cycle in (0, 1):
        result = propose_mutation(
            parent=parent,
            changes={"prompt": "methods-scrutiny"},
            lineage_id=parent.lineage_id,
            completed_weekly_cycles=cycle,
            profile_hash=PROFILE_HASH,
        )
        assert result.disposition == "disabled_by_profile"
        assert result.child is None


def test_propose_mutation_accepts_a_single_emphasis_field_change() -> None:
    parent = genome()
    result = propose_mutation(
        parent=parent,
        changes={"prompt": "methods-scrutiny"},
        lineage_id=parent.lineage_id,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "accepted"
    assert result.changed_field == "prompt"
    assert result.parent_hash == parent.configuration_hash
    child = result.child
    assert child is not None
    assert child.emphasis["prompt"] == "methods-scrutiny"
    assert child.emphasis["scan_policy"] == parent.emphasis["scan_policy"]
    assert child.infra_hash == parent.infra_hash
    assert child.parent_hash == parent.configuration_hash
    assert child.configuration_hash != parent.configuration_hash


def test_propose_mutation_refuses_a_two_part_proposal() -> None:
    parent = genome()
    result = propose_mutation(
        parent=parent,
        changes={"prompt": "methods-scrutiny", "scan_policy": "depth-first"},
        lineage_id=parent.lineage_id,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.reason == "invalid_proposal"
    assert result.child is None


def test_propose_mutation_refuses_a_budgets_proposal() -> None:
    parent = genome()
    result = propose_mutation(
        parent=parent,
        changes={"budgets": "unlimited"},
        lineage_id=parent.lineage_id,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.reason == "invalid_proposal"


def test_propose_mutation_refuses_a_schema_extension_proposal() -> None:
    parent = genome()
    result = propose_mutation(
        parent=parent,
        changes={"structured_output_schema": "{}"},
        lineage_id=parent.lineage_id,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.reason == "invalid_proposal"


def test_propose_mutation_rejects_missing_profile() -> None:
    parent = genome()
    with pytest.raises(ContractValidationError):
        propose_mutation(
            parent=parent,
            changes={"prompt": "methods-scrutiny"},
            lineage_id=parent.lineage_id,
            completed_weekly_cycles=2,
            profile_hash=None,
        )


# -- propose_performance_mutation (AG-06) -----------------------------------


def test_performance_mutation_disabled_leaves_population_unchanged_in_cycles_one_and_two() -> (
    None
):
    parent = genome()
    for cycle in (0, 1):
        result = propose_performance_mutation(
            parent=parent,
            changes={"prompt": "methods-scrutiny"},
            lineage_id=parent.lineage_id,
            completed_weekly_cycles=cycle,
            profile_hash=PROFILE_HASH,
        )
        assert result.disposition == "disabled_by_profile"
        assert result.child is None


def test_performance_mutation_produces_one_child_differing_in_one_part() -> None:
    parent = genome()
    result = propose_performance_mutation(
        parent=parent,
        changes={"read_policy": "skim-first"},
        lineage_id=parent.lineage_id,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "accepted"
    assert result.child is not None
    differing = [
        field
        for field in result.child.emphasis
        if result.child.emphasis[field] != parent.emphasis[field]
    ]
    assert differing == ["read_policy"]


def test_performance_mutation_refuses_a_second_child_for_the_same_parent_this_cycle() -> (
    None
):
    parent = genome()
    result = propose_performance_mutation(
        parent=parent,
        changes={"read_policy": "skim-first"},
        lineage_id=parent.lineage_id,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
        already_mutated_this_cycle=True,
    )
    assert result.disposition == "rejected"
    assert result.reason == "already_mutated_this_cycle"
