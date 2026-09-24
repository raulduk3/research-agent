"""The shared tool service over its own mutually authenticated listener (#323).

Real PostgreSQL behind the real storage server, the real tool service over
it, and ``tools.http`` serving that service on a real TLS listener that a
``ToolServiceClient`` reaches with a run worker's certificate. A call sent
over the listener is admitted, traced and answered exactly as the service
answers it in process.
"""

from __future__ import annotations

import base64
import hashlib
import json
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPSConnection
from pathlib import Path
from uuid import uuid4

import pytest

from research_agent.agents.loop import ToolCall
from research_agent.contracts import canonical_json
from research_agent.tools.client import (
    ToolServiceClient,
    ToolServiceError,
    ToolTransportError,
)
from research_agent.tools.http import create_tool_server
from research_agent.tools.service import ToolService

from service_harness import (
    ATTENTION,
    Paper,
    World,
    deep_read_args,
    envelope,
    latex_paper,
    lookup_args,
    tool_service,
)

pytestmark = pytest.mark.integration


def _fingerprint(certificate: Path) -> str:
    der = ssl.PEM_cert_to_DER_cert(certificate.read_text())
    return hashlib.sha256(der).hexdigest()


@contextmanager
def listen(
    service: ToolService, root: Path, *, admitted: str = "wrong"
) -> Iterator[tuple[str, int]]:
    """*service* on a TLS listener admitting the certificate named *admitted*."""

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(root / "server.pem", root / "server.key")
    context.load_verify_locations(root / "ca.pem")
    context.verify_mode = ssl.CERT_REQUIRED
    server = create_tool_server(
        ("127.0.0.1", 0),
        service,
        tls_context=context,
        client_fingerprints=frozenset({_fingerprint(root / f"{admitted}.pem")}),
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield str(host), int(port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def client(
    root: Path, address: tuple[str, int], name: str = "wrong"
) -> ToolServiceClient:
    return ToolServiceClient(
        connect_host=address[0],
        port=address[1],
        server_hostname="localhost",
        ca_file=root / "ca.pem",
        client_cert_file=root / f"{name}.pem",
        client_key_file=root / f"{name}.key",
        timeout_seconds=10,
    )


def _papers() -> tuple[Paper, Paper]:
    attention = latex_paper(
        "Attention", ATTENTION, {"Introduction": "attention in small models"}
    )
    scanned = Paper(
        family=str(uuid4()),
        version=str(uuid4()),
        title="Scanned figures",
        overview=(0.0, 1.0, 0.0, 0.0),
        pdf=b"%PDF-1.4\n% a two-page scan\n%%EOF\n",
    )
    return attention, scanned


def test_a_call_over_the_listener_is_answered_and_traced_as_in_process(
    world: World,
) -> None:
    attention, scanned = _papers()
    snapshot = world.seal_snapshot([attention, scanned])
    remote_run = world.create_run(snapshot, paper_id=attention.family)
    local_run = world.create_run(snapshot, paper_id=attention.family)
    lookup = envelope(lookup_args(attention.family))
    pages = envelope(deep_read_args(scanned.family, pages=[1, 2]), intent="read")

    with world.serve() as storage:
        service = tool_service(storage)
        with listen(service, world.tmp_path) as address:
            dispatcher = client(world.tmp_path, address).for_run(snapshot)
            remote = [
                dispatcher.dispatch(
                    ToolCall("c1", "query_cards", lookup), run_id=remote_run
                ),
                dispatcher.dispatch(
                    ToolCall("c2", "deep_read", pages), run_id=remote_run
                ),
                dispatcher.dispatch(
                    ToolCall("c3", "submit", lookup), run_id=remote_run
                ),
            ]
        local = [
            service.call(
                run_id=local_run, snapshot_id=snapshot, tool=tool, raw_call=call
            )
            for tool, call in (
                ("query_cards", lookup),
                ("deep_read", pages),
                ("submit", lookup),
            )
        ]

    # Each answer is the in-process answer: envelope, status and the budgets
    # the loop charges, a rendered page image and a refusal included.
    assert remote == local
    assert [outcome.status for outcome in remote] == ["ok", "ok", "refused"]
    assert (remote[1].deep_reads, remote[1].images) == (1, 2)
    image = base64.b64decode(remote[1].data["data"]["pages"][1]["image_base64"])
    assert image.endswith(b"page 2")

    def conduct(run: str) -> list[tuple[object, ...]]:
        return [
            (row["tool"], row["decision"], row["outcome"], row["budget_deltas"])
            for row in world.trace_rows(run)
        ]

    assert conduct(remote_run) == conduct(local_run)
    assert len(conduct(remote_run)) == 3


def test_a_call_with_no_canonical_form_reaches_admission_and_is_recorded(
    world: World,
) -> None:
    attention, _scanned = _papers()
    snapshot = world.seal_snapshot([attention])
    run = world.create_run(snapshot, paper_id=attention.family)
    call = envelope({**lookup_args(attention.family), "limit": float("nan")})

    with world.serve() as storage:
        with listen(tool_service(storage), world.tmp_path) as address:
            outcome = client(world.tmp_path, address).call(
                run_id=run,
                snapshot_id=snapshot,
                tool_call_id="c1",
                tool="query_cards",
                raw_call=call,
            )

    assert (outcome.status, outcome.data["code"]) == ("refused", "invalid_input")
    ((row),) = world.trace_rows(run)
    assert (row["decision"], row["reason"]) == ("refused", "invalid_input")


def test_an_unadmitted_certificate_and_a_malformed_call_leave_no_trace(
    world: World,
) -> None:
    attention, _scanned = _papers()
    snapshot = world.seal_snapshot([attention])
    run = world.create_run(snapshot, paper_id=attention.family)
    call = envelope(lookup_args(attention.family))

    with world.serve() as storage:
        with listen(tool_service(storage), world.tmp_path) as address:
            # The storage tools certificate is valid under the CA but is not
            # a run worker's.
            with pytest.raises(ToolServiceError) as refused:
                client(world.tmp_path, address, "client").call(
                    run_id=run,
                    snapshot_id=snapshot,
                    tool_call_id="c1",
                    tool="query_cards",
                    raw_call=call,
                )
            no_certificate = ssl.create_default_context(
                cafile=str(world.tmp_path / "ca.pem")
            )
            with pytest.raises((ssl.SSLError, OSError)):
                connection = HTTPSConnection(*address, context=no_certificate)
                connection.request("GET", "/health")
                connection.getresponse().read()
            admitted = client(world.tmp_path, address)
            with pytest.raises(ToolServiceError) as malformed:
                admitted.call(
                    run_id=run,
                    snapshot_id="not a hash",
                    tool_call_id="c1",
                    tool="query_cards",
                    raw_call=call,
                )
            extra = HTTPSConnection(
                "localhost",
                address[1],
                context=_worker_context(world.tmp_path),
            )
            body = canonical_json(
                {
                    "schema_version": 1,
                    "run_id": run,
                    "snapshot_id": snapshot,
                    "tool_call_id": "c1",
                    "tool": "query_cards",
                    "call": json.dumps(call),
                    "budgets": {"tool_calls": 99},
                }
            )
            extra.request(
                "POST", "/v1/calls", body, {"Content-Type": "application/json"}
            )
            extra_status = extra.getresponse().status
            extra.close()
            health = admitted.health()

    assert (refused.value.status_code, refused.value.code) == (401, "unauthenticated")
    assert (malformed.value.status_code, malformed.value.code) == (
        422,
        "invalid_input",
    )
    assert extra_status == 422
    assert health == "ready"
    assert world.trace_rows(run) == []


def _worker_context(root: Path) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(root / "ca.pem"))
    context.load_cert_chain(root / "wrong.pem", root / "wrong.key")
    return context


def test_the_listener_requires_verified_client_certificates(
    world: World,
) -> None:
    with world.serve() as storage:
        service = tool_service(storage)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with pytest.raises(ValueError, match="verified client certificates"):
        create_tool_server(
            ("127.0.0.1", 0),
            service,
            tls_context=context,
            client_fingerprints=frozenset({"a" * 64}),
        )


def test_a_lost_listener_is_a_transport_error_and_is_not_retried(
    world: World,
) -> None:
    with world.serve() as storage:
        with listen(tool_service(storage), world.tmp_path) as address:
            pass
        with pytest.raises(ToolTransportError, match="not retried"):
            client(world.tmp_path, address).health()
