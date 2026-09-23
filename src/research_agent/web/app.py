"""FastAPI wiring for the private, server-rendered rating app (PL-22).

Server-rendered HTML over authenticated sessions; no SPA, no client
framework, no JavaScript beyond what an HTML form needs (Appendix A).
Every page also has its ``/api/v1`` JSON twin built from the same view
(``web/api.py``, #249). Network reach is enforced by the platform (PL-19),
not by this app; the app only checks the rater credential and session (PL-22).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from research_agent.storage.client import StorageClient
from research_agent.web import api
from research_agent.web.auth import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    AuthenticationError,
    RaterDirectory,
    RaterSession,
    SessionStore,
    authenticate_session,
    verify_csrf,
)
from research_agent.web.digest import DigestFixture
from research_agent.web.projections import blind_digest
from research_agent.web.ratings import submit_rating
from research_agent.web.rendering import AUTOMATED_OUTPUT_NOTICE, validate_output_label

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class RatingAppConfig:
    """Everything one running rating app needs, all reached through interfaces it owns no data behind."""

    storage: StorageClient
    directory: RaterDirectory
    digest: DigestFixture


def create_app(config: RatingAppConfig) -> FastAPI:
    """Build the rating app; each call gets its own session."""
    app = FastAPI(title="rating-app", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    sessions = SessionStore()
    idempotency = api.IdempotencyCache()
    api.install(app)

    def require_session(request: Request) -> RaterSession:
        try:
            return authenticate_session(
                sessions, request.cookies.get(SESSION_COOKIE_NAME)
            )
        except AuthenticationError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

    def set_session_cookie(response: Response, session: RaterSession) -> None:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session.session_id,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            secure=True,
            httponly=True,
            samesite="strict",
        )

    def login_view() -> dict[str, Any]:
        return {"notice": validate_output_label(AUTOMATED_OUTPUT_NOTICE)}

    def digest_view(session: RaterSession) -> dict[str, Any]:
        return {
            "notice": validate_output_label(AUTOMATED_OUTPUT_NOTICE),
            "rows": [
                row.to_dict()
                for row in blind_digest(config.digest.entries, seed=config.digest.seed)
            ],
            "csrf_token": session.csrf_token,
        }

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "login.html", {**login_view(), "error": None}
        )

    @app.get(f"{api.PREFIX}/login")
    def api_login_form() -> JSONResponse:
        return api.ok(login_view())

    @app.post(f"{api.PREFIX}/login")
    def api_login(body: bytes = Depends(api.raw_body)) -> JSONResponse:
        """The one POST without a session, so it has no CSRF token to carry."""
        credential = api.json_fields(body, ("credential",))["credential"]
        principal = config.directory.authenticate(credential)
        if principal is None:
            raise api.ApiError(401, "credential not recognized")
        session = sessions.issue(principal.rater_id)
        response = api.ok(
            {
                "authenticated": True,
                "expires_at": api.utc_instant(session.expires_at),
                "csrf_token": session.csrf_token,
            }
        )
        set_session_cookie(response, session)
        return response

    @app.post("/login", response_model=None)
    def login(
        request: Request, credential: str = Form(...)
    ) -> HTMLResponse | RedirectResponse:
        principal = config.directory.authenticate(credential)
        if principal is None:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "notice": AUTOMATED_OUTPUT_NOTICE,
                    "error": "credential not recognized",
                },
                status_code=401,
            )
        session = sessions.issue(principal.rater_id)
        response = RedirectResponse("/", status_code=303)
        set_session_cookie(response, session)
        return response

    @app.get("/", response_class=HTMLResponse)
    def root(
        request: Request, session: RaterSession = Depends(require_session)
    ) -> HTMLResponse:
        return templates.TemplateResponse(request, "digest.html", digest_view(session))

    @app.get(f"{api.PREFIX}/digest")
    def api_digest(session: RaterSession = Depends(require_session)) -> JSONResponse:
        view = digest_view(session)
        return api.ok({**view, "rows": api.listing(view["rows"])})

    @app.post(f"{api.PREFIX}/ratings")
    def api_rate(
        request: Request,
        session: RaterSession = Depends(require_session),
        headers: tuple[str, str] = Depends(api.post_headers),
        body: bytes = Depends(api.raw_body),
    ) -> JSONResponse:
        csrf_token, key = headers
        try:
            verify_csrf(session, csrf_token)
        except AuthenticationError as error:
            raise api.ApiError(403, str(error), field="X-CSRF-Token") from error
        fields = api.json_fields(body, ("digest_entry_id", "paper_hash", "value"))
        principal = str(session.rater_id)

        def record() -> JSONResponse:
            try:
                digest_entry_id = UUID(fields["digest_entry_id"])
            except ValueError as error:
                raise api.ApiError(
                    422, "not a UUID", field="digest_entry_id"
                ) from error
            try:
                outcome = submit_rating(
                    config.storage,
                    rater_id=session.rater_id,
                    paper_hash=fields["paper_hash"],
                    digest_entry_id=digest_entry_id,
                    value=fields["value"],
                    command_id=api.derived_id("rating-command", principal, key),
                    request_id=uuid4(),
                    idempotency_key=api.derived_id("rating-key", principal, key),
                )
            except ValueError as error:
                raise api.ApiError(422, str(error)) from error
            if not outcome.accepted:
                if outcome.reason == "already rated":
                    raise api.ApiError(409, "already rated", field="digest_entry_id")
                raise api.ApiError(502, "not saved")
            return api.ok(
                {"rating_id": outcome.rating_id, "rated_at": outcome.rated_at},
                status_code=201,
            )

        return idempotency.run(
            principal, key, idempotency.fingerprint(request, body), record
        )

    @app.post("/ratings")
    def rate(
        request: Request,
        digest_entry_id: str = Form(...),
        paper_hash: str = Form(...),
        value: str = Form(...),
        csrf_token: str = Form(...),
        session: RaterSession = Depends(require_session),
    ) -> RedirectResponse:
        try:
            verify_csrf(session, csrf_token)
            outcome = submit_rating(
                config.storage,
                rater_id=session.rater_id,
                paper_hash=paper_hash,
                digest_entry_id=UUID(digest_entry_id),
                value=value,
                command_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            )
        except AuthenticationError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not outcome.accepted:
            status_code = 409 if outcome.reason == "already rated" else 502
            raise HTTPException(status_code=status_code, detail=outcome.reason)
        return RedirectResponse("/", status_code=303)

    return app
