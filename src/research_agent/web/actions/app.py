"""FastAPI wiring for the owner actions app: admit, retire, seed (#139).

Server-rendered HTML over an owner-only session, the same discipline
``web/app.py`` applies to a rater session: no SPA, no client framework,
mutating routes require the session's CSRF token. Network reach is the
platform's own boundary (PL-19). Like the rating and inspector apps, this
app reaches storage only through a :class:`StorageClient` over the
mutually-authenticated HTTP boundary, holding the ``owner`` role's scopes
(#234); it imports no storage repository module.

Every action here is refused for anything but the authenticated owner
identity (the session already fixes that -- there is no second identity a
form field could name), and every action appears in the history this app's
own pages read back: an admitted genome's :func:`agent_page`, and the full
:func:`retrospective_page`. Neither page renders a digest entry or a
nominating genome, so the blindness SR-21 and SR-22 already apply to a
rater's digest is never at stake here (#139).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from research_agent.contracts import ContractValidationError
from research_agent.evolution.genome import EMPHASIS_FIELDS
from research_agent.storage.client import (
    OwnerActionResult,
    StorageClient,
    StorageClientError,
)
from research_agent.web.auth import (
    OWNER_SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    AuthenticationError,
    OwnerDirectory,
    OwnerSession,
    OwnerSessionStore,
    authenticate_owner_session,
    verify_owner_csrf,
)
from research_agent.web.inspect.views import (
    cursor_query,
    guard_digest_for_rater,
    parse_cursor,
    read_agent_view,
    read_manifest_view,
    read_population_view,
    read_rated_entry_ids,
    read_run_view,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
# The inspector's population, run and manifest pages are served here as they
# are; this app's own templates come first, so its agent page stays its own.
INSPECTOR_TEMPLATES_DIR = Path(__file__).parent.parent / "inspect" / "templates"
EMPHASIS_FIELD_ORDER: tuple[str, ...] = tuple(sorted(EMPHASIS_FIELDS))


def _parse_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="not found") from error


def _verify_csrf(session: OwnerSession, presented: str) -> None:
    try:
        verify_owner_csrf(session, presented)
    except AuthenticationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


def _refusal_status(result: OwnerActionResult) -> int:
    if result.reason == "not_owner":
        return 403
    if result.reason in ("unknown_source_genome", "unknown_genome"):
        return 404
    return 409


@dataclass(frozen=True, slots=True)
class ActionsAppConfig:
    """Everything one running owner actions app needs.

    ``corpus_identifiers`` backs AG-31's admission-time scan (a caller's
    job, the same boundary ``agents/admission.py`` draws).
    ``budget_funded`` is the launch profile's funded-inference gate
    (``platform/profile.py``'s ``BudgetGroup``), read by whoever composes
    this app rather than imported here, so this web layer never depends on
    the platform layer above it. ``completed_weekly_cycles`` is ``None``
    until a real weekly-cycle integration exists; an edit-and-admit request
    is refused as cycle-disabled until then, honestly reflecting that no
    cycle has been recorded yet. ``health`` returns the platform health
    monitor's report (``HealthMonitor.report``), supplied by whoever
    composes this app for the same reason as ``budget_funded``; without it
    ``GET /api/v1/health`` answers 503 rather than inventing a state (#254).
    ``inspector`` is a second client holding the ``inspector`` role's read
    scopes and ``ratings:rated``: the population, agent, run and manifest
    reads and the digest guard go through it, so a browser session reaches
    what the certificate-holding inspector app serves (#255). Those routes
    answer 503 without it. ``owner_rater_id`` is the rater identity the owner
    also holds, whose rated entries the digest guard reads; without it the
    digest route answers 503.
    """

    actions: StorageClient
    directory: OwnerDirectory
    corpus_identifiers: Collection[str] = field(default_factory=tuple)
    profile_hash: str = ""
    budget_funded: bool = False
    completed_weekly_cycles: int | None = None
    health: Callable[[], Mapping[str, object]] | None = None
    inspector: StorageClient | None = None
    owner_rater_id: UUID | None = None


def create_app(config: ActionsAppConfig) -> FastAPI:
    """Build the owner actions app; each call gets its own session store."""
    app = FastAPI(
        title="owner-actions", docs_url=None, redoc_url=None, openapi_url=None
    )
    templates = Jinja2Templates(
        directory=[str(TEMPLATES_DIR), str(INSPECTOR_TEMPLATES_DIR)]
    )
    sessions = OwnerSessionStore()

    def require_session(request: Request) -> OwnerSession:
        try:
            return authenticate_owner_session(
                sessions, request.cookies.get(OWNER_SESSION_COOKIE_NAME)
            )
        except AuthenticationError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

    def set_session_cookie(response: RedirectResponse, session: OwnerSession) -> None:
        response.set_cookie(
            OWNER_SESSION_COOKIE_NAME,
            session.session_id,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            secure=True,
            httponly=True,
            samesite="strict",
        )

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login", response_model=None)
    def login(
        request: Request, credential: str = Form(...)
    ) -> HTMLResponse | RedirectResponse:
        principal = config.directory.authenticate(credential)
        if principal is None:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "credential not recognized"},
                status_code=401,
            )
        session = sessions.issue(principal.owner_id)
        response = RedirectResponse("/", status_code=303)
        set_session_cookie(response, session)
        return response

    @app.post("/logout")
    def logout(
        request: Request, session: OwnerSession = Depends(require_session)
    ) -> RedirectResponse:
        sessions.revoke(session.session_id)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(OWNER_SESSION_COOKIE_NAME)
        return response

    @app.get("/", response_class=HTMLResponse)
    def retrospective_page(
        request: Request, session: OwnerSession = Depends(require_session)
    ) -> HTMLResponse:
        admissions, retirements = config.actions.retrospective()
        return templates.TemplateResponse(
            request,
            "retrospective.html",
            {
                "admissions": admissions,
                "retirements": retirements,
                "csrf_token": session.csrf_token,
            },
        )

    @app.get("/api/v1/health")
    def health(session: OwnerSession = Depends(require_session)) -> JSONResponse:
        if config.health is None:
            raise HTTPException(status_code=503, detail="health monitor unavailable")
        return JSONResponse(dict(config.health()))

    def require_inspector() -> StorageClient:
        if config.inspector is None:
            raise HTTPException(status_code=503, detail="inspector reads unavailable")
        return config.inspector

    def parsed_cursor(value: str | None) -> tuple[str, str] | None:
        try:
            return parse_cursor(value)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/agents", response_class=HTMLResponse)
    def population_page(
        request: Request,
        cursor: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        view = read_population_view(require_inspector(), cursor=parsed_cursor(cursor))
        return templates.TemplateResponse(
            request,
            "population.html",
            {
                "configurations": view.configurations,
                "next_cursor_query": cursor_query(view.next_cursor),
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(
        request: Request,
        run_id: str,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        inspector = require_inspector()
        try:
            view = read_run_view(inspector, UUID(run_id))
        except (ValueError, ContractValidationError) as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        if view is None:
            raise HTTPException(status_code=404, detail="run not found")
        return templates.TemplateResponse(
            request,
            "run.html",
            {"run": view.run, "submissions": view.submissions},
        )

    @app.get("/models/{manifest_hash}", response_class=HTMLResponse)
    def models_page(
        request: Request,
        manifest_hash: str,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        inspector = require_inspector()
        try:
            view = read_manifest_view(inspector, manifest_hash)
        except ContractValidationError as error:
            raise HTTPException(status_code=404, detail="manifest not found") from error
        if view is None:
            raise HTTPException(status_code=404, detail="manifest not found")
        return templates.TemplateResponse(
            request, "manifest.html", {"manifest": view.manifest}
        )

    @app.get("/api/v1/digests/{digest_hash}")
    def digest(
        digest_hash: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """A stored digest as the owner, who is also a rater, may see it (#255)."""
        inspector = require_inspector()
        if config.owner_rater_id is None:
            raise HTTPException(status_code=503, detail="owner rater unavailable")
        try:
            stored = inspector.read_digest_with_provenance(digest_hash)
        except ContractValidationError as error:
            raise HTTPException(status_code=404, detail="digest not found") from error
        except StorageClientError as error:
            if error.code == "not_found":
                raise HTTPException(
                    status_code=404, detail="digest not found"
                ) from error
            raise
        rated = read_rated_entry_ids(inspector, config.owner_rater_id)
        return JSONResponse(guard_digest_for_rater(stored.data, rated))

    @app.get("/agents/{configuration_id}", response_class=HTMLResponse)
    def agent_page(
        request: Request,
        configuration_id: str,
        cursor: str | None = None,
        forecast_cursor: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        parsed = _parse_id(configuration_id)
        genome = config.actions.read_genome_view(parsed)
        if genome is None:
            raise HTTPException(status_code=404, detail="agent not found")
        admission = config.actions.admission_history(parsed)
        retirement = config.actions.retirement_status(parsed)
        inspected = (
            read_agent_view(
                config.inspector,
                parsed,
                cursor=parsed_cursor(cursor),
                forecasts_cursor=parsed_cursor(forecast_cursor),
            )
            if config.inspector is not None
            else None
        )
        return templates.TemplateResponse(
            request,
            "agent.html",
            {
                "genome": genome,
                "emphasis_fields": EMPHASIS_FIELD_ORDER,
                "admission": admission,
                "retirement": retirement,
                "csrf_token": session.csrf_token,
                "inspected": inspected,
                "next_cursor_query": inspected and cursor_query(inspected.next_cursor),
                "forecasts_next_cursor_query": inspected
                and cursor_query(inspected.forecasts_next_cursor),
            },
        )

    @app.post("/agents/{configuration_id}/admit", response_model=None)
    def admit(
        request: Request,
        configuration_id: str,
        csrf_token: str = Form(...),
        lineage_id: str = Form(...),
        prompt: str = Form(""),
        scan_policy: str = Form(""),
        read_policy: str = Form(""),
        probability_assignment_rule: str = Form(""),
        session: OwnerSession = Depends(require_session),
    ) -> RedirectResponse:
        _verify_csrf(session, csrf_token)
        source_id = _parse_id(configuration_id)
        source = config.actions.read_genome_view(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="agent not found")
        submitted = {
            "prompt": prompt,
            "scan_policy": scan_policy,
            "read_policy": read_policy,
            "probability_assignment_rule": probability_assignment_rule,
        }
        stored_emphasis = source["emphasis"]
        assert isinstance(stored_emphasis, dict)
        changes = {
            name: value
            for name, value in submitted.items()
            if value and value != stored_emphasis.get(name)
        }
        try:
            result = config.actions.admit_edited_genome(
                owner_id=session.owner_id,
                source_configuration_id=source_id,
                new_configuration_id=uuid4(),
                changes=changes,
                lineage_id=lineage_id,
                corpus_identifiers=config.corpus_identifiers,
                completed_weekly_cycles=config.completed_weekly_cycles,
                profile_hash=config.profile_hash or None,
                command_id=uuid4(),
            )
        except ContractValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not result.accepted:
            raise HTTPException(
                status_code=_refusal_status(result), detail=result.reason
            )
        return RedirectResponse(f"/agents/{result.configuration_id}", status_code=303)

    @app.post("/agents/{configuration_id}/retire", response_model=None)
    def retire(
        request: Request,
        configuration_id: str,
        csrf_token: str = Form(...),
        session: OwnerSession = Depends(require_session),
    ) -> RedirectResponse:
        _verify_csrf(session, csrf_token)
        result = config.actions.retire_genome(
            owner_id=session.owner_id,
            configuration_id=_parse_id(configuration_id),
            command_id=uuid4(),
        )
        if not result.accepted:
            raise HTTPException(
                status_code=_refusal_status(result), detail=result.reason
            )
        return RedirectResponse(f"/agents/{configuration_id}", status_code=303)

    @app.get("/seed", response_class=HTMLResponse)
    def seed_form(
        request: Request,
        template: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        copied: dict[str, object] | None = None
        if template:
            copied = config.actions.read_genome_view(_parse_id(template))
            if copied is None:
                raise HTTPException(status_code=404, detail="template not found")
        return templates.TemplateResponse(
            request,
            "seed.html",
            {
                "emphasis_fields": EMPHASIS_FIELD_ORDER,
                "copied": copied,
                "csrf_token": session.csrf_token,
            },
        )

    @app.post("/seed", response_model=None)
    def seed(
        request: Request,
        csrf_token: str = Form(...),
        island: str = Form(...),
        lineage_id: str = Form(...),
        template_configuration_id: str = Form(...),
        prompt: str = Form(...),
        scan_policy: str = Form(...),
        read_policy: str = Form(...),
        probability_assignment_rule: str = Form(...),
        session: OwnerSession = Depends(require_session),
    ) -> RedirectResponse:
        _verify_csrf(session, csrf_token)
        emphasis = {
            "prompt": prompt,
            "scan_policy": scan_policy,
            "read_policy": read_policy,
            "probability_assignment_rule": probability_assignment_rule,
        }
        try:
            result = config.actions.seed_variant(
                owner_id=session.owner_id,
                new_configuration_id=uuid4(),
                island=island,
                lineage_id=lineage_id,
                emphasis=emphasis,
                template_configuration_id=_parse_id(template_configuration_id),
                corpus_identifiers=config.corpus_identifiers,
                profile_hash=config.profile_hash,
                budget_funded=config.budget_funded,
                command_id=uuid4(),
            )
        except ContractValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not result.accepted:
            raise HTTPException(
                status_code=_refusal_status(result), detail=result.reason
            )
        return RedirectResponse(f"/agents/{result.configuration_id}", status_code=303)

    return app
