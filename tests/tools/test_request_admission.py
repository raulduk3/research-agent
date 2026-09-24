"""Every tool call is an untrusted proposal, refused whole and recorded (SR-05).

TDD-2.1.5: the call is checked against the run's stored specification --
never a field it supplies -- and a cross-run call, a disallowed tool or a
payload carrying an extra configuration field is refused, recorded in the
run's external trace, and changes nothing.
"""

from __future__ import annotations

import base64
from uuid import UUID

import pytest

from research_agent.contracts import canonical_loads
from research_agent.storage.client import RunSpecificationRecord
from research_agent.tools.admission import Admission, Refusal, admit_request
from research_agent.tools.lookup import SpecificationLookup

from service_harness import (
    ATTENTION,
    World,
    envelope,
    latex_paper,
    lookup_args,
    submit_args,
    tool_service,
)

RUN = "123e4567-e89b-42d3-a456-426614174010"
OTHER_RUN = "123e4567-e89b-42d3-a456-426614174011"
PAPER = "123e4567-e89b-42d3-a456-426614174012"
SNAPSHOT = "a" * 64
HANDLERS = frozenset({"query_cards", "neighbors", "graph", "deep_read", "submit"})


def _lookup(
    *, allowed: frozenset[str] = frozenset({"query_cards"}), active: bool = True
) -> SpecificationLookup:
    return SpecificationLookup(
        RunSpecificationRecord(
            run_id=UUID(RUN),
            snapshot_hash=SNAPSHOT,
            allowed_tools=allowed,
            paper_id=PAPER,
            issued_question_ids=frozenset(),
            active=active,
        )
    )


def _admit(
    tool: str,
    arguments: object,
    *,
    run_id: str = RUN,
    snapshot_id: str = SNAPSHOT,
    lookup: SpecificationLookup | None = None,
) -> Admission | Refusal:
    lookup = lookup or _lookup()
    return admit_request(
        tool=tool,
        raw_call=envelope(arguments),
        run_id=run_id,
        requested_snapshot_id=snapshot_id,
        lookup=lookup,
        handlers=HANDLERS,
        active=lookup.active,
    )


def _admit_call(
    tool: str, raw_call: object, *, lookup: SpecificationLookup | None = None
) -> Admission | Refusal:
    lookup = lookup or _lookup()
    return admit_request(
        tool=tool,
        raw_call=raw_call,
        run_id=RUN,
        requested_snapshot_id=SNAPSHOT,
        lookup=lookup,
        handlers=HANDLERS,
        active=lookup.active,
    )


def test_a_well_formed_call_is_admitted_with_the_stored_snapshot() -> None:
    admitted = _admit("query_cards", lookup_args(PAPER))
    assert isinstance(admitted, Admission)
    assert admitted.snapshot_hash == SNAPSHOT
    assert admitted.arguments == {"kind": "lookup", "paper_ids": (PAPER,)}


def test_a_call_for_another_run_is_refused() -> None:
    # The specification read for one run never speaks for another.
    refused = _admit("query_cards", lookup_args(PAPER), run_id=OTHER_RUN)
    assert refused == Refusal("invalid_input", "call names a run other than its own")


def test_a_tool_outside_the_run_specification_is_refused() -> None:
    refused = _admit("deep_read", {"paper_id": PAPER})
    assert isinstance(refused, Refusal)
    assert refused.code == "tool_not_allowed"


def test_a_protected_configuration_field_is_refused_whole() -> None:
    arguments = {**lookup_args(PAPER), "allowed_tools": ["deep_read"]}
    refused = _admit("query_cards", arguments)
    assert isinstance(refused, Refusal)
    assert refused.code == "invalid_input"


def test_a_call_naming_another_snapshot_is_refused() -> None:
    refused = _admit("query_cards", lookup_args(PAPER), snapshot_id="b" * 64)
    assert isinstance(refused, Refusal)
    assert refused.code == "invalid_input"


def test_an_ended_run_admits_nothing() -> None:
    refused = _admit("query_cards", lookup_args(PAPER), lookup=_lookup(active=False))
    assert refused == Refusal("run_not_active", "the run has already ended")


