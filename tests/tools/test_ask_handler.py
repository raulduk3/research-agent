"""The ask handler over real storage, the Jev work record and a sealed snapshot (#300).

Every call goes through the shared tool service as the other tools' do.
Jev itself is a stand-in transport that answers from recorded live
answers and counts every request that would have reached the provider.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from research_agent.contracts.canonical import (
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.ingest.jev import JevProviderConfig
from research_agent.storage.assessments import JevWorkRepository
from research_agent.storage.client import StorageClient
from research_agent.tools.ask import ASK_POOL_MICROS, AskHandler
from research_agent.tools.service import ToolService
from research_agent.tools.snapshots import SnapshotIndex
from research_agent.tools.text import PinnedTexts

from tests.tools.service_harness import (
    ALL_TOOLS,
    ATTENTION,
    Paper,
    WhitespaceTokenizer,
    World,
    envelope,
    latex_paper,
    tool_service,
)

pytestmark = pytest.mark.integration

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "jev"
_V2 = json.loads((_FIXTURES / "systemone-v2-response.json").read_text("utf-8"))
_V1 = json.loads((_FIXTURES / "systemone-response.json").read_text("utf-8"))
RECORDED = {
    "noul": _V2["answers"]["claims_supported_by_evidence"],
    "choice": _V1["answers"]["limitations_disclosure"],
    "score": _V2["answers"]["novelty_as_claimed"],
}
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
DAY = "2026-09-24"
CONFIG = JevProviderConfig(
    endpoint="http://127.0.0.1:9/v1/systemone",
    configured_model="typesafeai/jev-latest",
    known_revisions=frozenset({"jev-1.13.0"}),
    capability_evidence_hash="e" * 64,
    max_input_tokens=8192,
    prompt_price_micros_per_million_tokens=50_000,
    daily_limit_micros=2_000_000,
    smoke_revision=None,
)
INTRODUCTION = "We study attention in small models and report it."
ABSTRACT = "Sparse probes on frozen features recover attention patterns."


class RecordedJev:
    """Answers each ask with the recorded answer of the primitive it names."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    def post(self, body: bytes, *, timeout: float) -> tuple[int, bytes]:
        request = canonical_loads(body)
        assert isinstance(request, dict)
        self.bodies.append(request)
        primitive = request["questions"]["q"]["type"]
        return 200, canonical_json(
            {
                "model": "jev-1.13.0",
                "answers": {"q": RECORDED[primitive]},
                "usage": {"input_tokens": 400, "output_tokens": 8},
            }
        )


def _papers() -> tuple[Paper, Paper]:
    attention = latex_paper(
        "Attention in small models",
        ATTENTION,
        {"Introduction": INTRODUCTION, "Method": "A sparse probe on frozen features."},
    )
    probes = latex_paper(
        "Probing frozen features",
        (0.8, 0.6, 0.0, 0.0),
        {"Introduction": "Probes read frozen features of a network."},
    )
    return attention, replace(probes, abstract=ABSTRACT)


def _setup(world: World) -> tuple[str, str, Paper, Paper]:
    attention, probes = _papers()
    snapshot = world.seal_snapshot((attention, probes))
    run = world.create_run(
        snapshot, paper_id=attention.family, allowed_tools=(*ALL_TOOLS, "ask")
    )
    return snapshot, run, attention, probes


def _service(storage: StorageClient, world: World, jev: RecordedJev) -> ToolService:
    return tool_service(
        storage,
        ask=AskHandler(
            storage=storage,
            index=SnapshotIndex(storage),
            texts=PinnedTexts(storage),
            tokenizer=WhitespaceTokenizer(),
            store=JevWorkRepository(world.database),
            artifacts=world.store,
            transport=jev,
            config=CONFIG,
            clock=lambda: NOW,
        ),
    )


def _about(**fields: object) -> dict[str, object]:
    about: dict[str, object] = {
        "paper_id": None,
        "section": None,
        "passage_id": None,
        "self": None,
    }
    about.update(fields)
    return about


def _ask(about: dict[str, object], **overrides: object) -> dict[str, Any]:
    arguments: dict[str, object] = {
        "kind": "yes_no",
        "question": "Does the passage support the claim?",
        "options": None,
        "scale": None,
        "about": about,
        "claim": None,
    }
    arguments.update(overrides)
    return envelope(arguments, note="checking the claim", intent="read")


