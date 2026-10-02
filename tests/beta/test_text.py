"""Full text from arXiv's HTML: sections as passages, read a few at a time."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

import pytest

from research_agent.beta import spec as specs
from research_agent.beta.budget import budget_state
from research_agent.beta.config import BetaConfig
from research_agent.beta.costs import record_cost_receipt
from research_agent.beta.ingest import run_ingestion_pass
from research_agent.beta.papers import load_passages, prune_unread_papers, upsert_paper
from research_agent.beta.runs import create_run, execute_run, passage_outline
from research_agent.beta.projections import build_paper_projection, build_run_projection
from research_agent.beta.text import (
    PASSAGE_CHARS,
    TextFetchFailed,
    fetch_full_texts,
    parse_paper_html,
    split_section,
)
from tests.beta.helpers import (
    PROVIDER,
    FakeClock,
    ScriptedClient,
    call,
    entry,
    feed,
    reading,
    reply,
)

PAPER = "2609.00001"

#: The shape arXiv's LaTeX-to-HTML pages have, cut down.
HTML = """<!DOCTYPE html><html><head><style>.x{}</style><script>var a=1;</script></head>
<body><nav class="ltx_page_navbar">menu</nav>
<article class="ltx_document">
<h1 class="ltx_title ltx_title_document">A Paper</h1>
<div class="ltx_authors">Ada Reader</div>
<div class="ltx_abstract"><p class="ltx_p">The abstract again.</p></div>
<section id="S1" class="ltx_section">
<h2 class="ltx_title ltx_title_section"><span class="ltx_tag">1 </span>Introduction</h2>
<div id="S1.p1" class="ltx_para"><p class="ltx_p">Agents learn when traces
are visible.<span class="ltx_note ltx_role_footnote"><sup>1</sup>A footnote.</span></p></div>
<table class="ltx_equation"><tr><td><math class="ltx_Math" alttext="U_{\\beta}">
<mi>U</mi></math></td></tr></table>
<section id="S1.SS1" class="ltx_subsection">
<h3 class="ltx_title ltx_title_subsection">1.1 Main result</h3>
<div class="ltx_para"><p class="ltx_p">The result holds for all <math alttext="n">n</math>.</p></div>
<section id="S1.SS1.SSS1" class="ltx_subsubsection">
<h4 class="ltx_title">1.1.1 Detail</h4>
<div class="ltx_para"><p class="ltx_p">Deep detail stays with its parent.</p></div>
</section>
</section>
</section>
<section id="A1" class="ltx_appendix">
<h2 class="ltx_title ltx_title_appendix">Appendix A Proofs</h2>
<figure class="ltx_figure"><img src="x1.png"><figcaption>Figure 1: A plot.</figcaption></figure>
<div class="ltx_para"><p class="ltx_p">The proof.</p></div>
</section>
<section id="bib" class="ltx_bibliography"><h2 class="ltx_title">References</h2>
<ul><li>[1] Someone. A cited work.</li></ul></section>
</article></body></html>"""


def _receipt(db: sqlite3.Connection, clock: FakeClock) -> str:
    return record_cost_receipt(
        db,
        action="ingest",
        owner_kind="ingest_pass",
        owner_id="IP-test",
        parent_kind="source",
        parent_id="arxiv:cs.AI",
        unit_type="arxiv_request",
        quantity=1,
        amount_micros=0,
        now=clock(),
    )


def _fetcher(pages: dict[str, Any]):
    asked: list[tuple[str, int]] = []

    def fetch(paper_id: str, version: int) -> str | None:
        asked.append((paper_id, version))
        page = pages.get(paper_id)
        if isinstance(page, Exception):
            raise page
        return page

    fetch.asked = asked  # type: ignore[attr-defined]
    return fetch


def test_sections_come_out_titled_in_order_without_page_furniture() -> None:
    sections = parse_paper_html(HTML)

    assert [(s.id, s.title) for s in sections] == [
        ("S1", "1 Introduction"),
        ("S1.SS1", "1.1 Main result"),
        ("A1", "Appendix A Proofs"),
    ]
    intro, result, appendix = sections
    assert intro.paragraphs[0] == "Agents learn when traces are visible."
    # Mathematics is kept as the LaTeX it was written in.
    assert "$U_{\\beta}$" in " ".join(intro.paragraphs)
    assert result.paragraphs == [
        "The result holds for all $n$ .",
        "Deep detail stays with its parent.",
    ] or "1.1.1 Detail" in " ".join(result.paragraphs)
    assert "Figure 1: A plot." in appendix.paragraphs
    text = " ".join(p for s in sections for p in s.paragraphs)
    for absent in ("menu", "A footnote", "The abstract again", "A cited work", "var a"):
        assert absent not in text


def test_a_long_section_is_split_at_paragraphs_into_numbered_parts() -> None:
    sections = parse_paper_html(HTML)
    sections[0].paragraphs = [("word " * 500).strip()] * 5

    parts = split_section(sections[0])

    assert len(parts) > 1
    assert all(len(text) <= PASSAGE_CHARS for _, _, text in parts)
    assert [pid for pid, _, _ in parts][:2] == ["S1", "S1-2"]
    assert parts[1][1] == f"1 Introduction (part 2 of {len(parts)})"


def test_ingestion_stores_the_full_text_and_agents_read_it_by_section(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)
    plan = budget_state(db, spec, clock(), True).plan
    fetch_text = _fetcher({PAPER: HTML})

    summary = run_ingestion_pass(
        db,
        spec,
        plan,
        fetch=lambda category, limit: feed(entry(PAPER)),
        clock=clock,
        categories=["cs.AI"],
        sleep=lambda _: None,
        fetch_text=fetch_text,
    )

    assert summary["full_text"] == {
        "full_text": 1,
        "no_html_version": 0,
        "failed": 0,
        "passages": 3,
    }
    assert fetch_text.asked == [(PAPER, 1)]
    passages = load_passages(db, PAPER)
    assert [(p["id"], p["kind"], p["title"]) for p in passages] == [
        (f"{PAPER}:abstract", "abstract", "Abstract"),
        (f"{PAPER}:S1", "section", "1 Introduction"),
        (f"{PAPER}:S1.SS1", "section", "1.1 Main result"),
        (f"{PAPER}:A1", "section", "Appendix A Proofs"),
    ]
    # Offsets run on from the abstract without overlapping.
    for before, after in zip(passages, passages[1:], strict=False):
        assert after["char_start"] == before["char_end"] + 2
    view = build_paper_projection(db, PAPER)
    assert view["paper"]["text_status"] == "full_text"
    assert view["paper"]["sections"][1]["title"] == "1 Introduction"

    # A second pass does not ask again.
    run_ingestion_pass(
        db,
        spec,
        plan,
        fetch=lambda category, limit: feed(entry(PAPER)),
        clock=clock,
        categories=["cs.AI"],
        sleep=lambda _: None,
        fetch_text=fetch_text,
    )
    assert fetch_text.asked == [(PAPER, 1)]

    # The run's prompt carries the outline, and paper_text reads a section by id.
    revision, spec = specs.current_spec(db)
    run_id = create_run(
        db,
        spec=spec,
        revision=revision,
        provider=PROVIDER,
        clock=clock,
        paper_id=PAPER,
        island_id="cs",
        genome_id="cs-reader",
    )
    db.commit()
    execute_run(
        cfg.database,
        run_id,
        client=ScriptedClient(
            [
                reply(call("paper_text", {"passage_id": "S1.SS1"})),
                reply(call("submit_reading", reading("The result holds for all"))),
            ]
        ),
        provider=PROVIDER,
        clock=clock,
    )
    run = build_run_projection(db, run_id)
    assert run["run"]["status"] == "completed"
    # A paper this short fits whole in the prompt, every section in its place.
    user = run["run"]["prompt"]["user"]
    assert f"Passage {PAPER}:S1.SS1 (section): The result holds" in user
    read = [e for e in run["events"] if e["kind"] == "paper_read"]
    assert [e["payload"]["passage_id"] for e in read][-1] == f"{PAPER}:S1.SS1"
    assert read[-1]["locator"]["section"] == f"{PAPER}:S1.SS1"
    claim = run["reading"]["claims"][0]["evidence"][0]
    assert claim["verified"] and claim["locator"]["passage_id"] == f"{PAPER}:S1.SS1"


def test_a_paper_without_an_html_version_keeps_its_abstract_and_says_why(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    for paper_id in ("2609.00001", "2609.00002", "2609.00003"):
        upsert_paper(db, entry(paper_id), _receipt(db, clock), clock())
    fetch_text = _fetcher(
        {
            "2609.00002": "<html><body>No HTML here.</body></html>",
            "2609.00003": TextFetchFailed("arXiv answered 503"),
        }
    )

    counts = fetch_full_texts(
        db,
        fetch=fetch_text,
        clock=clock,
        owner_id="IP-1",
        limit=10,
        sleep=lambda _: None,
    )

    assert counts == {"full_text": 0, "no_html_version": 2, "failed": 1, "passages": 0}
    reasons = dict(db.execute("SELECT id, text_failure FROM papers").fetchall())
    assert reasons == {
        "2609.00001": "no_html_version",
        "2609.00002": "html_without_sections",
        "2609.00003": "html_fetch_failed: arXiv answered 503",
    }
    statuses = {row[0] for row in db.execute("SELECT text_status FROM papers")}
    assert statuses == {"abstract_only"}
    # Every request to arXiv left its zero-cost receipt.
    requests = db.execute(
        "SELECT COUNT(*) FROM cost_receipts WHERE parent_id LIKE 'arxiv-html:%'"
    ).fetchone()[0]
    assert requests == 3
    # A new version of a paper is looked for again.
    upsert_paper(db, entry("2609.00001", version=2), _receipt(db, clock), clock())
    again = _fetcher({"2609.00001": HTML})
    fetch_full_texts(
        db, fetch=again, clock=clock, owner_id="IP-2", limit=10, sleep=lambda _: None
    )
    assert again.asked == [("2609.00001", 2)]


def test_one_paper_text_call_returns_a_bounded_amount_and_names_the_rest() -> None:
    from research_agent.beta import runs

    passages = [
        {
            "id": f"{PAPER}:abstract",
            "kind": "abstract",
            "title": "Abstract",
            "text": "a" * 900,
        },
        *[
            {
                "id": f"{PAPER}:S{n}",
                "kind": "section",
                "title": f"{n} Part",
                "text": "s" * 3000,
            }
            for n in range(1, 5)
        ],
    ]

    class Ctx:
        pass

    ctx = Ctx()
    ctx.passages = passages  # type: ignore[attr-defined]
    ctx.paper_id = PAPER  # type: ignore[attr-defined]
    result = runs._run_tool(
        ctx, call("paper_text", {"passage_id": "section"}), {"passage_id": "section"}
    )  # type: ignore[arg-type]

    assert [p["passage_id"] for p in result["passages"]] == [f"{PAPER}:S1"]
    assert result["not_returned"] == [f"{PAPER}:S2", f"{PAPER}:S3", f"{PAPER}:S4"]
    assert "ask for one by its id" in result["note"]


def test_the_outline_folds_a_split_section_into_one_line() -> None:
    passages = [
        {
            "id": f"{PAPER}:abstract",
            "kind": "abstract",
            "title": "Abstract",
            "text": "a" * 900,
        },
        {
            "id": f"{PAPER}:S1",
            "kind": "section",
            "title": "1 Intro (part 1 of 2)",
            "text": "x" * 3000,
        },
        {
            "id": f"{PAPER}:S1-2",
            "kind": "section",
            "title": "1 Intro (part 2 of 2)",
            "text": "x" * 1000,
        },
        {
            "id": f"{PAPER}:S2",
            "kind": "section",
            "title": "2 Method",
            "text": "y" * 2000,
        },
    ]

    assert passage_outline(passages) == [
        f"- {PAPER}:abstract: Abstract (900 characters)",
        f"- {PAPER}:S1 to {PAPER}:S1-2: 1 Intro, 2 parts (4,000 characters)",
        f"- {PAPER}:S2: 2 Method (2,000 characters)",
    ]


def test_retention_forgets_only_old_papers_no_agent_touched(
    db: sqlite3.Connection, cfg: BetaConfig, clock: FakeClock
) -> None:
    for paper_id in ("2609.00001", "2609.00002", "2609.00003"):
        upsert_paper(db, entry(paper_id), _receipt(db, clock), clock())
    db.execute(
        "INSERT INTO assignments(paper_id, island_id, reasons, created_at)"
        " VALUES ('2609.00001', 'cs', '[]', 'x')"
    )
    # 2609.00002 was read; 2609.00003 drew feedback; 2609.00001 was never touched.
    revision, spec = specs.current_spec(db)
    create_run(
        db,
        spec=spec,
        revision=revision,
        provider=PROVIDER,
        clock=clock,
        paper_id="2609.00002",
        island_id="cs",
        genome_id="cs-reader",
    )
    db.execute(
        "INSERT INTO feedback(id, island_id, target_kind, target_id, signal, paper_id,"
        " created_at) VALUES ('F-1', 'cs', 'paper', '2609.00003', 'accept',"
        " '2609.00003', 'x')"
    )
    later = clock() + timedelta(days=15)

    assert prune_unread_papers(db, clock(), 14) == 0
    assert prune_unread_papers(db, later, 14) == 1

    remaining = [row[0] for row in db.execute("SELECT id FROM papers ORDER BY id")]
    assert remaining == ["2609.00002", "2609.00003"]
    for table in ("paper_passages", "assignments", "search_index"):
        gone = db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE paper_id = '2609.00001'"
        ).fetchone()[0]
        assert gone == 0, table


def test_the_retention_age_is_a_lever(db: sqlite3.Connection) -> None:
    _, spec = specs.current_spec(db)
    from research_agent.beta.budget import levers_from
    from research_agent.beta.errors import Invalid

    assert levers_from({}).unread_paper_days == 14
    assert levers_from({"unread_paper_days": 30}).unread_paper_days == 30
    with pytest.raises(Invalid):
        levers_from({"unread_paper_days": 0})
