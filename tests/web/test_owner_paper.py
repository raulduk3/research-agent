"""The owner's paper page and run traces, from stored records to JSON (#301).

A paper family acquired on one run's request is read by two runs, one that
submitted and one that voided, each with a stored tool trace. Both reads go
through the owner actions app, the owner storage routes over mutual TLS
and real PostgreSQL, and are checked against the contract. A rater session
reaches neither.
"""

from __future__ import annotations

import base64
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "storage"))

from test_http import Jobs, _tls_material  # noqa: E402
from test_queries import (  # noqa: E402
    BUDGETS,
    Storage,
    _paper_with_two_runs,
    identity,
    storage,
)
from web.api_contract import check, check_refusal  # noqa: E402
from web import test_private_rater_access as rater_access  # noqa: E402
from web.test_costs import CREDENTIAL, OWNER_ID, SETTINGS, sign_in  # noqa: E402

from research_agent.contracts import sha256_hex
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.owners import OwnerRepository
from research_agent.storage.trace import TraceRepository, bound_payload
from research_agent.web.actions.app import ActionsAppConfig, create_app
from research_agent.web.auth import OwnerDirectory, hash_credential

pytestmark = pytest.mark.integration

__all__ = ["storage"]

# The rating app over real storage with two provisioned raters.
storage_server = rater_access.storage_server
storage_client = rater_access.storage_client
_provisioned_raters = rater_access._provisioned_raters
rater_directory = rater_access.rater_directory
rating_app_client = rater_access.rating_app_client

PAPER = "/api/v1/owner/papers/{paper_id}"
TRACE = "/api/v1/owner/runs/{run_id}/trace"


class Tracer:
    """Records a run's tool calls with their payloads, as the tool service does."""

    def __init__(self, storage: Storage) -> None:
        self.trace = TraceRepository(storage.database, storage.store, **SETTINGS)

    def call(
        self,
        run_id: str,
        tool: str,
        request: bytes,
        *,
        response: bytes | None = None,
        reason: str | None = None,
        error_code: str | None = None,
        retrieved_ids: tuple[str, ...] = (),
    ) -> None:
        call_id = str(uuid4())
        stored, truncated = bound_payload(request)
        self.trace.execute(
            "request",
            identity=identity(),
            payload={
                "run_id": run_id,
                "call_id": call_id,
                "tool": tool,
                "request_hash": sha256_hex(request),
                "decision": "refused" if reason else "admitted",
                "reason": reason,
                "request_payload": base64.b64encode(stored).decode("ascii"),
                "request_truncated": truncated,
            },
        )
        if response is None:
            return
        stored, truncated = bound_payload(response)
        self.trace.execute(
            "terminal",
            identity=identity(),
            payload={
                "run_id": run_id,
                "call_id": call_id,
                "outcome": "error" if error_code else "response",
                "response_hash": sha256_hex(response),
                "error_code": error_code,
                "retrieved_ids": list(retrieved_ids),
                "budget_deltas": {"tool_calls": 1},
                "response_payload": base64.b64encode(stored).decode("ascii"),
                "response_truncated": truncated,
            },
        )


@pytest.fixture
def owner_client(storage: Storage, tmp_path: Path) -> Iterator[TestClient]:
    """The owner actions app over an owner storage identity that reads the
    inspector queries and the trace."""

    owners = OwnerRepository(storage.database, storage.store, **SETTINGS)
    salt, credential_hash = hash_credential(CREDENTIAL)
    owners.execute(
        "provision",
        identity=identity(),
        payload={
            "owner_id": str(OWNER_ID),
            "salt": salt,
            "credential_hash": credential_hash,
        },
    )
    tls = tmp_path / "owner-tls"
    tls.mkdir()
    server_context, _client, fingerprint, _wrong, _other, _none = _tls_material(tls)
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {fingerprint: ServiceCapability(uuid4(), "owner", frozenset({"owner:read"}))},
        tls_context=server_context,
        authorization=StorageAuthorization(storage.database),
        queries=storage.inspector,
        trace=TraceRepository(storage.database, storage.store, **SETTINGS),
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    host, port = httpd.server_address[:2]
    client = StorageClient(
        connect_host=str(host),
        port=int(port),
        server_hostname="localhost",
        ca_file=tls / "ca.pem",
        client_cert_file=tls / "client.pem",
        client_key_file=tls / "client.key",
        scopes=frozenset({"owner:read"}),
        timeout_seconds=10,
    )
    app = create_app(ActionsAppConfig(actions=client, directory=OwnerDirectory(owners)))
    try:
        yield TestClient(app, base_url="https://testserver")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


@pytest.fixture
def seeded(storage: Storage) -> dict[str, Any]:
    seeded = _paper_with_two_runs(storage)
    tracer = Tracer(storage)
    lookup = (
        b'{"arguments":{"kind":"lookup","paper_ids":["%s"]},"tool":"query_cards"}'
        % (seeded["family"].encode())
    )
    cards = b'{"cards":[{"head_predictions":[{"probability":0.3}]}],"status":"ok"}'
    tracer.call(
        seeded["submitted"],
        "query_cards",
        lookup,
        response=cards,
        retrieved_ids=(seeded["card_hash"],),
    )
    tracer.call(
        seeded["submitted"],
        "submit",
        b'{"arguments":{"answers":[]},"tool":"submit"}',
        response=b'{"accepted":true,"status":"ok"}',
    )
    tracer.call(seeded["void"], "query_cards", lookup, response=cards)
    tracer.call(
        seeded["void"],
        "graph",
        b'{"arguments":{"direction":"citations"},"tool":"graph"}',
        reason="tool_not_allowed",
    )
    tracer.call(
        seeded["void"],
        "query_cards",
        b'{"arguments":{"mode":"overview","query":"x"},"tool":"query_cards"}',
        response=b'{"error":{"code":"index_unavailable"},"status":"error"}',
        error_code="index_unavailable",
    )
    return {**seeded, "lookup": lookup, "cards": cards}


