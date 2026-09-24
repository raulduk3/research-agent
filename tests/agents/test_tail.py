"""The tail prints a run's stored trace as it is recorded, and again (#326).

A run is driven through the shared tool service over real storage (the
tools harness) while the tail follows it through the owner's own
``StorageClient`` on the same server: a lookup, a refused malformed call and
an accepted submit, then the run's settlement. The live lines, each printed
once across polls, are the lines a replay of the finished run prints, and
the lines a tail of the run's day or island prints.
"""

from __future__ import annotations

import io
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from research_agent.agents.tail import Line, Tail, follow, main, replay
from research_agent.artifacts import ArtifactStore
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.storage.actions import OwnerActions
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient
from research_agent.storage.database import Database
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.settlements import SettlementRepository

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from service_harness import (  # noqa: E402
    ATTENTION,
    SETTINGS,
    TOOL_SCOPES,
    World,
    envelope,
    identity,
    latex_paper,
    lookup_args,
    submit_args,
    tool_service,
)
from test_http import Jobs, _tls_material  # noqa: E402

pytestmark = pytest.mark.integration

OWNER_SCOPES = frozenset({"owner:read"})
LEFT_FULL = "tool_calls=12 deep_reads=3 images=3"


@pytest.fixture
def world(postgres_dsn: str, artifact_root: Path, tmp_path: Path) -> World:
    return World(Database(postgres_dsn), ArtifactStore(artifact_root), tmp_path)


@contextmanager
def serve(world: World) -> Iterator[tuple[StorageClient, StorageClient]]:
    """One storage server with a tools principal and an owner principal."""

    (server_context, _, tools_fingerprint, _, owner_fingerprint, _) = _tls_material(
        world.tmp_path
    )
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {
            tools_fingerprint: ServiceCapability(uuid4(), "tools", TOOL_SCOPES),
            owner_fingerprint: ServiceCapability(uuid4(), "owner", OWNER_SCOPES),
        },
        tls_context=server_context,
        authorization=StorageAuthorization(world.database),
        artifacts=world.artifacts,
        documents=world.documents,
        queries=world.queries,
        runs=world.runs,
        submissions=world.submissions,
        paper_requests=world.paper_requests,
        trace=world.trace,
        owners=OwnerActions(world.database, world.store, **SETTINGS),
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
        yield client("client", TOOL_SCOPES), client("wrong", OWNER_SCOPES)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def _seed_genome(world: World, run_id: str) -> None:
    run = world.queries.run(run_id)
    assert run is not None
    PopulationStore(world.database, world.store, **SETTINGS).record_seed(
        configuration_id=UUID(run["configuration_id"]),
        genome=Genome(
            lineage_id="lineage-7",
            island="quant-ph",
            infra_hash="b" * 64,
            emphasis={
                "prompt": "evidence first",
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


def _settle(world: World, run_id: str) -> None:
    SettlementRepository(world.database, world.store, **SETTINGS).execute(
        "record",
        identity=identity(),
        payload={
            "run_id": run_id,
            "provider": "zai",
            "model": "glm-5.3-flash",
            "input_tokens": 1200,
            "output_tokens": 340,
            "usage_source": "provider",
        },
    )


def test_the_tail_prints_each_event_once_and_a_replay_prints_the_same(
    world: World,
) -> None:
    paper = latex_paper("Attention", ATTENTION, {"Introduction": "attention"})
    snapshot = world.seal_snapshot([paper])
    run = world.create_run(snapshot, paper_id=paper.family)
    _seed_genome(world, run)
    evidence = world.documents.family_pin(snapshot, paper.family).card_hash
    polls: list[list[Line]] = []
    with serve(world) as (tools, owner):
        service = tool_service(tools)
        tail = Tail(owner, run_id=run)
        polls.append(tail.poll())
        service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="query_cards",
            raw_call=envelope(lookup_args(paper.family), note="reading the cards"),
        )
        service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="query_cards",
            raw_call=envelope(
                {**lookup_args(paper.family), "section": "Method"},
                note="a malformed call",
            ),
        )
        polls.append(tail.poll())
        service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="submit",
            raw_call=envelope(
                submit_args(paper.family, evidence), note="done", intent="decide"
            ),
        )
        polls.append(tail.poll())
        ended = tail.finished
        _settle(world, run)
        polls.append(tail.poll())
        polls.append(tail.poll())
        replayed = list(replay(owner, run, speed=None))
        created_day = polls[0][0].at[:10]
        by_day = Tail(owner, day=created_day).poll()
        by_island = Tail(owner, island="quant-ph").poll()
        followed = list(
            follow(Tail(owner, run_id=run), interval_seconds=5, sleep=_no_wait)
        )
    trace = world.trace_rows(run)
    lookup_ids, submit_ids = (len(trace[i]["retrieved_ids"]) for i in (0, 2))
    lines = [line for poll in polls for line in poll]
    assert [(line.kind, line.text) for line in lines] == [
        (
            "start",
            f"run {run} paper={paper.family} lineage=lineage-7 island=quant-ph "
            f"budgets {LEFT_FULL}",
        ),
        ("call", '#1 query_cards note="reading the cards" intent="scan"'),
        (
            "result",
            f"#1 query_cards response retrieved={lookup_ids} "
            "left tool_calls=11 deep_reads=3 images=3",
        ),
        (
            "refused",
            '#2 query_cards note="a malformed call" intent="scan" '
            "reason=invalid_input left tool_calls=11 deep_reads=3 images=3",
        ),
        ("call", '#3 submit note="done" intent="decide"'),
        ("submitted", f"submission={_submission_id(world, run)} forecasts=2"),
        *(
            (
                "forecast",
                f"question={question} p=0.60 "
                'rationale="the method section supports this"',
            )
            for question in sorted(_questions(world, run))
        ),
        (
            "result",
            f"#3 submit response retrieved={submit_ids} "
            "left tool_calls=10 deep_reads=3 images=3",
        ),
        (
            "settled",
            "zai glm-5.3-flash input_tokens=1200 output_tokens=340 usage=provider",
        ),
    ]
    # One poll per recorded step, nothing printed twice, nothing after settling.
    assert [len(poll) for poll in polls] == [1, 3, 5, 1, 0]
    assert not ended and tail.finished
    assert [line.at for line in lines] == sorted(line.at for line in lines)
    assert all(line.run_id == run for line in lines)
    assert replayed == lines
    assert by_day == lines and by_island == lines
    assert followed == lines