def _call(service: ToolService, run: str, snapshot: str, call: dict[str, Any]) -> Any:
    return service.call(run_id=run, snapshot_id=snapshot, tool="ask", raw_call=call)


def _usage(world: World) -> tuple[int, int]:
    row = world.database.transaction(
        lambda connection: connection.execute(
            "SELECT attempts, ask_reserved_micros FROM jev_daily_usage WHERE day=%s",
            (DAY,),
        ).fetchone()
    )
    return (0, 0) if row is None else (int(row[0]), int(row[1]))


def test_each_kind_asks_jev_about_state_the_snapshot_pins(world: World) -> None:
    snapshot, run, attention, probes = _setup(world)
    passage = _about(
        paper_id=attention.family, passage_id=sha256_hex(INTRODUCTION.encode())
    )
    jev = RecordedJev()
    with world.serve() as storage:
        service = _service(storage, world, jev)
        yes_no = _call(
            service, run, snapshot, _ask(passage, claim="Attention is studied.")
        )
        choose = _call(
            service,
            run,
            snapshot,
            _ask(
                _about(paper_id=probes.family, section="abstract"),
                kind="choose",
                options=[
                    {"name": name, "criterion": f"The limitations are {name}."}
                    for name in sorted(RECORDED["choice"]["probabilities"])
                ],
            ),
        )
        rate = _call(
            service,
            run,
            snapshot,
            _ask(
                _about(self="The paper gates attention by a learned sparsity mask."),
                kind="rate",
                scale=[RECORDED["score"]["legend"][str(i)] for i in range(4)],
            ),
        )

    assert [outcome.status for outcome in (yes_no, choose, rate)] == ["ok"] * 3
    assert [outcome.ask_calls for outcome in (yes_no, choose, rate)] == [1, 1, 1]
    assert yes_no.data["data"]["answer"] == "yes"
    assert yes_no.data["data"]["sentence"] == "Jev answers yes (p_yes 0.78)."
    assert choose.data["data"]["answer"] == "not_reported"
    assert rate.data["data"]["answer"] == 1
    # Jev read the pinned text, never text the agent copied in.
    assert jev.bodies[0]["state"] == INTRODUCTION
    assert jev.bodies[0]["questions"]["q"]["instructions"].endswith(
        "Claim under test: Attention is studied."
    )
    assert jev.bodies[1]["state"] == f"Probing frozen features\n\n{ABSTRACT}"
    assert [body["questions"]["q"]["type"] for body in jev.bodies] == [
        "noul",
        "choice",
        "score",
    ]
    # Request and response are stored artifacts under the recorded hashes.
    provenance = yes_no.data["data"]["provenance"]
    assert provenance["returned_model"] == "jev-1.13.0"
    assert provenance["configuration_hash"] == CONFIG.configuration_hash
    for digest in (provenance["request_hash"], provenance["response_hash"]):
        assert world.store.path_for(digest).read_bytes()
    # The trace charges each answered ask beside the call.
    rows = world.trace_rows(run)
    assert [row["budget_deltas"] for row in rows] == [
        {"tool_calls": 1, "ask_calls": 1}
    ] * 3
    assert sha256_hex(INTRODUCTION.encode()) in rows[0]["retrieved_ids"]
    attempts, reserved = _usage(world)
    assert attempts == 3 and 0 < reserved <= ASK_POOL_MICROS


def test_the_fifth_ask_of_a_run_is_refused_before_jev(world: World) -> None:
    snapshot, run, _attention, _probes = _setup(world)
    jev = RecordedJev()
    with world.serve() as storage:
        service = _service(storage, world, jev)
        answered = [
            _call(service, run, snapshot, _ask(_about(self=f"My reading number {n}.")))
            for n in range(4)
        ]
        fifth = _call(service, run, snapshot, _ask(_about(self="One more reading.")))

    assert [outcome.status for outcome in answered] == ["ok"] * 4
    assert fifth.status == "error"
    assert fifth.data["code"] == "ask_budget_exhausted"
    assert fifth.ask_calls == 0
    assert len(jev.bodies) == 4
    assert world.trace_rows(run)[-1]["error_code"] == "ask_budget_exhausted"


