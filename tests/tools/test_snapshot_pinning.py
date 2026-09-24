"""A run is answered from its own snapshot, never a newer one (PL-21).

TDD-2.1.37: snapshot B adds one paper that is the closest match there is
to the query. After the service has built and cached B's index for a run
bound to B, a run bound to A searches, asks for neighbors and reads by
passage; the added paper is absent from every answer and from the index
that produced it. A call from A's run naming B is refused and recorded.
"""

from __future__ import annotations

import pytest

from research_agent.tools.snapshots import SnapshotIndex

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


def test_a_run_never_sees_a_paper_added_in_a_newer_snapshot(world: World) -> None:
    base = latex_paper(
        "Base", (0.6, 0.8, 0.0, 0.0), {"Introduction": "attention is described"}
    )
    other = latex_paper("Other", (0.0, 1.0, 0.0, 0.0), {"Introduction": "no match"})
    added = latex_paper(
        "Added later", ATTENTION, {"Introduction": "attention attention attention"}
    )
    older = world.seal_snapshot([base, other])
    newer = world.seal_snapshot([base, other, added])
    old_run = world.create_run(older, paper_id=base.family)
    new_run = world.create_run(newer, paper_id=base.family)

    with world.serve() as storage:
        index = SnapshotIndex(storage)
        service = tool_service(storage, index=index)

        def call(run: str, snapshot: str, tool: str, arguments: object) -> dict:
            return service.call(
                run_id=run,
                snapshot_id=snapshot,
                tool=tool,
                raw_call=envelope(arguments),
            ).data

        # The newer snapshot's index is built and cached first.
        newer_top = call(
            new_run, newer, "query_cards", search_args("attention", mode="overview")
        )
        answers = [
            call(
                old_run, older, "query_cards", search_args("attention", mode="overview")
            ),
            call(old_run, older, "neighbors", {"paper_id": base.family, "limit": None}),
            call(
                old_run, older, "query_cards", search_args("attention", mode="passages")
            ),
        ]
        lookup = call(old_run, older, "query_cards", lookup_args(added.family))
        read = call(
            old_run,
            older,
            "deep_read",
            deep_read_args(added.family, section_id="Introduction"),
        )
        other_snapshot = call(old_run, newer, "query_cards", lookup_args(base.family))
        old_members = {member.family_id for member in index.handle(older).members}
        new_members = {member.family_id for member in index.handle(newer).members}

    assert newer_top["data"]["results"][0]["paper_id"] == added.family
    for answer in answers:
        assert answer["status"] == "ok"
        assert added.family not in str(answer)
        assert answer["data"].get("results", answer["data"].get("neighbors"))
    assert answers[0]["data"]["results"][0]["paper_id"] == base.family
    assert answers[2]["data"]["results"][0]["paper_id"] == base.family
    assert (lookup["status"], lookup["code"]) == ("error", "not_in_snapshot")
    assert read["data"]["kind"] == "not_in_snapshot"
    assert (other_snapshot["status"], other_snapshot["code"]) == (
        "refused",
        "invalid_input",
    )
    assert added.family not in old_members
    assert added.family in new_members
    assert world.trace_rows(old_run)[-1]["reason"] == "invalid_input"
