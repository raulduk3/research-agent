"""The /api/v1 schemas, endpoint table and routes agree with each other (#249).

Real responses are validated per endpoint in ``tests/web/test_api_v1_*.py``;
this module checks what holds without storage: every schema is well formed
and uses only what the validator enforces, every JSON route of every app is
in the endpoint table and every HTML route has its twin, and the validator
refuses the concrete leaks the schemas exist to catch.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.requests import Request
from tests.web.api_contract import (
    KNOWN_KEYWORDS,
    SCHEMA_DIR,
    SchemaError,
    endpoints,
    load,
    validate,
)

from research_agent.web import api
from research_agent.web.actions.app import ActionsAppConfig
from research_agent.web.actions.app import create_app as create_actions_app
from research_agent.web.app import RatingAppConfig
from research_agent.web.app import create_app as create_rating_app
from research_agent.web.digest import default_fixture
from research_agent.web.inspect.app import InspectorAppConfig
from research_agent.web.inspect.app import create_app as create_inspector_app
from research_agent.web.report.app import ReportAppConfig
from research_agent.web.report.app import create_app as create_report_app

SCHEMAS = sorted(
    path.name for path in SCHEMA_DIR.glob("*.json") if path.name != "endpoints.json"
)
UNUSED: Any = None


def apps() -> dict[str, FastAPI]:
    """Each app's routes; nothing here is called, so no storage is wired."""
    return {
        "rating": create_rating_app(
            RatingAppConfig(storage=UNUSED, directory=UNUSED, digest=default_fixture())
        ),
        "inspector": create_inspector_app(InspectorAppConfig(storage=UNUSED)),
        "report": create_report_app(ReportAppConfig(load=lambda _i, _w: None)),
        "actions": create_actions_app(
            ActionsAppConfig(actions=UNUSED, directory=UNUSED)
        ),
    }


def routes(app: FastAPI) -> Iterator[tuple[str, str]]:
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods):
                yield method, route.path


def subschemas(schema: Any) -> Iterator[dict[str, Any]]:
    if isinstance(schema, dict):
        yield schema
        for key, value in schema.items():
            if key in ("properties", "$defs"):
                for child in value.values():
                    yield from subschemas(child)
            elif key in ("items", "additionalProperties"):
                yield from subschemas(value)
            elif key == "oneOf":
                for child in value:
                    yield from subschemas(child)