def test_a_bad_envelope_is_refused_after_the_tool_and_run_gates() -> None:
    # One owner orders the refusals: the tool and the run's state are
    # judged before the envelope, the envelope before the arguments.
    bare = lookup_args(PAPER)
    assert _admit_call("deep_read", bare) == Refusal(
        "tool_not_allowed", "tool is not in this run's admitted set"
    )
    assert _admit_call("query_cards", bare, lookup=_lookup(active=False)) == Refusal(
        "run_not_active", "the run has already ended"
    )
    refused = _admit_call("query_cards", {"note": "reading", "arguments": bare})
    assert refused == Refusal(
        "invalid_input", "tool call has unknown or missing fields"
    )
    refused = _admit_call(
        "query_cards", {"note": "reading", "intent": "browse", "arguments": {}}
    )
    assert refused == Refusal("invalid_input", "intent is not an admitted value")


@pytest.mark.integration
def test_a_bad_envelope_is_recorded_as_sent_and_reads_nothing(world: World) -> None:
    paper = latex_paper("Attention", ATTENTION, {"Introduction": "attention"})
    snapshot = world.seal_snapshot([paper])
    run = world.create_run(snapshot, paper_id=paper.family)
    raw_call = envelope(lookup_args(paper.family), intent="browse")
    with world.serve() as storage:
        outcome = tool_service(storage).call(
            run_id=run, snapshot_id=snapshot, tool="query_cards", raw_call=raw_call
        )
    assert (outcome.status, outcome.data["code"]) == ("refused", "invalid_input")
    assert [
        (row["tool"], row["decision"], row["reason"], row["outcome"])
        for row in world.trace_rows(run)
    ] == [("query_cards", "refused", "invalid_input", None)]
    trace = world.trace.read(run)
    assert trace is not None
    [call] = trace["calls"]
    stored = canonical_loads(base64.b64decode(call["request"]["bytes"]))
    assert isinstance(stored, dict) and stored["arguments"] == raw_call


@pytest.mark.integration
def test_refusals_are_recorded_and_accept_nothing(world: World) -> None:
    paper = latex_paper("Attention", ATTENTION, {"Introduction": "attention"})
    snapshot = world.seal_snapshot([paper])
    run = world.create_run(
        snapshot, paper_id=paper.family, allowed_tools=("query_cards", "submit")
    )
    with world.serve() as storage:
        service = tool_service(storage)
        outcomes = [
            service.call(
                run_id=run,
                snapshot_id=snapshot,
                tool="deep_read",
                raw_call=envelope({"paper_id": paper.family}),
            ),
            service.call(
                run_id=run,
                snapshot_id=snapshot,
                tool="query_cards",
                raw_call=envelope({**lookup_args(paper.family), "allowed_tools": []}),
            ),
            service.call(
                run_id=run,
                snapshot_id=snapshot,
                tool="submit",
                raw_call=envelope(
                    {**submit_args(paper.family, "c" * 64), "run_id": run}
                ),
            ),
        ]
        unknown = service.call(
            run_id="123e4567-e89b-42d3-a456-426614174099",
            snapshot_id=snapshot,
            tool="query_cards",
            raw_call=envelope(lookup_args(paper.family)),
        )
        specification = storage.read_run_specification(UUID(run))
    assert [outcome.status for outcome in outcomes] == ["refused"] * 3
    assert [outcome.data["code"] for outcome in outcomes] == [
        "tool_not_allowed",
        "invalid_input",
        "invalid_input",
    ]
    assert [
        (row["tool"], row["decision"], row["reason"], row["outcome"])
        for row in world.trace_rows(run)
    ] == [
        ("deep_read", "refused", "tool_not_allowed", None),
        ("query_cards", "refused", "invalid_input", None),
        ("submit", "refused", "invalid_input", None),
    ]
    # Nothing was sealed and the specification the calls tried to widen is
    # exactly as stored.
    assert world.count("run_submissions", run) == 0
    assert specification.allowed_tools == frozenset({"query_cards", "submit"})
    assert specification.active is True
    assert (unknown.status, unknown.data["code"]) == ("refused", "unknown_run")
