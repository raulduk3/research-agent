"""arXiv ingestion: parsing, one record per paper, failures kept apart."""

from __future__ import annotations

from dataclasses import replace

import sqlite3

import pytest

from research_agent.beta.budget import budget_state
from research_agent.beta.ingest import (
    SourceFailed,
    parse_arxiv_feed,
    run_ingestion_pass,
    watched_categories,
)
from research_agent.beta.projections import build_paper_projection
from research_agent.beta.spec import current_spec
from tests.beta.helpers import ABSTRACT, FakeClock, entry, feed


def _pass(db: sqlite3.Connection, clock: FakeClock, feeds: dict[str, str], **kwargs):
    _, spec = current_spec(db)

    def fetch(category: str, limit: int) -> str:
        if category not in feeds:
            raise SourceFailed(f"no answer for {category}")
        return feeds[category]

    # The lever defaults to one paper a pass (one every ten minutes in service);
    # these tests hold ten so a pass can be seen choosing.
    plan = replace(
        budget_state(db, spec, clock(), provider_configured=True).plan,
        papers_per_pass=kwargs.pop("per_pass", 10),
    )
    return run_ingestion_pass(
        db, spec, plan, fetch=fetch, clock=clock, sleep=lambda _: None, **kwargs
    )


def test_parsing_reads_identity_metadata_and_links() -> None:
    entries, quarantined = parse_arxiv_feed(
        feed(entry("2609.00001", version=3, categories=("cs.AI", "stat.ML")))
    )

    assert quarantined == []
    [paper] = entries
    # The canonical id carries no version; the version is kept beside it.
    assert (paper.id, paper.version) == ("2609.00001", 3)
    assert paper.title == "Tool-using agents learn when traces are visible"
    assert paper.abstract == ABSTRACT
    assert paper.authors == ("Ada Reader", "Sam Tracer")
    assert paper.primary_category == "cs.AI"
    assert paper.categories == ("cs.AI", "stat.ML")
    assert paper.abs_url == "https://arxiv.org/abs/2609.00001v3"
    assert paper.pdf_url == "https://arxiv.org/pdf/2609.00001v3"


def test_an_entry_without_a_readable_identity_is_set_aside() -> None:
    broken = "<entry><id>urn:not-an-arxiv-id</id><title>Orphan</title></entry>"

    entries, quarantined = parse_arxiv_feed(feed(entry(), extra=broken))

    assert [paper.id for paper in entries] == ["2609.00001"]
    assert quarantined == [
        {"source_id": "urn:not-an-arxiv-id", "reason": "ambiguous_identity"}
    ]


def test_a_feed_that_is_not_plain_atom_is_refused() -> None:
    with pytest.raises(SourceFailed):
        parse_arxiv_feed("<!DOCTYPE feed [<!ENTITY a 'b'>]><feed/>")
    with pytest.raises(SourceFailed):
        parse_arxiv_feed("<feed><entry>")


