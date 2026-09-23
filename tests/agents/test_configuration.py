"""validate_seeded_population: the twelve-configuration seed boundary (AG-03)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from research_agent.agents.configuration import (
    SEED_POPULATION_COUNT,
    AgentConfiguration,
    validate_seeded_population,
    verify_configuration_digest,
)
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.runs import BUDGET_FIELDS

ISLAND_NAMES = ("cs", "quant-ph", "q-bio")
EMPHASES = ("evidence-first", "breadth-first", "citation-first", "skeptic")


def configuration(island: str, index: int, **overrides: Any) -> AgentConfiguration:
    arguments: dict[str, Any] = {
        "island": island,
        "founder": index == 0,
        "prompt": EMPHASES[index],
        "scan_policy": "scan",
        "read_policy": "read",
        "probability_assignment_rule": "one sample",
        "tools": ("query_cards", "neighbors", "graph", "deep_read", "submit"),
        "budgets": {name: 1 for name in BUDGET_FIELDS},
        "sampling": {"count": 1},
        "output_schema": {"note": "string"},
    }
    arguments.update(overrides)
    return AgentConfiguration(**arguments)


def seed() -> list[AgentConfiguration]:
    return [
        configuration(island, index) for island in ISLAND_NAMES for index in range(4)
    ]


def test_a_valid_three_island_seed_with_one_founder_per_island_is_admitted() -> None:
    admitted = validate_seeded_population(seed())
    assert len(admitted) == SEED_POPULATION_COUNT
    assert sum(member.founder for member in admitted) == 3


@pytest.mark.parametrize("size", [0, 11, 13])
def test_a_seed_that_is_not_twelve_configurations_is_refused(size: int) -> None:
    members = seed()
    members = members[:size] if size < 12 else members + [configuration("cs", 3)]
    with pytest.raises(ContractValidationError, match="exactly"):
        validate_seeded_population(members)


def test_an_island_lacking_a_founder_is_refused() -> None:
    members = seed()
    members[0] = replace(members[0], founder=False)
    with pytest.raises(ContractValidationError, match="founder"):
        validate_seeded_population(members)


def test_an_island_with_two_founders_is_refused() -> None:
    members = seed()
    members[1] = replace(members[1], founder=True)
    with pytest.raises(ContractValidationError, match="founder"):
        validate_seeded_population(members)


def test_an_uneven_split_of_twelve_across_islands_is_refused() -> None:
    members = seed()
    members[7] = configuration("cs", 3, prompt="another emphasis")
    with pytest.raises(ContractValidationError, match="island"):
        validate_seeded_population(members)


@pytest.mark.parametrize(
    "override",
    [
        {"tools": ("query_cards", "submit")},
        {"budgets": {name: 2 for name in BUDGET_FIELDS}},
        {"output_schema": {"note": "text"}},
    ],
    ids=["tools", "budgets", "schema"],
)
def test_a_per_member_change_to_a_shared_component_is_refused(
    override: dict[str, Any],
) -> None:
    members = seed()
    members[5] = configuration("quant-ph", 1, **override)
    with pytest.raises(ContractValidationError, match="common infrastructure"):
        validate_seeded_population(members)


def test_a_repeated_configuration_is_refused() -> None:
    members = seed()
    members[1] = configuration("cs", 1, prompt=EMPHASES[2])
    members[2] = configuration("cs", 2)
    with pytest.raises(ContractValidationError, match="repeat"):
        validate_seeded_population(members)


def test_a_non_configuration_entry_is_refused() -> None:
    members: list[Any] = seed()
    members[3] = {"island": "cs"}
    with pytest.raises(ContractValidationError, match="AgentConfiguration"):
        validate_seeded_population(members)


def test_a_mounted_configuration_verifies_only_against_its_own_sealed_digest() -> None:
    sealed = configuration("cs", 0)
    assert verify_configuration_digest(sealed, sealed.configuration_hash)
    assert not verify_configuration_digest(
        replace(sealed, prompt="edited"), sealed.configuration_hash
    )
    assert not verify_configuration_digest(
        replace(sealed, tools=("submit",)), sealed.configuration_hash
    )
