"""The fixed protected core of the agent model's own turns (AG-32 to AG-34).

Every genome's structured output schema is this schema, byte for byte: a
plain-language ``note`` of bounded length, an ``intent`` from a fixed list
and an ``extension`` object that is empty at launch. Tool calls travel in
the API's separate ``tool_calls`` field and forecasts in ``submit``
arguments, so neither appears here.
"""

from __future__ import annotations

from typing import Any

from .canonical import canonical_json, sha256_hex
from .primitives import ContractValidationError

NOTE_MAXIMUM_CHARS = 1000
TURN_INTENTS = ("scan", "compare", "inspect", "forecast", "nominate", "submit", "stop")
SCHEMA_EXTENSION_DISABLED = "disabled_by_profile"


class SchemaExtensionDisabled(ContractValidationError):
    """A nonempty schema extension was offered; none is admitted at launch (AG-34)."""

    reason = SCHEMA_EXTENSION_DISABLED

    def __init__(self, detail: str) -> None:
        super().__init__(f"schema-extension-disabled: {detail}")


EMPTY_EXTENSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

PROTECTED_CORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "note": {"type": "string", "maxLength": NOTE_MAXIMUM_CHARS},
        "intent": {"type": "string", "enum": list(TURN_INTENTS)},
        "extension": EMPTY_EXTENSION_SCHEMA,
    },
    "required": ["note", "intent", "extension"],
    "additionalProperties": False,
}

#: One hash for every configuration, so a change to the core is visible.
PROTECTED_CORE_HASH = sha256_hex(canonical_json(PROTECTED_CORE_SCHEMA))