def test_a_failed_source_is_recorded_and_the_others_still_commit(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    summary = _pass(
        db,
        clock,
        {"cs.AI": feed(entry("2609.00001"))},
        categories=["cs.AI", "quant-ph"],
    )

    assert summary["status"] == "completed"
    assert summary["stored"] == 1
    assert summary["failures"] == [
        {"category": "quant-ph", "error": "no answer for quant-ph"}
    ]
    assert db.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
    stored = db.execute("SELECT failures, status FROM ingest_passes").fetchone()
    assert "quant-ph" in stored["failures"] and stored["status"] == "completed"


def test_rerunning_a_pass_and_a_newer_version_never_duplicate_a_paper(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    first = _pass(db, clock, {"cs.AI": feed(entry("2609.00001"))}, categories=["cs.AI"])
    again = _pass(db, clock, {"cs.AI": feed(entry("2609.00001"))}, categories=["cs.AI"])
    newer = _pass(
        db,
        clock,
        {"cs.AI": feed(entry("2609.00001", version=2, abstract="A revised abstract."))},
        categories=["cs.AI"],
    )

    assert (first["stored"], again["unchanged"], newer["updated"]) == (1, 1, 1)
    rows = db.execute("SELECT id, version, abstract FROM papers").fetchall()
    assert [tuple(row) for row in rows] == [("2609.00001", 2, "A revised abstract.")]
    # The assignment made on first sight is not repeated either.
    assert db.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 1
    assert again["assigned"] == []
    passages = db.execute("SELECT text FROM paper_passages").fetchall()
    assert [row[0] for row in passages] == ["A revised abstract."]


def test_a_pass_holds_no_more_papers_than_the_plan_allows(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    many = feed(*(entry(f"2609.{n:05d}") for n in range(1, 31)))

    summary = _pass(db, clock, {"cs.AI": many}, categories=["cs.AI"])

    assert summary["paper_cap"] == 10
    assert db.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 10
    limited = _pass(db, clock, {"cs.AI": many}, categories=["cs.AI"], limit=3)
    assert limited["paper_cap"] == 3


def test_every_source_request_leaves_a_zero_cost_receipt_the_paper_cites(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _pass(db, clock, {"cs.AI": feed(entry())}, categories=["cs.AI", "quant-ph"])

    receipts = db.execute(
        "SELECT id, action, unit_type, amount_micros, settlement FROM cost_receipts"
    ).fetchall()
    # One receipt per request, the failed one included.
    assert [(r["action"], r["amount_micros"]) for r in receipts] == [("ingest", 0)] * 2
    cited = db.execute("SELECT ingest_receipt_id FROM papers").fetchone()[0]
    assert cited in {row["id"] for row in receipts}


def test_assignment_routes_known_cross_topic_and_sparse_papers(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    summary = _pass(
        db,
        clock,
        {
            "mixed": feed(
                entry("2609.00001", primary="cs.AI", categories=("cs.AI",)),
                entry(
                    "2609.00002",
                    title="Variational circuits for protein folding",
                    abstract="A quantum method.",
                    primary="quant-ph",
                    categories=("quant-ph", "q-bio.BM"),
                ),
                entry(
                    "2609.00003",
                    title="A note on river deltas",
                    abstract="Sediment transport.",
                    primary="physics.geo-ph",
                    categories=("physics.geo-ph",),
                ),
            )
        },
        categories=["mixed"],
    )

    assigned = {(item["paper_id"], item["island_id"]) for item in summary["assigned"]}
    assert assigned == {
        ("2609.00001", "cs"),
        ("2609.00002", "quant"),
        ("2609.00002", "bio"),
        ("2609.00003", "general"),
    }
    reasons = {
        (row["paper_id"], row["island_id"]): row["reasons"]
        for row in db.execute("SELECT * FROM assignments")
    }
    assert "primary_category:cs.AI" in reasons[("2609.00001", "cs")]
    assert "cross_list:q-bio.BM" in reasons[("2609.00002", "bio")]
    assert reasons[("2609.00003", "general")] == '["assignment_uncertain"]'


def test_a_keyword_alone_does_not_pull_a_paper_onto_a_category_island(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    # "simulation" is a quant keyword; the paper is in no quant category.
    summary = _pass(
        db,
        clock,
        {
            "cs.AI": feed(
                entry(
                    "2609.00009",
                    title="Simulation and optimization for robot agents",
                    primary="cs.RO",
                    categories=("cs.RO", "cs.AI"),
                )
            )
        },
        categories=["cs.AI"],
    )

    assert summary["assigned"] == [{"paper_id": "2609.00009", "island_id": "cs"}]
    reasons = db.execute("SELECT reasons FROM assignments").fetchone()[0]
    assert reasons == '["cross_list:cs.AI","focus_keyword:agents"]'


def test_a_paper_without_an_abstract_stays_visible_with_no_invented_text(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _pass(db, clock, {"cs.AI": feed(entry(abstract=""))}, categories=["cs.AI"])

    view = build_paper_projection(db, "2609.00001")

    assert view["paper"]["text_status"] == "failed"
    assert view["paper"]["text_failure"] == "abstract_missing"
    assert view["paper"]["summary"] == "" and view["paper"]["sections"] == []
    assert len(view["assignments"]) == 1
    assert db.execute("SELECT COUNT(*) FROM paper_passages").fetchone()[0] == 0


def test_watched_categories_come_from_open_islands(db: sqlite3.Connection) -> None:
    _, spec = current_spec(db)

    assert watched_categories(spec) == [
        "cs.AI",
        "cs.LG",
        "cs.CL",
        "cs.MA",
        "quant-ph",
        "q-bio.*",
    ]


def test_small_passes_rotate_sources_and_skip_unchanged_heads(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    feeds = {
        "cs.AI": feed(entry("2609.00001"), entry("2609.00002")),
        "quant-ph": feed(
            entry("2609.00003", primary="quant-ph", categories=("quant-ph",))
        ),
        "q-bio.*": feed(
            entry("2609.00004", primary="q-bio.BM", categories=("q-bio.BM",))
        ),
    }
    for _ in range(4):
        summary = _pass(db, clock, feeds, categories=list(feeds), per_pass=1)
        assert summary["stored"] == 1
        clock.advance(minutes=10)
    assert {row[0] for row in db.execute("SELECT id FROM papers")} == {
        "2609.00001",
        "2609.00002",
        "2609.00003",
        "2609.00004",
    }
