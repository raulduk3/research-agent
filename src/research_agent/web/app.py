"""Private, server-rendered reader access and immutable ratings (PL-22)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from research_agent.storage.client import (
    StorageClient,
    StorageClientError,
    StorageTransportError,
)
from research_agent.web.auth import (
    PRELOGIN_CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    AuthenticationError,
    PreLoginCSRFStore,
    RaterDirectory,
    RaterSession,
    SessionStore,
    authenticate_session,
    verify_csrf,
    verify_origin,
)
from research_agent.web.digest import DigestFixture
from research_agent.web.projections import blind_digest
from research_agent.web.ratings import submit_rating
from research_agent.web.rendering import AUTOMATED_OUTPUT_NOTICE, validate_output_label

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class RatingAppConfig:
    """The storage boundary and explicitly bound digest served by this app."""

    storage: StorageClient
    directory: RaterDirectory
    digest: DigestFixture
    public_origin: str


def create_app(config: RatingAppConfig) -> FastAPI:
    verify_origin(config.public_origin, config.public_origin)
    app = FastAPI(title="rating-app", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=TEMPLATES_DIR.parent / "static"))
    sessions = SessionStore()
    login_tokens = PreLoginCSRFStore()

    def error_page(request: Request, message: str, status: int) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"notice": AUTOMATED_OUTPUT_NOTICE, "error": message},
            status_code=status,
        )

    @app.middleware("http")
    async def private_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            verify_origin(str(request.base_url).rstrip("/"), config.public_origin)
            if request.method == "POST":
                verify_origin(request.headers.get("origin"), config.public_origin)
        except AuthenticationError:
            response: Response = error_page(
                request,
                "This request could not be verified. Return to the digest and try again.",
                403,
            )
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> Response:
        if error.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return error_page(request, str(error.detail), error.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid_form(request: Request, error: RequestValidationError) -> Response:
        return error_page(
            request,
            "The form is incomplete or invalid. Return to the digest and try again.",
            422,
        )

    @app.exception_handler(StorageTransportError)
    @app.exception_handler(StorageClientError)
    async def storage_unavailable(request: Request, error: Exception) -> Response:
        return error_page(
            request,
            "Reader data is temporarily unavailable. Please try again later.",
            503,
        )

    def require_session(request: Request) -> RaterSession:
        try:
            return authenticate_session(
                sessions,
                request.cookies.get(SESSION_COOKIE_NAME),
                directory=config.directory,
            )
        except AuthenticationError as error:
            raise HTTPException(
                status_code=401, detail="Sign in to continue."
            ) from error

    def show_login(
        request: Request, *, error: str | None = None, status: int = 200
    ) -> HTMLResponse:
        token = login_tokens.issue()
        response = templates.TemplateResponse(
            request,
            "login.html",
            {
                "notice": AUTOMATED_OUTPUT_NOTICE,
                "error": error,
                "csrf_token": token.form_token,
            },
            status_code=status,
        )
        response.set_cookie(
            PRELOGIN_CSRF_COOKIE_NAME,
            token.cookie_token,
            secure=True,
            httponly=True,
            samesite="strict",
            max_age=600,
        )
        return response

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> HTMLResponse:
        return show_login(request)

    @app.post("/login", response_model=None)
    def login(
        request: Request, credential: str = Form(...), csrf_token: str = Form("")
    ) -> HTMLResponse | RedirectResponse:
        try:
            login_tokens.consume(
                request.cookies.get(PRELOGIN_CSRF_COOKIE_NAME), csrf_token
            )
        except AuthenticationError:
            return show_login(
                request,
                error="Sign-in form expired or could not be verified. Please try again.",
                status=403,
            )
        principal = config.directory.authenticate(credential)
        if principal is None:
            return show_login(request, error="Credential not recognized.", status=401)
        previous = request.cookies.get(SESSION_COOKIE_NAME)
        if previous:
            sessions.revoke(previous)
        session = sessions.issue(principal)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session.session_id,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            secure=True,
            httponly=True,
            samesite="strict",
        )
        response.delete_cookie(
            PRELOGIN_CSRF_COOKIE_NAME, secure=True, httponly=True, samesite="strict"
        )
        return response

    def digest_is_bound(session: RaterSession) -> bool:
        return session.island == config.digest.island.replace("-", "_")

    def render_digest(
        request: Request,
        session: RaterSession,
        *,
        error: str | None = None,
        status: int = 200,
    ) -> HTMLResponse:
        rows = (
            [
                row.to_dict()
                for row in blind_digest(config.digest.entries, seed=config.digest.seed)
            ]
            if digest_is_bound(session)
            else []
        )
        ratings = (
            config.storage.list_own_ratings(
                session.rater_id, batch_id=config.digest.batch_id
            ).data.get("ratings")
            if rows
            else []
        )
        fields = {"rating_id", "digest_entry_id", "paper_hash", "value", "rated_at"}
        if not isinstance(ratings, list):
            raise StorageTransportError("persisted ratings response is invalid")
        saved: dict[str, dict[str, str]] = {}
        for item in ratings:
            if (
                not isinstance(item, dict)
                or set(item) != fields
                or not all(isinstance(value, str) for value in item.values())
                or item["value"] not in {"like", "dislike", "skip"}
                or item["digest_entry_id"] in saved
            ):
                raise StorageTransportError("persisted rating response is invalid")
            saved[item["digest_entry_id"]] = cast(dict[str, str], item)
        return templates.TemplateResponse(
            request,
            "digest.html",
            {
                "notice": validate_output_label(AUTOMATED_OUTPUT_NOTICE),
                "rows": rows,
                "csrf_token": session.csrf_token,
                "saved_ratings": saved,
                "error": error,
            },
            status_code=status,
        )

    @app.get("/", response_class=HTMLResponse)
    def root(
        request: Request, session: RaterSession = Depends(require_session)
    ) -> HTMLResponse:
        return render_digest(request, session)

    @app.post("/logout")
    def logout(
        request: Request,
        csrf_token: str = Form(""),
        session: RaterSession = Depends(require_session),
    ) -> RedirectResponse:
        try:
            verify_csrf(session, csrf_token)
        except AuthenticationError as error:
            raise HTTPException(
                status_code=403, detail="Sign-out request could not be verified."
            ) from error
        sessions.revoke(session.session_id)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(
            SESSION_COOKIE_NAME, secure=True, httponly=True, samesite="strict"
        )
        return response

    @app.post("/ratings", response_model=None)
    def rate(
        request: Request,
        digest_entry_id: str = Form(...),
        paper_hash: str = Form(...),
        value: str = Form(...),
        csrf_token: str = Form(""),
        session: RaterSession = Depends(require_session),
    ) -> HTMLResponse | RedirectResponse:
        try:
            verify_csrf(session, csrf_token)
        except AuthenticationError as error:
            raise HTTPException(
                status_code=403,
                detail="Rating request could not be verified. Return to the digest and try again.",
            ) from error
        entry = next(
            (
                entry
                for entry in config.digest.entries
                if str(entry.digest_entry_id) == digest_entry_id
            ),
            None,
        )
        if (
            not digest_is_bound(session)
            or entry is None
            or entry.paper_hash != paper_hash
        ):
            raise HTTPException(
                status_code=403, detail="This paper is not in your current digest."
            )
        if value not in {"like", "dislike", "skip"}:
            raise HTTPException(
                status_code=422, detail="Choose like, dislike, or skip."
            )
        outcome = submit_rating(
            config.storage,
            rater_id=session.rater_id,
            paper_hash=entry.paper_hash,
            digest_entry_id=UUID(digest_entry_id),
            value=value,
            command_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
        if not outcome.accepted:
            duplicate = outcome.reason == "already rated"
            return render_digest(
                request,
                session,
                error="A rating is already recorded for this paper."
                if duplicate
                else "Your rating could not be saved. Please try again.",
                status=409 if duplicate else 502,
            )
        return RedirectResponse("/", status_code=303)

    return app
