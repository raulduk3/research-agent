"""The owner's live run stream, from stored trace events to server-sent
events (#327).

The paper page's two runs, one submitted and one void, each with a stored
tool trace, are replayed through the owner actions app, the owner storage
routes over mutual TLS and real PostgreSQL. A call recorded while a stream
is open reaches it. A rater session reaches nothing.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from tests.storage.test_http import Jobs, _tls_material
from tests.storage.test_queries import Storage
from tests.web import test_owner_paper as paper
from tests.web.api_contract import check_refusal, validate
from tests.web.test_costs import CREDENTIAL, OWNER_ID, SETTINGS, sign_in
from tests.storage.test_queries import identity

from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.owners import OwnerRepository
from research_agent.storage.trace import TraceRepository
from research_agent.web.actions.app import ActionsAppConfig, create_app
from research_agent.web.auth import OwnerDirectory, hash_credential

pytestmark = pytest.mark.integration

LIVE = "/api/v1/owner/runs/live"

# The paper page's stored runs and the rating app, as that module builds them.
storage = paper.storage
seeded = paper.seeded
storage_server = paper.storage_server
storage_client = paper.storage_client
_provisioned_raters = paper._provisioned_raters
rater_directory = paper.rater_directory
rating_app_client = paper.rating_app_client


@pytest.fixture
def live_client(storage: Storage, tmp_path: Path) -> Iterator[TestClient]:
    """The owner actions app over an owner storage identity, polling fast
    and closing each live connection after a second."""
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
    app = create_app(
        ActionsAppConfig(
            actions=client,
            directory=OwnerDirectory(owners),
            live_poll_seconds=0.05,
            live_stream_seconds=1.0,
        )
    )
    try:
        yield TestClient(app, base_url="https://testserver")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def _events(response: Any) -> list[dict[str, Any]]:
    """Each server-sent event's fields, its data checked against the contract."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events: list[dict[str, Any]] = []
    for block in response.text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if line)
        if "data" not in fields:
            continue
        data = json.loads(fields["data"])
        validate(data, "owner-run-event.json")
        assert (fields["id"], fields["event"]) == (data["id"], data["kind"])
        events.append(data)
    return events


def test_a_recorded_run_replays_as_an_ordered_stream(
    seeded: dict[str, Any], live_client: TestClient
) -> None:
    sign_in(live_client)
    void = _events(live_client.get(LIVE, params={"run_id": seeded["void"]}))
    # The run voided before its calls were recorded; the ledger keeps that order.
    assert [event["kind"] for event in void] == [
        "ending",
        "call",
        "terminal",
        "call",
        "call",
        "terminal",
    ]
    assert {event["run_id"] for event in void} == {seeded["void"]}
    ids = [int(event["id"]) for event in void]
    assert ids == sorted(set(ids))
    assert void[0]["ending"]["state"] == "void"
    assert void[1]["call"]["request"]["text"] == seeded["lookup"].decode()
    assert void[1]["call"]["terminal"] is None
    assert void[2]["call"]["terminal"]["response"]["text"] == seeded["cards"].decode()
    assert void[3]["call"]["decision"] == "refused"
    assert void[5]["call"]["terminal"]["error_code"] == "index_unavailable"
    # A reconnect resumes after the last event it saw.
    resumed = _events(
        live_client.get(
            LIVE,
            params={"run_id": seeded["void"]},
            headers={"Last-Event-ID": void[2]["id"]},
        )
    )
    assert resumed == void[3:]
    family = _events(live_client.get(LIVE, params={"paper_id": seeded["family"]}))
    assert {event["run_id"] for event in family} == {
        seeded["void"],
        seeded["submitted"],
    }
    assert [event for event in family if event["run_id"] == seeded["void"]] == void
    # These runs' configurations hold no genome, so no island names them.
    assert {event["island"] for event in family} == {None}
    assert not [
        event
        for event in _events(live_client.get(LIVE, params={"island": "cs"}))
        if event["paper_id"] == seeded["family"]
    ]
    refused = live_client.get(LIVE, headers={"Last-Event-ID": "x"})
    check_refusal(refused, 422, "invalid_request")


def test_a_call_recorded_while_a_stream_is_open_reaches_it(
    seeded: dict[str, Any], storage: Storage, live_client: TestClient
) -> None:
    sign_in(live_client)
    last = _events(live_client.get(LIVE, params={"run_id": seeded["submitted"]}))[-1]

    def record() -> None:
        time.sleep(0.3)
        paper.Tracer(storage).call(
            seeded["submitted"], "query_cards", b'{"late":true}', response=b"{}"
        )

    recorder = threading.Thread(target=record)
    recorder.start()
    late = _events(
        live_client.get(
            LIVE,
            params={"run_id": seeded["submitted"]},
            headers={"Last-Event-ID": last["id"]},
        )
    )
    recorder.join()
    assert [event["kind"] for event in late] == ["call", "terminal"]
    assert late[0]["call"]["request"]["text"] == '{"late":true}'


def test_the_stream_reaches_no_rater_and_no_request_without_an_owner_session(
    live_client: TestClient, rating_app_client: TestClient
) -> None:
    signed_in = rating_app_client.post(
        "/api/v1/login", json={"credential": paper.rater_access.RATER_ONE_CREDENTIAL}
    )
    assert signed_in.status_code == 200, signed_in.text
    refused = rating_app_client.get(LIVE)
    assert refused.status_code == 404
    assert refused.json() == {"detail": "Not Found"}
    check_refusal(live_client.get(LIVE), 401, "unauthenticated")
