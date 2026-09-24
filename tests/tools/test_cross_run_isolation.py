"""No value from one run's calls is visible to another's (PL-20).

TDD-2.1.36: two runs call the one shared tool service at once with
distinguishable, run-specific arguments -- papers they ask for, papers the
snapshot lacks, a refused call -- and neither run's responses, errors,
trace or paper requests carry any trace of the other's.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from research_agent.contracts.canonical import canonical_json
from research_agent.tools.service import ToolService

from service_harness import (
    ATTENTION,
    World,
    deep_read_args,
    envelope,
    latex_paper,
    lookup_args,
    search_args,
    tool_service,
)

pytestmark = pytest.mark.integration


def _calls(
    service: ToolService,
    barrier: threading.Barrier,
    *,
    run: str,
    snapshot: str,
    own_paper: str,
    absent: str,
) -> list[dict[str, Any]]:
    calls: list[tuple[str, dict[str, Any]]] = [
        ("query_cards", lookup_args(own_paper)),
        ("deep_read", deep_read_args(absent, section_id="Method")),
        ("query_cards", search_args("attention", mode="overview", paper_id=own_paper)),
        ("neighbors", {"paper_id": own_paper, "limit": 1, "extra": absent}),
    ]
    envelopes = []
    for tool, arguments in calls:
        barrier.wait()
        envelopes.append(
            service.call(
                run_id=run,
                snapshot_id=snapshot,
                tool=tool,
                raw_call=envelope(arguments),
            ).data
        )
    return envelopes


def test_two_concurrent_runs_see_nothing_of_each_other(world: World) -> None:
    first_paper = latex_paper("First", ATTENTION, {"Introduction": "attention one"})
    second_paper = latex_paper("Second", (0.0, 1.0, 0.0, 0.0), {"Introduction": "two"})
    snapshot = world.seal_snapshot([first_paper, second_paper])
    first = world.create_run(snapshot, paper_id=first_paper.family)
    second = world.create_run(snapshot, paper_id=second_paper.family)
    first_absent = "123e4567-e89b-42d3-a456-426614174201"
    second_absent = "123e4567-e89b-42d3-a456-426614174202"
    barrier = threading.Barrier(2)
    with world.serve() as storage:
        service = tool_service(storage)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(
                _calls,
                service,
                barrier,
                run=first,
                snapshot=snapshot,
                own_paper=first_paper.family,
                absent=first_absent,
            )
            second_future = pool.submit(
                _calls,
                service,
                barrier,
                run=second,
                snapshot=snapshot,
                own_paper=second_paper.family,
                absent=second_absent,
            )
            first_envelopes = first_future.result(timeout=60)
            second_envelopes = second_future.result(timeout=60)

    first_bytes = canonical_json(first_envelopes).decode()
    second_bytes = canonical_json(second_envelopes).decode()
    for value in (first, second_paper.family, second_absent):
        assert value not in first_bytes
    for value in (second, first_paper.family, first_absent):
        assert value not in second_bytes
    # Each run's own values did reach its own answers.
    assert first_paper.family in first_bytes and first_absent in first_bytes
    assert second_paper.family in second_bytes and second_absent in second_bytes
    # The refused call (an extra field) is an error of that run alone.
    assert first_envelopes[3]["code"] == second_envelopes[3]["code"] == "invalid_input"

    for run, own_absent, other_absent in (
        (first, first_absent, second_absent),
        (second, second_absent, first_absent),
    ):
        trace = world.trace_rows(run)
        assert [row["sequence"] for row in trace] == [1, 2, 3, 4]
        assert [row["decision"] for row in trace] == [
            "admitted",
            "admitted",
            "admitted",
            "refused",
        ]
        requested = world.database.transaction(
            lambda connection, run=run: connection.execute(
                "SELECT family_id FROM paper_requests WHERE run_id = %s", (run,)
            ).fetchall()
        )
        assert [str(row[0]) for row in requested] == [own_absent]
        assert other_absent not in {str(row[0]) for row in requested}
    first_cards = {
        id_ for row in world.trace_rows(first) for id_ in row["retrieved_ids"]
    }
    second_cards = {
        id_ for row in world.trace_rows(second) for id_ in row["retrieved_ids"]
    }
    assert first_cards and second_cards and not first_cards & second_cards
