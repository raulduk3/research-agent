"""One stored run executed end to end over real storage (#279).

Real PostgreSQL behind the real storage HTTP server, reached over mutually
authenticated TLS by two principals: the orchestrator the runner reads and
writes as, and the ``tools`` principal of the shared tool service it runs in
process. Only the agent model (a fixed script), the query embedding and the
page rasterizer are stand-ins.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.agents.loop import ModelResponse
from research_agent.agents.messages import Message
from research_agent.agents.runner import (
    ORCHESTRATOR_SCOPES,
    TOOL_SCOPES,
    RunRefused,
    build_tool_service,
    run_agent,
)
from research_agent.artifacts import ArtifactStore
from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import RunWorkerRecord, StorageClient
from research_agent.storage.database import Database
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.settlements import SettlementRepository

from support import RecordedResponseClient

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from service_harness import (  # noqa: E402
    ATTENTION,
    PRODUCER,
    SETTINGS,
    FakeRenderer,
    FixedEmbedder,
    World,
    WhitespaceTokenizer,
    deep_read_args,
    latex_paper,
    lookup_args,
    search_args,
    submit_args,
)
from test_http import Jobs, _tls_material  # noqa: E402

pytestmark = pytest.mark.integration

PROMPT = "Read the method section before answering."
GRAPH = {"incoming": ["123e4567-e89b-42d3-a456-426614174900"], "outgoing": []}


@pytest.fixture
def world(postgres_dsn: str, artifact_root: Path, tmp_path: Path) -> World:
    return World(Database(postgres_dsn), ArtifactStore(artifact_root), tmp_path)


@dataclass
class Principals:
    orchestrator: StorageClient
    tools: StorageClient


@contextmanager
def serve(world: World) -> Iterator[Principals]:
    """Storage over mTLS with an orchestrator and a tools certificate."""

    (
        server_context,
        _client_context,
        tools_fingerprint,
        _orchestrator_context,
        orchestrator_fingerprint,
        _no_certificate_context,
    ) = _tls_material(world.tmp_path)
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {
            tools_fingerprint: ServiceCapability(uuid4(), "tools", TOOL_SCOPES),
            orchestrator_fingerprint: ServiceCapability(
                uuid4(), "orchestrator", ORCHESTRATOR_SCOPES
            ),
        },
        tls_context=server_context,
        authorization=StorageAuthorization(world.database),
        artifacts=world.artifacts,
        documents=world.documents,
        queries=world.queries,
        runs=world.runs,
        submissions=world.submissions,
        paper_requests=world.paper_requests,
        settlements=SettlementRepository(world.database, world.store, **SETTINGS),
        trace=world.trace,
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    host, port = httpd.server_address[:2]

    def client(name: str, scopes: frozenset[str]) -> StorageClient:
        return StorageClient(
            connect_host=str(host),
            port=int(port),
            server_hostname="localhost",
            ca_file=world.tmp_path / "ca.pem",
            client_cert_file=world.tmp_path / f"{name}.pem",
            client_key_file=world.tmp_path / f"{name}.key",
            scopes=scopes,
            timeout_seconds=10,
        )

    try:
        yield Principals(
            orchestrator=client("wrong", ORCHESTRATOR_SCOPES),
            tools=client("client", TOOL_SCOPES),
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def seed_genome(world: World, run_id: str) -> None:
    """Store the genome whose prompt the run's configuration names."""

    configuration_id = _one(
        world, "SELECT configuration_id FROM runs WHERE id = %s", run_id
    )[0]
    PopulationStore(
        world.database,
        world.store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    ).record_seed(
        configuration_id=UUID(str(configuration_id)),
        genome=Genome(
            lineage_id="lineage-1",
            island="cs",
            infra_hash="b" * 64,
            emphasis={
                "prompt": PROMPT,
                "scan_policy": "breadth-first",
                "read_policy": "cite-first",
                "probability_assignment_rule": "single-sample",
            },
            founder=True,
            parent_hash=None,
        ),
        profile_hash="9" * 64,
        command_id=uuid4(),
    )


def _one(world: World, sql: str, run_id: str) -> tuple[Any, ...]:
    row = world.database.transaction(
        lambda connection: connection.execute(sql, (run_id,)).fetchone()
    )
    assert row is not None
    return tuple(row)


def _rows(world: World, sql: str, run_id: str) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in world.database.transaction(
            lambda connection: connection.execute(sql, (run_id,)).fetchall()
        )
    ]


