from __future__ import annotations

import pytest

from research_agent.agents.configuration import validate_island
from research_agent.contracts.primitives import ContractValidationError
from research_agent.orchestration.scheduler import ISLANDS
from research_agent.orchestration.slots import ConfigurationLaunch, create_slots


def test_validate_island_admits_each_of_the_three_islands() -> None:
    for island in ISLANDS:
        assert validate_island(island) == island


def test_validate_island_rejects_a_missing_island() -> None:
    with pytest.raises(ContractValidationError):
        validate_island(None)  # type: ignore[arg-type]


def test_validate_island_rejects_an_unknown_island() -> None:
    with pytest.raises(ContractValidationError):
        validate_island("astro-ph")


def _launch(configuration_id: str, configuration_hash: str) -> ConfigurationLaunch:
    return ConfigurationLaunch(
        configuration_id=configuration_id,
        configuration_hash=configuration_hash,
        seed=1,
        snapshot_hash="a" * 64,
        model_deployment="b" * 64,
        loop_image="c" * 64,
        budgets={"model_calls": 16},
        tool_schema_manifest="d" * 64,
    )


def test_a_slot_set_over_a_three_island_batch_never_holds_a_foreign_paper() -> None:
    # AG-36's paper/island pairing is enforced by calling create_slots once
    # per island with only that island's papers -- a slot's paper and its
    # configuration are always drawn from the same call, so no configuration
    # can hold a paper of another island. This test documents that
    # invariant across all three islands built the same way.
    batch_id = "e" * 64
    island_papers = {
        "cs": ("cs-paper-1", "cs-paper-2"),
        "quant-ph": ("quant-ph-paper-1",),
        "q-bio": ("q-bio-paper-1", "q-bio-paper-2"),
    }
    island_configurations = {
        "cs": [_launch("123e4567-e89b-42d3-a456-426614174000", "1" * 64)],
        "quant-ph": [_launch("123e4567-e89b-42d3-a456-426614174001", "2" * 64)],
        "q-bio": [_launch("123e4567-e89b-42d3-a456-426614174002", "3" * 64)],
    }
    slots_by_island = {
        island: create_slots(batch_id, papers, island_configurations[island])
        for island, papers in island_papers.items()
    }
    for island, slots in slots_by_island.items():
        allowed_papers = set(island_papers[island])
        assert {slot.slot.paper_id for slot in slots} <= allowed_papers
