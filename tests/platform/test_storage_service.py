"""The deployed storage service constructs every owner its server can serve (#277)."""

from __future__ import annotations

import inspect
import json
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest


from tests.storage.test_http import _tls_material, request  # noqa: E402

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.platform.storage_service import build_storage_server
from research_agent.storage.database import Database
from research_agent.storage.http import ServiceCapability, create_storage_server

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
CONFIG_HASH = "c" * 64
RETENTION_POLICY_HASH = "d" * 64
ID = "11111111-1111-4111-8111-111111111111"
HASH = "e" * 64

# One route of each owner, under the role and scope that route admits. With
# the capability granted, only an unwired owner answers "route not found"
# (reads) or "capability does not permit route" (writes).
ROUTES: dict[str, tuple[str, str, str, str]] = {
    "artifacts": ("tools", "artifacts:publish", "POST", "/v1/artifacts"),
    "documents": ("tools", "snapshots:read", "GET", f"/v1/snapshots/{HASH}/members"),
    "queries": ("inspector", "runs:read", "GET", f"/v1/runs?configuration_id={ID}"),
    "runs": ("orchestrator", "runs:create", "POST", "/v1/runs"),
    "snapshots": ("orchestrator", "snapshots:seal", "POST", "/v1/snapshots"),
    "sheets": ("orchestrator", "sheets:seal", "POST", "/v1/sheets"),
    "submissions": ("orchestrator", "submissions:submit", "POST", "/v1/submissions"),
    "ratings": (
        "rating_app",
        "raters:read",
        "GET",
        f"/v1/ratings?rater_id={ID}&batch_id={HASH}",
    ),
    "raters": ("operator", "raters:provision", "POST", "/v1/raters"),
    "digests": ("orchestrator", "digests:store", "POST", "/v1/digests"),
    "owners": ("owner", "owner:read", "GET", "/v1/owner/retrospective"),
    "assessments": (
        "reader",
        "assessments:read",
        "GET",
        f"/v1/assessments/pointers?paper_version_id={ID}",
    ),
    "paper_requests": ("ingest", "paper_requests:read", "GET", "/v1/paper-requests"),
    "preference": (
        "rating_app",
        "raters:read",
        "GET",
        f"/v1/preference?rater_id={ID}&iso_week=2026-W39",
    ),
    "settlements": ("owner", "owner:read", "GET", "/v1/owner/costs?day=2026-09-23"),
    "trace": ("tools", "trace:request", "POST", f"/v1/runs/{ID}/trace/requests"),
    "embedding_views": (
        "owner",
        "owner:read",
        "GET",
        f"/v1/owner/papers/{ID}/embedding",
    ),
}
UNWIRED = {
    (404, "route not found"),
    (403, "capability does not permit route"),
}


@pytest.fixture(scope="module")
def tls(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[ssl.SSLContext, ssl.SSLContext, str, ssl.SSLContext, str, ssl.SSLContext]:
    return _tls_material(tmp_path_factory.mktemp("tls"))


def test_every_owner_the_server_accepts_has_a_route_here() -> None:
    owners = {
        name
        for name, parameter in inspect.signature(
            create_storage_server
        ).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    } - {"tls_context", "authorization"}

    assert owners == set(ROUTES)


@pytest.mark.parametrize("owner", sorted(ROUTES))
def test_production_wiring_serves_each_owner(
    owner: str,
    postgres_dsn: str,
    artifact_root: Path,
    tls: tuple[
        ssl.SSLContext, ssl.SSLContext, str, ssl.SSLContext, str, ssl.SSLContext
    ],
) -> None:
    server_context, client_context, fingerprint, *_ = tls
    role, scope, method, path = ROUTES[owner]
    with _served(
        postgres_dsn,
        artifact_root,
        server_context,
        {
            fingerprint: ServiceCapability(
                uuid4(),
                role,
                frozenset({scope}),
                frozenset(),
                PRODUCER,
                CONFIG_HASH,
                RETENTION_POLICY_HASH,
            )
        },
    ) as address:
        response, body = request(
            address,
            client_context,
            method,
            path,
            body=b"" if method == "POST" else None,
            headers={"Content-Type": "application/json"} if method == "POST" else None,
        )

    error = json.loads(body).get("error") or {}
    assert (response.status, error.get("message")) not in UNWIRED, body


@contextmanager
def _served(
    dsn: str,
    artifact_root: Path,
    server_context: ssl.SSLContext,
    capabilities: dict[str, ServiceCapability],
) -> Iterator[tuple[str, int]]:
    server = build_storage_server(
        ("127.0.0.1", 0),
        capabilities,
        tls_context=server_context,
        database=Database(dsn),
        artifact_store=ArtifactStore(artifact_root),
        producer=PRODUCER,
        config_hash=CONFIG_HASH,
        retention_policy_hash=RETENTION_POLICY_HASH,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield str(host), int(port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
