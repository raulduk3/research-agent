"""Paper requests a run's tools record for families its snapshot lacks (decision 0025)."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.agents.budgets import RunBudget
from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_loads
from research_agent.contracts.tools import PAPER_REQUESTS_PER_RUN
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient, StorageClientError
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.requests import (
    MAX_ACQUISITIONS_PER_UTC_DAY,
    PaperRequestRepository,
)
from research_agent.tools.dispatch import dispatch_tool
from tests.storage.test_exclusions import PRODUCER, World, identity, world
from tests.storage.test_http import Jobs, _tls_material

pytestmark = pytest.mark.integration

__all__ = ["world"]

SCOPES = frozenset(
    {"paper_requests:record", "paper_requests:read", "paper_requests:transition"}
)


def repository(world: World, artifact_root: Path) -> PaperRequestRepository:
    return PaperRequestRepository(
        Database(world.dsn),
        ArtifactStore(artifact_root),
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )


def record(
    requests: PaperRequestRepository,
    run_id: UUID,
    family_id: UUID,
    snapshot_hash: str,
) -> dict[str, Any]:
    response = requests.execute(
        "record",
        identity=identity(),
        payload={
            "run_id": str(run_id),
            "family_id": str(family_id),
            "snapshot_hash": snapshot_hash,
        },
    )
    return dict(canonical_loads(response.body)["data"])


def rows(dsn: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as connection:
        return connection.execute(
            """SELECT family_id, run_id, encode(snapshot_hash,'hex'), status
               FROM paper_requests ORDER BY requested_at"""
        ).fetchall()


def ledger_events(dsn: str, kind: str = "paper_requested") -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT count(*) FROM ledger_records WHERE event_kind=%s", (kind,)
        ).fetchone()
    assert row is not None
    return int(row[0])


def move(
    requests: PaperRequestRepository,
    request_id: str,
    status: str,
    *,
    reason: str | None = None,
    paper_version_id: str | None = None,
) -> dict[str, Any]:
    response = requests.execute(
        "transition",
        identity=identity(),
        payload={
            "request_id": request_id,
            "status": status,
            "reason": reason,
            "paper_version_id": paper_version_id,
        },
    )
    return dict(canonical_loads(response.body)["data"])


class _Lookup:
    def __init__(self, snapshot_hash: str) -> None:
        self.snapshot_hash = snapshot_hash

    def snapshot_hash_for(self, run_id: str) -> str:
        return self.snapshot_hash

    def allowed_tools_for(self, run_id: str) -> frozenset[str]:
        return frozenset({"deep_read", "graph"})

    def paper_id_for(self, run_id: str) -> str:
        return str(uuid4())

    def issued_question_ids_for(self, run_id: str) -> frozenset[str]:
        return frozenset()


class _EmptySnapshot:
    def holds_family(self, snapshot_hash: str, family_id: str) -> bool:
        return False


def _unreachable(arguments: Mapping[str, Any], budget: RunBudget) -> dict[str, Any]:
    raise AssertionError("a family outside the snapshot never reaches its handler")


@pytest.fixture
def served(
    world: World, artifact_root: Path, tmp_path: Path
) -> Iterator[tuple[StorageClient, StorageClient]]:
    """A storage server with a tools and an ingest identity, both holding
    every paper-request scope, so only the role decides what each may do."""

    (
        server_context,
        _client_context,
        tools_fingerprint,
        _wrong_context,
        ingest_fingerprint,
        _no_certificate_context,
    ) = _tls_material(tmp_path)
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {
            tools_fingerprint: ServiceCapability(uuid4(), "tools", SCOPES),
            ingest_fingerprint: ServiceCapability(uuid4(), "ingest", SCOPES),
        },
        tls_context=server_context,
        authorization=StorageAuthorization(Database(world.dsn)),
        paper_requests=repository(world, artifact_root),
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    host, port = httpd.server_address[:2]

    def client(cert: str) -> StorageClient:
        return StorageClient(
            connect_host=str(host),
            port=int(port),
            server_hostname="localhost",
            ca_file=tmp_path / "ca.pem",
            client_cert_file=tmp_path / f"{cert}.pem",
            client_key_file=tmp_path / f"{cert}.key",
            scopes=SCOPES,
            timeout_seconds=5,
        )

    try:
        yield client("client"), client("wrong")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def envelope(arguments: dict[str, Any]) -> dict[str, Any]:
    """*arguments* inside the note and intent envelope the model sends (AG-39)."""

    return {
        "note": "reading the introduction",
        "intent": "read",
        "arguments": arguments,
    }


def deep_read(
    world: World, tools: StorageClient, run_id: UUID, family_id: UUID
) -> dict[str, Any]:
    response = dispatch_tool(
        tool="deep_read",
        raw_call=envelope(
            {
                "paper_id": str(family_id),
                "section_id": "introduction",
                "pages": None,
                "next_span": None,
            }
        ),
        run_id=str(run_id),
        requested_snapshot_id=world.snapshot_hash,
        lookup=_Lookup(world.snapshot_hash),
        handlers={"deep_read": _unreachable},
        membership=_EmptySnapshot(),
        paper_requests=tools,
        budget=RunBudget(),
        context_tokens=0,
    )
    assert response["status"] == "ok"
    assert response["data"]["kind"] == "not_in_snapshot"
    assert response["data"]["paper_id"] == str(family_id)
    return dict(response["data"]["request"])


def test_a_deep_read_outside_the_snapshot_records_once_then_dedupes_then_caps(
    world: World, served: tuple[StorageClient, StorageClient]
) -> None:
    tools, ingest = served
    run_id = world.run(uuid4(), "p1")
    first = uuid4()

    answer = deep_read(world, tools, run_id, first)
    assert answer["outcome"] == "requested"
    assert rows(world.dsn) == [(first, run_id, world.snapshot_hash, "requested")]
    assert ledger_events(world.dsn) == 1

    again = deep_read(world, tools, run_id, first)
    assert again == {"outcome": "already_requested", "request_id": answer["request_id"]}
    assert len(rows(world.dsn)) == 1
    assert ledger_events(world.dsn) == 1

    for _ in range(PAPER_REQUESTS_PER_RUN - 1):
        assert deep_read(world, tools, run_id, uuid4())["outcome"] == "requested"
    past_cap = uuid4()
    over = deep_read(world, tools, run_id, past_cap)
    assert over == {"outcome": "request_budget_exhausted", "request_id": None}
    # The refusal is recorded as a row of its own, never silently dropped.
    assert len(rows(world.dsn)) == PAPER_REQUESTS_PER_RUN + 1
    assert rows(world.dsn)[-1] == (past_cap, run_id, world.snapshot_hash, "refused")
    assert ledger_events(world.dsn) == PAPER_REQUESTS_PER_RUN + 1

    # The cap is per run: another run on the same snapshot still asks.
    other_run = world.run(uuid4(), "p1")
    assert deep_read(world, tools, other_run, uuid4())["outcome"] == "requested"

    listed = ingest.list_open_paper_requests()
    assert len(listed) == PAPER_REQUESTS_PER_RUN + 1
    assert listed[0].request_id == UUID(answer["request_id"])
    assert listed[0].family_id == first
    assert listed[0].run_id == run_id
    assert listed[0].snapshot_hash == world.snapshot_hash
    assert listed[0].status == "requested"


def test_a_run_can_neither_read_nor_write_requests_outside_its_roles(
    world: World, served: tuple[StorageClient, StorageClient]
) -> None:
    tools, ingest = served
    run_id = world.run(uuid4(), "p1")

    # The tool service's identity holds the read scope too, but its role is
    # not ingest, so the list is not there for it.
    with pytest.raises(StorageClientError) as refused_read:
        tools.list_open_paper_requests()
    assert refused_read.value.status_code == 404

    with pytest.raises(StorageClientError) as refused_write:
        ingest.record_paper_request(
            run_id=run_id,
            family_id=uuid4(),
            snapshot_hash=world.snapshot_hash,
            command_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    assert refused_write.value.status_code == 403
    assert rows(world.dsn) == []


def test_a_request_must_name_the_runs_own_snapshot(
    world: World, artifact_root: Path
) -> None:
    requests = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")
    with pytest.raises(StateConflict, match="snapshot other than"):
        record(requests, run_id, uuid4(), "0" * 64)
    assert rows(world.dsn) == []


def test_a_family_the_snapshot_holds_is_never_requested(
    world: World, artifact_root: Path
) -> None:
    requests = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")
    held = uuid4()
    with psycopg.connect(world.dsn) as connection:
        connection.execute(
            """INSERT INTO snapshot_items(snapshot_hash, paper_family_id,
                   paper_version_id, card_hash)
               SELECT decode(%s,'hex'), %s, %s, hash FROM artifacts LIMIT 1""",
            (world.snapshot_hash, held, uuid4()),
        )
    with pytest.raises(StateConflict, match="holds the requested family"):
        record(requests, run_id, held, world.snapshot_hash)
    assert rows(world.dsn) == []


def test_a_failed_request_may_be_asked_again(world: World, artifact_root: Path) -> None:
    requests = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")
    family = uuid4()
    first = record(requests, run_id, family, world.snapshot_hash)
    move(requests, first["request_id"], "acquiring")
    move(requests, first["request_id"], "failed", reason="no source")
    second = record(requests, run_id, family, world.snapshot_hash)
    assert second["outcome"] == "requested"
    assert second["request_id"] != first["request_id"]
    assert requests.open_requests()[0]["request_id"] == second["request_id"]


def test_each_transition_is_ledgered_and_an_acquired_row_names_its_paper(
    world: World, artifact_root: Path
) -> None:
    requests = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")
    first = record(requests, run_id, uuid4(), world.snapshot_hash)["request_id"]
    second = record(requests, run_id, uuid4(), world.snapshot_hash)["request_id"]
    paper = str(uuid4())

    assert move(requests, first, "acquiring")["status"] == "acquiring"
    # Still open while acquiring, so a restarted stage resumes it.
    assert [r["status"] for r in requests.open_requests()] == [
        "acquiring",
        "requested",
    ]
    acquired = move(requests, first, "acquired", paper_version_id=paper)
    assert (acquired["status"], acquired["paper_version_id"]) == ("acquired", paper)
    refused = move(requests, second, "refused", reason="unresolved_family")
    assert (refused["status"], refused["reason"]) == ("refused", "unresolved_family")

    assert requests.open_requests() == ()
    assert ledger_events(world.dsn, "paper_request_transitioned") == 3
    with psycopg.connect(world.dsn) as connection:
        stored = connection.execute(
            """SELECT status, paper_version_id, started_at IS NOT NULL,
                      last_ledger_sequence > ledger_sequence
               FROM paper_requests WHERE id=%s""",
            (first,),
        ).fetchone()
    assert stored == ("acquired", UUID(paper), True, True)


def test_a_transition_from_the_wrong_status_is_refused_and_records_nothing(
    world: World, artifact_root: Path
) -> None:
    requests = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")
    request_id = record(requests, run_id, uuid4(), world.snapshot_hash)["request_id"]

    with pytest.raises(StateConflict, match="requested paper request cannot become"):
        move(requests, request_id, "acquired", paper_version_id=str(uuid4()))
    with pytest.raises(StateConflict):
        move(requests, request_id, "failed", reason="no source")
    move(requests, request_id, "acquiring")
    with pytest.raises(StateConflict, match="acquiring paper request cannot become"):
        move(requests, request_id, "acquiring")
    assert ledger_events(world.dsn, "paper_request_transitioned") == 1


def test_the_first_acquisition_past_the_days_budget_is_refused_and_recorded(
    world: World, artifact_root: Path
) -> None:
    requests = repository(world, artifact_root)
    ids: list[str] = []
    while len(ids) <= MAX_ACQUISITIONS_PER_UTC_DAY:
        run_id = world.run(uuid4(), "p1")
        for _ in range(PAPER_REQUESTS_PER_RUN):
            if len(ids) <= MAX_ACQUISITIONS_PER_UTC_DAY:
                answer = record(requests, run_id, uuid4(), world.snapshot_hash)
                ids.append(answer["request_id"])

    started = [move(requests, request_id, "acquiring") for request_id in ids]
    assert {answer["status"] for answer in started[:-1]} == {"acquiring"}
    assert started[-1]["status"] == "refused"
    assert started[-1]["reason"] == "request_budget_exhausted"
    # Finishing an acquisition does not free a place in the day's budget.
    move(requests, ids[0], "acquired", paper_version_id=str(uuid4()))
    with psycopg.connect(world.dsn) as connection:
        row = connection.execute(
            "SELECT status, reason FROM paper_requests WHERE id=%s", (ids[-1],)
        ).fetchone()
    assert row == ("refused", "request_budget_exhausted")
    assert (
        ledger_events(world.dsn, "paper_request_transitioned")
        == MAX_ACQUISITIONS_PER_UTC_DAY + 2
    )


def test_only_ingest_moves_a_request_over_http(
    world: World, served: tuple[StorageClient, StorageClient]
) -> None:
    tools, ingest = served
    run_id = world.run(uuid4(), "p1")
    request_id = UUID(deep_read(world, tools, run_id, uuid4())["request_id"])

    def begin(client: StorageClient) -> dict[str, Any]:
        return dict(
            client.transition_paper_request(
                paper_request_id=request_id,
                status="acquiring",
                reason=None,
                paper_version_id=None,
                command_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            ).data
        )

    with pytest.raises(StorageClientError) as refused:
        begin(tools)
    assert refused.value.status_code == 403
    assert rows(world.dsn)[0][3] == "requested"

    answer = begin(ingest)
    assert answer["status"] == "acquiring"
    assert answer["receipt"] is not None
    assert ingest.list_open_paper_requests()[0].status == "acquiring"
