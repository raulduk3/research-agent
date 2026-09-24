"""AgentConfiguration: the strict, hashed launch configuration record (AG-16)."""

from __future__ import annotations

from typing import Any

import pytest

from research_agent.agents.configuration import (
    ASK_EXAMPLES,
    ASK_GUIDANCE,
    ASSEMBLED_PROMPT_MAX_CHARS,
    POLICY_FIELD_MAX_CHARS,
    AgentConfiguration,
)
from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.runs import BUDGET_FIELDS
from research_agent.contracts.tools import ToolRequest

POLICY_PARTS = (
    "prompt",
    "scan_policy",
    "read_policy",
    "probability_assignment_rule",
)


def fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "island": "cs",
        "founder": False,
        "prompt": "read evidence first",
        "scan_policy": "breadth first",
        "read_policy": "cite first",
        "probability_assignment_rule": "one sample",
        "tools": ("query_cards", "neighbors", "graph", "deep_read", "submit"),
        "budgets": {name: 1 for name in BUDGET_FIELDS},
        "sampling": {"count": 1},
        "output_schema": {"note": "string", "intent": "string"},
    }
    base.update(overrides)
    return base


def test_a_complete_configuration_hashes_deterministically() -> None:
    assert (
        AgentConfiguration(**fields()).configuration_hash
        == AgentConfiguration(**fields()).configuration_hash
    )


@pytest.mark.parametrize("missing", sorted(fields()))
def test_every_missing_part_is_refused(missing: str) -> None:
    arguments = fields()
    del arguments[missing]
    with pytest.raises(TypeError):
        AgentConfiguration(**arguments)


@pytest.mark.parametrize("part", POLICY_PARTS)
def test_an_empty_policy_part_is_refused(part: str) -> None:
    with pytest.raises(ContractValidationError):
        AgentConfiguration(**fields(**{part: ""}))


@pytest.mark.parametrize("part", POLICY_PARTS)
def test_a_one_byte_policy_change_changes_the_configuration_hash(part: str) -> None:
    original = AgentConfiguration(**fields())
    changed = AgentConfiguration(**fields(**{part: fields()[part] + "x"}))
    assert changed.configuration_hash != original.configuration_hash


@pytest.mark.parametrize("part", POLICY_PARTS)
def test_policy_text_is_bounded_at_four_thousand_characters(part: str) -> None:
    AgentConfiguration(**fields(**{part: "a" * POLICY_FIELD_MAX_CHARS}))
    with pytest.raises(ContractValidationError, match="exceeds"):
        AgentConfiguration(**fields(**{part: "a" * (POLICY_FIELD_MAX_CHARS + 1)}))


def test_four_full_policy_parts_fill_the_assembled_prompt_bound_exactly() -> None:
    full = "a" * POLICY_FIELD_MAX_CHARS
    configuration = AgentConfiguration(**fields(**dict.fromkeys(POLICY_PARTS, full)))
    assert len("".join(configuration.emphasis.values())) == ASSEMBLED_PROMPT_MAX_CHARS


@pytest.mark.parametrize("count", [0, 2, 3, True, "1", 1.0])
def test_a_sampling_count_other_than_one_is_refused(count: object) -> None:
    with pytest.raises(ContractValidationError, match="sampling"):
        AgentConfiguration(**fields(sampling={"count": count}))


def test_a_sampling_setting_beyond_the_count_is_refused() -> None:
    with pytest.raises(ContractValidationError, match="sampling"):
        AgentConfiguration(**fields(sampling={"count": 1, "temperature": 1}))


def test_budgets_must_name_exactly_the_run_budget_fields() -> None:
    short = {name: 1 for name in sorted(BUDGET_FIELDS)[1:]}
    with pytest.raises(ContractValidationError, match="budgets"):
        AgentConfiguration(**fields(budgets=short))
    extra = {**{name: 1 for name in BUDGET_FIELDS}, "surplus": 1}
    with pytest.raises(ContractValidationError, match="budgets"):
        AgentConfiguration(**fields(budgets=extra))


def test_a_tool_outside_the_fixed_six_is_refused() -> None:
    with pytest.raises(ContractValidationError, match="tool"):
        AgentConfiguration(**fields(tools=("query_cards", "shell")))


def test_a_genome_may_keep_ask_or_narrow_it_away_as_different_genomes() -> None:
    without = AgentConfiguration(**fields())
    with_ask = AgentConfiguration(
        **fields(
            tools=("query_cards", "neighbors", "graph", "deep_read", "ask", "submit"),
            prompt=f"read evidence first\n\n{ASK_GUIDANCE}",
        )
    )
    assert "ask" in with_ask.tools and "ask" not in without.tools
    assert with_ask.configuration_hash != without.configuration_hash


def test_the_ask_guidance_carries_one_admitted_example_per_kind() -> None:
    kinds = [
        ToolRequest.parse("ask", arguments).arguments["kind"]
        for _, arguments in ASK_EXAMPLES
    ]
    assert sorted(kinds) == ["choose", "rate", "yes_no"]
    for situation, arguments in ASK_EXAMPLES:
        assert situation in ASK_GUIDANCE
        assert canonical_json(arguments).decode("utf-8") in ASK_GUIDANCE
    assert len(ASK_GUIDANCE) < POLICY_FIELD_MAX_CHARS


def test_an_unknown_island_is_refused() -> None:
    with pytest.raises(ContractValidationError, match="island"):
        AgentConfiguration(**fields(island="astro-ph"))


def test_the_configuration_hash_is_the_genome_hash_the_population_store_keys_on() -> (
    None
):
    configuration = AgentConfiguration(**fields())
    genome = configuration.to_genome(lineage_id="lineage-1")
    assert genome.configuration_hash == configuration.configuration_hash
    assert genome.infra_hash == configuration.infra_hash
    assert dict(genome.emphasis) == configuration.emphasis


def test_island_changes_the_hash_but_the_founder_flag_does_not() -> None:
    base = AgentConfiguration(**fields())
    assert (
        AgentConfiguration(**fields(island="quant-ph")).configuration_hash
        != base.configuration_hash
    )
    assert (
        AgentConfiguration(**fields(founder=True)).configuration_hash
        == base.configuration_hash
    )


def test_infra_hash_ignores_emphasis_and_follows_every_other_shared_part() -> None:
    base = AgentConfiguration(**fields())
    assert (
        AgentConfiguration(**fields(prompt="something else")).infra_hash
        == base.infra_hash
    )
    assert (
        AgentConfiguration(**fields(tools=("query_cards", "submit"))).infra_hash
        != base.infra_hash
    )
    assert (
        AgentConfiguration(
            **fields(budgets={name: 2 for name in BUDGET_FIELDS})
        ).infra_hash
        != base.infra_hash
    )
    assert (
        AgentConfiguration(**fields(output_schema={"note": "text"})).infra_hash
        != base.infra_hash
    )
