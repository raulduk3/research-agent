"""The declared tool schemas and the strict parsers are one contract (AG-11).

A valid call round-trips through both. Every schema field is one the
parser closes over, every enum value and integer bound the schema
declares is the one the parser admits, so a parser change that the
schema does not follow fails here.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.tools import TOOL_NAMES, TOOL_SCHEMAS, ToolRequest

PAPER_ID = "0b4b8f5e-3f7a-4c2d-9a1e-6d2c7b9e8f10"
QUESTION_ID = "5c2e1d4a-8b3f-4e6a-a9c7-1f0e2d3b4a5c"
SUBMISSION_ID = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b"
EVIDENCE = "e" * 64

VALID_CALLS: dict[str, list[dict[str, Any]]] = {
    "query_cards": [
        {
            "paper_ids": [PAPER_ID],
            "query": None,
            "mode": None,
            "paper_id": None,
            "limit": None,
        },
        {
            "paper_ids": None,
            "query": "sparse attention",
            "mode": "passages",
            "paper_id": PAPER_ID,
            "limit": 5,
        },
    ],
    "neighbors": [{"paper_id": PAPER_ID, "limit": 3}],
    "graph": [{"paper_id": PAPER_ID, "direction": "citations", "limit": 20}],
    "deep_read": [
        {
            "paper_id": PAPER_ID,
            "section_id": "results",
            "pages": None,
            "next_span": None,
        },
        {"paper_id": PAPER_ID, "section_id": None, "pages": [3, 4], "next_span": None},
    ],
    "submit": [
        {
            "submission_id": SUBMISSION_ID,
            "answers": [
                {
                    "question_id": QUESTION_ID,
                    "probability": 0.4,
                    "rationale": "The results section reports the gain.",
                    "evidence_ids": [EVIDENCE],
                }
            ],
            "nomination": {
                "paper_id": PAPER_ID,
                "recommend": True,
                "preference": 0.7,
                "rationale": "A clear result a reader would want.",
            },
        }
    ],
}


def _types(value: Any) -> set[str]:
    if value is None:
        return {"null"}
    if isinstance(value, bool):
        return {"boolean"}
    if isinstance(value, int):
        return {"integer", "number"}
    if isinstance(value, float):
        return {"number"}
    if isinstance(value, str):
        return {"string"}
    if isinstance(value, list):
        return {"array"}
    return {"object"}


def _conforms(value: Any, schema: dict[str, Any]) -> bool:
    """The subset of JSON Schema the declared tool schemas use."""

    declared = schema["type"]
    allowed = {declared} if isinstance(declared, str) else set(declared)
    if not _types(value) & allowed:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return False
        if len(value) > schema.get("maxLength", len(value)):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            return False
    if isinstance(value, list):
        if (
            not schema.get("minItems", 0)
            <= len(value)
            <= schema.get("maxItems", len(value))
        ):
            return False
        if schema.get("uniqueItems") and len(
            {json.dumps(item, sort_keys=True) for item in value}
        ) != len(value):
            return False
        return all(_conforms(item, schema["items"]) for item in value)
    if isinstance(value, dict):
        properties = schema["properties"]
        if set(value) != set(schema["required"]) or set(value) - set(properties):
            return False
        return all(_conforms(value[key], properties[key]) for key in value)
    return True


def _schema(tool: str) -> dict[str, Any]:
    (schema,) = [entry for entry in TOOL_SCHEMAS if entry["name"] == tool]
    return schema


def _refused(tool: str, arguments: object) -> bool:
    try:
        ToolRequest.parse(tool, arguments)
    except ContractValidationError:
        return True
    return False


def test_every_admitted_tool_has_exactly_one_schema() -> None:
    names = [schema["name"] for schema in TOOL_SCHEMAS]
    assert sorted(names) == sorted(TOOL_NAMES)
    assert len(names) == len(set(names))


def test_every_schema_is_closed_and_requires_every_field() -> None:
    for schema in TOOL_SCHEMAS:
        parameters = schema["parameters"]
        assert parameters["additionalProperties"] is False
        assert set(parameters["required"]) == set(parameters["properties"])
        assert schema["description"]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [(tool, call) for tool, calls in VALID_CALLS.items() for call in calls],
)
def test_a_valid_call_round_trips_through_schema_and_parser(
    tool: str, arguments: dict[str, Any]
) -> None:
    wire = json.loads(json.dumps(arguments))
    assert _conforms(wire, _schema(tool)["parameters"])
    ToolRequest.parse(tool, wire)


@pytest.mark.parametrize("tool", sorted(VALID_CALLS))
def test_the_parser_closes_over_exactly_the_schema_fields(tool: str) -> None:
    call = VALID_CALLS[tool][0]
    for field in _schema(tool)["parameters"]["properties"]:
        missing = {key: value for key, value in call.items() if key != field}
        assert _refused(tool, missing), f"{tool} admitted a call without {field}"
    assert _refused(tool, {**call, "undeclared": None})


def _bounded_integers(
    schema: dict[str, Any], path: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], int]]:
    found = []
    for key, prop in schema.get("properties", {}).items():
        types = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
        if "integer" in types and "maximum" in prop:
            found.append(((*path, key), prop["maximum"]))
    return found


@pytest.mark.parametrize("tool", ["query_cards", "neighbors", "graph"])
def test_the_parser_admits_the_schema_maximum_and_refuses_one_past_it(
    tool: str,
) -> None:
    call = VALID_CALLS[tool][-1]
    bounds = _bounded_integers(_schema(tool)["parameters"])
    assert bounds
    for (field,), maximum in bounds:
        ToolRequest.parse(tool, {**call, field: maximum})
        assert _refused(tool, {**call, field: maximum + 1})
        assert _refused(tool, {**call, field: 0})


@pytest.mark.parametrize(
    ("tool", "field"), [("query_cards", "mode"), ("graph", "direction")]
)
def test_the_parser_admits_exactly_the_schema_enum(tool: str, field: str) -> None:
    call = VALID_CALLS[tool][-1]
    for value in _schema(tool)["parameters"]["properties"][field]["enum"]:
        ToolRequest.parse(tool, {**call, field: value})
    assert _refused(tool, {**call, field: "undeclared"})


def test_the_parser_follows_the_schema_array_bounds() -> None:
    properties = _schema("query_cards")["parameters"]["properties"]
    maximum = properties["paper_ids"]["maxItems"]
    ids = [f"{index:08x}-3f7a-4c2d-9a1e-6d2c7b9e8f10" for index in range(maximum + 1)]
    call = VALID_CALLS["query_cards"][0]
    ToolRequest.parse("query_cards", {**call, "paper_ids": ids[:maximum]})
    assert _refused("query_cards", {**call, "paper_ids": ids})

    pages_maximum = _schema("deep_read")["parameters"]["properties"]["pages"][
        "maxItems"
    ]
    call = VALID_CALLS["deep_read"][1]
    pages = list(range(1, pages_maximum + 2))
    ToolRequest.parse("deep_read", {**call, "pages": pages[:pages_maximum]})
    assert _refused("deep_read", {**call, "pages": pages})


def test_the_submit_schema_follows_the_submit_parser_bounds() -> None:
    submit = _schema("submit")["parameters"]["properties"]
    call = VALID_CALLS["submit"][0]
    answer = call["answers"][0]

    answers_maximum = submit["answers"]["maxItems"]
    many = [
        {**answer, "question_id": f"{index:08x}-8b3f-4e6a-a9c7-1f0e2d3b4a5c"}
        for index in range(answers_maximum + 1)
    ]
    ToolRequest.parse("submit", {**call, "answers": many[:answers_maximum]})
    assert _refused("submit", {**call, "answers": many})

    answer_fields = submit["answers"]["items"]["properties"]
    for field in answer_fields:
        missing = {key: value for key, value in answer.items() if key != field}
        assert _refused("submit", {**call, "answers": [missing]})
    rationale_maximum = answer_fields["rationale"]["maxLength"]
    long = {**answer, "rationale": "x" * rationale_maximum}
    ToolRequest.parse("submit", {**call, "answers": [long]})
    assert _refused(
        "submit", {**call, "answers": [{**long, "rationale": long["rationale"] + "x"}]}
    )

    nomination = call["nomination"]
    for field in submit["nomination"]["properties"]:
        missing = {key: value for key, value in nomination.items() if key != field}
        assert _refused("submit", {**call, "nomination": missing})
    assert _refused("submit", {**call, "nomination": {**nomination, "undeclared": 1}})


def test_the_schema_refuses_what_the_parser_refuses_on_shape() -> None:
    parameters = _schema("neighbors")["parameters"]
    call = copy.deepcopy(VALID_CALLS["neighbors"][0])
    for bad in (
        {**call, "paper_id": "not-a-uuid"},
        {**call, "limit": True},
        {**call, "extra": 1},
    ):
        assert not _conforms(bad, parameters)
        assert _refused("neighbors", bad)
