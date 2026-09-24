"""FastAPI wiring for the owner actions app: admit, retire, seed (#139).

Server-rendered HTML over an owner-only session, the same discipline
``web/app.py`` applies to a rater session: no SPA, no client framework,
mutating routes require the session's CSRF token. Every page and form also
has its ``/api/v1`` JSON twin built from the same view and command
(``web/api.py``, #249). Network reach is the
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

import asyncio
import base64
import json
from collections import deque
from collections.abc import AsyncIterator, Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
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
from research_agent.web import api
from research_agent.web.inspect.views import (
    ManifestView,
    RunView,
    agent_data,
    cursor_query,
    guard_digest_for_rater,
    manifest_data,
    parse_cursor,
    population_data,
    read_agent_view,
    read_manifest_view,
    read_population_view,
    read_rated_entry_ids,
    read_run_view,
    run_data,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
# The inspector's population, run and manifest pages are served here as they
# are; this app's own templates come first, so its agent page stays its own.
INSPECTOR_TEMPLATES_DIR = Path(__file__).parent.parent / "inspect" / "templates"
EMPHASIS_FIELD_ORDER: tuple[str, ...] = tuple(sorted(EMPHASIS_FIELDS))


#: The budgets a tool call charges in its trace terminal (``tools/service.py``).
#: Token and spend budgets are charged by model turns, which the trace does
#: not hold, so a trace's remaining budgets are these alone (#301).
TRACE_BUDGETS: tuple[str, ...] = ("deep_reads", "images", "tool_calls")


#: TDD Spending authorization's Jev daily sublimit (USD 2). The launch
#: profile has no field for it, so the cost read labels its source (#251).
JEV_DAILY_SUBLIMIT_MICROS = 2_000_000


def _usd_micros(value: str) -> int:
    """A profile cap written in USD, as whole microdollars."""
    try:
        micros = Decimal(value) * 1_000_000
    except InvalidOperation as error:
        raise ValueError("a budget cap must be a USD amount") from error
    if not micros.is_finite() or micros < 0 or micros != micros.to_integral_value():
        raise ValueError("a budget cap must be whole microdollars")
    return int(micros)


@dataclass(frozen=True, slots=True)
class CostCaps:
    """The launch profile's spending caps (``BudgetGroup``) the cost read reports.

    Supplied by whoever composes this app, for the reason ``budget_funded``
    is; ``funded`` itself is ``ActionsAppConfig.budget_funded``.
    """

    daily_cap_usd: str
    monthly_cap_usd: str
    paid_execution_enabled: bool

    def __post_init__(self) -> None:
        _usd_micros(self.daily_cap_usd)
        _usd_micros(self.monthly_cap_usd)


def _trace_path(run_id: str) -> str:
    return f"{api.PREFIX}/owner/runs/{run_id}/trace"


def _owner_run_data(run: Mapping[str, Any]) -> dict[str, Any]:
    """A stored run as the owner's paper page lists it, with its trace's path."""
    return {**run, "trace": _trace_path(str(run["run_id"]))}


def _owner_paper_data(stored: Mapping[str, Any]) -> dict[str, Any]:
    """The stored paper document in the contract's list form (#301).

    ``acquired_on_request`` reads the stored requests: true when one of them
    acquired the paper, false when every one of the family's snapshot pins
    came from the population rule.
    """
    paper_id = str(stored["paper_id"])
    requests = list(stored["requests"])
    return {
        "paper_id": paper_id,
        "embedding_view": f"{api.PREFIX}/papers/{paper_id}/embedding",
        "acquired_on_request": any(
            request["status"] == "acquired" for request in requests
        ),
        "requests": api.listing(requests),
        "cards": api.listing(stored["cards"]),
        "runs": api.listing(
            [_owner_run_data(run) for run in stored["runs"]], stored["next_cursor"]
        ),
    }


def _payload_text(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A stored trace payload as text a person reads; ``None`` when the row
    predates stored payloads. Bytes that are not UTF-8, such as the tail of
    a payload cut at its bound, read as U+FFFD; the exact bytes are the
    artifact ``artifact_hash`` names."""
    if payload is None:
        return None
    return {
        "artifact_hash": payload["artifact_hash"],
        "truncated": payload["truncated"],
        "text": base64.b64decode(payload["bytes"]).decode("utf-8", errors="replace"),
    }


