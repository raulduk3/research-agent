"""Strict wire contracts for the five agent tools' domain arguments (AG-11).

Only the model-supplied domain arguments live here. The trusted harness adds
``schema_version``, ``run_id``, ``snapshot_id`` and ``tool_call_id`` to the
internal envelope from its own immutable context (TDD-3.1.51); a caller
cannot override those fields through a tool call, so they are validated
separately from ``ToolRequest``. Every argument object is closed: every
field named below must be present, with an unused optional field set to
JSON ``null`` rather than omitted, so an extra or missing key is rejected
before any handler runs.

``ToolCall`` wraps ``ToolRequest`` in the model's own note and intent
(AG-39): a call is refused whole when either is missing, invalid or out of
bound, before ``ToolRequest`` reads the tool's own domain arguments.
``call_envelope`` is that first step alone, which admission runs on every
call before it parses the arguments it returns.

A ``deep_read`` or ``graph`` naming a family the run's snapshot does not
hold answers ``not_in_snapshot`` with a paper-request receipt instead of
domain data (decision 0025): ``requested`` when storage recorded a new
request, ``already_requested`` when the family already has one, and
``request_budget_exhausted`` once the run has made
``PAPER_REQUESTS_PER_RUN`` requests.

``TOOL_SCHEMAS`` is the same five parsers rendered as the function schemas
the agent model is declared with, each the ``{note, intent, arguments}``
envelope ``ToolCall`` parses. Each schema's ``arguments`` properties are the
field set its parser closes over, and its enums and bounds are the constants
the parser checks, so a parser change is a schema change. What a JSON
schema cannot state (exactly one of a mutually exclusive set, ascending
pages, NFC text, a note's word bound) is said in the description and still
enforced here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_positive_int,
    validate_uuid4,
)
from .submissions import parse_submit_args

TOOL_NAMES = frozenset({"query_cards", "neighbors", "graph", "deep_read", "submit"})
SEARCH_MODES = frozenset({"overview", "passages"})
GRAPH_DIRECTIONS = frozenset({"references", "citations"})
INTENT_VALUES = frozenset({"scan", "read", "compare", "decide"})
PAPER_REQUEST_TOOLS = frozenset({"deep_read", "graph"})
PAPER_REQUEST_OUTCOMES = frozenset(
    {"requested", "already_requested", "request_budget_exhausted"}
)
PAPER_REQUESTS_PER_RUN = 3

_QUERY_TEXT_MAXIMUM_CHARS = 2048
_NOTE_MAXIMUM_WORDS = 60

_LOOKUP_IDS_MAXIMUM = 5
_SEARCH_LIMIT_MAXIMUM = 5
_NEIGHBORS_LIMIT_MAXIMUM = 5
_GRAPH_LIMIT_MAXIMUM = 20
_PAGES_MAXIMUM = 2

# The submit parser lives in ``submissions.py``; these mirror its bounds for
# the schema, and tests/contracts/test_tools.py holds the two together.
_SUBMIT_ANSWERS_MAXIMUM = 5
_SUBMIT_EVIDENCE_MAXIMUM = 5
_SUBMIT_RATIONALE_MAXIMUM_CHARS = 2000
_SUBMIT_PAPER_ID_MAXIMUM_CHARS = 128

_UUID4_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
_SHA256_PATTERN = "^[0-9a-f]{64}$"


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    kind = schema["type"]
    return {**schema, "type": [kind, "null"]}


def _uuid4() -> dict[str, Any]:
    return {"type": "string", "pattern": _UUID4_PATTERN}


def _limit_schema(upper: int) -> dict[str, Any]:
    return _nullable({"type": "integer", "minimum": 1, "maximum": upper})


def _object(properties: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _probability() -> dict[str, Any]:
    return {"type": "number", "minimum": 0, "maximum": 1}


def _rationale() -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": _SUBMIT_RATIONALE_MAXIMUM_CHARS,
    }


_PROPERTIES: dict[str, dict[str, dict[str, Any]]] = {
    "query_cards": {
        "paper_ids": _nullable(
            {
                "type": "array",
                "items": _uuid4(),
                "minItems": 1,
                "maxItems": _LOOKUP_IDS_MAXIMUM,
                "uniqueItems": True,
            }
        ),
        "query": _nullable(
            {
                "type": "string",
                "minLength": 1,
                "maxLength": _QUERY_TEXT_MAXIMUM_CHARS,
            }
        ),
        "mode": {"type": ["string", "null"], "enum": [*sorted(SEARCH_MODES), None]},
        "paper_id": _nullable(_uuid4()),
        "limit": _limit_schema(_SEARCH_LIMIT_MAXIMUM),
    },
    "neighbors": {
        "paper_id": _uuid4(),
        "limit": _limit_schema(_NEIGHBORS_LIMIT_MAXIMUM),
    },
    "graph": {
        "paper_id": _uuid4(),
        "direction": {
            "type": ["string", "null"],
            "enum": [*sorted(GRAPH_DIRECTIONS), None],
        },
        "limit": _limit_schema(_GRAPH_LIMIT_MAXIMUM),
    },
    "deep_read": {
        "paper_id": _uuid4(),
        "section_id": _nullable({"type": "string", "minLength": 1}),
        "pages": _nullable(
            {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "minItems": 1,
                "maxItems": _PAGES_MAXIMUM,
                "uniqueItems": True,
            }
        ),
        "next_span": _nullable({"type": "string", "minLength": 1}),
    },
    "submit": {
        "submission_id": _uuid4(),
        "answers": {
            "type": "array",
            "items": _object(
                {
                    "question_id": _uuid4(),
                    "probability": _probability(),
                    "rationale": _rationale(),
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string", "pattern": _SHA256_PATTERN},
                        "minItems": 1,
                        "maxItems": _SUBMIT_EVIDENCE_MAXIMUM,
                        "uniqueItems": True,
                    },
                }
            ),
            "minItems": 0,
            "maxItems": _SUBMIT_ANSWERS_MAXIMUM,
        },
        "nomination": _object(
            {
                "paper_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": _SUBMIT_PAPER_ID_MAXIMUM_CHARS,
                },
                "recommend": {"type": "boolean"},
                "preference": _probability(),
                "rationale": _rationale(),
            }
        ),
    },
}

_NOTE_DESCRIPTION = (
    f"A plain-language note of at most {_NOTE_MAXIMUM_WORDS} words on why "
    "this call is made."
)

_DESCRIPTIONS = {
    "query_cards": (
        "Read paper cards from the run's snapshot. Give exactly one of "
        "paper_ids (a lookup; mode, paper_id and limit are then null) or "
        "query (a search, optionally within one paper_id). Unused fields are null."
    ),
    "neighbors": "List a snapshot paper's nearest neighbors by embedding distance.",
    "graph": (
        "List a snapshot paper's citation edges: references (the default) or citations."
    ),
    "deep_read": (
        "Read a bounded span of one snapshot paper. Give exactly one of "
        "section_id, pages (one or two ascending page numbers) or next_span "
        "(the cursor a previous read returned); the others are null."
    ),
    "submit": (
        "Submit the run's answers, one per issued question with a probability, "
        "rationale and evidence ids, and its one nomination for its own paper. "
        "The first accepted submit ends the run."
    ),
}


def _fields(tool: str) -> set[str]:
    return set(_PROPERTIES[tool])


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _bounded_paper_ids(value: object, lower: int, upper: int, name: str) -> list[str]:
    if not isinstance(value, list) or not lower <= len(value) <= upper:
        raise ContractValidationError(
            f"{name} must be a JSON array with {lower} to {upper} items"
        )
    ids = [validate_uuid4(item) for item in value]
    if len(set(ids)) != len(ids):
        raise ContractValidationError(f"{name} must be distinct")
    return ids


def _optional_uuid4(value: object, name: str) -> str | None:
    if value is None:
        return None
    return validate_uuid4(value)


def _limit(value: object, upper: int, default: int, name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
        raise ContractValidationError(f"{name} must be an integer from 1 to {upper}")
    return value


def _query_text(value: object) -> str:
    text = validate_non_empty_string(value)
    if len(text) > _QUERY_TEXT_MAXIMUM_CHARS:
        raise ContractValidationError("query text is too long")
    return text


def bounded_word_text(value: object, max_words: int, name: str) -> str:
    """A nonempty NFC string of at most *max_words* whitespace-split words.

    Shared by the tool call's own note (AG-39) and submit's per-claim
    rationale (AG-40): both are plain-language text a person reads, bounded
    by a configured word count rather than the raw character counts other
    fields use, since a word bound reads naturally as "write a short note."
    """

    text = validate_non_empty_string(value)
    if len(text.split()) > max_words:
        raise ContractValidationError(f"{name} exceeds its bound")
    return text


def _note(value: object) -> str:
    return bounded_word_text(value, _NOTE_MAXIMUM_WORDS, "note")


def _intent(value: object) -> str:
    if not isinstance(value, str) or value not in INTENT_VALUES:
        raise ContractValidationError("intent is not an admitted value")
    return value


def _parse_query_cards(value: object) -> dict[str, Any]:
    args = _closed(value, _fields("query_cards"), "query_cards")
    has_ids = args["paper_ids"] is not None
    has_query = args["query"] is not None
    if has_ids == has_query:
        raise ContractValidationError(
            "query_cards takes exactly one of paper_ids or query"
        )
    if has_ids:
        if (
            args["mode"] is not None
            or args["paper_id"] is not None
            or args["limit"] is not None
        ):
            raise ContractValidationError("a paper_ids lookup needs no query fields")
        return {
            "kind": "lookup",
            "paper_ids": tuple(
                _bounded_paper_ids(
                    args["paper_ids"], 1, _LOOKUP_IDS_MAXIMUM, "paper_ids"
                )
            ),
        }
    mode = args["mode"] if args["mode"] is not None else "overview"
    if mode not in SEARCH_MODES:
        raise ContractValidationError("mode is not an admitted value")
    return {
        "kind": "search",
        "query": _query_text(args["query"]),
        "mode": mode,
        "paper_id": _optional_uuid4(args["paper_id"], "paper_id"),
        "limit": _limit(
            args["limit"], _SEARCH_LIMIT_MAXIMUM, _SEARCH_LIMIT_MAXIMUM, "limit"
        ),
    }


def _parse_neighbors(value: object) -> dict[str, Any]:
    args = _closed(value, _fields("neighbors"), "neighbors")
    return {
        "paper_id": validate_uuid4(args["paper_id"]),
        "limit": _limit(
            args["limit"], _NEIGHBORS_LIMIT_MAXIMUM, _NEIGHBORS_LIMIT_MAXIMUM, "limit"
        ),
    }


def _parse_graph(value: object) -> dict[str, Any]:
    args = _closed(value, _fields("graph"), "graph")
    direction = args["direction"] if args["direction"] is not None else "references"
    if direction not in GRAPH_DIRECTIONS:
        raise ContractValidationError("direction is not an admitted value")
    return {
        "paper_id": validate_uuid4(args["paper_id"]),
        "direction": direction,
        "limit": _limit(
            args["limit"], _GRAPH_LIMIT_MAXIMUM, _GRAPH_LIMIT_MAXIMUM, "limit"
        ),
    }


def _pages(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= _PAGES_MAXIMUM:
        raise ContractValidationError(
            f"pages must be a JSON array with 1 to {_PAGES_MAXIMUM} items"
        )
    pages = [validate_positive_int(item) for item in value]
    if pages != sorted(set(pages)):
        raise ContractValidationError("pages must be strictly ascending and distinct")
    return tuple(pages)


def _parse_deep_read(value: object) -> dict[str, Any]:
    args = _closed(value, _fields("deep_read"), "deep_read")
    variants = (args["section_id"], args["pages"], args["next_span"])
    if sum(variant is not None for variant in variants) != 1:
        raise ContractValidationError(
            "deep_read takes exactly one of section_id, pages or next_span"
        )
    paper_id = validate_uuid4(args["paper_id"])
    if args["section_id"] is not None:
        return {
            "paper_id": paper_id,
            "kind": "section",
            "section_id": validate_non_empty_string(args["section_id"]),
        }
    if args["pages"] is not None:
        return {"paper_id": paper_id, "kind": "pages", "pages": _pages(args["pages"])}
    return {
        "paper_id": paper_id,
        "kind": "next_span",
        "next_span": validate_non_empty_string(args["next_span"]),
    }


def _parse_submit(value: object) -> dict[str, Any]:
    return parse_submit_args(value)


_PARSERS = {
    "query_cards": _parse_query_cards,
    "neighbors": _parse_neighbors,
    "graph": _parse_graph,
    "deep_read": _parse_deep_read,
    "submit": _parse_submit,
}


def _envelope_schema(tool: str) -> dict[str, Any]:
    return _object(
        {
            "note": {
                "type": "string",
                "minLength": 1,
                "description": _NOTE_DESCRIPTION,
            },
            "intent": {"type": "string", "enum": sorted(INTENT_VALUES)},
            "arguments": _object(_PROPERTIES[tool]),
        }
    )


#: The five tools as the function schemas the agent model is declared with,
#: in the fixed order of AG-09, each declaring the note and intent envelope
#: of AG-39 around the tool's own arguments.
TOOL_SCHEMAS: tuple[dict[str, Any], ...] = tuple(
    {
        "name": tool,
        "description": _DESCRIPTIONS[tool],
        "parameters": _envelope_schema(tool),
    }
    for tool in ("query_cards", "neighbors", "graph", "deep_read", "submit")
)


def call_envelope(raw_call: object) -> tuple[str, str, object]:
    """Check *raw_call*'s envelope and return its note, intent and arguments.

    The arguments are returned unread, for the tool's own parser. Raises
    ``ContractValidationError`` for a missing or extra envelope field, a
    note that is empty or over its bound, or an intent outside the fixed
    list (AG-39).
    """

    envelope = _closed(raw_call, {"note", "intent", "arguments"}, "tool call")
    return _note(envelope["note"]), _intent(envelope["intent"]), envelope["arguments"]


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """One tool call's name and strictly validated domain arguments (AG-11)."""

    tool: str
    arguments: Mapping[str, Any]

    @classmethod
    def parse(cls, tool: str, raw_arguments: object) -> "ToolRequest":
        """Validate *raw_arguments* for *tool*, or raise ``ContractValidationError``.

        Coercion is never applied: a boolean where an integer is expected, an
        extra or missing field, or both variants of a mutually exclusive pair
        all fail here rather than being narrowed silently. Callers execute no
        handler when this raises.
        """

        if tool not in TOOL_NAMES:
            raise ContractValidationError("tool is not an admitted name")
        return cls(tool, _PARSERS[tool](raw_arguments))


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool call's full envelope: its own note and intent beside the
    strictly validated domain arguments of :class:`ToolRequest` (AG-39).

    A call is refused whole, before its domain arguments are read, when the
    note or the intent is missing or invalid -- the same all-or-nothing rule
    :class:`ToolRequest` already applies to a tool's own arguments (AG-11).
    """

    tool: str
    note: str
    intent: str
    arguments: Mapping[str, Any]

    @classmethod
    def parse(cls, tool: str, raw_call: object) -> "ToolCall":
        """Validate *raw_call* as ``{note, intent, arguments}`` for *tool*.

        Raises ``ContractValidationError`` for a missing or extra envelope
        field, an invalid note or intent, or any failure of the tool's own
        domain arguments (AG-11). Callers execute no handler when this
        raises.
        """

        note, intent, raw_arguments = call_envelope(raw_call)
        request = ToolRequest.parse(tool, raw_arguments)
        return cls(tool=tool, note=note, intent=intent, arguments=request.arguments)


def not_in_snapshot_answer(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """The ``deep_read``/``graph`` answer for a family the snapshot lacks.

    *receipt* is storage's answer to recording the paper request:
    ``family_id``, ``outcome`` and ``request_id``, the last ``None`` only
    when the run's request budget refused the request. The answer carries
    the receipt whole, so the run's trace records the outcome and replay
    returns it unchanged.
    """

    if not isinstance(receipt, Mapping) or not {
        "family_id",
        "outcome",
        "request_id",
    } <= set(receipt):
        raise ContractValidationError("paper request receipt is missing fields")
    outcome = receipt["outcome"]
    if not isinstance(outcome, str) or outcome not in PAPER_REQUEST_OUTCOMES:
        raise ContractValidationError("paper request outcome is not admitted")
    exhausted = outcome == "request_budget_exhausted"
    request_id = receipt["request_id"]
    if exhausted != (request_id is None):
        raise ContractValidationError(
            "only an exhausted request budget answers without a request id"
        )
    return {
        "kind": "not_in_snapshot",
        "paper_id": validate_uuid4(receipt["family_id"]),
        "request": {
            "outcome": outcome,
            "request_id": None if exhausted else validate_uuid4(request_id),
        },
    }
