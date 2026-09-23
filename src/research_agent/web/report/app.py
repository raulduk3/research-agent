"""FastAPI wiring for the read-only weekly island report (FT-26, #140).

Server-rendered HTML, no scripts and no form: the page has nothing to submit
and no route that asks for a replacement or a parent draw. The report itself
is built by ``measurement/weekly.py`` from stored records; this app only
loads one through the callable it is given and renders it under the
automated-output notice (IN-28). The page's ``/api/v1`` JSON twin serves the
same view (``web/api.py``, #249).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from research_agent.contracts import ContractValidationError
from research_agent.contracts.digests import DIGEST_ISLANDS
from research_agent.contracts.preference import validate_iso_week
from research_agent.measurement.weekly import IslandReport
from research_agent.web import api
from research_agent.web.rendering import AUTOMATED_OUTPUT_NOTICE, validate_output_label

TEMPLATES_DIR = Path(__file__).parent / "templates"

COMPARATOR_NAMES = {"random_control": "random controls", "service": "service picks"}


@dataclass(frozen=True, slots=True)
class ReportAppConfig:
    """Loads one island's report for one ISO week, or ``None`` when there is none."""

    load: Callable[[str, str], IslandReport | None]


def create_app(config: ReportAppConfig) -> FastAPI:
    app = FastAPI(title="report", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    api.install(app)

    def report_view(island: str, iso_week: str) -> dict[str, Any]:
        try:
            validate_iso_week(iso_week)
        except ContractValidationError as error:
            raise HTTPException(status_code=404, detail="report not found") from error
        if island not in DIGEST_ISLANDS:
            raise HTTPException(status_code=404, detail="report not found")
        report = config.load(island, iso_week)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return {
            "notice": validate_output_label(AUTOMATED_OUTPUT_NOTICE),
            "report": report,
            "comparator_names": COMPARATOR_NAMES,
        }

    @app.get("/reports/{island}/{iso_week}", response_class=HTMLResponse)
    def report_page(request: Request, island: str, iso_week: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "report.html", report_view(island, iso_week)
        )

    @app.get(f"{api.PREFIX}/reports/{{island}}/{{iso_week}}")
    def api_report(island: str, iso_week: str) -> JSONResponse:
        return api.ok(report_view(island, iso_week))

    return app