def run_events(world: World, run_id: str) -> list[tuple[int, str, str]]:
    return [
        (int(row[0]), str(row[1]), str(row[2]))
        for row in _rows(
            world,
            """SELECT ordinal, kind, encode(payload_hash, 'hex') FROM run_events
               WHERE run_id = %s ORDER BY attempt, ordinal""",
            run_id,
        )
    ]


def count_tokens(messages: Sequence[Message]) -> int:
    return len(canonical_json([message.to_dict() for message in messages])) // 4


class ScriptedModel(RecordedResponseClient):
    """The recorded script, keeping every conversation it was sent."""

    def __init__(self, turns: list[dict[str, Any]]) -> None:
        super().__init__(turns)
        self.sent: list[list[dict[str, Any]]] = []

    def complete(
        self, messages: list[dict[str, Any]], *, max_generation_tokens: int
    ) -> ModelResponse:
        self.sent.append([dict(message) for message in messages])
        return super().complete(messages, max_generation_tokens=max_generation_tokens)


_INTENTS = {
    "query_cards": "scan",
    "neighbors": "scan",
    "graph": "compare",
    "deep_read": "read",
    "submit": "decide",
}


def call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """A scripted call as the model sends it: its note, intent and arguments."""

    envelope = {
        "note": f"Calling {name} for the paper under review.",
        "intent": _INTENTS[name],
        "arguments": arguments,
    }
    return {"tool_call_id": call_id, "name": name, "arguments": envelope}


def turn(*calls: dict[str, Any]) -> dict[str, Any]:
    return {"content": {}, "tool_calls": list(calls), "generated_tokens": 10}


def setup_run(world: World) -> tuple[str, str, str, str]:
    """A sealed snapshot of two papers and a run over the first."""

    attention = latex_paper(
        "Attention in small models",
        ATTENTION,
        {
            "Introduction": "We study attention in small models and report it.",
            "Method": "The method trains a sparse probe on frozen features.",
        },
        graph=GRAPH,
    )
    probes = latex_paper(
        "Probing frozen features",
        (0.8, 0.6, 0.0, 0.0),
        {"Introduction": "Probes read frozen features of a network."},
    )
    snapshot = world.seal_snapshot((attention, probes))
    run = world.create_run(snapshot, paper_id=attention.family)
    seed_genome(world, run)
    return snapshot, run, attention.family, probes.family


def execute(
    world: World, principals: Principals, run: str, model: ScriptedModel
) -> Any:
    service = build_tool_service(
        principals.tools,
        embedder=FixedEmbedder({"attention": ATTENTION}),
        tokenizer=WhitespaceTokenizer(),
        renderer=FakeRenderer(),
    )
    return run_agent(
        UUID(run),
        storage=principals.orchestrator,
        specifications=principals.tools,
        service=service,
        model_client=lambda run_id: model,
        count_tokens=count_tokens,
    )


def test_a_run_calls_each_tool_submits_and_settles(world: World) -> None:
    snapshot, run, paper, other = setup_run(world)
    evidence = world.documents.family_pin(snapshot, paper).card_hash
    model = ScriptedModel(
        [
            turn(
                call("c1", "query_cards", lookup_args(paper)),
                call("c2", "neighbors", {"paper_id": paper, "limit": 1}),
                call(
                    "c3",
                    "graph",
                    {"paper_id": paper, "direction": None, "limit": None},
                ),
            ),
            turn(
                call("c4", "deep_read", deep_read_args(paper, section_id="Method")),
                call("c5", "query_cards", search_args("attention", mode="overview")),
            ),
            turn(call("c6", "submit", submit_args(paper, evidence))),
        ]
    )

    with serve(world) as principals:
        outcome = execute(world, principals, run, model)

    assert (outcome.status, outcome.reason) == ("submitted", None)
    # The first message is the stored prompt, then the paper, its issued
    # questions, the stored budgets and the snapshot as storage describes it.
    system, first = model.sent[0]
    assert system == {"role": "system", "content": PROMPT}
    sealed_at = world.queries.snapshot(snapshot)["sealed_at"]  # type: ignore[index]
    assert first["content"]["paper_id"] == paper
    assert first["content"]["snapshot"] == {
        "snapshot_hash": snapshot,
        "sealed_at": sealed_at,
        "paper_count": 2,
    }
    assert {question["question_id"] for question in first["content"]["questions"]} == {
        "123e4567-e89b-42d3-a456-426614174100",
        "123e4567-e89b-42d3-a456-426614174101",
    }
    assert first["content"]["budgets"]["tool_calls"] == 12
    # Every request and response is in the run's events, by the exact hash
    # of the conversation sent and the response received.
    events = run_events(world, run)
    assert [kind for _, kind, _ in events] == ["request", "response"] * 3
    assert [ordinal for ordinal, _, _ in events] == list(range(6))
    assert [digest for _, kind, digest in events if kind == "request"] == [
        sha256_hex(canonical_json(sent)) for sent in model.sent
    ]
    # Each call went through the shared tool service and its trace.
    trace = world.trace_rows(run)
    assert [(row["tool"], row["decision"], row["outcome"]) for row in trace] == [
        ("query_cards", "admitted", "response"),
        ("neighbors", "admitted", "response"),
        ("graph", "admitted", "response"),
        ("deep_read", "admitted", "response"),
        ("query_cards", "admitted", "response"),
        ("submit", "admitted", "response"),
    ]
    assert other in {
        result["paper_id"] for result in _tool_answer(model, "c5")["data"]["results"]
    }
    assert world.count("run_submissions", run) == 1
    assert _one(
        world, "SELECT state FROM run_terminal_states WHERE run_id = %s", run
    ) == ("submitted",)
    assert _one(
        world,
        """SELECT provider, model, input_tokens, output_tokens, usage_source
           FROM run_settlements WHERE run_id = %s""",
        run,
    ) == (
        "zai",
        "glm-5.3-flash",
        outcome.input_tokens,
        30,
        "loop_count",
    )