def test_asks_are_refused_once_the_days_pool_is_spent(world: World) -> None:
    snapshot, run, _attention, _probes = _setup(world)
    world.database.transaction(
        lambda connection: connection.execute(
            """INSERT INTO jev_daily_usage(day, attempts, reserved_micros,
                                           ask_reserved_micros)
               VALUES(%s, 0, %s, %s)""",
            (DAY, ASK_POOL_MICROS, ASK_POOL_MICROS),
        )
    )
    jev = RecordedJev()
    with world.serve() as storage:
        refused = _call(
            _service(storage, world, jev), run, snapshot, _ask(_about(self="Mine."))
        )

    assert refused.status == "error"
    assert refused.data["code"] == "daily_ask_budget_exhausted"
    assert jev.bodies == []
    assert _usage(world) == (0, ASK_POOL_MICROS)


def test_a_replayed_ask_is_served_the_kept_answer_without_asking_jev(
    world: World,
) -> None:
    snapshot, run, attention, _probes = _setup(world)
    call = _ask(
        _about(paper_id=attention.family, passage_id=sha256_hex(INTRODUCTION.encode()))
    )
    first_jev, replay_jev = RecordedJev(), RecordedJev()
    with world.serve() as storage:
        first = _call(_service(storage, world, first_jev), run, snapshot, call)
        # A replay is a new service answering the same run's recorded call.
        replayed = _call(_service(storage, world, replay_jev), run, snapshot, call)

    assert len(first_jev.bodies) == 1
    assert replay_jev.bodies == []
    assert replayed.status == "ok"
    assert replayed.data["data"] == first.data["data"]
    assert _usage(world)[0] == 1


@pytest.mark.parametrize("where", ["unknown_passage", "other_family"])
def test_an_about_outside_the_runs_snapshot_is_refused(
    world: World, where: str
) -> None:
    snapshot, run, attention, _probes = _setup(world)
    about = (
        _about(paper_id=attention.family, passage_id=sha256_hex(b"not pinned"))
        if where == "unknown_passage"
        else _about(paper_id=str(uuid4()), passage_id=sha256_hex(INTRODUCTION.encode()))
    )
    jev = RecordedJev()
    with world.serve() as storage:
        refused = _call(_service(storage, world, jev), run, snapshot, _ask(about))

    assert refused.status == "error"
    assert refused.data["code"] == "not_in_snapshot"
    assert jev.bodies == []
    assert _usage(world) == (0, 0)


def test_a_run_whose_genome_narrowed_ask_away_cannot_ask(world: World) -> None:
    attention, probes = _papers()
    snapshot = world.seal_snapshot((attention, probes))
    run = world.create_run(snapshot, paper_id=attention.family)
    jev = RecordedJev()
    with world.serve() as storage:
        refused = _call(
            _service(storage, world, jev), run, snapshot, _ask(_about(self="Mine."))
        )

    assert refused.status == "refused"
    assert refused.data["code"] == "tool_not_allowed"
    assert jev.bodies == []


def test_an_ask_never_spends_what_the_sublimit_leaves_the_cards(world: World) -> None:
    store = JevWorkRepository(world.database)
    limits = {
        "day": DAY,
        "worst_case_micros": 100,
        "daily_attempt_cap": 1000,
        "daily_limit_micros": CONFIG.daily_limit_micros,
        "ask_pool_micros": ASK_POOL_MICROS,
    }
    # The cards have reserved all but 50 micros of the day's sublimit.
    world.database.transaction(
        lambda connection: connection.execute(
            "INSERT INTO jev_daily_usage(day, attempts, reserved_micros) "
            "VALUES(%s, 10, %s)",
            (DAY, CONFIG.daily_limit_micros - 50),
        )
    )

    assert store.reserve_ask(work_key=sha256_hex(b"one"), **limits) is None
    reservation = store.reserve_ask(
        work_key=sha256_hex(b"two"), **{**limits, "worst_case_micros": 50}
    )
    assert reservation is not None
    store.settle_attempt(reservation, "known_completed")
    assert _usage(world) == (11, 50)
