from __future__ import annotations

import pytest

from research_agent.agents.configuration import validate_tools
from research_agent.contracts import ContractValidationError


def test_validate_tools_accepts_the_full_launch_set_in_order() -> None:
    tools = ("query_cards", "neighbors", "graph", "deep_read", "submit")
    assert validate_tools(tools) == tools


def test_validate_tools_accepts_a_strictly_smaller_set() -> None:
    assert validate_tools(("query_cards", "submit")) == ("query_cards", "submit")


def test_validate_tools_rejects_a_sixth_unknown_tool() -> None:
    with pytest.raises(ContractValidationError):
        validate_tools(("query_cards", "browse"))


def test_validate_tools_rejects_duplicates_and_empty() -> None:
    with pytest.raises(ContractValidationError):
        validate_tools(("query_cards", "query_cards"))
    with pytest.raises(ContractValidationError):
        validate_tools(())