def _texts(calls: list[dict[str, Any]], side: str) -> list[str | None]:
    if side == "request":
        return [call["request"]["text"] for call in calls]
    return [
        None if call["terminal"] is None else call["terminal"]["response"]["text"]
        for call in calls
    ]


def test_a_paper_with_a_submitted_and_a_void_run_renders_both_traces_in_order(
    seeded: dict[str, Any], owner_client: TestClient
) -> None:
    sign_in(owner_client)
    paper = check(
        owner_client.get(PAPER.format(paper_id=seeded["family"])),
        "actions",
        "GET",
        PAPER,
    )

    assert paper["paper_id"] == seeded["family"]
    assert paper["embedding_view"] == f"/api/v1/papers/{seeded['family']}/embedding"
    runs = paper["runs"]["items"]
    assert [run["run_id"] for run in runs] == [seeded["void"], seeded["submitted"]]
    assert paper["runs"]["next_cursor"] is None
    (card,) = paper["cards"]["items"]
    assert card["card"] == seeded["card"]
    assert card["snapshot_hash"] == runs[0]["snapshot_hash"]

    traces = {
        run["run_id"]: check(owner_client.get(run["trace"]), "actions", "GET", TRACE)
        for run in runs
    }
    submitted = traces[seeded["submitted"]]
    assert submitted["run"] == runs[1]
    assert submitted["run"]["ending"]["state"] == "submitted"
    assert [
        forecast["probability"]
        for forecast in submitted["run"]["ending"]["submission"]["forecasts"]
    ] == [0.25, 0.25]
    calls = submitted["calls"]["items"]
    assert [call["tool"] for call in calls] == ["query_cards", "submit"]
    assert _texts(calls, "request")[0] == seeded["lookup"].decode()
    assert _texts(calls, "response") == [
        seeded["cards"].decode(),
        '{"accepted":true,"status":"ok"}',
    ]
    assert calls[0]["terminal"]["retrieved_ids"] == [seeded["card_hash"]]

    void = traces[seeded["void"]]
    assert void["run"]["ending"] == {
        "state": "void",
        "reason": "budget_exhausted",
        "ended_at": void["run"]["ending"]["ended_at"],
        "submission": None,
    }
    calls = void["calls"]["items"]
    assert [call["call_sequence"] for call in calls] == [1, 2, 3]
    assert [call["tool"] for call in calls] == ["query_cards", "graph", "query_cards"]
    # The refused call is shown with its reason and takes no terminal.
    assert calls[1]["decision"] == "refused"
    assert calls[1]["reason"] == "tool_not_allowed" and calls[1]["terminal"] is None
    assert calls[2]["terminal"]["error_code"] == "index_unavailable"
    assert _texts(calls, "response")[2] == (
        '{"error":{"code":"index_unavailable"},"status":"error"}'
    )
    # Each call leaves the budgets the calls up to it had not yet charged.
    assert [call["remaining_budgets"] for call in calls] == [
        {
            "deep_reads": BUDGETS["deep_reads"],
            "images": BUDGETS["images"],
            "tool_calls": BUDGETS["tool_calls"] - spent,
        }
        for spent in (1, 1, 2)
    ]


def test_a_paper_acquired_on_request_names_the_requesting_run(
    seeded: dict[str, Any], owner_client: TestClient
) -> None:
    sign_in(owner_client)
    paper = check(
        owner_client.get(PAPER.format(paper_id=seeded["family"])),
        "actions",
        "GET",
        PAPER,
    )

    assert paper["acquired_on_request"] is True
    (request,) = paper["requests"]["items"]
    assert request["run_id"] == seeded["asker"]
    assert request["status"] == "acquired"
    assert request["paper_version_id"] == seeded["version"]


def test_unknown_or_malformed_ids_are_404_and_a_bad_cursor_is_422(
    storage: Storage, owner_client: TestClient
) -> None:
    sign_in(owner_client)
    for path in (
        PAPER.format(paper_id=uuid4()),
        PAPER.format(paper_id="not-a-uuid"),
        TRACE.format(run_id=uuid4()),
        TRACE.format(run_id="not-a-uuid"),
    ):
        check_refusal(owner_client.get(path), 404, "not_found")
    check_refusal(
        owner_client.get(PAPER.format(paper_id=uuid4()) + "?cursor=x"),
        422,
        "invalid_request",
    )


def test_neither_route_reaches_a_rater_or_a_request_without_an_owner_session(
    seeded: dict[str, Any],
    owner_client: TestClient,
    rating_app_client: TestClient,
) -> None:
    paths = (
        PAPER.format(paper_id=seeded["family"]),
        TRACE.format(run_id=seeded["submitted"]),
    )
    signed_in = rating_app_client.post(
        "/api/v1/login", json={"credential": rater_access.RATER_ONE_CREDENTIAL}
    )
    assert signed_in.status_code == 200, signed_in.text
    for path in paths:
        # The rating app has no such route: a signed-in rater gets the
        # framework's own 404, which carries nothing of the paper or run.
        refused = rating_app_client.get(path)
        assert refused.status_code == 404
        assert refused.json() == {"detail": "Not Found"}
        check_refusal(owner_client.get(path), 401, "unauthenticated")
