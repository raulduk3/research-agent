"""FastAPI wiring for the owner actions app: admit, retire, seed (#139).

Server-rendered HTML over an owner-only session, the same discipline
``web/app.py`` applies to a rater session: no SPA, no client framework,
mutating routes require the session's CSRF token. Network reach is the
platform's own boundary (PL-19). This app reaches storage's population
commands directly through :class:`OwnerActions`, not through the
mutually-authenticated HTTP client boundary the rating and inspector apps
use (see ``storage/actions.py`` for why), since it is single-host,
owner-only tooling.

Every action here is refused for anything but the authenticated owner
identity (the session already fixes that -- there is no second identity a
form field could name), and every action appears in the history this app's
own pages read back: an admitted genome's :func:`agent_page`, and the full
:func:`retrospective_page`. Neither page renders a digest entry or a
nominating genome, so the blindness SR-21 and SR-22 already apply to a
rater's digest is never at stake here (#139).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from research_agent.contracts import ContractValidationError
from research_agent.evolution.genome import EMPHASIS_FIELDS
from research_agent.storage.actions import OwnerActionResult, OwnerActions
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

TEMPLATES_DIR = Path(__file__).parent / "templates"
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
    cycle has been recorded yet.
    """

    actions: OwnerActions
    directory: OwnerDirectory
    corpus_identifiers: Collection[str] = field(default_factory=tuple)
    profile_hash: str = ""
    budget_funded: bool = False
    completed_weekly_cycles: int | None = None


def create_app(config: ActionsAppConfig) -> FastAPI:
    """Build the owner actions app; each call gets its own session store."""
    app = FastAPI(
        title="owner-actions", docs_url=None, redoc_url=None, openapi_url=None
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
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

    @app.get("/agents/{configuration_id}", response_class=HTMLResponse)
    def agent_page(
        request: Request,
        configuration_id: str,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        parsed = _parse_id(configuration_id)
        genome = config.actions.read_genome_view(parsed)
        if genome is None:
            raise HTTPException(status_code=404, detail="agent not found")
        admission = config.actions.admission_history(parsed)
        retirement = config.actions.retirement_status(parsed)
        return templates.TemplateResponse(
            request,
            "agent.html",
            {
                "genome": genome,
                "emphasis_fields": EMPHASIS_FIELD_ORDER,
                "admission": admission,
                "retirement": retirement,
                "csrf_token": session.csrf_token,
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
