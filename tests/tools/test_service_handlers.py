"""Each tool handler over real PostgreSQL and a sealed snapshot (#287).

Every call goes through the shared tool service and storage's HTTP routes
as a ``tools`` principal, and every answer is checked against what the
sealed snapshot pinned -- and against the run's external trace.
"""

from __future__ import annotations

import base64
from uuid import UUID

import pytest

from research_agent.contracts.canonical import sha256_hex

from service_harness import (
    ATTENTION,
    Paper,
    World,
    deep_read_args,
    envelope,
    latex_paper,
    lookup_args,
    search_args,
    submit_args,
    tool_service,
)

pytestmark = pytest.mark.integration

GRAPH = {"incoming": ["123e4567-e89b-42d3-a456-426614174900"], "outgoing": []}


def _papers() -> tuple[Paper, Paper, Paper, Paper]:
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
        {
            "Introduction": "Probes read frozen features of a network.",
            "Results": "Probes recover syntax from those features.",
        },
    )
    optics = latex_paper(
        "Unrelated optics",
        (0.0, 0.0, 1.0, 0.0),
        {"Introduction": "Lenses bend light.", "Results": "Mirrors reflect it."},
    )
    scanned = Paper(
        family="123e4567-e89b-42d3-a456-426614174901",
        version="123e4567-e89b-42d3-a456-426614174902",
        title="Scanned figures",
        overview=(0.0, 1.0, 0.0, 0.0),
        pdf=b"%PDF-1.4\n% a two-page scan\n%%EOF\n",
    )
    return attention, probes, optics, scanned


def _setup(world: World) -> tuple[str, str, tuple[Paper, Paper, Paper, Paper]]:
    papers = _papers()
    snapshot = world.seal_snapshot(papers)
    run = world.create_run(snapshot, paper_id=papers[0].family)
    return snapshot, run, papers


def test_query_cards_looks_up_pinned_cards_in_the_order_named(world: World) -> None:
    snapshot, run, (attention, probes, _optics, _scanned) = _setup(world)
    with world.serve() as storage:
        outcome = tool_service(storage).call(
            run_id=run,
            snapshot_id=snapshot,
            tool="query_cards",
            raw_call=envelope(lookup_args(probes.family, attention.family)),
        )
    cards = outcome.data["data"]["cards"]
    assert outcome.status == "ok"
    assert [card["paper_family_id"] for card in cards] == [
        probes.family,
        attention.family,
    ]
    (row,) = world.trace_rows(run)
    assert (row["tool"], row["decision"], row["outcome"]) == (
        "query_cards",
        "admitted",
        "response",
    )
    pins = {pin.paper_family_id: pin for pin in world.documents.members(snapshot)}
    assert row["retrieved_ids"] == [
        pins[probes.family].card_hash,
        pins[attention.family].card_hash,
    ]
    assert row["budget_deltas"] == {"tool_calls": 1}


def test_query_cards_ranks_overviews_by_exact_cosine(world: World) -> None:
    snapshot, run, (attention, probes, optics, scanned) = _setup(world)
    with world.serve() as storage:
        outcome = tool_service(storage).call(
            run_id=run,
            snapshot_id=snapshot,
            tool="query_cards",
            raw_call=envelope(search_args("attention", mode="overview", limit=3)),
        )
    results = outcome.data["data"]["results"]
    assert [result["paper_id"] for result in results] == [
        attention.family,
        probes.family,
        min(optics.family, scanned.family),
    ]
    assert [result["similarity"] for result in results] == pytest.approx(
        [1.0, 0.8, 0.0]
    )
    assert results[0]["card"]["overview"]["title"] == "Attention in small models"


def test_query_cards_ranks_passages_and_answers_their_exact_text(
    world: World,
) -> None:
    snapshot, run, (attention, _probes, _optics, _scanned) = _setup(world)
    with world.serve() as storage:
        outcome = tool_service(storage).call(
            run_id=run,
            snapshot_id=snapshot,
            tool="query_cards",
            raw_call=envelope(search_args("attention", mode="passages", limit=1)),
        )
    data = outcome.data["data"]
    top = data["results"][0]
    assert top["paper_id"] == attention.family
    assert top["text"] == "We study attention in small models and report it."
    assert top["section_path"] == ["Introduction"]
    assert top["similarity"] == pytest.approx(1.0)
    assert top["passage_id"] == sha256_hex(top["text"].encode("utf-8"))
    assert top["source_locators"]
    # The scanned PDF has no stored text to rank; it is counted, not guessed.
    assert data["text_unavailable_papers"] == 1
    (row,) = world.trace_rows(run)
    assert top["passage_id"] in row["retrieved_ids"]


def test_neighbors_ranks_the_snapshots_other_papers(world: World) -> None:
    snapshot, run, (attention, probes, optics, scanned) = _setup(world)
    with world.serve() as storage:
        outcome = tool_service(storage).call(
            run_id=run,
            snapshot_id=snapshot,
            tool="neighbors",
            raw_call=envelope({"paper_id": attention.family, "limit": 2}),
        )
    neighbors = outcome.data["data"]["neighbors"]
    assert [item["paper_id"] for item in neighbors] == [
        probes.family,
        min(optics.family, scanned.family),
    ]
    assert neighbors[0]["title"] == "Probing frozen features"
    assert neighbors[0]["similarity"] == pytest.approx(0.8)
    assert attention.family not in {item["paper_id"] for item in neighbors}


