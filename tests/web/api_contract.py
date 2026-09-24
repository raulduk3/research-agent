"""Checks a real ``/api/v1`` response against its schema and its HTML twin (#249).

The validator covers the subset of JSON Schema 2020-12 the checked-in
schemas use and refuses any other keyword, so a schema can never pass here
because a keyword it relies on was silently ignored.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader, nodes

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "docs" / "contracts" / "api-v1"
WEB_DIR = ROOT / "src" / "research_agent" / "web"

KNOWN_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$defs",
        "$ref",
        "title",
        "description",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "pattern",
        "minimum",
        "minLength",
        "oneOf",
    }
)
#: HTML-only variables: a list's ``next`` link is its ``next_cursor``, and a
#: sign-in page's error is the refusal envelope's message.
HTML_ONLY = frozenset({"next_cursor_query", "forecasts_next_cursor_query", "error"})


class SchemaError(AssertionError):
    pass


@cache
def load(name: str) -> dict[str, Any]:
    document = json.loads((SCHEMA_DIR / name).read_text())
    assert isinstance(document, dict)
    return document


def endpoints() -> list[dict[str, Any]]:
    table = json.loads((SCHEMA_DIR / "endpoints.json").read_text())
    return list(table["endpoints"])


def endpoint(app: str, method: str, path: str) -> dict[str, Any]:
    matches = [
        row
        for row in endpoints()
        if (row["app"], row["method"], row["path"]) == (app, method, path)
    ]
    assert len(matches) == 1, f"{app} {method} {path} is not in endpoints.json"
    return matches[0]


def _resolve(reference: str, document: str) -> tuple[dict[str, Any], str]:
    name, _, pointer = reference.partition("#")
    name = name or document
    target: Any = load(name)
    for part in [part for part in pointer.split("/") if part]:
        target = target[part]
    assert isinstance(target, dict), reference
    return target, name


def _is_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise SchemaError(f"unknown type {expected}")


def validate(value: Any, schema_name: str) -> None:
    """Raise :class:`SchemaError` naming the first place ``value`` breaks the schema."""
    _validate(value, load(schema_name), schema_name, "$")


def _validate(value: Any, schema: Mapping[str, Any], document: str, path: str) -> None:
    unknown = set(schema) - KNOWN_KEYWORDS
    if unknown:
        raise SchemaError(f"{document}: unsupported keywords {sorted(unknown)}")
    if "$ref" in schema:
        target, target_document = _resolve(schema["$ref"], document)
        _validate(value, target, target_document, path)
    if "type" in schema:
        expected = schema["type"]
        options = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(value, option) for option in options):
            raise SchemaError(f"{path}: {value!r} is not {expected}")
    if "const" in schema and (
        value != schema["const"] or type(value) is not type(schema["const"])
    ):
        raise SchemaError(f"{path}: {value!r} is not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise SchemaError(f"{path}: {value!r} does not match {schema['pattern']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaError(f"{path}: {value!r} is too short")
    if "minimum" in schema and _is_type(value, "number") and value < schema["minimum"]:
        raise SchemaError(f"{path}: {value!r} is below {schema['minimum']}")
    if "oneOf" in schema:
        passing = 0
        for option in schema["oneOf"]:
            try:
                _validate(value, option, document, path)
            except SchemaError:
                continue
            passing += 1
        if passing != 1:
            raise SchemaError(f"{path}: {passing} oneOf branches match, not 1")
    if isinstance(value, dict):
        for name in schema.get("required", ()):
            if name not in value:
                raise SchemaError(f"{path}: missing {name}")
        properties = schema.get("properties", {})
        for name, item in value.items():
            if name in properties:
                _validate(item, properties[name], document, f"{path}.{name}")
            elif schema.get("additionalProperties", True) is False:
                raise SchemaError(f"{path}: {name} is not an admitted field")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], document, f"{path}[{index}]")


def check(response: httpx.Response, app: str, method: str, path: str) -> dict[str, Any]:
    """Validate a real success response of one endpoint; return its ``data``."""
    row = endpoint(app, method, path)
    assert response.status_code == row["status"], response.text
    body = response.json()
    validate(body, "envelope.json")
    validate(body["data"], row["schema"])
    data = body["data"]
    assert isinstance(data, dict)
    return data


def check_refusal(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    validate(body, "error.json")
    error = body["error"]
    assert error["code"] == code, error
    assert isinstance(error, dict)
    return error


def _parse(template: Path) -> nodes.Template:
    environment = Environment(loader=FileSystemLoader(str(template.parent)))
    return environment.parse(template.read_text())


def _items(value: Any) -> list[Any]:
    if isinstance(value, dict) and set(value) == {"items", "next_cursor"}:
        value = value["items"]
    return list(value) if isinstance(value, list) else []


def html_fields_missing_from(
    template: Path,
    data: Mapping[str, Any],
    *,
    page_only: frozenset[str] = frozenset(),
) -> list[str]:
    """Every field ``template`` renders that the JSON ``data`` does not carry.

    Walks the template's variables, their attributes, and the attributes of
    loop variables over them, resolving each against the JSON data; a name
    the HTML shows and the JSON lacks is returned as a dotted path.
    ``page_only`` names this page's variables that have no twin in ``data``.
    """
    missing: list[str] = []
    aliases: dict[str, tuple[str, list[Any]]] = {}

    def values(expression: nodes.Node) -> tuple[str, list[Any]] | None:
        if isinstance(expression, nodes.Name):
            if expression.name in aliases:
                return aliases[expression.name]
            if expression.name in HTML_ONLY | page_only:
                return None
            if expression.name not in data:
                missing.append(expression.name)
                return None
            return expression.name, [data[expression.name]]
        if isinstance(expression, nodes.Getattr):
            parent = values(expression.node)
            if parent is None:
                return None
            label, found = parent
            label = f"{label}.{expression.attr}"
            present = []
            for item in found:
                if not isinstance(item, dict):
                    continue
                if expression.attr not in item:
                    missing.append(label)
                    return None
                present.append(item[expression.attr])
            return label, present
        return None

    def walk(node: nodes.Node) -> None:
        if isinstance(node, nodes.For):
            source = values(node.iter)
            label, found = source if source is not None else ("", [])
            items = [item for value in found for item in _items(value)]
            if isinstance(node.target, nodes.Name):
                aliases[node.target.name] = (f"{label}[]", items)
            else:
                # A tuple target unpacks pairs the loop builds itself.
                for target in node.target.find_all(nodes.Name):
                    aliases[target.name] = (f"{label}[]", [])
            for child in (*node.body, *node.else_):
                walk(child)
            return
        if isinstance(node, (nodes.Name, nodes.Getattr)):
            values(node)
            return
        for child in node.iter_child_nodes():
            walk(child)

    walk(_parse(template))
    return sorted(set(missing))