def _trace_calls(
    budgets: Mapping[str, Any], calls: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Each stored call in call order, its payloads as text and the budgets
    left once it and every call before it had been charged."""
    remaining = {name: budgets[name] for name in TRACE_BUDGETS if name in budgets}
    shaped: list[dict[str, Any]] = []
    for call in calls:
        terminal = call["terminal"]
        if terminal is not None:
            for name, spent in terminal["budget_deltas"].items():
                if name in remaining:
                    remaining[name] -= spent
            terminal = {**terminal, "response": _payload_text(terminal["response"])}
        shaped.append(
            {
                **call,
                "request": _payload_text(call["request"]),
                "terminal": terminal,
                "remaining_budgets": dict(remaining),
            }
        )
    return shaped


#: Filters a live stream admits; each names a field every event carries.
LIVE_FILTERS = ("paper_id", "run_id", "island")


def _live_event(stored: Mapping[str, Any]) -> dict[str, Any]:
    """A stored trace event as ``owner-run-event.json``: a call or terminal
    event's call reads as the paper page's trace renders it, payloads as
    text, without the running ``remaining_budgets`` a single event cannot
    know (#327)."""
    event: dict[str, Any] = {
        "id": str(stored["sequence"]),
        "kind": stored["kind"],
        "run_id": stored["run_id"],
        "paper_id": stored["paper_id"],
        "island": stored["island"],
        "call": None,
        "ending": stored.get("ending"),
        "settlement": stored.get("settlement"),
    }
    if "call" in stored:
        call = stored["call"]
        terminal = call["terminal"]
        if terminal is not None:
            terminal = {**terminal, "response": _payload_text(terminal["response"])}
        event["call"] = {
            **call,
            "request": _payload_text(call["request"]),
            "terminal": terminal,
        }
    return event


class LiveRunFeed:
    """One poll of storage's trace read a second, fanned out to every open
    live stream (#327).

    The feed holds the newest ``retained`` events, those after ``floor`` up
    to ``cursor``. A stream resuming from before ``floor`` reads storage
    itself until it reaches the held events, then follows the feed. The
    poll runs only while a stream is open, starting from the first
    stream's cursor.
    """

    def __init__(
        self,
        read: Callable[[int], Mapping[str, Any]],
        *,
        interval: float = 1.0,
        retained: int = 2000,
    ) -> None:
        self._read = read
        self._interval = interval
        self._retained = retained
        self._events: deque[dict[str, Any]] = deque()
        self._floor = 0
        self._cursor = 0
        self._changed = asyncio.Condition()
        self._streams = 0
        self._task: asyncio.Task[None] | None = None

    async def follow(
        self, cursor: int, seconds: float
    ) -> AsyncIterator[dict[str, Any]]:
        """Every stored event after *cursor* in order, for *seconds*."""
        if self._task is None:
            self._events.clear()
            self._floor = self._cursor = cursor
            self._changed = asyncio.Condition()
            self._task = asyncio.create_task(self._poll())
        self._streams += 1
        deadline = asyncio.get_running_loop().time() + seconds
        try:
            while True:
                if cursor < self._floor:
                    page = await run_in_threadpool(self._read, cursor)
                    for event in page["events"]:
                        yield event
                    cursor = max(cursor, page["cursor"])
                    if page["events"]:
                        continue
                held = [event for event in self._events if event["sequence"] > cursor]
                for event in held:
                    yield event
                if held:
                    cursor = held[-1]["sequence"]
                left = deadline - asyncio.get_running_loop().time()
                if left <= 0:
                    return
                async with self._changed:
                    try:
                        await asyncio.wait_for(
                            self._changed.wait_for(lambda: self._cursor > cursor),
                            min(left, 15.0),
                        )
                    except TimeoutError:
                        pass
        finally:
            self._streams -= 1
            if self._streams == 0 and self._task is not None:
                self._task.cancel()
                self._task = None

    async def _poll(self) -> None:
        while True:
            try:
                page = await run_in_threadpool(self._read, self._cursor)
            except StorageClientError:
                page = {"events": []}
            for event in page["events"]:
                if len(self._events) == self._retained:
                    self._floor = self._events.popleft()["sequence"]
                self._events.append(event)
                self._cursor = event["sequence"]
            if page["events"]:
                async with self._changed:
                    self._changed.notify_all()
                continue
            await asyncio.sleep(self._interval)


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


def _accepted(result: OwnerActionResult) -> str:
    """The admitted or retired configuration id, or the refusal as its status."""
    if not result.accepted or result.configuration_id is None:
        raise HTTPException(status_code=_refusal_status(result), detail=result.reason)
    return result.configuration_id


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
    digest route answers 503. ``cost_caps`` backs ``GET /api/v1/costs``,
    which answers 503 without it (#251). ``front_end_origin`` is the launch
    profile's one browser origin the API admits cross-origin, read by the
    composer like ``budget_funded``; empty admits none (#336).
    ``live_poll_seconds`` is how often the live run stream polls storage
    and ``live_stream_seconds`` how long one live connection stays open
    before the browser reconnects with ``Last-Event-ID`` (#327).
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
    cost_caps: CostCaps | None = None
    front_end_origin: str = ""
    live_poll_seconds: float = 1.0
    live_stream_seconds: float = 300.0


def create_app(config: ActionsAppConfig) -> FastAPI:
    """Build the owner actions app; each call gets its own session store."""
    app = FastAPI(
        title="owner-actions", docs_url=None, redoc_url=None, openapi_url=None
    )
    templates = Jinja2Templates(
        directory=[str(TEMPLATES_DIR), str(INSPECTOR_TEMPLATES_DIR)]
    )
    sessions = OwnerSessionStore()
    idempotency = api.IdempotencyCache()
    api.install(app, front_end_origin=config.front_end_origin)

    def require_session(request: Request) -> OwnerSession:
        try:
            return authenticate_owner_session(
                sessions, request.cookies.get(OWNER_SESSION_COOKIE_NAME)
            )
        except AuthenticationError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

    def set_session_cookie(response: Response, session: OwnerSession) -> None:
        response.set_cookie(
            OWNER_SESSION_COOKIE_NAME,
            session.session_id,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            secure=True,
            httponly=True,
            # A separate front end (decision 0030) calls this API cross-site, and a
            # Strict cookie is never sent on such a request; None keeps the session
            # for that origin alone, which CORS admits and the CSRF token still guards.
            samesite="none" if config.front_end_origin else "strict",
        )

    def verified_key(session: OwnerSession, headers: tuple[str, str]) -> str:
        """The request's Idempotency-Key, once its CSRF token matches the session."""
        csrf_token, key = headers
        try:
            verify_owner_csrf(session, csrf_token)
        except AuthenticationError as error:
            raise api.ApiError(403, str(error), field="X-CSRF-Token") from error
        return key

    def run_once(
        request: Request,
        body: bytes,
        session: OwnerSession,
        key: str,
        command: Callable[[], JSONResponse],
    ) -> JSONResponse:
        return idempotency.run(
            str(session.owner_id),
            key,
            idempotency.fingerprint(request, body),
            command,
        )

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.get(f"{api.PREFIX}/login")
    def api_login_form() -> JSONResponse:
        return api.ok({})

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

    @app.post(f"{api.PREFIX}/login")
    def api_login(body: bytes = Depends(api.raw_body)) -> JSONResponse:
        """The one POST without a session, so it has no CSRF token to carry."""
        credential = api.json_fields(body, ("credential",))["credential"]
        principal = config.directory.authenticate(credential)
        if principal is None:
            raise api.ApiError(401, "credential not recognized")
        session = sessions.issue(principal.owner_id)
        response = api.ok(
            {
                "authenticated": True,
                "expires_at": api.utc_instant(session.expires_at),
                "csrf_token": session.csrf_token,
            }
        )
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

    @app.post(f"{api.PREFIX}/logout")
    def api_logout(
        request: Request,
        session: OwnerSession = Depends(require_session),
        headers: tuple[str, str] = Depends(api.post_headers),
        body: bytes = Depends(api.raw_body),
    ) -> JSONResponse:
        key = verified_key(session, headers)
        api.json_fields(body, ())

        def revoke() -> JSONResponse:
            sessions.revoke(session.session_id)
            response = api.ok({"authenticated": False})
            response.delete_cookie(OWNER_SESSION_COOKIE_NAME)
            return response

        return run_once(request, body, session, key, revoke)

    def retrospective_view(session: OwnerSession) -> dict[str, Any]:
        admissions, retirements = config.actions.retrospective()
        return {
            "admissions": admissions,
            "retirements": retirements,
            "csrf_token": session.csrf_token,
        }

    @app.get("/", response_class=HTMLResponse)
    def retrospective_page(
        request: Request, session: OwnerSession = Depends(require_session)
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "retrospective.html", retrospective_view(session)
        )

    @app.get(f"{api.PREFIX}/retrospective")
    def api_retrospective(
        session: OwnerSession = Depends(require_session),
    ) -> JSONResponse:
        view = retrospective_view(session)
        return api.ok(
            {
                **view,
                "admissions": api.listing(view["admissions"]),
                "retirements": api.listing(view["retirements"]),
            }
        )

    @app.get(f"{api.PREFIX}/health")
    def health(session: OwnerSession = Depends(require_session)) -> JSONResponse:
        if config.health is None:
            raise HTTPException(status_code=503, detail="health monitor unavailable")
        return api.ok(dict(config.health()))

    @app.get(f"{api.PREFIX}/costs")
    def costs(
        day: str | None = None, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """Settled spend of a UTC day and its month against the profile's caps.

        ``day`` defaults to today (UTC). Priced spend is summed from
        ``cost_micros``; runs without a price are counted with their tokens
        beside it, never priced here (#251).
        """
        caps = config.cost_caps
        if caps is None:
            raise HTTPException(status_code=503, detail="budget profile unavailable")
        requested = day or datetime.now(timezone.utc).date().isoformat()
        try:
            read = config.actions.read_costs(requested).data
        except ContractValidationError as error:
            raise api.ApiError(422, str(error), field="day") from error
        return api.ok(
            {
                "day": read["day"],
                "month": read["month"],
                "source": "settlements",
                "caps": {
                    "daily_cap_micros": _usd_micros(caps.daily_cap_usd),
                    "monthly_cap_micros": _usd_micros(caps.monthly_cap_usd),
                    "jev_daily_sublimit_micros": JEV_DAILY_SUBLIMIT_MICROS,
                    "jev_daily_sublimit_source": "profile_constant",
                    "funded": config.budget_funded,
                    "paid_execution_enabled": caps.paid_execution_enabled,
                },
                "today": read["day_totals"],
                "month_to_date": read["month_totals"],
                "by_island": api.listing(read["islands"]),
                "by_configuration": api.listing(read["configurations"]),
            }
        )

    @app.get(f"{api.PREFIX}/costs/days")
    def cost_days(
        day: str | None = None, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """Settled spend of each UTC day and island in ``day``'s month (#344).

        ``day`` defaults to today (UTC); days after it are absent. Sums of
        the stored settlements only, oldest day first.
        """
        requested = day or datetime.now(timezone.utc).date().isoformat()
        try:
            stored = config.actions.list_owner_cost_days(requested).data
        except ContractValidationError as error:
            raise api.ApiError(422, str(error), field="day") from error
        return api.ok({"day": requested, "days": api.listing(stored["days"])})

    @app.get(f"{api.PREFIX}/day")
    def owner_day(
        day: str | None = None, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """The runs created and the digests built on one UTC day (#344).

        ``day`` defaults to today (UTC). Each run with its genome's island and
        its stored ending and end instant, each digest with its entries and
        the rated ones; the owner home's board, tiles and cards count these.
        """
        requested = day or datetime.now(timezone.utc).date().isoformat()
        try:
            stored = config.actions.read_owner_day(requested).data
        except ContractValidationError as error:
            raise api.ApiError(422, str(error), field="day") from error
        return api.ok(
            {
                "day": stored["day"],
                "runs": api.listing(stored["runs"]),
                "digests": api.listing(stored["digests"]),
            }
        )

    @app.get(f"{api.PREFIX}/islands")
    def islands(session: OwnerSession = Depends(require_session)) -> JSONResponse:
        """Each island the population store holds, with its stored counts (#344).

        Counts of stored rows only: genomes, founders, lineages, the runs of
        those genomes and the latest run's instant. An island with no genome
        is absent.
        """
        stored = config.actions.list_owner_islands().data
        return api.ok({"islands": api.listing(stored["islands"])})

    @app.get(f"{api.PREFIX}/islands/{{island}}")
    def island(
        island: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """One island's genomes, founders first, with stored counts (#344).

        Each genome's runs, void runs, priced settlements and their summed
        cost in micro-dollars. 404 for a name outside the three islands; an
        island with no genome has an empty list.
        """
        try:
            stored = config.actions.read_owner_island(island).data
        except ContractValidationError as error:
            raise api.ApiError(404, "island not found", field="island") from error
        return api.ok({"island": island, "genomes": api.listing(stored["genomes"])})

    @app.get(f"{api.PREFIX}/reports")
    def reports(session: OwnerSession = Depends(require_session)) -> JSONResponse:
        """Each island and ISO week with a stored digest or rating (#344).

        Newest week first. Counts of stored rows only: digests built, their
        entries, ratings recorded and preference credit rows. The report for
        a row is read at ``/api/v1/reports/{island}/{iso_week}``.
        """
        stored = config.actions.list_owner_reports().data
        return api.ok({"reports": api.listing(stored["reports"])})

    @app.get(f"{api.PREFIX}/reports/{{island}}/{{iso_week}}/selection")
    def report_selection(
        island: str, iso_week: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """The genomes one island archived and admitted in one ISO week (#344).

        Oldest first, each by its stored instant in UTC. An archived genome
        carries the skill and support it was archived on; nothing is scored
        anew. 404 for a name outside the three islands or a malformed week.
        """
        try:
            stored = config.actions.read_owner_report_selection(island, iso_week).data
        except ContractValidationError as error:
            raise api.ApiError(404, "report not found", field="iso_week") from error
        except StorageClientError as error:
            if error.code == "not_found":
                raise api.ApiError(404, "report not found", field="iso_week") from error
            raise
        return api.ok(
            {
                "island": island,
                "iso_week": iso_week,
                "archived": api.listing(stored["archived"]),
                "admitted": api.listing(stored["admitted"]),
            }
        )

    @app.get(f"{api.PREFIX}/impact")
    def impact(session: OwnerSession = Depends(require_session)) -> JSONResponse:
        """Each island and ISO week with a stored rating, and what it set in
        motion (#344).

        Newest week first. Counts of stored rows only: ratings by value,
        preference credit rows, the genomes they credit, and credit gaps.
        """
        stored = config.actions.list_owner_impact().data
        return api.ok({"impact": api.listing(stored["impact"])})

    @app.get(f"{api.PREFIX}/models")
    def models(session: OwnerSession = Depends(require_session)) -> JSONResponse:
        """Each agent model manifest a stored run pins, with its runs (#344).

        Newest run first. Each hash opens at ``/api/v1/models/{manifest_hash}``.
        """
        stored = config.actions.list_owner_models().data
        return api.ok({"models": api.listing(stored["models"])})

    @app.get(f"{api.PREFIX}/genomes")
    def genomes(session: OwnerSession = Depends(require_session)) -> JSONResponse:
        """Every stored genome with its run, forecast and credit counts (#344).

        By island, founders first. Counts and sums of stored rows only: runs,
        void and priced runs, settled cost, the forecasts its runs sealed and
        the preference credit rows naming its hash with their summed share.
        Agreement is not stored and is not served.
        """
        stored = config.actions.list_owner_agents().data
        return api.ok({"genomes": api.listing(stored["agents"])})

    @app.get(f"{api.PREFIX}/genomes/{{configuration_id}}/runs")
    def genome_runs(
        configuration_id: str,
        cursor: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> JSONResponse:
        """One genome's runs per UTC day and its run endings (#344).

        The days are complete on every page; the runs are paged newest first,
        each with its stored ending, end instant and settled cost. No duration
        is stored, so the page reads the instants. 404 for a malformed id or
        a genome the population store does not hold.
        """
        genome = _parse_id(configuration_id)
        try:
            stored = config.actions.read_owner_agent_runs(
                genome, cursor=parsed_cursor(cursor)
            ).data
        except ContractValidationError as error:
            raise api.ApiError(
                404, "genome not found", field="configuration_id"
            ) from error
        except StorageClientError as error:
            if error.code == "not_found":
                raise api.ApiError(
                    404, "genome not found", field="configuration_id"
                ) from error
            if error.code == "invalid_input":
                raise api.ApiError(422, str(error), field="cursor") from error
            raise
        return api.ok(
            {
                "configuration_id": str(genome),
                "days": api.listing(stored["days"]),
                "runs": api.listing(stored["runs"], stored["next_cursor"]),
            }
        )

    @app.get(f"{api.PREFIX}/questions")
    def questions(session: OwnerSession = Depends(require_session)) -> JSONResponse:
        """Each question a sealed sheet holds, with its stored counts (#344).

        By horizon. Counts of stored rows only: sheets carrying the question,
        runs that forecast it, sealed submissions on it and the current
        resolution of each resolved forecast by status.
        """
        stored = config.actions.list_owner_questions().data
        return api.ok({"questions": api.listing(stored["questions"])})

    @app.get(f"{api.PREFIX}/questions/{{question_id}}")
    def question(
        question_id: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """One question, the runs that forecast it and its resolutions (#344).

        404 for a malformed id or a question no sealed sheet holds.
        """
        try:
            stored = config.actions.read_owner_question(_parse_id(question_id)).data
        except ContractValidationError as error:
            raise api.ApiError(
                404, "question not found", field="question_id"
            ) from error
        except StorageClientError as error:
            if error.code == "not_found":
                raise api.ApiError(
                    404, "question not found", field="question_id"
                ) from error
            raise
        return api.ok(
            {
                **stored,
                "runs": api.listing(stored["runs"]),
                "resolutions": api.listing(stored["resolutions"]),
            }
        )

    @app.get(f"{api.PREFIX}/runs/{{run_id}}/record")
    def run_record(
        run_id: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """What storage holds about one run beyond its run record (#344).

        Its genome's island, its stored ending, end instant and settled cost,
        its trace calls per tool with the refused ones counted, and the digest
        entries its sealed claims were nominated to. 404 for a malformed id or
        a run the store does not hold.
        """
        run = _parse_id(run_id)
        try:
            stored = config.actions.read_owner_run_record(run).data
        except ContractValidationError as error:
            raise api.ApiError(404, "run not found", field="run_id") from error
        except StorageClientError as error:
            if error.code == "not_found":
                raise api.ApiError(404, "run not found", field="run_id") from error
            raise
        return api.ok(
            {
                "run_id": str(run),
                **stored,
                "calls": api.listing(stored["calls"]),
                "nominations": api.listing(stored["nominations"]),
            }
        )

    @app.get(f"{api.PREFIX}/papers/{{paper_id}}/embedding")
    def embedding_view(
        paper_id: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """The family's current embedding view, as stored (#298).

        JSON only. 404 until the paper has a published embedding; the view's
        passages and neighbors are lists in the contract's list form.
        """
        try:
            stored = config.actions.read_embedding_view(_parse_id(paper_id)).data
        except ContractValidationError as error:
            raise api.ApiError(404, "paper not found", field="paper_id") from error
        except StorageClientError as error:
            if error.code == "not_found":
                raise api.ApiError(
                    404, "paper has no embedding view", field="paper_id"
                ) from error
            raise
        return api.ok(
            {
                **stored,
                "passages": api.listing(stored["passages"]),
                "neighbors": api.listing(stored["neighbors"]),
            }
        )

    def require_inspector() -> StorageClient:
        if config.inspector is None:
            raise HTTPException(status_code=503, detail="inspector reads unavailable")
        return config.inspector

    def parsed_cursor(value: str | None) -> tuple[str, str] | None:
        try:
            return parse_cursor(value)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def load_run(run_id: str) -> RunView:
        inspector = require_inspector()
        try:
            view = read_run_view(inspector, UUID(run_id))
        except (ValueError, ContractValidationError) as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        if view is None:
            raise HTTPException(status_code=404, detail="run not found")
        return view

    def load_manifest(manifest_hash: str) -> ManifestView:
        inspector = require_inspector()
        try:
            view = read_manifest_view(inspector, manifest_hash)
        except ContractValidationError as error:
            raise HTTPException(status_code=404, detail="manifest not found") from error
        if view is None:
            raise HTTPException(status_code=404, detail="manifest not found")
        return view

    @app.get(f"{api.PREFIX}/owner/papers/{{paper_id}}")
    def owner_paper(
        paper_id: str,
        cursor: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> JSONResponse:
        """Everything the agents saw of one paper, from stored records (#301).

        JSON only. ``paper_id`` is the family id. The runs are paged newest
        first; each run's trace is its own read at the run's ``trace`` path.
        404 when storage holds no run, request or snapshot pin for the paper.
        """
        try:
            stored = config.actions.read_owner_paper(
                _parse_id(paper_id), cursor=parsed_cursor(cursor)
            ).data
        except StorageClientError as error:
            if error.code == "not_found":
                raise api.ApiError(404, "paper not found", field="paper_id") from error
            if error.code == "invalid_input":
                raise api.ApiError(422, str(error), field="cursor") from error
            raise
        return api.ok(_owner_paper_data(stored))

    @app.get(f"{api.PREFIX}/owner/papers/{{paper_id}}/documents")
    def owner_paper_documents(
        paper_id: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """The retained PDFs a paper family's pinned cards came from (#344).

        Oldest first, each with the path of its bytes. Empty when storage
        holds no PDF behind the family's cards; 404 for a malformed id.
        """
        try:
            stored = config.actions.list_owner_paper_documents(_parse_id(paper_id)).data
        except StorageClientError as error:
            if error.code == "not_found":
                raise api.ApiError(404, "paper not found", field="paper_id") from error
            raise
        documents = [
            {
                **document,
                "path": f"{api.PREFIX}/owner/documents/{document['artifact_hash']}",
            }
            for document in stored["documents"]
        ]
        return api.ok(
            {"paper_id": stored["paper_id"], "documents": api.listing(documents)}
        )

    @app.get(f"{api.PREFIX}/owner/documents/{{artifact_hash}}")
    def owner_document(
        artifact_hash: str, session: OwnerSession = Depends(require_session)
    ) -> Response:
        """One retained PDF's exact bytes by hash, as ``application/pdf`` (#344).

        404 unless storage holds the hash as a retained PDF source document.
        """
        try:
            document = config.actions.read_owner_document(artifact_hash)
        except ContractValidationError as error:
            raise api.ApiError(
                404, "document not found", field="artifact_hash"
            ) from error
        except StorageClientError as error:
            if error.code == "not_found":
                raise api.ApiError(
                    404, "document not found", field="artifact_hash"
                ) from error
            raise
        return Response(
            document.payload,
            media_type="application/pdf",
            headers={"ETag": f'"{artifact_hash}"', "Cache-Control": "private"},
        )

    live = LiveRunFeed(
        lambda cursor: config.actions.read_trace_since(cursor, limit=500).data,
        interval=config.live_poll_seconds,
    )

    @app.get(f"{api.PREFIX}/owner/runs/live")
    async def owner_runs_live(
        request: Request,
        paper_id: str | None = None,
        run_id: str | None = None,
        island: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> StreamingResponse:
        """Trace calls, terminals, run endings and settlements as storage
        records them, as server-sent events (#327).

        Each event's ``id`` is its ledger sequence; a reconnect's
        ``Last-Event-ID`` resumes after it, and without one the stream
        starts from the first recorded event. ``paper_id``, ``run_id`` and
        ``island`` keep only the events that match. The connection closes
        after ``live_stream_seconds`` and the browser reconnects.
        """
        last = request.headers.get("last-event-id", "0") or "0"
        if not last.isdigit():
            raise api.ApiError(422, "not an event id", field="Last-Event-ID")
        wanted = {
            name: value
            for name, value in zip(LIVE_FILTERS, (paper_id, run_id, island))
            if value is not None
        }

        async def stream() -> AsyncIterator[str]:
            yield "retry: 1000\n\n"
            async for stored in live.follow(int(last), config.live_stream_seconds):
                event = _live_event(stored)
                if all(event[name] == value for name, value in wanted.items()):
                    data = json.dumps(event, separators=(",", ":"), sort_keys=True)
                    yield f"id: {event['id']}\nevent: {event['kind']}\ndata: {data}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )

    @app.get(f"{api.PREFIX}/owner/runs/{{run_id}}/trace")
    def owner_run_trace(
        run_id: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        """One run and its trace in call order, payloads as text (#301).

        JSON only; 404 for a run storage does not hold.
        """
        parsed = _parse_id(run_id)
        try:
            run = config.actions.read_owner_run(parsed).data
            trace = config.actions.read_run_trace(parsed).data
        except StorageClientError as error:
            if error.code == "not_found":
                raise api.ApiError(404, "run not found", field="run_id") from error
            raise
        return api.ok(
            {
                "run": _owner_run_data(run),
                "calls": api.listing(_trace_calls(run["budgets"], trace["calls"])),
            }
        )

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

    @app.get(f"{api.PREFIX}/agents")
    def api_population(
        cursor: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> JSONResponse:
        view = read_population_view(require_inspector(), cursor=parsed_cursor(cursor))
        return api.ok(population_data(view))

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(
        request: Request,
        run_id: str,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        view = load_run(run_id)
        return templates.TemplateResponse(
            request,
            "run.html",
            {"run": view.run, "submissions": view.submissions},
        )

    @app.get(f"{api.PREFIX}/runs/{{run_id}}")
    def api_run(
        run_id: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        return api.ok(run_data(load_run(run_id)))

    @app.get("/models/{manifest_hash}", response_class=HTMLResponse)
    def models_page(
        request: Request,
        manifest_hash: str,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        view = load_manifest(manifest_hash)
        return templates.TemplateResponse(
            request, "manifest.html", {"manifest": view.manifest}
        )

    @app.get(f"{api.PREFIX}/models/{{manifest_hash}}")
    def api_manifest(
        manifest_hash: str, session: OwnerSession = Depends(require_session)
    ) -> JSONResponse:
        return api.ok(manifest_data(load_manifest(manifest_hash)))

    @app.get(f"{api.PREFIX}/digests/{{digest_hash}}")
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
        return api.ok(guard_digest_for_rater(stored.data, rated))

    def agent_view(
        session: OwnerSession,
        configuration_id: str,
        cursor: str | None,
        forecast_cursor: str | None,
    ) -> dict[str, Any]:
        parsed = _parse_id(configuration_id)
        genome = config.actions.read_genome_view(parsed)
        if genome is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return {
            "genome": genome,
            "emphasis_fields": EMPHASIS_FIELD_ORDER,
            "admission": config.actions.admission_history(parsed),
            "retirement": config.actions.retirement_status(parsed),
            "csrf_token": session.csrf_token,
            "inspected": (
                read_agent_view(
                    config.inspector,
                    parsed,
                    cursor=parsed_cursor(cursor),
                    forecasts_cursor=parsed_cursor(forecast_cursor),
                )
                if config.inspector is not None
                else None
            ),
        }

    @app.get("/agents/{configuration_id}", response_class=HTMLResponse)
    def agent_page(
        request: Request,
        configuration_id: str,
        cursor: str | None = None,
        forecast_cursor: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        view = agent_view(session, configuration_id, cursor, forecast_cursor)
        inspected = view["inspected"]
        return templates.TemplateResponse(
            request,
            "agent.html",
            {
                **view,
                "next_cursor_query": inspected and cursor_query(inspected.next_cursor),
                "forecasts_next_cursor_query": inspected
                and cursor_query(inspected.forecasts_next_cursor),
            },
        )

    @app.get(f"{api.PREFIX}/agents/{{configuration_id}}")
    def api_agent(
        configuration_id: str,
        cursor: str | None = None,
        forecast_cursor: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> JSONResponse:
        view = agent_view(session, configuration_id, cursor, forecast_cursor)
        inspected = view.pop("inspected")
        data = {**view, "emphasis_fields": api.listing(view["emphasis_fields"])}
        # Without the inspector client the page has no runs or verdicts
        # section, so the object carries no such field rather than a null.
        if inspected is not None:
            data["inspected"] = agent_data(inspected)
        return api.ok(data)

    def admit_edit(
        session: OwnerSession,
        configuration_id: str,
        lineage_id: str,
        submitted: Mapping[str, str],
    ) -> str:
        source_id = _parse_id(configuration_id)
        source = config.actions.read_genome_view(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="agent not found")
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
        return _accepted(result)

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
        admitted = admit_edit(
            session,
            configuration_id,
            lineage_id,
            {
                "prompt": prompt,
                "scan_policy": scan_policy,
                "read_policy": read_policy,
                "probability_assignment_rule": probability_assignment_rule,
            },
        )
        return RedirectResponse(f"/agents/{admitted}", status_code=303)

    @app.post(f"{api.PREFIX}/agents/{{configuration_id}}/admit")
    def api_admit(
        request: Request,
        configuration_id: str,
        session: OwnerSession = Depends(require_session),
        headers: tuple[str, str] = Depends(api.post_headers),
        body: bytes = Depends(api.raw_body),
    ) -> JSONResponse:
        key = verified_key(session, headers)
        fields = api.json_fields(body, ("lineage_id",), EMPHASIS_FIELD_ORDER)

        def command() -> JSONResponse:
            admitted = admit_edit(
                session,
                configuration_id,
                fields["lineage_id"],
                {name: fields.get(name, "") for name in EMPHASIS_FIELD_ORDER},
            )
            return api.ok({"configuration_id": admitted}, status_code=201)

        return run_once(request, body, session, key, command)

    def retire_genome(session: OwnerSession, configuration_id: str) -> str:
        result = config.actions.retire_genome(
            owner_id=session.owner_id,
            configuration_id=_parse_id(configuration_id),
            command_id=uuid4(),
        )
        _accepted(result)
        return configuration_id

    @app.post("/agents/{configuration_id}/retire", response_model=None)
    def retire(
        request: Request,
        configuration_id: str,
        csrf_token: str = Form(...),
        session: OwnerSession = Depends(require_session),
    ) -> RedirectResponse:
        _verify_csrf(session, csrf_token)
        retire_genome(session, configuration_id)
        return RedirectResponse(f"/agents/{configuration_id}", status_code=303)

    @app.post(f"{api.PREFIX}/agents/{{configuration_id}}/retire")
    def api_retire(
        request: Request,
        configuration_id: str,
        session: OwnerSession = Depends(require_session),
        headers: tuple[str, str] = Depends(api.post_headers),
        body: bytes = Depends(api.raw_body),
    ) -> JSONResponse:
        key = verified_key(session, headers)
        api.json_fields(body, ())

        def command() -> JSONResponse:
            retired = retire_genome(session, configuration_id)
            return api.ok({"configuration_id": retired})

        return run_once(request, body, session, key, command)

    def seed_view(session: OwnerSession, template: str | None) -> dict[str, Any]:
        copied: dict[str, object] | None = None
        if template:
            copied = config.actions.read_genome_view(_parse_id(template))
            if copied is None:
                raise HTTPException(status_code=404, detail="template not found")
        return {
            "emphasis_fields": EMPHASIS_FIELD_ORDER,
            "copied": copied,
            "csrf_token": session.csrf_token,
        }

    @app.get("/seed", response_class=HTMLResponse)
    def seed_form(
        request: Request,
        template: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "seed.html", seed_view(session, template)
        )

    @app.get(f"{api.PREFIX}/seed")
    def api_seed_form(
        template: str | None = None,
        session: OwnerSession = Depends(require_session),
    ) -> JSONResponse:
        view = seed_view(session, template)
        return api.ok({**view, "emphasis_fields": api.listing(view["emphasis_fields"])})

    def seed_genome(
        session: OwnerSession,
        *,
        island: str,
        lineage_id: str,
        template_configuration_id: str,
        emphasis: Mapping[str, str],
    ) -> str:
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
        return _accepted(result)

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
        seeded = seed_genome(
            session,
            island=island,
            lineage_id=lineage_id,
            template_configuration_id=template_configuration_id,
            emphasis={
                "prompt": prompt,
                "scan_policy": scan_policy,
                "read_policy": read_policy,
                "probability_assignment_rule": probability_assignment_rule,
            },
        )
        return RedirectResponse(f"/agents/{seeded}", status_code=303)

    @app.post(f"{api.PREFIX}/seed")
    def api_seed(
        request: Request,
        session: OwnerSession = Depends(require_session),
        headers: tuple[str, str] = Depends(api.post_headers),
        body: bytes = Depends(api.raw_body),
    ) -> JSONResponse:
        key = verified_key(session, headers)
        fields = api.json_fields(
            body,
            (
                "island",
                "lineage_id",
                "template_configuration_id",
                *EMPHASIS_FIELD_ORDER,
            ),
        )

        def command() -> JSONResponse:
            seeded = seed_genome(
                session,
                island=fields["island"],
                lineage_id=fields["lineage_id"],
                template_configuration_id=fields["template_configuration_id"],
                emphasis={name: fields[name] for name in EMPHASIS_FIELD_ORDER},
            )
            return api.ok({"configuration_id": seeded}, status_code=201)

        return run_once(request, body, session, key, command)

    return app
