"""The swarm beta HTTP API.

Every ``/api/v1`` answer wears the contract envelope: ``{"contract": "1",
"data": ...}`` on success and ``{"contract": "1", "error": {code, message,
field}}`` on a refusal. Every data answer carries a ``budget`` block, and an
answer to a signed-in caller carries the session's ``csrf_token``.

Reading is open to any session. Edits are scoped: an island session edits its
own island and that island's agents; the operator edits anything, including
the budget levers and the whole spec. Every edit is a new spec revision.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from research_agent.beta import spec as specs
from research_agent.beta.auth import COOKIE, Session, open_island_session, read_session
from research_agent.beta.budget import BudgetState, budget_state
from research_agent.beta.chat import answer_question
from research_agent.beta.config import BetaConfig, load_config
from research_agent.beta.db import (
    Clock,
    Json,
    connect,
    dumps,
    iso,
    loads,
    schema_version,
    utc_now,
)
from research_agent.beta.errors import (
    Conflict,
    Forbidden,
    Invalid,
    Refusal,
    Unauthenticated,
)
from research_agent.beta.feedback import record_feedback
from research_agent.beta.ingest import Fetcher, arxiv_fetcher
from research_agent.beta.models import ChatCompletionsClient, ModelClient
from research_agent.beta.projections import (
    agent_briefs,
    build_agent_projection,
    build_island_projection,
    build_paper_projection,
    build_run_projection,
    build_storm,
    island_brief,
)
from research_agent.beta.runs import create_run
from research_agent.beta.service import Swarm

logger = logging.getLogger("research_agent.beta")

_CODE_BY_STATUS = {
    400: "invalid_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "invalid_request",
    409: "state_conflict",
    422: "invalid_request",
    503: "unavailable",
}
#: Island fields only the operator may change: they move money or hide an island.
_OPERATOR_FIELDS = frozenset({"budget_share", "archived"})


class LoginBody(BaseModel):
    credential: str | None = None
    password: str | None = None


class IngestBody(BaseModel):
    category: str | None = None
    categories: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=200)
    advance: bool | None = None


class RunBody(BaseModel):
    paper_id: str
    island_id: str | None = None
    genome_id: str | None = None
    agent_id: str | None = None
    seed: int | None = None


class FeedbackBody(BaseModel):
    target_kind: str
    target_id: str
    signal: str
    note: str = ""
    island_id: str | None = None


class ChatBody(BaseModel):
    message: str
    synthesize: bool = False
    island_id: str | None = None


class EditBody(BaseModel):
    fields: dict[str, Any]
    island_id: str | None = None
    note: str = ""
    dry_run: bool = False
    base_revision: int | None = None


class SpecBody(BaseModel):
    spec: dict[str, Any]
    note: str = ""
    dry_run: bool = False
    base_revision: int | None = None


class RestoreBody(BaseModel):
    dry_run: bool = False


def _refusal(status: int, code: str, message: str, field: str | None) -> JSONResponse:
    error = {"code": code, "message": message, "field": field}
    return JSONResponse({"contract": "1", "error": error}, status_code=status)


def create_app(
    config: BetaConfig | None = None,
    *,
    model_client: ModelClient | None = None,
    clock: Clock = utc_now,
    fetch: Fetcher | None = None,
    sleep: Callable[[float], None] | None = None,
) -> FastAPI:
    """Build the application over one database; migrates and seeds on the way."""
    cfg = config or load_config()
    client = model_client
    if client is None and cfg.provider is not None:
        client = ChatCompletionsClient(cfg.provider)
    swarm = Swarm(cfg, client, clock, fetch or arxiv_fetcher(cfg.arxiv_api))
    if sleep is not None:
        swarm.sleep = sleep
    swarm.prepare()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        intervals = [value for value in (cfg.tick_seconds, cfg.ingest_seconds) if value]
        beat: asyncio.Task[None] | None = None
        if intervals:

            async def run_heartbeat() -> None:
                while True:
                    await asyncio.sleep(min(min(intervals), 60))
                    try:
                        await asyncio.to_thread(swarm.heartbeat)
                    except Exception:
                        logger.exception("swarm heartbeat failed")

            beat = asyncio.create_task(run_heartbeat())
        yield
        if beat is not None:
            beat.cancel()

    app = FastAPI(title="research-agent swarm beta", version="beta", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.allowed_origins),
        allow_origin_regex=cfg.allowed_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-CSRF-Token",
            "Idempotency-Key",
        ],
    )

    @app.exception_handler(Refusal)
    async def on_refusal(_: Request, refusal: Refusal) -> JSONResponse:
        return _refusal(refusal.status, refusal.code, refusal.message, refusal.field)

    @app.exception_handler(RequestValidationError)
    async def on_invalid(_: Request, error: RequestValidationError) -> JSONResponse:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"] if part != "body") or None
        return _refusal(422, "invalid_request", str(first["msg"]), where)

    @app.exception_handler(HTTPException)
    async def on_http(_: Request, error: HTTPException) -> JSONResponse:
        code = _CODE_BY_STATUS.get(error.status_code, "unavailable")
        return _refusal(error.status_code, code, str(error.detail), None)

    def session_of(request: Request) -> Session:
        """The caller's session, from a bearer token or the session cookie."""
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            return read_session(cfg, header[7:].strip(), clock())
        token = request.cookies.get(COOKIE)
        if not token:
            raise Unauthenticated("sign in to an island first")
        session = read_session(cfg, token, clock())
        # A cookie rides along on its own, so a POST must prove it came from the page.
        if (
            request.method == "POST"
            and request.headers.get("X-CSRF-Token") != session.csrf_token
        ):
            raise Forbidden(
                "the X-CSRF-Token header does not match the session", "X-CSRF-Token"
            )
        return session

    def operator_of(request: Request) -> Session:
        session = session_of(request)
        if not session.is_operator:
            raise Forbidden("this action is the operator's")
        return session

    def island_for(session: Session, named: str | None) -> str:
        """The island a write is scoped to: the session's own, or the operator's choice."""
        if not session.is_operator:
            if named is not None and named != session.island_id:
                raise Forbidden("a session writes to its own island", "island_id")
            return str(session.island_id)
        if named is None:
            raise Invalid("the operator names the island", "island_id")
        return named

    def ok(
        data: Mapping[str, Any],
        budget: BudgetState,
        session: Session | None = None,
        island_id: str | None = None,
        status: int = 200,
    ) -> JSONResponse:
        body: Json = {**data, "budget": budget.compact(island_id)}
        if session is not None:
            body["csrf_token"] = session.csrf_token
        return JSONResponse({"contract": "1", "data": body}, status_code=status)

    def edit(
        request: Request,
        propose: Callable[[Json], Json],
        body: EditBody | SpecBody,
        restored_from: int | None = None,
    ) -> JSONResponse:
        """Apply one edit as a new spec revision, within the caller's scope."""
        session = session_of(request)
        with connect(cfg.database) as db:
            revision, current = specs.current_spec(db)
            if body.base_revision is not None and body.base_revision != revision:
                raise Conflict(
                    f"spec_changed: the spec is at revision {revision}, not {body.base_revision}",
                    "base_revision",
                )
            proposed = propose(current)
            # A dry run first: it validates and names the changes before anything is written.
            preview = specs.apply_spec(
                db, proposed, actor=session.actor, now=clock(), dry_run=True
            )
            if not session.is_operator:
                for change in preview["changes"]:
                    outside = change["kind"] == "budget" or change["island_id"] != (
                        session.island_id
                    )
                    reserved = change["kind"] == "island" and (
                        change["created"] or _OPERATOR_FIELDS & set(change["fields"])
                    )
                    if outside or reserved:
                        raise Forbidden(
                            f"editing {change['kind']} {change['id']} is the operator's"
                        )
            record = preview
            if not body.dry_run:
                record = specs.apply_spec(
                    db,
                    proposed,
                    actor=session.actor,
                    now=clock(),
                    note=body.note,
                    restored_from=restored_from,
                )
            budget = swarm_budget(db, record["spec"])
        return ok(record, budget, session)

    def swarm_budget(db: sqlite3.Connection, spec: Mapping[str, Any]) -> BudgetState:
        return budget_state(db, spec, clock(), cfg.provider is not None)

    @app.get("/health")
    def health() -> Json:
        with connect(cfg.database) as db:
            version = schema_version(db)
        return {
            "status": "ok",
            "schema_version": version,
            "provider_configured": cfg.provider is not None,
        }

    @app.get("/api/v1/public/storm")
    def storm() -> JSONResponse:
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            return ok(build_storm(db, spec, budget), budget)

    @app.post("/api/v1/login")
    def login(body: LoginBody) -> JSONResponse:
        credential = body.credential or body.password
        if not credential:
            raise Invalid("a credential is required", "credential")
        session = open_island_session(cfg, credential, clock())
        _, _, budget = swarm.state()
        response = ok(
            {
                "role": session.role,
                "island": session.island_id,
                "token": session.token,
                "expires_at": session.expires_at,
            },
            budget,
            session,
            session.island_id,
        )
        response.set_cookie(
            COOKIE,
            session.token,
            max_age=cfg.session_ttl_seconds,
            httponly=True,
            secure=cfg.cookie_secure,
            samesite=cfg.cookie_samesite,
            path="/",
        )
        return response

    @app.post("/api/v1/logout")
    def logout() -> JSONResponse:
        _, _, budget = swarm.state()
        response = ok({}, budget)
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/api/v1/session")
    def whoami(request: Request) -> JSONResponse:
        session = session_of(request)
        _, _, budget = swarm.state()
        data = {"role": session.role, "island": session.island_id}
        return ok(data, budget, session, session.island_id)

    @app.post("/api/v1/ingest/arxiv")
    def ingest(
        request: Request, body: IngestBody, background: BackgroundTasks
    ) -> JSONResponse:
        session = operator_of(request)
        categories = body.categories or ([body.category] if body.category else None)
        summary = swarm.ingest(categories, body.limit, body.advance)
        background.add_task(
            swarm.execute, [item["run_id"] for item in summary["advance"]["started"]]
        )
        _, _, budget = swarm.state()
        return ok(summary, budget, session)

    @app.post("/api/v1/swarm/advance")
    def advance(request: Request, background: BackgroundTasks) -> JSONResponse:
        session = operator_of(request)
        summary = swarm.advance()
        background.add_task(
            swarm.execute, [item["run_id"] for item in summary["started"]]
        )
        _, _, budget = swarm.state()
        return ok(summary, budget, session)

    @app.get("/api/v1/islands")
    def islands(request: Request) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            rows = [island_brief(db, island, budget) for island in spec["islands"]]
        return ok({"islands": rows}, budget, session, session.island_id)

    @app.get("/api/v1/islands/{island_id}")
    def island(request: Request, island_id: str) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            data = build_island_projection(db, spec, island_id, budget)
        return ok(data, budget, session, island_id)

    @app.post("/api/v1/islands/{island_id}")
    def edit_island(request: Request, island_id: str, body: EditBody) -> JSONResponse:
        return edit(
            request, lambda spec: specs.patch_island(spec, island_id, body.fields), body
        )

    @app.get("/api/v1/agents")
    def agents(request: Request, island: str | None = None) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            if island is not None:
                specs.find_island(spec, island)
            rows = agent_briefs(db, spec, budget, island)
        return ok({"agents": rows}, budget, session, island or session.island_id)

    @app.get("/api/v1/agents/{agent_id}")
    def agent(request: Request, agent_id: str) -> JSONResponse:
        session = session_of(request)
        genome_id = agent_id.split("@", 1)[0]
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            data = build_agent_projection(db, spec, genome_id, budget)
        return ok(data, budget, session, data["agent"]["island_id"])

    @app.post("/api/v1/agents/{agent_id}")
    def edit_agent(request: Request, agent_id: str, body: EditBody) -> JSONResponse:
        genome_id = agent_id.split("@", 1)[0]

        def propose(spec: Json) -> Json:
            try:
                island_id = specs.find_genome(spec, genome_id)[0]["id"]
            except Refusal:
                # A new agent: the body names the island it is seated on.
                island_id = island_for(session_of(request), body.island_id)
            return specs.patch_genome(spec, island_id, genome_id, body.fields)

        return edit(request, propose, body)

    @app.post("/api/v1/agents/{agent_id}/versions/{version}/restore")
    def restore_agent(
        request: Request, agent_id: str, version: int, body: RestoreBody
    ) -> JSONResponse:
        genome_id = agent_id.split("@", 1)[0]
        with connect(cfg.database) as db:
            versions = specs.genome_versions(db, genome_id)
        wanted = next((item for item in versions if item["version"] == version), None)
        if wanted is None:
            raise Invalid(f"agent {genome_id} has no version {version}", "version")
        fields = {name: wanted[name] for name in specs.GENOME_CONTENT}
        note = f"restore {genome_id} to version {version}"
        return edit(
            request,
            lambda spec: specs.patch_genome(
                spec, wanted["island_id"], genome_id, fields
            ),
            EditBody(fields={}, note=note, dry_run=body.dry_run),
            restored_from=wanted["revision"],
        )

    @app.get("/api/v1/papers/{paper_id:path}")
    def paper(request: Request, paper_id: str) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            data = build_paper_projection(db, paper_id)
        return ok(data, budget, session, session.island_id)

    def remembered(
        db: sqlite3.Connection, request: Request, session: Session
    ) -> tuple[str | None, Json | None]:
        """A repeated POST with the same Idempotency-Key gets its first answer back."""
        key = request.headers.get("Idempotency-Key")
        if not key:
            return None, None
        row = db.execute(
            "SELECT response FROM idempotency WHERE key = ? AND scope = ?",
            (key, f"{session.actor} {request.url.path}"),
        ).fetchone()
        return key, None if row is None else loads(row[0])

    def remember(
        db: sqlite3.Connection,
        request: Request,
        session: Session,
        key: str | None,
        data: Json,
    ) -> None:
        if key:
            db.execute(
                "INSERT INTO idempotency(key, scope, response, created_at) VALUES (?, ?, ?, ?)",
                (key, f"{session.actor} {request.url.path}", dumps(data), iso(clock())),
            )

    @app.post("/api/v1/runs")
    def start_run(
        request: Request, body: RunBody, background: BackgroundTasks
    ) -> JSONResponse:
        session = session_of(request)
        genome_id = body.genome_id or (
            body.agent_id.split("@", 1)[0] if body.agent_id else None
        )
        with connect(cfg.database) as db:
            revision, spec = specs.current_spec(db)
            named = body.island_id
            if named is None and genome_id is not None and session.is_operator:
                named = specs.find_genome(spec, genome_id)[0]["id"]
            island_id = island_for(session, named)
            key, earlier = remembered(db, request, session)
            if earlier is not None:
                return ok(
                    earlier, swarm_budget(db, spec), session, island_id, status=202
                )
            run_id = create_run(
                db,
                spec=spec,
                revision=revision,
                provider=cfg.provider,
                clock=clock,
                paper_id=body.paper_id,
                island_id=island_id,
                genome_id=genome_id,
                seed=body.seed,
            )
            data = {"run_id": run_id, "status": "queued", "href": f"/runs/{run_id}"}
            remember(db, request, session, key, data)
            budget = swarm_budget(db, spec)
        # The run is stored before its work starts; the page watches its events arrive.
        background.add_task(swarm.execute, [run_id])
        return ok(data, budget, session, island_id, status=202)

    @app.get("/api/v1/runs/{run_id}")
    def run(request: Request, run_id: str, after: int = 0) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            data = build_run_projection(db, run_id, after)
        return ok(data, budget, session, data["run"]["island_id"])

    @app.post("/api/v1/feedback")
    def feedback(request: Request, body: FeedbackBody) -> JSONResponse:
        session = session_of(request)
        island_id = island_for(session, body.island_id)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            specs.find_island(spec, island_id)
            key, earlier = remembered(db, request, session)
            if earlier is not None:
                return ok(
                    earlier, swarm_budget(db, spec), session, island_id, status=201
                )
            data = {
                "feedback": record_feedback(
                    db,
                    island_id=island_id,
                    target_kind=body.target_kind,
                    target_id=body.target_id,
                    signal=body.signal,
                    note=body.note,
                    now=clock(),
                )
            }
            remember(db, request, session, key, data)
            budget = swarm_budget(db, spec)
        return ok(data, budget, session, island_id, status=201)

    @app.post("/api/v1/chat")
    def chat(request: Request, body: ChatBody) -> JSONResponse:
        session = session_of(request)
        island_id = island_for(session, body.island_id)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            data = answer_question(
                db,
                island=specs.find_island(spec, island_id),
                message=body.message,
                synthesize=body.synthesize,
                state=swarm_budget(db, spec),
                provider=cfg.provider,
                client=client,
                clock=clock,
            )
            budget = swarm_budget(db, spec)
        return ok(data, budget, session, island_id)

    @app.get("/api/v1/costs/budget")
    def budget_view(request: Request) -> JSONResponse:
        session = session_of(request)
        _, _, budget = swarm.state()
        return ok({"state": budget.full()}, budget, session, session.island_id)

    @app.post("/api/v1/costs/budget")
    def edit_budget(request: Request, body: EditBody) -> JSONResponse:
        return edit(request, lambda spec: specs.patch_budget(spec, body.fields), body)

    @app.get("/api/v1/swarm/spec")
    def spec_view(request: Request) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            revision, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
        return ok({"revision": revision, "spec": spec}, budget, session)

    @app.post("/api/v1/swarm/spec")
    def edit_spec(request: Request, body: SpecBody) -> JSONResponse:
        return edit(request, lambda _: body.spec, body)

    @app.get("/api/v1/swarm/revisions")
    def revisions(request: Request) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            rows: Sequence[Json] = specs.list_revisions(db)
            budget = swarm_budget(db, spec)
        return ok({"revisions": rows}, budget, session)

    @app.get("/api/v1/swarm/revisions/{revision}")
    def revision_view(request: Request, revision: int) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            data = specs.get_revision(db, revision)
            budget = swarm_budget(db, spec)
        return ok(data, budget, session)

    @app.post("/api/v1/swarm/revisions/{revision}/restore")
    def restore(request: Request, revision: int, body: RestoreBody) -> JSONResponse:
        session = operator_of(request)
        with connect(cfg.database) as db:
            record = specs.restore_revision(
                db, revision, actor=session.actor, now=clock(), dry_run=body.dry_run
            )
            budget = swarm_budget(db, record["spec"])
        return ok(record, budget, session)

    return app
