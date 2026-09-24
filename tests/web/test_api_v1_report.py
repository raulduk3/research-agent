"""The weekly report's /api/v1 twin serves the page's own view (#249)."""

from __future__ import annotations

import pytest
from tests.web.api_contract import (
    WEB_DIR,
    check,
    check_refusal,
    html_fields_missing_from,
)
from tests.web.test_report import WEEK, client

PATH = "/api/v1/reports/{island}/{iso_week}"


@pytest.mark.parametrize("island", ["cs", "q-bio"])
def test_the_report_validates_and_carries_every_field_the_page_shows(
    island: str,
) -> None:
    data = check(
        client().get(f"/api/v1/reports/{island}/{WEEK}"), "report", "GET", PATH
    )
    template = WEB_DIR / "report" / "templates" / "report.html"
    assert html_fields_missing_from(template, data) == []
    assert data["report"]["island"] == island
    assert [row["founder"] for row in data["report"]["rows"]] == [True, False]


def test_a_field_the_page_shows_and_the_json_drops_is_reported() -> None:
    data = check(client().get(f"/api/v1/reports/cs/{WEEK}"), "report", "GET", PATH)
    template = WEB_DIR / "report" / "templates" / "report.html"
    report = data["report"]
    dropped = {
        **data,
        "notice": None,
        "report": {
            **{key: value for key, value in report.items() if key != "migrations"},
            "rows": [
                {key: value for key, value in row.items() if key != "founder"}
                for row in report["rows"]
            ],
        },
    }
    del dropped["notice"]
    assert html_fields_missing_from(template, dropped) == [
        "notice",
        "report.migrations",
        "report.rows[].founder",
    ]


def test_an_unknown_island_week_or_report_is_the_not_found_envelope() -> None:
    for path in (
        f"/api/v1/reports/astro/{WEEK}",
        "/api/v1/reports/cs/2026-38",
        "/api/v1/reports/cs/2026-W01",
    ):
        check_refusal(client().get(path), 404, "not_found")
