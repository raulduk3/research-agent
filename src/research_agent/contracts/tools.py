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
(AG-36): a call is refused whole when either is missing, invalid or out of
bound, before ``ToolRequest`` reads the tool's own domain arguments.
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
from .submissions import parse_claims

TOOL_NAMES = frozenset({"query_cards", "neighbors", "graph", "deep_read", "submit"})
SEARCH_MODES = frozenset({"overview", "passages"})
GRAPH_DIRECTIONS = frozenset({"references", "citations"})
INTENT_VALUES = frozenset({"scan", "read", "compare", "decide"})

_QUERY_TEXT_MAXIMUM_CHARS = 2048
_NOTE_MAXIMUM_WORDS = 60


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

    Shared by the tool call's own note (AG-36) and submit's per-claim
    rationale (AG-37): both are plain-language text a person reads, bounded
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
    args = _closed(
        value, {"paper_ids", "query", "mode", "paper_id", "limit"}, "query_cards"
    )
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
                _bounded_paper_ids(args["paper_ids"], 1, 5, "paper_ids")
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
        "limit": _limit(args["limit"], 5, 5, "limit"),
    }


def _parse_neighbors(value: object) -> dict[str, Any]:
    args = _closed(value, {"paper_id", "limit"}, "neighbors")
    return {
        "paper_id": validate_uuid4(args["paper_id"]),
        "limit": _limit(args["limit"], 5, 5, "limit"),
    }


def _parse_graph(value: object) -> dict[str, Any]:
    args = _closed(value, {"paper_id", "direction", "limit"}, "graph")
    direction = args["direction"] if args["direction"] is not None else "references"
    if direction not in GRAPH_DIRECTIONS:
        raise ContractValidationError("direction is not an admitted value")
    return {
        "paper_id": validate_uuid4(args["paper_id"]),
        "direction": direction,
        "limit": _limit(args["limit"], 20, 20, "limit"),
    }


def _pages(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 2:
        raise ContractValidationError("pages must be a JSON array with 1 to 2 items")
    pages = [validate_positive_int(item) for item in value]
    if pages != sorted(set(pages)):
        raise ContractValidationError("pages must be strictly ascending and distinct")
    return tuple(pages)


def _parse_deep_read(value: object) -> dict[str, Any]:
    args = _closed(value, {"paper_id", "section_id", "pages", "next_span"}, "deep_read")
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
    args = _closed(value, {"claims"}, "submit")
    return {"claims": parse_claims(args["claims"])}


_PARSERS = {
    "query_cards": _parse_query_cards,
    "neighbors": _parse_neighbors,
    "graph": _parse_graph,
    "deep_read": _parse_deep_read,
    "submit": _parse_submit,
}


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
    strictly validated domain arguments of :class:`ToolRequest` (AG-36).

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

        envelope = _closed(raw_call, {"note", "intent", "arguments"}, "tool call")
        note = _note(envelope["note"])
        intent = _intent(envelope["intent"])
        request = ToolRequest.parse(tool, envelope["arguments"])
        return cls(tool=tool, note=note, intent=intent, arguments=request.arguments)
