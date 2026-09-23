"""FastAPI wiring for the owner-only, read-only storage inspector (#128).

Server-rendered HTML over the storage `inspector` role; no session and no
JavaScript beyond what the private rating app already uses (`web/app.py`).
Network reach is the platform's own boundary (PL-19), exactly as for the
rating app; this app checks nothing beyond a well-formed path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from research_agent.contracts import ContractValidationError
from research_agent.storage.client import StorageClient
from research_agent.web.inspect.views import (
    read_agent_view,
    read_manifest_view,
    read_population_view,
    read_run_view,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class InspectorAppConfig:
    """Everything one running inspector needs, reached only through storage."""

    storage: StorageClient


def create_app(config: InspectorAppConfig) -> FastAPI:
    app = FastAPI(title="inspector", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, run_id: str) -> HTMLResponse:
        try:
            view = read_run_view(config.storage, UUID(run_id))
        except (ValueError, ContractValidationError) as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        if view is None:
            raise HTTPException(status_code=404, detail="run not found")
        return templates.TemplateResponse(
            request,
            "run.html",
            {"run": view.run, "submissions": view.submissions},
        )

    @app.get("/agents", response_class=HTMLResponse)
    def population_page(request: Request, cursor: str | None = None) -> HTMLResponse:
        try:
            parsed_cursor = _parse_cursor(cursor)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        view = read_population_view(config.storage, cursor=parsed_cursor)
        return templates.TemplateResponse(
            request,
            "population.html",
            {
                "configurations": view.configurations,
                "next_cursor_query": _cursor_query(view.next_cursor),
            },
        )

    @app.get("/agents/{configuration_id}", response_class=HTMLResponse)
    def agent_page(
        request: Request,
        configuration_id: str,
        cursor: str | None = None,
        forecast_cursor: str | None = None,
    ) -> HTMLResponse:
        try:
            parsed_cursor = _parse_cursor(cursor)
            parsed_forecast_cursor = _parse_cursor(forecast_cursor)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            view = read_agent_view(
                config.storage,
                UUID(configuration_id),
                cursor=parsed_cursor,
                forecasts_cursor=parsed_forecast_cursor,
            )
        except (ValueError, ContractValidationError) as error:
            raise HTTPException(
                status_code=404, detail="configuration not found"
            ) from error
        return templates.TemplateResponse(
            request,
            "agent.html",
            {
                "configuration_id": view.configuration_id,
                "genome": view.genome,
                "runs": view.runs,
                "next_cursor_query": _cursor_query(view.next_cursor),
                "forecasts": view.forecasts,
                "forecasts_next_cursor_query": _cursor_query(
                    view.forecasts_next_cursor
                ),
            },
        )

    @app.get("/models/{manifest_hash}", response_class=HTMLResponse)
    def models_page(request: Request, manifest_hash: str) -> HTMLResponse:
        try:
            view = read_manifest_view(config.storage, manifest_hash)
        except ContractValidationError as error:
            raise HTTPException(status_code=404, detail="manifest not found") from error
        if view is None:
            raise HTTPException(status_code=404, detail="manifest not found")
        return templates.TemplateResponse(
            request, "manifest.html", {"manifest": view.manifest}
        )

    return app


def _cursor_query(value: str | None) -> str | None:
    return quote(value, safe="") if value is not None else None


def _parse_cursor(value: str | None) -> tuple[str, str] | None:
    if value is None:
        return None
    created_at, separator, run_id = value.partition(",")
    if not separator:
        raise ValueError("cursor is not an admitted value")
    return created_at, run_id
