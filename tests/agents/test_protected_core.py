"""validate_protected_core: the note and intent no genome may alter (AG-33)."""

from __future__ import annotations

import copy

import pytest

from research_agent.agents.turns import validate_core_schema, validate_protected_core
from research_agent.contracts import ContractValidationError
from research_agent.contracts.turns import (
    NOTE_MAXIMUM_CHARS,
    PROTECTED_CORE_SCHEMA,
    TURN_INTENTS,
)


def test_every_listed_intent_is_accepted() -> None:
    for intent in TURN_INTENTS:
        assert validate_protected_core({"note": "n", "intent": intent}) == ("n", intent)


@pytest.mark.parametrize("intent", ["read", "decide", "SCAN", "", None, 1, ["scan"]])
def test_an_intent_outside_the_fixed_list_is_refused(intent: object) -> None:
    with pytest.raises(ContractValidationError):
        validate_protected_core({"note": "n", "intent": intent})


def test_a_missing_intent_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        validate_protected_core({"note": "n"})


def test_a_missing_or_non_string_note_is_refused() -> None:
    for note in (None, 5, b"n", ["n"]):
        with pytest.raises(ContractValidationError):
            validate_protected_core({"note": note, "intent": "scan"})
    with pytest.raises(ContractValidationError):
        validate_protected_core({"intent": "scan"})


def test_the_note_limit_counts_characters_not_bytes() -> None:
    at_limit = "é" * NOTE_MAXIMUM_CHARS  # 2000 UTF-8 bytes
    assert validate_protected_core({"note": at_limit, "intent": "scan"})[0] == at_limit
    with pytest.raises(ContractValidationError):
        validate_protected_core({"note": at_limit + "a", "intent": "scan"})
    with pytest.raises(ContractValidationError):
        validate_protected_core(
            {"note": "中" * (NOTE_MAXIMUM_CHARS + 1), "intent": "scan"}
        )


def test_a_note_that_is_not_valid_utf8_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        validate_protected_core({"note": "bad \ud800", "intent": "scan"})


def test_the_turn_must_be_an_object() -> None:
    with pytest.raises(ContractValidationError):
        validate_protected_core("scan")


def _mutations() -> list[dict[str, object]]:
    out = []
    for path, value in [
        (("properties", "note", "maxLength"), 2000),
        (("properties", "note", "type"), "integer"),
        (("properties", "intent", "enum"), ["scan"]),
        (("properties", "intent", "enum"), [*TURN_INTENTS, "decide"]),
        (("required",), ["intent", "extension"]),
        (("additionalProperties",), True),
    ]:
        schema = copy.deepcopy(PROTECTED_CORE_SCHEMA)
        target = schema
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        out.append(schema)
    removed = copy.deepcopy(PROTECTED_CORE_SCHEMA)
    del removed["properties"]["note"]
    out.append(removed)
    return out


@pytest.mark.parametrize("schema", _mutations())
def test_a_schema_that_alters_a_protected_field_is_refused(schema: object) -> None:
    with pytest.raises(ContractValidationError):
        validate_core_schema(schema)


def test_a_schema_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        validate_core_schema("core")
