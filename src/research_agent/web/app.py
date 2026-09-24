"""Private, server-rendered reader access and immutable ratings (PL-22).

Every page also has its ``/api/v1`` JSON twin built from the same view
(``web/api.py``, #249). Network reach is enforced by the platform (PL-19),
not by this app; the app checks the rater credential, session, host and
Origin (PL-22).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from research_agent.contracts import ContractValidationError, validate_sha256
from research_agent.contracts.preference import validate_iso_week
from research_agent.storage.client import (
    QueryResult,
    StorageClient,
    StorageClientError,
    StorageTransportError,
)
from research_agent.web import api
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
from research_agent.web.projections import SourceEntry, blind_digest
from research_agent.web.ratings import submit_rating
from research_agent.web.rendering import AUTOMATED_OUTPUT_NOTICE, validate_output_label

TEMPLATES_DIR = Path(__file__).parent / "templates"
RATING_VALUES = frozenset({"like", "dislike", "skip"})


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
    idempotency = api.IdempotencyCache()
    api.install(app)
    # ``api.install`` registers async handlers; keep them to delegate API paths.
    ApiHandler = Callable[[Request, Any], Awaitable[Response]]
    api_http_error = cast(ApiHandler, app.exception_handlers[HTTPException])
    api_invalid_request = cast(
        ApiHandler, app.exception_handlers[RequestValidationError]
    )

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
            response: Response = (
                api.refusal(403, "request origin could not be verified")
                if api.is_api(request)
                else error_page(
                    request,
                    "This request could not be verified. Return to the digest and try again.",
                    403,
                )
            )
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> Response:
        if api.is_api(request):
            return await api_http_error(request, error)
        if error.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return error_page(request, str(error.detail), error.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid_form(request: Request, error: RequestValidationError) -> Response:
        if api.is_api(request):
            return await api_invalid_request(request, error)
        return error_page(
            request,
            "The form is incomplete or invalid. Return to the digest and try again.",
            422,
        )

    @app.exception_handler(StorageTransportError)
    @app.exception_handler(StorageClientError)
    async def storage_unavailable(request: Request, error: Exception) -> Response:
        if api.is_api(request):
            return api.refusal(503, "stored records are unavailable")
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

    def digest_is_bound(session: RaterSession) -> bool:
        return session.island == config.digest.island.replace("-", "_")

    def digest_view(session: RaterSession) -> dict[str, Any]:
        """The session's digest; a reader of another island gets an empty queue."""
        return {
            "notice": validate_output_label(AUTOMATED_OUTPUT_NOTICE),
            "rows": (
                [
                    row.to_dict()
                    for row in blind_digest(
                        config.digest.entries, seed=config.digest.seed
                    )
                ]
                if digest_is_bound(session)
                else []
            ),
            "csrf_token": session.csrf_token,
        }

    def bound_entry(
        session: RaterSession, digest_entry_id: str, paper_hash: str
    ) -> SourceEntry | None:
        """The digest entry the session may rate, or ``None`` when it may not."""
        if not digest_is_bound(session):
            return None
        entry = next(
            (
                entry
                for entry in config.digest.entries
                if str(entry.digest_entry_id) == digest_entry_id
            ),
            None,
        )
        if entry is None or entry.paper_hash != paper_hash:
            return None
        return entry

    def own_rater(session: RaterSession, rater_id: str | None) -> UUID:
        """The session's rater; a query naming any other rater is refused (#252)."""
        if rater_id is None:
            return session.rater_id
        try:
            named = UUID(rater_id)
        except ValueError as error:
            raise api.ApiError(422, "not a UUID", field="rater_id") from error
        if named != session.rater_id:
            raise api.ApiError(
                403, "another rater's records are not readable", field="rater_id"
            )
        return session.rater_id

    def stored_rows(
        read: Callable[[], QueryResult], key: str, fields: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        """The named fields of each stored row; a failed read is unavailable, never empty."""
        try:
            rows = read().data[key]
            return [{name: row[name] for name in fields} for row in rows]
        except (
            StorageClientError,
            StorageTransportError,
            KeyError,
            TypeError,
        ) as error:
            raise api.ApiError(503, "stored records are unavailable") from error

    def show_login(
        request: Request, *, error: str | None = None, status: int = 200
    ) -> HTMLResponse:
        """The sign-in form; a GET with a live pre-login cookie reuses its token."""
        reused = (
            login_tokens.current(request.cookies.get(PRELOGIN_CSRF_COOKIE_NAME))
            if request.method == "GET"
            else None
        )
        token = reused or login_tokens.issue()
        response = templates.TemplateResponse(
            request,
            "login.html",
            {**login_view(), "error": error, "csrf_token": token.form_token},
            status_code=status,
        )
        if reused is not None:
            return response
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

    @app.get(f"{api.PREFIX}/login")
    def api_login_form() -> JSONResponse:
        return api.ok(login_view())

    @app.post(f"{api.PREFIX}/login")
    def api_login(
        request: Request, body: bytes = Depends(api.raw_body)
    ) -> JSONResponse:
        """The one POST without a session, so it has no CSRF token to carry."""
        credential = api.json_fields(body, ("credential",))["credential"]
        principal = config.directory.authenticate(credential)
        if principal is None:
            raise api.ApiError(401, "credential not recognized")
        previous = request.cookies.get(SESSION_COOKIE_NAME)
        if previous:
            sessions.revoke(previous)
        session = sessions.issue(principal)
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
        set_session_cookie(response, session)
        response.delete_cookie(
            PRELOGIN_CSRF_COOKIE_NAME, secure=True, httponly=True, samesite="strict"
        )
        return response

    def render_digest(
        request: Request,
        session: RaterSession,
        *,
        error: str | None = None,
        status: int = 200,
    ) -> HTMLResponse:
        view = digest_view(session)
        ratings = (
            config.storage.list_own_ratings(
                session.rater_id, batch_id=config.digest.batch_id
            ).data.get("ratings")
            if view["rows"]
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
                or item["value"] not in RATING_VALUES
                or item["digest_entry_id"] in saved
            ):
                raise StorageTransportError("persisted rating response is invalid")
            saved[item["digest_entry_id"]] = cast(dict[str, str], item)
        return templates.TemplateResponse(
            request,
            "digest.html",
            {**view, "saved_ratings": saved, "error": error},
            status_code=status,
        )

    @app.get("/", response_class=HTMLResponse)
    def root(
        request: Request, session: RaterSession = Depends(require_session)
    ) -> HTMLResponse:
        return render_digest(request, session)

    @app.get(f"{api.PREFIX}/digest")
    def api_digest(session: RaterSession = Depends(require_session)) -> JSONResponse:
        view = digest_view(session)
        return api.ok({**view, "rows": api.listing(view["rows"])})

    @app.get(f"{api.PREFIX}/ratings")
    def api_own_ratings(
        batch_id: str = Query(...),
        rater_id: str | None = Query(None),
        session: RaterSession = Depends(require_session),
    ) -> JSONResponse:
        """The session rater's ratings of one batch, for progress and the accepted list."""
        rater = own_rater(session, rater_id)
        try:
            validate_sha256(batch_id)
        except ContractValidationError as error:
            raise api.ApiError(422, str(error), field="batch_id") from error
        ratings = stored_rows(
            lambda: config.storage.list_own_ratings(rater, batch_id=batch_id),
            "ratings",
            ("rating_id", "digest_entry_id", "paper_hash", "value", "rated_at"),
        )
        return api.ok({"ratings": api.listing(ratings)})

    @app.get(f"{api.PREFIX}/credit")
    def api_own_credit(
        week: str = Query(...),
        rater_id: str | None = Query(None),
        session: RaterSession = Depends(require_session),
    ) -> JSONResponse:
        """The session rater's preference credit of one ISO week, a share per row.

        No total is computed: the page states what each rating did.
        """
        rater = own_rater(session, rater_id)
        try:
            validate_iso_week(week)
        except ContractValidationError as error:
            raise api.ApiError(422, str(error), field="week") from error
        credits = stored_rows(
            lambda: config.storage.list_own_credits(rater, iso_week=week),
            "credits",
            ("rating_id", "genome_hash", "share"),
        )
        return api.ok({"credits": api.listing(credits)})

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

    @app.post(f"{api.PREFIX}/logout")
    def api_logout(
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
        api.json_fields(body, ())

        def revoke() -> JSONResponse:
            sessions.revoke(session.session_id)
            response = api.ok({"authenticated": False})
            response.delete_cookie(
                SESSION_COOKIE_NAME, secure=True, httponly=True, samesite="strict"
            )
            return response

        return idempotency.run(
            str(session.rater_id), key, idempotency.fingerprint(request, body), revoke
        )

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
            entry = bound_entry(
                session, fields["digest_entry_id"], fields["paper_hash"]
            )
            if entry is None:
                raise api.ApiError(
                    403,
                    "entry is not in the session's digest",
                    field="digest_entry_id",
                )
            try:
                outcome = submit_rating(
                    config.storage,
                    rater_id=session.rater_id,
                    paper_hash=entry.paper_hash,
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
        entry = bound_entry(session, digest_entry_id, paper_hash)
        if entry is None:
            raise HTTPException(
                status_code=403, detail="This paper is not in your current digest."
            )
        if value not in RATING_VALUES:
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