@pytest.mark.parametrize("name", SCHEMAS)
def test_every_schema_is_well_formed_and_fully_enforced(name: str) -> None:
    schema = load(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == name
    for part in subschemas(schema):
        assert set(part) <= KNOWN_KEYWORDS, (name, set(part) - KNOWN_KEYWORDS)
        if "$ref" in part:
            target, _, pointer = part["$ref"].partition("#")
            resolved: Any = load(target or name)
            for step in [step for step in pointer.split("/") if step]:
                resolved = resolved[step]
            assert isinstance(resolved, dict), part["$ref"]
        if part.get("type") == "object" and "properties" in part:
            assert "additionalProperties" in part, (
                f"{name}: an object with properties must say whether it is closed"
            )


def test_every_json_route_is_in_the_table_with_a_schema() -> None:
    table = {(row["app"], row["method"], row["path"]) for row in endpoints()}
    served = {
        (name, method, path)
        for name, app in apps().items()
        for method, path in routes(app)
        if path.startswith(f"{api.PREFIX}/")
    }
    assert served == table
    for row in endpoints():
        assert row["schema"] in SCHEMAS
        assert row["status"] in (200, 201)


def test_every_html_route_has_its_json_twin() -> None:
    twins = {(row["app"], row["twin_of"]) for row in endpoints() if row["twin_of"]}
    for name, app in apps().items():
        for method, path in routes(app):
            if path.startswith("/api/"):
                continue
            assert (name, f"{method} {path}") in twins, f"{name} {method} {path}"


def test_the_validator_refuses_a_blinded_entry_that_names_its_origin() -> None:
    entry = {
        "paper_hash": "a" * 64,
        "digest_entry_id": "11111111-1111-4111-8111-111111111111",
        "title": "t",
        "abstract": "a",
    }
    validate(entry, "blinded-entry.json")
    for leak in ("origin", "genome_hash", "probability", "rationale", "reading"):
        with pytest.raises(SchemaError, match=leak):
            validate({**entry, leak: "x"}, "blinded-entry.json")


def test_the_validator_refuses_an_unrated_owner_entry_carrying_provenance() -> None:
    unrated = {
        "entry_id": "11111111-1111-4111-8111-111111111111",
        "paper_hash": "a" * 64,
        "display_position": 0,
        "rated": False,
    }
    digest = {
        "digest_hash": "b" * 64,
        "batch_id": "c" * 64,
        "island": "cs",
        "source_watermark": 0,
        "shuffle_seed": "00",
        "built_at": "2026-09-23T00:00:00.000000Z",
        "entries": [unrated],
    }
    validate(digest, "owner-digest.json")
    leaked = {**digest, "entries": [{**unrated, "origin": "service"}]}
    with pytest.raises(SchemaError, match="oneOf"):
        validate(leaked, "owner-digest.json")


def test_the_validator_refuses_another_instant_format_and_a_bool_count() -> None:
    recorded = {
        "rating_id": "11111111-1111-4111-8111-111111111111",
        "rated_at": "2026-09-23T00:00:00.000000Z",
    }
    validate(recorded, "rating-recorded.json")
    with pytest.raises(SchemaError, match="does not match"):
        validate(
            {**recorded, "rated_at": "2026-09-23T00:00:00Z"}, "rating-recorded.json"
        )
    manifest = {
        "manifest_hash": "a" * 64,
        "artifact_hash": "b" * 64,
        "manifest_kind": "representation",
        "media_type": "application/json",
        "byte_length": 10,
        "created_at": "2026-09-23T00:00:00.000000Z",
        "fields": {},
    }
    validate({"manifest": manifest}, "manifest-view.json")
    with pytest.raises(SchemaError, match="is not integer"):
        validate({"manifest": {**manifest, "byte_length": True}}, "manifest-view.json")


def test_the_validator_refuses_a_nulled_gated_field() -> None:
    view = {
        "genome": {
            "configuration_id": "11111111-1111-4111-8111-111111111111",
            "configuration_hash": "a" * 64,
            "island": "cs",
            "founder": True,
            "lineage_id": "l",
            "emphasis": {
                "prompt": "p",
                "scan_policy": "s",
                "read_policy": "r",
                "probability_assignment_rule": "a",
            },
        },
        "emphasis_fields": {"items": ["prompt"], "next_cursor": None},
        "admission": None,
        "retirement": None,
        "csrf_token": "t",
    }
    validate(view, "owner-agent-view.json")
    with pytest.raises(SchemaError, match="inspected"):
        validate({**view, "inspected": None}, "owner-agent-view.json")


def test_a_refusal_is_the_error_envelope_with_its_fixed_code() -> None:
    for status, code in api.ERROR_CODES.items():
        body = json.loads(bytes(api.refusal(status, "reason", "field").body))
        validate(body, "error.json")
        assert body["error"] == {"code": code, "message": "reason", "field": "field"}
    with pytest.raises(SchemaError):
        validate(
            {
                "contract": "1",
                "error": {"code": "teapot", "message": "", "field": None},
            },
            "error.json",
        )


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


def test_a_reused_key_replays_its_answer_and_refuses_another_request() -> None:
    cache = api.IdempotencyCache()
    calls: list[int] = []

    def command() -> Any:
        calls.append(1)
        return api.ok({"configuration_id": str(UUID(int=len(calls)))}, status_code=201)

    first_print = cache.fingerprint(_request("/api/v1/seed"), b"{}")
    first = cache.run("owner", "key", first_print, command)
    again = cache.run("owner", "key", first_print, command)
    assert calls == [1]
    assert (again.status_code, bytes(again.body)) == (201, bytes(first.body))
    assert again.headers["X-Replayed"] == "true"
    # another principal's same key is its own request
    cache.run("other", "key", first_print, command)
    assert calls == [1, 1]

    other_print = cache.fingerprint(_request("/api/v1/seed"), b'{"x":"y"}')
    with pytest.raises(api.ApiError) as refused:
        cache.run("owner", "key", other_print, command)
    assert (refused.value.status_code, refused.value.field) == (409, "Idempotency-Key")


def test_a_refused_command_is_replayed_but_a_server_failure_runs_again() -> None:
    cache = api.IdempotencyCache()
    outcomes = [api.ApiError(409, "invalid_edit"), api.ApiError(502, "not saved")]

    def refuse() -> Any:
        raise outcomes.pop(0)

    fingerprint = cache.fingerprint(_request("/api/v1/seed"), b"{}")
    conflict = cache.run("owner", "a", fingerprint, refuse)
    assert conflict.status_code == 409
    assert cache.run("owner", "a", fingerprint, refuse).status_code == 409
    assert cache.run("owner", "b", fingerprint, refuse).status_code == 502
    outcomes.append(api.ApiError(502, "not saved"))
    assert cache.run("owner", "b", fingerprint, refuse).status_code == 502
    assert outcomes == []


def test_a_derived_storage_key_is_stable_and_scoped_to_its_principal() -> None:
    one = api.derived_id("rating-key", "rater-one", "k")
    assert one == api.derived_id("rating-key", "rater-one", "k")
    assert one != api.derived_id("rating-key", "rater-two", "k")
    assert one != api.derived_id("rating-command", "rater-one", "k")
    assert one.version == 4
