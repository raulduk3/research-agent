"""validate_empty_extension: no evolved field at launch (AG-34)."""

from __future__ import annotations

import copy

import pytest

from research_agent.agents.turns import (
    AssistantTurn,
    validate_core_schema,
    validate_empty_extension,
)
from research_agent.contracts import ContractValidationError
from research_agent.contracts.turns import (
    PROTECTED_CORE_SCHEMA,
    SchemaExtensionDisabled,
)

DESCRIBED = {
    "confidence": {
        "type": "number",
        "description": "how sure the agent is",
        "minimum": 0,
    }
}


def test_an_empty_extension_is_accepted() -> None:
    assert validate_empty_extension({}) == {}


@pytest.mark.parametrize(
    "extension",
    [
        DESCRIBED,
        {"surprise": 1},
        {"nested": {"type": "array", "items": {"type": "object", "properties": {}}}},
        {"": None},
    ],
)
def test_a_nonempty_extension_returns_the_disabled_reason(
    extension: dict[str, object],
) -> None:
    with pytest.raises(SchemaExtensionDisabled) as raised:
        validate_empty_extension(extension)
    assert raised.value.reason == "disabled_by_profile"
    assert "schema-extension-disabled" in str(raised.value)


@pytest.mark.parametrize("extension", [None, [], "", 0, [{"a": 1}]])
def test_an_extension_that_is_not_an_object_is_refused(extension: object) -> None:
    with pytest.raises(ContractValidationError):
        validate_empty_extension(extension)


def test_a_turn_with_a_nonempty_extension_is_not_accepted() -> None:
    with pytest.raises(SchemaExtensionDisabled):
        AssistantTurn.parse({"note": "n", "intent": "scan", "extension": DESCRIBED})


def test_a_schema_with_an_extension_field_is_refused_whatever_its_label() -> None:
    schema = copy.deepcopy(PROTECTED_CORE_SCHEMA)
    schema["properties"]["extension"]["properties"] = DESCRIBED
    with pytest.raises(SchemaExtensionDisabled):
        validate_core_schema(schema)


def test_a_schema_with_a_field_beside_the_core_is_refused() -> None:
    schema = copy.deepcopy(PROTECTED_CORE_SCHEMA)
    schema["properties"]["confidence"] = DESCRIBED["confidence"]
    with pytest.raises(SchemaExtensionDisabled):
        validate_core_schema(schema)
