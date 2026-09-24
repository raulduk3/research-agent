"""The owner API admits the profile's one front-end origin and no other (#336)."""

from __future__ import annotations

from typing import cast

import pytest
from starlette.testclient import TestClient

from research_agent.storage.client import StorageClient
from research_agent.web.actions.app import ActionsAppConfig, create_app
from research_agent.web.auth import OwnerDirectory

FRONT_END = "https://front.example.org"


def _client(front_end_origin: str) -> TestClient:
    # A preflight is answered before any route runs, so the storage client
    # and the owner directory are never reached.
    app = create_app(
        ActionsAppConfig(
            actions=cast(StorageClient, object()),
            directory=cast(OwnerDirectory, object()),
            front_end_origin=front_end_origin,
        )
    )
    return TestClient(app, base_url="https://testserver")


def _preflight(client: TestClient, origin: str) -> tuple[int, dict[str, str]]:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    return response.status_code, dict(response.headers)


def test_the_named_origin_is_admitted_with_credentials_and_no_wildcard() -> None:
    status, headers = _preflight(_client(FRONT_END), FRONT_END)
    assert status == 200
    assert headers["access-control-allow-origin"] == FRONT_END
    assert headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize(
    "origin",
    ["https://elsewhere.example.org", "http://front.example.org", "null"],
)
def test_a_preflight_from_an_unlisted_origin_is_refused(origin: str) -> None:
    status, headers = _preflight(_client(FRONT_END), origin)
    assert status == 400
    assert "access-control-allow-origin" not in headers


def test_an_empty_origin_admits_none() -> None:
    status, headers = _preflight(_client(""), FRONT_END)
    assert status == 400
    assert "access-control-allow-origin" not in headers


def test_a_simple_request_from_an_unlisted_origin_gets_no_allow_header() -> None:
    response = _client(FRONT_END).get(
        "/api/v1/health", headers={"Origin": "https://elsewhere.example.org"}
    )
    assert "access-control-allow-origin" not in response.headers
