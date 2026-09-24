"""A run's recorded resources: once, after its settlement, summing to it (#330)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_loads
from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient, StorageClientError
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.resources import ResourceRepository
from research_agent.storage.trace import TraceRepository
from tests.storage.test_exclusions import World, identity, world
from tests.storage.test_http import Jobs, _tls_material
from tests.storage.test_settlements import SETTINGS, repository, settle

pytestmark = pytest.mark.integration

__all__ = ["world"]


def resources(world: World, artifact_root: Path) -> ResourceRepository:
    return ResourceRepository(
        Database(world.dsn), ArtifactStore(artifact_root), **SETTINGS
    )


def model_call(
    turn_index: int, input_tokens: int, output_tokens: int
) -> dict[str, Any]:
    return {
        "turn_index": turn_index,
        "model": "model-a",
        "revision": None,
        "input_tokens": input_tokens,
        "cached_input_tokens": input_tokens // 2,
        "output_tokens": output_tokens,
        "latency_ms": 850,
        "bytes_sent": 4096,
        "bytes_received": 512,
    }


def record(run_id: UUID, calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "started_at": "2099-01-01T00:00:00.000000Z",
        "first_model_call_at": "2099-01-01T00:00:01.000000Z" if calls else None,
        "last_model_call_at": "2099-01-01T00:00:09.000000Z" if calls else None,
        "ended_at": "2099-01-01T00:00:10.000000Z",
        "model_endpoint": "https://api.example/v4/chat/completions",
        "tool_service": "tools@127.0.0.1:8443",
        "model_calls": calls,
        "process": {
            "kind": "in_process",
            "cpu_user_ms": 1200,
            "cpu_system_ms": 300,
            "peak_rss_bytes": 200 * 1024 * 1024,
            "load_start": [150, 120, 100],
            "load_end": [180, 130, 100],
        },
        "image_digest": None,
        "run_log": None,
    }


def test_a_settled_runs_resources_sum_to_its_settlement_and_read_back(
    world: World, artifact_root: Path
) -> None:
    run_id = world.run(uuid4(), "p1")
    settle(
        repository(world, artifact_root),
        run_id,
        input_tokens=1200,
        output_tokens=300,
        usage_source="provider",
    )
    owner = resources(world, artifact_root)
    calls = [model_call(0, 500, 100), model_call(1, 700, 200)]
    response = owner.execute(
        "record", identity=identity(), payload=record(run_id, calls)
    )
    assert canonical_loads(response.body)["data"]["run_id"] == str(run_id)

    read = owner.read(str(run_id))
    assert read is not None
    assert read["tokens"] == {
        "input_tokens": 1200,
        "cached_input_tokens": 600,
        "output_tokens": 300,
    }
    assert read["wall_ms"] == 10_000
    assert read["first_model_call_to_end_ms"] == 9_000
    assert read["model_calls"] == calls
    assert read["tool_calls"] == []
    with psycopg.connect(world.dsn) as connection:
        stored = connection.execute(
            """SELECT r.input_tokens, r.output_tokens, s.input_tokens, s.output_tokens
               FROM run_resources r JOIN run_settlements s USING (run_id)
               WHERE run_id=%s""",
            (run_id,),
        ).fetchone()
        assert stored == (1200, 300, 1200, 300)
        events = connection.execute(
            """SELECT count(*) FROM ledger_records l JOIN run_resources r
               ON r.ledger_sequence = l.sequence
               WHERE l.event_kind='run_resources_recorded'"""
        ).fetchone()
        assert events == (1,)
        with pytest.raises(psycopg.Error):
            connection.execute("UPDATE run_resources SET input_tokens=0")


def test_calls_that_do_not_sum_to_a_provider_settlement_are_refused(
    world: World, artifact_root: Path
) -> None:
    run_id = world.run(uuid4(), "p1")
    settle(
        repository(world, artifact_root),
        run_id,
        input_tokens=1200,
        output_tokens=300,
        usage_source="provider",
    )
    with pytest.raises(StateConflict, match="sum"):
        resources(world, artifact_root).execute(
            "record",
            identity=identity(),
            payload=record(run_id, [model_call(0, 1199, 300)]),
        )
    assert world.count("run_resources") == 0


def test_resources_wait_for_the_settlement_and_are_recorded_once(
    world: World, artifact_root: Path
) -> None:
    run_id = world.run(uuid4(), "p1")
    owner = resources(world, artifact_root)
    with pytest.raises(UnavailableInput):
        owner.execute("record", identity=identity(), payload=record(run_id, []))
    assert owner.read(str(run_id)) is None
    settle(repository(world, artifact_root), run_id, input_tokens=0, output_tokens=0)
    owner.execute("record", identity=identity(), payload=record(run_id, []))
    with pytest.raises(StateConflict):
        owner.execute("record", identity=identity(), payload=record(run_id, []))


def test_out_of_order_instants_and_misnumbered_calls_are_invalid(
    world: World, artifact_root: Path
) -> None:
    run_id = world.run(uuid4(), "p1")
    owner = resources(world, artifact_root)
    late = record(run_id, [model_call(0, 1, 1)])
    late["first_model_call_at"] = "2099-01-01T00:00:11.000000Z"
    skipped = record(run_id, [model_call(1, 1, 1)])
    for payload in (late, skipped):
        with pytest.raises(ContractValidationError):
            owner.execute("record", identity=identity(), payload=payload)


@pytest.fixture
def served(
    world: World, artifact_root: Path, tmp_path: Path
) -> Iterator[tuple[StorageClient, StorageClient]]:
    """Orchestrator and owner identities holding the same scopes, so only
    the role decides what each may do."""

    server_context, _, orchestrator_fingerprint, _, owner_fingerprint, _ = (
        _tls_material(tmp_path)
    )
    scopes = frozenset({"settlements:record", "resources:record", "owner:read"})
    database = Database(world.dsn)
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {
            orchestrator_fingerprint: ServiceCapability(
                uuid4(), "orchestrator", scopes
            ),
            owner_fingerprint: ServiceCapability(uuid4(), "owner", scopes),
        },
        tls_context=server_context,
        authorization=StorageAuthorization(database),
        settlements=repository(world, artifact_root),
        trace=TraceRepository(database, ArtifactStore(artifact_root), **SETTINGS),
        resources=resources(world, artifact_root),
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
            scopes=scopes,
            timeout_seconds=5,
        )

    try:
        yield client("client"), client("wrong")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def _ids() -> dict[str, UUID]:
    return {"command_id": uuid4(), "request_id": uuid4(), "idempotency_key": uuid4()}


def test_only_the_orchestrator_records_and_the_trace_read_carries_them(
    world: World, served: tuple[StorageClient, StorageClient]
) -> None:
    orchestrator, owner = served
    run_id = world.run(uuid4(), "p1")
    orchestrator.record_settlement(
        run_id=run_id,
        provider="provider-a",
        model="model-a",
        input_tokens=0,
        output_tokens=0,
        usage_source="provider",
        **_ids(),
    )
    assert owner.read_run_trace(run_id).data["resources"] is None
    body = {key: value for key, value in record(run_id, []).items() if key != "run_id"}
    with pytest.raises(StorageClientError) as refused:
        owner.record_run_resources(run_id=run_id, resources=body, **_ids())
    assert refused.value.status_code == 403
    orchestrator.record_run_resources(run_id=run_id, resources=body, **_ids())

    section = owner.read_run_trace(run_id).data["resources"]
    assert section["model_endpoint"] == "https://api.example/v4/chat/completions"
    assert section["queue_wait_ms"] >= 0
    with pytest.raises(StorageClientError) as private:
        orchestrator.read_run_trace(run_id)
    assert private.value.status_code == 403
