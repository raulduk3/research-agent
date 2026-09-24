"""FastAPI wiring for the owner-only, read-only storage inspector (#128).

Server-rendered HTML over the storage `inspector` role; no session and no
JavaScript beyond what the private rating app already uses (`web/app.py`).
Every page also has its ``/api/v1`` JSON twin built from the same view
(``web/api.py``, #249). Network reach is the platform's own boundary
(PL-19), exactly as for the rating app; this app checks nothing beyond a
well-formed path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from research_agent.contracts import ContractValidationError
from research_agent.storage.client import StorageClient
from research_agent.web import api
from research_agent.web.inspect.views import (
    AgentView,
    ManifestView,
    PopulationView,
    RunView,
    agent_data,
    cursor_query,
    manifest_data,
    parse_cursor,
    population_data,
    read_agent_view,
    read_manifest_view,
    read_population_view,
    read_run_view,
    run_data,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class InspectorAppConfig:
    """Everything one running inspector needs, reached only through storage."""

    storage: StorageClient


def create_app(config: InspectorAppConfig) -> FastAPI:
    app = FastAPI(title="inspector", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    api.install(app)

    def parsed_cursor(value: str | None) -> tuple[str, str] | None:
        try:
            return parse_cursor(value)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def load_run(run_id: str) -> RunView:
        try:
            view = read_run_view(config.storage, UUID(run_id))
        except (ValueError, ContractValidationError) as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        if view is None:
            raise HTTPException(status_code=404, detail="run not found")
        return view

    def load_population(cursor: str | None) -> PopulationView:
        return read_population_view(config.storage, cursor=parsed_cursor(cursor))

    def load_agent(
        configuration_id: str, cursor: str | None, forecast_cursor: str | None
    ) -> AgentView:
        parsed = parsed_cursor(cursor)
        parsed_forecasts = parsed_cursor(forecast_cursor)
        try:
            return read_agent_view(
                config.storage,
                UUID(configuration_id),
                cursor=parsed,
                forecasts_cursor=parsed_forecasts,
            )
        except (ValueError, ContractValidationError) as error:
            raise HTTPException(
                status_code=404, detail="configuration not found"
            ) from error

    def load_manifest(manifest_hash: str) -> ManifestView:
        try:
            view = read_manifest_view(config.storage, manifest_hash)
        except ContractValidationError as error:
            raise HTTPException(status_code=404, detail="manifest not found") from error
        if view is None:
            raise HTTPException(status_code=404, detail="manifest not found")
        return view

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, run_id: str) -> HTMLResponse:
        view = load_run(run_id)
        return templates.TemplateResponse(
            request,
            "run.html",
            {"run": view.run, "submissions": view.submissions},
        )

    @app.get(f"{api.PREFIX}/runs/{{run_id}}")
    def api_run(run_id: str) -> JSONResponse:
        return api.ok(run_data(load_run(run_id)))

    @app.get("/agents", response_class=HTMLResponse)
    def population_page(request: Request, cursor: str | None = None) -> HTMLResponse:
        view = load_population(cursor)
        return templates.TemplateResponse(
            request,
            "population.html",
            {
                "configurations": view.configurations,
                "next_cursor_query": cursor_query(view.next_cursor),
            },
        )

    @app.get(f"{api.PREFIX}/agents")
    def api_population(cursor: str | None = None) -> JSONResponse:
        return api.ok(population_data(load_population(cursor)))

    @app.get("/agents/{configuration_id}", response_class=HTMLResponse)
    def agent_page(
        request: Request,
        configuration_id: str,
        cursor: str | None = None,
        forecast_cursor: str | None = None,
    ) -> HTMLResponse:
        view = load_agent(configuration_id, cursor, forecast_cursor)
        return templates.TemplateResponse(
            request,
            "agent.html",
            {
                "configuration_id": view.configuration_id,
                "genome": view.genome,
                "runs": view.runs,
                "next_cursor_query": cursor_query(view.next_cursor),
                "forecasts": view.forecasts,
                "forecasts_next_cursor_query": cursor_query(view.forecasts_next_cursor),
            },
        )

    @app.get(f"{api.PREFIX}/agents/{{configuration_id}}")
    def api_agent(
        configuration_id: str,
        cursor: str | None = None,
        forecast_cursor: str | None = None,
    ) -> JSONResponse:
        return api.ok(agent_data(load_agent(configuration_id, cursor, forecast_cursor)))

    @app.get("/models/{manifest_hash}", response_class=HTMLResponse)
    def models_page(request: Request, manifest_hash: str) -> HTMLResponse:
        view = load_manifest(manifest_hash)
        return templates.TemplateResponse(
            request, "manifest.html", {"manifest": view.manifest}
        )

    @app.get(f"{api.PREFIX}/models/{{manifest_hash}}")
    def api_manifest(manifest_hash: str) -> JSONResponse:
        return api.ok(manifest_data(load_manifest(manifest_hash)))

    return app