def test_graph_answers_the_pinned_graph_or_an_error_when_none_is_pinned(
    world: World,
) -> None:
    snapshot, run, (attention, probes, _optics, _scanned) = _setup(world)
    with world.serve() as storage:
        service = tool_service(storage)
        pinned = service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="graph",
            raw_call=envelope(
                {
                    "paper_id": attention.family,
                    "direction": None,
                    "limit": None,
                }
            ),
        )
        absent = service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="graph",
            raw_call=envelope(
                {"paper_id": probes.family, "direction": None, "limit": None}
            ),
        )
    assert pinned.data["data"]["graph"] == GRAPH
    assert (absent.status, absent.data["code"]) == ("error", "graph_unavailable")
    first, second = world.trace_rows(run)
    assert first["retrieved_ids"] == [
        world.documents.family_pin(snapshot, attention.family).graph_hash
    ]
    assert (second["outcome"], second["error_code"]) == ("error", "graph_unavailable")


def test_deep_read_serves_a_section_from_the_verified_pinned_text(
    world: World,
) -> None:
    snapshot, run, (attention, _probes, _optics, scanned) = _setup(world)
    with world.serve() as storage:
        service = tool_service(storage)
        section = service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="deep_read",
            raw_call=envelope(deep_read_args(attention.family, section_id="Method")),
        )
        unavailable = service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="deep_read",
            raw_call=envelope(deep_read_args(scanned.family, section_id="Method")),
        )
    data = section.data["data"]
    # The span is the extraction's own block span for that heading.
    assert "The method trains a sparse probe on frozen features." in data["text"]
    assert "We study attention" not in data["text"]
    assert data["untrusted"] is True
    assert data["next_span"] is None
    assert section.deep_reads == 1
    assert (unavailable.status, unavailable.data["code"]) == (
        "error",
        "text_unavailable",
    )
    first, second = world.trace_rows(run)
    assert first["budget_deltas"] == {"tool_calls": 1, "deep_reads": 1}
    assert len(first["retrieved_ids"]) == 1
    assert second["error_code"] == "text_unavailable"


def test_deep_read_renders_pages_of_the_pinned_pdf(world: World) -> None:
    snapshot, run, (attention, _probes, _optics, scanned) = _setup(world)
    with world.serve() as storage:
        service = tool_service(storage)
        pages = service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="deep_read",
            raw_call=envelope(deep_read_args(scanned.family, pages=[1, 2])),
        )
        latex_pages = service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="deep_read",
            raw_call=envelope(deep_read_args(attention.family, pages=[1])),
        )
    rendered = pages.data["data"]["pages"]
    assert [page["page_number"] for page in rendered] == [1, 2]
    image = base64.b64decode(rendered[1]["image_base64"])
    assert image.endswith(b"page 2")
    assert rendered[1]["media_hash"] == sha256_hex(image)
    assert rendered[0]["source_locator"]["source_hash"] == sha256_hex(
        scanned.pdf or b""
    )
    assert (pages.deep_reads, pages.images) == (1, 2)
    assert latex_pages.data["code"] == "pages_unavailable"
    assert world.trace_rows(run)[0]["budget_deltas"] == {
        "tool_calls": 1,
        "deep_reads": 1,
        "images": 2,
    }


def test_deep_read_of_an_absent_family_records_a_paper_request(
    world: World,
) -> None:
    snapshot, run, _papers_ = _setup(world)
    absent = "123e4567-e89b-42d3-a456-426614174999"
    with world.serve() as storage:
        outcome = tool_service(storage).call(
            run_id=run,
            snapshot_id=snapshot,
            tool="deep_read",
            raw_call=envelope(deep_read_args(absent, section_id="Method")),
        )
    assert outcome.data["data"]["kind"] == "not_in_snapshot"
    assert outcome.data["data"]["request"]["outcome"] == "requested"
    assert world.count("paper_requests", run) == 1


def test_submit_seals_through_storage_and_ends_the_run(world: World) -> None:
    snapshot, run, (attention, _probes, _optics, _scanned) = _setup(world)
    evidence = world.documents.family_pin(snapshot, attention.family).card_hash
    with world.serve() as storage:
        service = tool_service(storage)
        other_paper = service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="submit",
            raw_call=envelope(
                submit_args("123e4567-e89b-42d3-a456-426614174777", evidence)
            ),
        )
        accepted = service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="submit",
            raw_call=envelope(submit_args(attention.family, evidence)),
        )
        after = service.call(
            run_id=run,
            snapshot_id=snapshot,
            tool="query_cards",
            raw_call=envelope(lookup_args(attention.family)),
        )
        specification = storage.read_run_specification(UUID(run))
    assert (other_paper.status, other_paper.data["code"]) == (
        "refused",
        "invalid_input",
    )
    assert accepted.status == "ok"
    assert accepted.accepted_submit is True
    assert accepted.data["data"]["accepted"] is True
    assert specification.active is False
    assert (after.status, after.data["code"]) == ("refused", "run_not_active")
    assert world.count("run_submissions", run) == 1
    assert [(row["decision"], row["reason"]) for row in world.trace_rows(run)] == [
        ("refused", "invalid_input"),
        ("admitted", None),
        ("refused", "run_not_active"),
    ]
