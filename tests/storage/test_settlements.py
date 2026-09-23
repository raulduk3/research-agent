"""Settled inference spend: one row per run, and the owner's cost windows (#251)."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.agents.budgets import TOOL_CALLS_LIMIT, RunBudget
from research_agent.agents.loop import (
    ModelResponse,
    RunOutcome,
    TokenUsage,
    ToolCall,
    ToolOutcome,
    run_conversation,
)
from research_agent.agents.messages import (
    Message,
    SnapshotDescription,
    assemble_system_prompt,
    build_initial_message,
)
from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_loads
from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient, StorageClientError
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.settlements import SettlementRepository
from test_exclusions import PRODUCER, World, identity, world
from test_http import Jobs, _tls_material

pytestmark = pytest.mark.integration

__all__ = ["world"]

SETTINGS = {
    "producer": PRODUCER,
    "config_hash": "c" * 64,
    "retention_policy_hash": "d" * 64,
}
ALLOWED_TOOLS = frozenset({"query_cards", "submit"})
CONTEXT_TOKENS = 100


def repository(world: World, artifact_root: Path) -> SettlementRepository:
    return SettlementRepository(
        Database(world.dsn), ArtifactStore(artifact_root), **SETTINGS
    )


def settle(
    settlements: SettlementRepository,
    run_id: UUID,
    *,
    input_tokens: int = 1200,
    output_tokens: int = 300,
    usage_source: str = "loop_count",
) -> dict[str, Any]:
    response = settlements.execute(
        "record",
        identity=identity(),
        payload={
            "run_id": str(run_id),
            "provider": "provider-a",
            "model": "model-a",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "usage_source": usage_source,
        },
    )
    return dict(canonical_loads(response.body)["data"])


def rows(dsn: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as connection:
        return connection.execute(
            """SELECT run_id, input_tokens, output_tokens, usage_source, cost_micros
               FROM run_settlements ORDER BY settled_at"""
        ).fetchall()


def ledgered(dsn: str) -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT count(*) FROM ledger_records WHERE event_kind='run_settled'"
        ).fetchone()
    assert row is not None
    return int(row[0])


def backdate(dsn: str, run_id: UUID, settled_at: str, cost_micros: int | None) -> None:
    """Move a settlement into another window and give it a price.

    Settlements are immutable to every role, so the test lifts the trigger
    for this one statement; nothing in the application can do this.
    """

    with psycopg.connect(dsn) as connection:
        connection.execute(
            "ALTER TABLE run_settlements DISABLE TRIGGER run_settlements_immutable"
        )
        connection.execute(
            "UPDATE run_settlements SET settled_at=%s, cost_micros=%s WHERE run_id=%s",
            (settled_at, cost_micros, run_id),
        )
        connection.execute(
            "ALTER TABLE run_settlements ENABLE TRIGGER run_settlements_immutable"
        )


class _Sink:
    def append(
        self, *, run_id: str, attempt: int, ordinal: int, kind: str, payload: bytes
    ) -> None:
        return None


class _Client:
    """One scripted response per call; raises once the script runs out."""

    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self._responses = list(responses)

    def complete(
        self, messages: list[dict[str, Any]], *, max_generation_tokens: int
    ) -> ModelResponse:
        if not self._responses:
            raise ConnectionError("provider unreachable")
        return self._responses.pop(0)


class _Dispatcher:
    def dispatch(self, call: ToolCall, *, run_id: str) -> ToolOutcome:
        return ToolOutcome(status="ok", data={"cards": []})


def _query(generated_tokens: int, usage: TokenUsage | None = None) -> ModelResponse:
    return ModelResponse(
        content={"note": "looking"},
        tool_calls=(ToolCall("call-1", "query_cards", {"paper_ids": []}),),
        generated_tokens=generated_tokens,
        usage=usage,
    )


def _converse(
    run_id: UUID,
    client: _Client,
    budget: RunBudget,
    settle_with: Any,
) -> RunOutcome:
    system: Message = assemble_system_prompt("Read the paper.")
    initial: Message = build_initial_message(
        paper_id="paper-a",
        questions=[],
        budgets={"tool_calls": TOOL_CALLS_LIMIT},
        snapshot=SnapshotDescription(
            snapshot_hash="a" * 64,
            sealed_at="2027-01-01T00:00:00.000000Z",
            paper_count=1,
        ),
    )
    return run_conversation(
        run_id=str(run_id),
        attempt=1,
        system_message=system,
        initial_message=initial,
        allowed_tools=ALLOWED_TOOLS,
        client=client,
        dispatcher=_Dispatcher(),
        sink=_Sink(),
        count_tokens=lambda _messages: CONTEXT_TOKENS,
        budget=budget,
        elapsed_seconds=lambda: 0.0,
        settle=settle_with,
    )


def _settling(settlements: SettlementRepository, run_id: UUID) -> Any:
    """The caller's settle callable: the loop hands over its outcome once."""

    def write(outcome: RunOutcome) -> None:
        settle(
            settlements,
            run_id,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            usage_source=outcome.usage_source,
        )

    return write