def _tool_answer(model: ScriptedModel, call_id: str) -> dict[str, Any]:
    for message in model.sent[-1]:
        if message["role"] == "tool" and message["tool_call_id"] == call_id:
            return dict(message["content"])
    raise AssertionError(f"no tool response for {call_id}")


def test_a_run_that_exhausts_its_tool_calls_is_voided_and_settled(
    world: World,
) -> None:
    _snapshot, run, paper, _other = setup_run(world)
    model = ScriptedModel(
        [
            turn(
                *(
                    call(f"c{index}", "neighbors", {"paper_id": paper, "limit": 1})
                    for index in range(13)
                )
            )
        ]
    )

    with serve(world) as principals:
        outcome = execute(world, principals, run, model)
        # An ended run is refused before the model is built or anything written.
        with pytest.raises(RunRefused, match="already ended"):
            execute(world, principals, run, ScriptedModel([]))

    assert (outcome.status, outcome.reason) == (
        "void",
        "budget_exhausted:tool_calls",
    )
    # Twelve calls were answered; the thirteenth was never dispatched.
    assert [(row["decision"], row["outcome"]) for row in world.trace_rows(run)] == [
        ("admitted", "response")
    ] * 12
    assert world.count("run_submissions", run) == 0
    assert _one(
        world,
        """SELECT state, reason, last_event_ordinal
           FROM run_terminal_states WHERE run_id = %s""",
        run,
    ) == ("void", "budget_exhausted:tool_calls", 1)
    assert _one(
        world,
        "SELECT output_tokens, usage_source FROM run_settlements WHERE run_id = %s",
        run,
    ) == (10, "loop_count")
    assert len(run_events(world, run)) == 2


class UnsealedSnapshot:
    """The orchestrator's storage, but the run names a snapshot never sealed.

    Storage refuses to create such a run, so only the worker record is
    changed; the snapshot read and every write still go to real storage.
    """

    def __init__(self, storage: StorageClient) -> None:
        self._storage = storage

    def read_run_worker(self, run_id: UUID) -> RunWorkerRecord:
        return replace(self._storage.read_run_worker(run_id), snapshot_hash="7" * 64)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._storage, name)


def test_a_run_naming_a_snapshot_storage_does_not_hold_is_refused(
    world: World,
) -> None:
    _snapshot, run, _paper, _other = setup_run(world)
    model = ScriptedModel([])

    with serve(world) as principals:
        service = build_tool_service(
            principals.tools,
            embedder=FixedEmbedder({}),
            tokenizer=WhitespaceTokenizer(),
            renderer=FakeRenderer(),
        )
        with pytest.raises(RunRefused, match="does not hold"):
            run_agent(
                UUID(run),
                storage=UnsealedSnapshot(principals.orchestrator),
                specifications=principals.tools,
                service=service,
                model_client=lambda run_id: model,
                count_tokens=count_tokens,
            )

    assert model.sent == []
    assert run_events(world, run) == []
    assert (
        _rows(world, "SELECT 1 FROM run_terminal_states WHERE run_id = %s", run) == []
    )
    assert _rows(world, "SELECT 1 FROM run_settlements WHERE run_id = %s", run) == []