def test_a_replay_keeps_the_stored_spacing_and_prints_what_live_prints(
    world: World,
) -> None:
    paper = latex_paper("Attention", ATTENTION, {"Introduction": "attention"})
    snapshot = world.seal_snapshot([paper])
    run = world.create_run(snapshot, paper_id=paper.family)
    unended = world.create_run(snapshot, paper_id=paper.family)
    with serve(world) as (tools, owner):
        tool_service(tools).call(
            run_id=run,
            snapshot_id=snapshot,
            tool="query_cards",
            raw_call=envelope(lookup_args(paper.family)),
        )
        world.void(run)
        live = Tail(owner, run_id=run).poll()
        waits: list[float] = []
        paced = list(replay(owner, run, speed=4.0, sleep=waits.append))
        printed, verbose, colored = io.StringIO(), io.StringIO(), _Terminal()
        status = main(["--replay", run, "--instant"], storage=owner, out=printed)
        main(["--replay", run, "--instant", "--verbose"], storage=owner, out=verbose)
        main(["--replay", run, "--instant"], storage=owner, out=colored)
        tail = io.StringIO()
        since = main(
            ["--replay", run, "--instant", "--since", live[-1].at],
            storage=owner,
            out=tail,
        )
        refused = main(["--replay", unended, "--instant"], storage=owner, out=None)
    assert [line.kind for line in live] == ["start", "call", "result", "void"]
    assert live[-1].text == "reason=model_stopped"
    assert paced == live
    assert sum(waits) == pytest.approx(
        (_seconds(live[-1].at) - _seconds(live[0].at)) / 4.0
    )
    assert status == 0 and since == 0 and refused == 2
    assert printed.getvalue() == "".join(f"{line.render()}\n" for line in live)
    # Payloads only on --verbose: the stored request carries the envelope.
    assert '"note":"reading the cards"' not in printed.getvalue()
    assert '"note":"reading the cards"' in verbose.getvalue()
    # Colors only on a terminal.
    assert "\x1b[" not in printed.getvalue() and "\x1b[" in colored.getvalue()
    # --since keeps the run's first line and the events at or after it.
    assert tail.getvalue() == "".join(
        f"{line.render()}\n" for line in (live[0], live[-1])
    )


def _no_wait(seconds: float) -> None:
    raise AssertionError(f"a settled run is not polled again ({seconds} s)")


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _seconds(instant: str) -> float:
    return (
        datetime.strptime(instant, "%Y-%m-%dT%H:%M:%S.%fZ")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _submission_id(world: World, run_id: str) -> str:
    row = world.database.transaction(
        lambda connection: connection.execute(
            "SELECT submission_id FROM run_submissions WHERE run_id = %s", (run_id,)
        ).fetchone()
    )
    assert row is not None
    return str(row[0])


def _questions(world: World, run_id: str) -> list[str]:
    rows = world.database.transaction(
        lambda connection: connection.execute(
            "SELECT question_id FROM run_forecasts WHERE run_id = %s", (run_id,)
        ).fetchall()
    )
    return [str(row[0]) for row in rows]
