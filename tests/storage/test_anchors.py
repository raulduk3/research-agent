"""The anchor receiver transport, binding record, bind-anchor and schedule (#325).

A real TLS receiver runs in-process; each test chooses what it answers. The
binding is stored in the test database, and the schedule reads the real
ledger head that `LedgerRepository` advances.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from test_http import _tls_material
from test_ledger import _insert_payload_artifact

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.anchoring import (
    AnchorBindRefused,
    AnchorScheduler,
    AnchorSettings,
    anchor_request,
    bind_anchor,
    start_anchoring,
)
from research_agent.storage.anchors import (
    AnchorBindingRepository,
    AnchorReceipt,
    AnchorRejected,
    AnchorTimeout,
    HttpsAnchorTransport,
)
from research_agent.storage.database import Database
from research_agent.storage.ledger import GENESIS_HASH, LedgerRepository

ACCEPTED_AT = "2026-09-23T00:00:00.000000Z"
TOKEN = "anchor-test-token"


@dataclass
class Receiver:
    """What the test receiver answers, and every request it received."""

    url: str
    answer: str = "ack"
    received: list[dict[str, Any]] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Tls:
    ca: Path
    certificate: Path
    private_key: Path


@pytest.fixture(scope="module")
def tls(tmp_path_factory: pytest.TempPathFactory) -> Tls:
    root = tmp_path_factory.mktemp("anchor-tls")
    _tls_material(root)
    return Tls(root / "ca.pem", root / "client.pem", root / "client.key")


def _serve(tls: Tls, *, mutual: bool) -> Iterator[Receiver]:
    root = tls.ca.parent
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(root / "server.pem", root / "server.key")
    if mutual:
        context.load_verify_locations(tls.ca)
        context.verify_mode = ssl.CERT_REQUIRED
    state: list[Receiver] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:
            receiver = state[0]
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            receiver.received.append(body)
            receiver.headers.append(dict(self.headers))
            if self.path != "/v1/anchors" or receiver.answer == "refuse":
                self._reply(409, {"error": "decreasing sequence"})
                return
            sequence = body["sequence"] + (1 if receiver.answer == "other" else 0)
            self._reply(
                201,
                {
                    "sequence": sequence,
                    "record_hash": body["record_hash"],
                    "receiver_signature": "signature",
                    "accepted_at": ACCEPTED_AT,
                },
            )

        def _reply(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    state.append(Receiver(f"https://localhost:{server.server_address[1]}"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def receiver(tls: Tls) -> Iterator[Receiver]:
    yield from _serve(tls, mutual=True)


@pytest.fixture
def bearer_receiver(tls: Tls) -> Iterator[Receiver]:
    yield from _serve(tls, mutual=False)


def _transport(tls: Tls, url: str) -> HttpsAnchorTransport:
    return HttpsAnchorTransport(
        url,
        ca_file=tls.ca,
        client_certificate_file=tls.certificate,
        client_private_key_file=tls.private_key,
        timeout_seconds=5.0,
    )


def _append(database: Database, count: int) -> None:
    payload_hash = hashlib.sha256(uuid4().bytes).hexdigest()
    _insert_payload_artifact(database, payload_hash)
    ledger = LedgerRepository()
    for _ in range(count):
        database.serializable(
            lambda connection: ledger.append(
                connection,
                record_id=uuid4(),
                event_kind="run_event",
                payload_hash=payload_hash,
                command_id=uuid4(),
            )
        )


# --- transport ------------------------------------------------------------------


def test_transport_posts_the_head_over_mtls_and_returns_its_receipt(
    tls: Tls, receiver: Receiver
) -> None:
    receipt = _transport(tls, receiver.url)(anchor_request("launch-v2", 7, "a" * 64))
    assert (receipt.sequence, receipt.record_hash) == (7, "a" * 64)
    assert receiver.received == [
        {
            "sequence": 7,
            "record_hash": "a" * 64,
            "profile_id": "launch-v2",
            "idempotency_key": f"anchor:launch-v2:7:{'a' * 64}",
        }
    ]


def test_transport_authenticates_with_a_bearer_token_when_the_receiver_needs_one(
    tls: Tls, bearer_receiver: Receiver, tmp_path: Path
) -> None:
    token = tmp_path / "token"
    token.write_text(TOKEN + "\n")
    transport = HttpsAnchorTransport(
        bearer_receiver.url, ca_file=tls.ca, bearer_token_file=token
    )
    transport(anchor_request("launch-v2", 1, "a" * 64))
    assert bearer_receiver.headers[0]["Authorization"] == f"Bearer {TOKEN}"


def test_transport_refuses_a_receipt_for_another_head_and_a_refusal(
    tls: Tls, receiver: Receiver
) -> None:
    transport = _transport(tls, receiver.url)
    receiver.answer = "other"
    with pytest.raises(AnchorRejected, match="does not acknowledge"):
        transport(anchor_request("launch-v2", 7, "a" * 64))
    receiver.answer = "refuse"
    with pytest.raises(AnchorRejected, match="status 409"):
        transport(anchor_request("launch-v2", 7, "a" * 64))


def test_transport_reports_an_unreachable_receiver_as_a_timeout(tls: Tls) -> None:
    with pytest.raises(AnchorTimeout):
        _transport(tls, "https://localhost:1")(anchor_request("p", 1, "a" * 64))


def test_transport_requires_https_and_exactly_one_credential(
    tls: Tls, tmp_path: Path
) -> None:
    token = tmp_path / "token"
    token.write_text(TOKEN)
    with pytest.raises(ContractValidationError, match="https"):
        HttpsAnchorTransport("http://receiver", ca_file=tls.ca, bearer_token_file=token)
    with pytest.raises(ContractValidationError, match="exactly one"):
        HttpsAnchorTransport("https://receiver", ca_file=tls.ca)
    with pytest.raises(ContractValidationError, match="exactly one"):
        HttpsAnchorTransport(
            "https://receiver",
            ca_file=tls.ca,
            client_certificate_file=tls.certificate,
            client_private_key_file=tls.private_key,
            bearer_token_file=token,
        )


# --- binding and schedule -------------------------------------------------------


@pytest.mark.integration
def test_bind_anchor_records_the_receiver_only_after_it_acknowledges_the_head(
    postgres_dsn: str, tls: Tls, receiver: Receiver
) -> None:
    bindings = AnchorBindingRepository(Database(postgres_dsn))
    receiver.answer = "other"
    with pytest.raises(AnchorBindRefused):
        bind_anchor(
            bindings, receiver.url, _transport(tls, receiver.url), profile_id="p"
        )
    with pytest.raises(AnchorBindRefused, match="did not answer"):
        bind_anchor(
            bindings,
            "https://localhost:1",
            _transport(tls, "https://localhost:1"),
            profile_id="p",
        )
    assert bindings.current() is None

    receiver.answer = "ack"
    binding = bind_anchor(
        bindings, receiver.url, _transport(tls, receiver.url), profile_id="p"
    )
    assert binding == bindings.current()
    assert (binding.receiver_url, binding.last_acknowledged_sequence) == (
        receiver.url,
        0,
    )
    assert binding.last_acknowledged_hash == GENESIS_HASH
    assert binding.last_acknowledged_at == ACCEPTED_AT


@pytest.mark.integration
def test_schedule_anchors_after_100_records_and_holds_through_an_outage(
    postgres_dsn: str, tls: Tls, receiver: Receiver
) -> None:
    database = Database(postgres_dsn)
    bindings = AnchorBindingRepository(database)
    bind_anchor(bindings, receiver.url, _transport(tls, receiver.url), profile_id="p")
    accepted = datetime(2026, 9, 23, tzinfo=timezone.utc)
    clock = [accepted + timedelta(minutes=1)]
    scheduler = AnchorScheduler(
        bindings, _transport(tls, receiver.url), profile_id="p", now=lambda: clock[0]
    )
    receiver.received.clear()

    _append(database, 99)
    assert scheduler.tick() == "not_due"
    assert receiver.received == []

    _append(database, 1)
    receiver.answer = "refuse"
    assert scheduler.tick() == "failed"
    stored = bindings.current()
    assert stored is not None and stored.last_acknowledged_sequence == 0

    receiver.answer = "ack"
    assert scheduler.tick() == "anchored"
    head = bindings.ledger_head()
    stored = bindings.current()
    assert stored is not None
    assert (stored.last_acknowledged_sequence, stored.last_acknowledged_hash) == head
    assert receiver.received[-1]["sequence"] == 100

    # One new record is due only once 15 minutes have passed since the receipt.
    _append(database, 1)
    assert scheduler.tick() == "not_due"
    clock[0] = accepted + timedelta(minutes=15)
    assert scheduler.tick() == "anchored"
    stored = bindings.current()
    assert stored is not None and stored.last_acknowledged_sequence == 101


@pytest.mark.integration
def test_the_binding_never_moves_back_and_is_never_deleted(
    postgres_dsn: str, tls: Tls, receiver: Receiver
) -> None:
    database = Database(postgres_dsn)
    bindings = AnchorBindingRepository(database)
    _append(database, 2)
    bind_anchor(bindings, receiver.url, _transport(tls, receiver.url), profile_id="p")
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        for statement in (
            "UPDATE anchor_bindings SET last_acknowledged_sequence = 1",
            "UPDATE anchor_bindings SET last_acknowledged_hash = decode(repeat('11', 32), 'hex')",
            "UPDATE anchor_bindings SET receiver_url = 'https://elsewhere'",
            "DELETE FROM anchor_bindings",
        ):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                connection.execute(statement)
    stored = bindings.current()
    assert stored is not None
    with pytest.raises(ContractValidationError, match="decreasing"):
        bindings.acknowledge(
            receiver.url, AnchorReceipt(2, "a" * 64, "signature", ACCEPTED_AT)
        )


@pytest.mark.integration
def test_the_storage_service_schedule_refuses_to_start_unbound(
    postgres_dsn: str, tls: Tls
) -> None:
    settings = AnchorSettings.from_config(
        {
            "profile_id": "p",
            "ca_file": str(tls.ca),
            "client_certificate_file": str(tls.certificate),
            "client_private_key_file": str(tls.private_key),
        }
    )
    with pytest.raises(ValueError, match="run bind-anchor"):
        start_anchoring(AnchorBindingRepository(Database(postgres_dsn)), settings)


# --- entry point ----------------------------------------------------------------


def _bind_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "research_agent", "bind-anchor", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_bind_anchor_refuses_to_record_without_verify(tmp_path: Path) -> None:
    result = _bind_command(
        "--receiver", "https://receiver", "--storage-config", str(tmp_path / "c")
    )
    assert result.returncode == 2
    assert "pass --verify" in result.stderr


@pytest.mark.integration
def test_bind_anchor_command_binds_the_receiver_from_the_storage_config(
    postgres_dsn: str, tls: Tls, receiver: Receiver, tmp_path: Path
) -> None:
    dsn_file = tmp_path / "dsn"
    dsn_file.write_text(postgres_dsn)
    config = tmp_path / "storage.json"
    config.write_text(
        json.dumps(
            {
                "database_dsn_file": str(dsn_file),
                "anchor": {
                    "profile_id": "launch-v2",
                    "ca_file": str(tls.ca),
                    "client_certificate_file": str(tls.certificate),
                    "client_private_key_file": str(tls.private_key),
                },
            }
        )
    )
    receiver.answer = "refuse"
    refused = _bind_command(
        "--receiver", receiver.url, "--verify", "--storage-config", str(config)
    )
    assert refused.returncode == 1
    assert "Anchor binding refused" in refused.stderr
    bindings = AnchorBindingRepository(Database(postgres_dsn))
    assert bindings.current() is None

    receiver.answer = "ack"
    bound = _bind_command(
        "--receiver", receiver.url, "--verify", "--storage-config", str(config)
    )
    assert bound.returncode == 0, bound.stderr
    assert "acknowledged sequence 0" in bound.stdout
    stored = bindings.current()
    assert stored is not None and stored.receiver_url == receiver.url