def test_a_run_ended_by_budget_exhaustion_still_settles_what_it_received(
    world: World, artifact_root: Path
) -> None:
    settlements = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")
    # One tool call left: the second response's call exhausts the budget.
    budget = RunBudget(tool_calls=TOOL_CALLS_LIMIT - 1)

    outcome = _converse(
        run_id,
        _Client([_query(40), _query(25)]),
        budget,
        _settling(settlements, run_id),
    )

    assert (outcome.status, outcome.reason) == ("void", "budget_exhausted:tool_calls")
    assert rows(world.dsn) == [
        (run_id, 2 * CONTEXT_TOKENS, 40 + 25, "loop_count", None)
    ]
    assert ledgered(world.dsn) == 1


def test_a_run_whose_provider_call_raises_settles_before_the_error_propagates(
    world: World, artifact_root: Path
) -> None:
    settlements = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")
    seen: list[RunOutcome] = []

    def write(outcome: RunOutcome) -> None:
        seen.append(outcome)
        _settling(settlements, run_id)(outcome)

    usage = TokenUsage(input_tokens=130, output_tokens=41)
    with pytest.raises(ConnectionError):
        _converse(run_id, _Client([_query(40, usage)]), RunBudget(), write)

    [outcome] = seen
    assert (outcome.status, outcome.reason) == ("void", "loop_error")
    # The request of the failed second call is recorded, its response never came.
    assert outcome.exchange_count == 3
    assert rows(world.dsn) == [(run_id, 130, 41, "provider", None)]


def test_one_response_without_a_usage_record_makes_the_run_a_loop_count(
    world: World, artifact_root: Path
) -> None:
    settlements = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")
    budget = RunBudget(tool_calls=TOOL_CALLS_LIMIT - 1)

    _converse(
        run_id,
        _Client([_query(40, TokenUsage(130, 41)), _query(25)]),
        budget,
        _settling(settlements, run_id),
    )

    assert rows(world.dsn) == [
        (run_id, 130 + CONTEXT_TOKENS, 41 + 25, "loop_count", None)
    ]


def test_a_run_settles_once_and_the_row_is_immutable(
    world: World, artifact_root: Path
) -> None:
    settlements = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")

    data = settle(settlements, run_id)

    assert data["run_id"] == str(run_id)
    assert data["receipt"] is not None
    with pytest.raises(StateConflict):
        settle(settlements, run_id)
    with pytest.raises(UnavailableInput):
        settle(settlements, uuid4())
    with pytest.raises(ContractValidationError):
        settle(settlements, run_id, usage_source="quoted")
    with psycopg.connect(world.dsn) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute("UPDATE run_settlements SET input_tokens = 0")
    assert len(rows(world.dsn)) == 1
    assert ledgered(world.dsn) == 1


