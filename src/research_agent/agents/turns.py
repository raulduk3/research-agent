"""The agent model's own turn: protected core and empty extension (AG-32 to AG-34)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.turns import (
    NOTE_MAXIMUM_CHARS,
    PROTECTED_CORE_SCHEMA,
    TURN_INTENTS,
    SchemaExtensionDisabled,
)

_TURN_FIELDS = frozenset({"note", "intent", "extension"})


def validate_empty_extension(extension: object) -> dict[str, Any]:
    """An extension is an object with zero properties, whatever a field is labeled (AG-34)."""
    if not isinstance(extension, Mapping):
        raise ContractValidationError("extension must be a JSON object")
    if extension:
        raise SchemaExtensionDisabled("the launch extension admits no field")
    return {}


def validate_protected_core(turn: object) -> tuple[str, str]:
    """Return a turn's note and intent, refusing any that break the fixed core (AG-33).

    The note is kept exactly as the model wrote it: it is checked, never
    normalized.
    """
    if not isinstance(turn, Mapping):
        raise ContractValidationError("turn must be a JSON object")
    note = turn.get("note")
    if not isinstance(note, str):
        raise ContractValidationError("note must be a string")
    try:
        note.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ContractValidationError("note must be valid UTF-8 text") from error
    if len(note) > NOTE_MAXIMUM_CHARS:
        raise ContractValidationError(f"note exceeds {NOTE_MAXIMUM_CHARS} characters")
    intent = turn.get("intent")
    if not isinstance(intent, str) or intent not in TURN_INTENTS:
        raise ContractValidationError("intent is not in the fixed list")
    return note, intent


def validate_core_schema(schema: object) -> dict[str, Any]:
    """A structured output schema is the protected core, with no evolved field (AG-32, AG-33)."""
    if not isinstance(schema, Mapping):
        raise ContractValidationError("structured output schema must be a JSON object")
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        if set(properties) - _TURN_FIELDS:
            raise SchemaExtensionDisabled("a field beside the protected core")
        extension = properties.get("extension")
        if isinstance(extension, Mapping) and extension.get("properties"):
            raise SchemaExtensionDisabled("the launch extension admits no field")
    if dict(schema) != PROTECTED_CORE_SCHEMA:
        raise ContractValidationError(
            "structured output schema differs from the protected core"
        )
    return dict(schema)


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    """The protected assistant content: ``{note, intent, extension: {}}`` (AG-32)."""

    note: str
    intent: str

    @classmethod
    def parse(cls, value: object) -> AssistantTurn:
        if not isinstance(value, dict) or set(value) != _TURN_FIELDS:
            raise ContractValidationError("turn has unknown or missing fields")
        note, intent = validate_protected_core(value)
        validate_empty_extension(value["extension"])
        return cls(note=note, intent=intent)
