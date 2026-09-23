"""SDD-FT-26: the weekly island report page shows the report and nothing else."""

from __future__ import annotations

from starlette.testclient import TestClient

from research_agent.measurement.preference import PreferenceCredit
from research_agent.measurement.weekly import (
    AdmittedMigration,
    IslandReport,
    PresentGenome,
    RatedEntry,
    island_report,
)
from research_agent.web.rendering import AUTOMATED_OUTPUT_NOTICE
from research_agent.web.report.app import ReportAppConfig, create_app

FOUNDER = "a" * 64
OTHER = "b" * 64
WEEK = "2026-W38"


def uid(number: int) -> str:
    return f"{number:08d}-0000-4000-8000-000000000000"


def build(island: str = "cs") -> IslandReport:
    credits = (
        []
        if island == "q-bio"
        else [PreferenceCredit(uid(1), FOUNDER, island, uid(2), 0.5, 0.25, WEEK)]
    )
    rated = (
        [] if island == "q-bio" else [RatedEntry(uid(3), "population", "like", WEEK)]
    )
    return island_report(
        island=island,
        iso_week=WEEK,
        genomes=[PresentGenome(FOUNDER, True), PresentGenome(OTHER, False)],
        skills={},
        credits=credits,
        rated_entries=rated,
        migrations=[AdmittedMigration("c" * 64, "quant-ph", "d" * 64)],
    )


def client() -> TestClient:
    def load(island: str, iso_week: str) -> IslandReport | None:
        return build(island) if iso_week == WEEK else None

    return TestClient(create_app(ReportAppConfig(load=load)))


def test_the_page_carries_the_notice_and_every_genome_with_separate_columns() -> None:
    response = client().get(f"/reports/cs/{WEEK}")
    assert response.status_code == 200
    body = response.text
    assert AUTOMATED_OUTPUT_NOTICE in body
    assert "<th>preference credit</th><th>credited entries</th>" in body
    assert FOUNDER[:12] in body and OTHER[:12] in body
    assert "founder" in body
    assert "<td>0.2500</td>" in body
    assert "random controls" in body and "service picks" in body
    assert "quant-ph" in body and ("c" * 12) in body


def test_the_qbio_page_says_why_it_has_no_preference() -> None:
    body = client().get(f"/reports/q-bio/{WEEK}").text
    assert "has no rater" in body
    assert "<td>0.0000</td>" in body
    assert "random controls" not in body


def test_an_unknown_island_week_or_report_is_not_found() -> None:
    web = client()
    assert web.get(f"/reports/physics/{WEEK}").status_code == 404
    assert web.get("/reports/cs/last-week").status_code == 404
    assert web.get("/reports/cs/2026-W01").status_code == 404


def test_the_page_offers_no_write() -> None:
    web = client()
    assert "<form" not in web.get(f"/reports/cs/{WEEK}").text
    assert web.post(f"/reports/cs/{WEEK}").status_code == 405