def test_costs_sum_priced_rows_and_report_unpriced_tokens_per_window(
    world: World, artifact_root: Path
) -> None:
    database, store = Database(world.dsn), ArtifactStore(artifact_root)
    island_configuration = uuid4()
    PopulationStore(database, store, **SETTINGS).record_seed(
        configuration_id=island_configuration,
        genome=Genome(
            lineage_id="lineage-1",
            island="cs",
            infra_hash="b" * 64,
            emphasis={
                "prompt": "prompt",
                "scan_policy": "scan",
                "read_policy": "read",
                "probability_assignment_rule": "one sample",
            },
            founder=True,
        ),
        profile_hash="a" * 64,
        command_id=uuid4(),
    )
    unseeded = uuid4()
    settlements = repository(world, artifact_root)
    today_priced = world.run(island_configuration, "p1")
    today_unpriced = world.run(unseeded, "p2")
    earlier_this_month = world.run(island_configuration, "p3")
    last_month = world.run(island_configuration, "p4")
    tomorrow = world.run(unseeded, "p5")
    for run_id in (
        today_priced,
        today_unpriced,
        earlier_this_month,
        last_month,
        tomorrow,
    ):
        settle(settlements, run_id, input_tokens=1000, output_tokens=100)
    backdate(world.dsn, today_priced, "2026-09-23T08:00:00Z", 1500)
    backdate(world.dsn, today_unpriced, "2026-09-23T23:59:59Z", None)
    backdate(world.dsn, earlier_this_month, "2026-09-01T00:00:00Z", 700)
    backdate(world.dsn, last_month, "2026-08-31T23:59:59Z", 9000)
    backdate(world.dsn, tomorrow, "2026-09-24T00:00:00Z", None)

    costs = settlements.costs("2026-09-23")

    assert (costs["day"], costs["month"]) == ("2026-09-23", "2026-09")
    assert costs["day_totals"] == {
        "priced_micros": 1500,
        "priced_runs": 1,
        "unpriced_runs": 1,
        "unpriced_input_tokens": 1000,
        "unpriced_output_tokens": 100,
    }
    assert costs["month_totals"] == {
        "priced_micros": 1500 + 700,
        "priced_runs": 2,
        "unpriced_runs": 1,
        "unpriced_input_tokens": 1000,
        "unpriced_output_tokens": 100,
    }
    assert [(row["island"], row["priced_micros"]) for row in costs["islands"]] == [
        ("cs", 2200),
        (None, 0),
    ]
    by_configuration = {row["configuration_id"]: row for row in costs["configurations"]}
    assert by_configuration[str(island_configuration)]["priced_runs"] == 2
    assert by_configuration[str(unseeded)]["unpriced_runs"] == 1
    assert by_configuration[str(unseeded)]["island"] is None
    with pytest.raises(ContractValidationError):
        settlements.costs("20260923")


@pytest.fixture
def served(
    world: World, artifact_root: Path, tmp_path: Path
) -> Iterator[tuple[StorageClient, StorageClient]]:
    """Orchestrator and owner identities, each holding both scopes, so only
    the role decides what each may do."""

    (
        server_context,
        _client_context,
        orchestrator_fingerprint,
        _wrong_context,
        owner_fingerprint,
        _no_certificate_context,
    ) = _tls_material(tmp_path)
    scopes = frozenset({"settlements:record", "owner:read"})
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
        authorization=StorageAuthorization(Database(world.dsn)),
        settlements=repository(world, artifact_root),
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


def test_only_the_orchestrator_settles_and_only_the_owner_reads_costs(
    world: World, served: tuple[StorageClient, StorageClient]
) -> None:
    orchestrator, owner = served
    run_id = world.run(uuid4(), "p1")

    with pytest.raises(StorageClientError) as refused_write:
        owner.record_settlement(
            run_id=run_id,
            provider="provider-a",
            model="model-a",
            input_tokens=10,
            output_tokens=5,
            usage_source="loop_count",
            command_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    assert refused_write.value.status_code == 403
    recorded = orchestrator.record_settlement(
        run_id=run_id,
        provider="provider-a",
        model="model-a",
        input_tokens=10,
        output_tokens=5,
        usage_source="loop_count",
        command_id=uuid4(),
        request_id=uuid4(),
        idempotency_key=uuid4(),
    )
    assert recorded.data["run_id"] == str(run_id)

    with pytest.raises(StorageClientError) as refused_read:
        orchestrator.read_costs("2026-09-23")
    assert refused_read.value.status_code == 403
    today = datetime.now(timezone.utc).date().isoformat()
    read = owner.read_costs(today).data
    assert read["day_totals"]["unpriced_runs"] == 1
    assert read["day_totals"]["unpriced_input_tokens"] == 10
