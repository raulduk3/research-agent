"""AssistantTurn: the closed turn shape (AG-32)."""

from __future__ import annotations

import pytest

from research_agent.agents.turns import AssistantTurn, validate_core_schema
from research_agent.contracts import ContractValidationError
from research_agent.contracts.turns import PROTECTED_CORE_HASH, PROTECTED_CORE_SCHEMA


def turn(**overrides: object) -> dict[str, object]:
    return {"note": "read the abstract", "intent": "scan", "extension": {}, **overrides}


def test_a_turn_of_exactly_the_closed_shape_is_accepted() -> None:
    parsed = AssistantTurn.parse(turn())
    assert (parsed.note, parsed.intent) == ("read the abstract", "scan")


@pytest.mark.parametrize("extra", ["confidence", "forecast", "tool_calls", "Note"])
def test_every_extra_top_level_field_is_refused(extra: str) -> None:
    with pytest.raises(ContractValidationError):
        AssistantTurn.parse({**turn(), extra: 1})


@pytest.mark.parametrize("missing", ["note", "intent", "extension"])
def test_a_missing_field_is_refused(missing: str) -> None:
    payload = turn()
    del payload[missing]
    with pytest.raises(ContractValidationError):
        AssistantTurn.parse(payload)


@pytest.mark.parametrize("value", [None, [], "scan", 3])
def test_a_turn_that_is_not_an_object_is_refused(value: object) -> None:
    with pytest.raises(ContractValidationError):
        AssistantTurn.parse(value)


def test_the_note_stays_exactly_as_the_model_wrote_it() -> None:
    note = "  é spaced  "
    assert AssistantTurn.parse(turn(note=note)).note == note


def test_the_core_schema_is_the_one_every_configuration_carries() -> None:
    assert validate_core_schema(PROTECTED_CORE_SCHEMA) == PROTECTED_CORE_SCHEMA
    assert len(PROTECTED_CORE_HASH) == 64
