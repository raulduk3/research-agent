"""The swarm beta HTTP API.

Requests and answers are plain JSON. A refusal is a non-2xx status with
``{"detail": ..., "code": ..., "field": ...}``: ``detail`` is the sentence a
page shows, and for a budget refusal it starts with a reason code. Every
answer carries a ``budget`` block. Money is whole micro-dollars and every
time is whole seconds since 1970 UTC.

After sign-in a caller sends ``Authorization: Bearer <token>``. Reading is
open to any session. Edits are scoped: an island session edits its own island
and that island's agents; the operator edits anything, including the budget
levers, the evolution settings and the whole spec. Every edit is a new spec
revision.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
import sqlite3
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from research_agent.beta import spec as specs
from research_agent.beta.auth import Session, open_island_session, read_session
from research_agent.beta.brief import (
    SECTIONS,
    build_activity,
    build_brief,
    build_public_paper,
    render_paper_text,
    render_text,
)
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
    NotFound,
    Refusal,
    Unauthenticated,
)
from research_agent.beta.feedback import record_feedback
from research_agent.beta.ingest import (
    Fetcher,
    PaperFetcher,
    arxiv_fetcher,
    arxiv_paper_fetcher,
)
from research_agent.beta.models import ChatCompletionsClient, ModelClient
from research_agent.beta.papers import (
    count_paper_use,
    get_paper,
    hold_paper,
    release_paper,
)
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
from research_agent.beta.text import TextFetcher, arxiv_html_fetcher

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
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def wire(value: Any, key: str = "") -> Any:
    """An answer as it goes out: every ``*_at`` time as whole seconds since 1970."""
    if isinstance(value, dict):
        return {name: wire(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [wire(item, key) for item in value]
    if isinstance(value, str) and key.endswith("_at") and _STAMP.match(value):
        return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    return value


class ReleaseBody(BaseModel):
    note: str = Field(default="", max_length=500)


class LoginBody(BaseModel):
    island: str | None = None
    password: str | None = None
    credential: str | None = None


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
    target_kind: str | None = None
    #: The same field under the name the web app sends.
    target_type: str | None = None
    target_id: str
    signal: str
    note: str = ""
    island_id: str | None = None


class ChatBody(BaseModel):
    message: str
    #: A model writes the answer when the budget admits it; false asks for
    #: the free answer built from the records alone.
    synthesize: bool = True
    island_id: str | None = None


class EditBody(BaseModel):
    fields: dict[str, Any]
    island_id: str | None = None
    note: str = ""
    dry_run: bool = False
    base_revision: int | None = None


class GenomeBody(BaseModel):
    """An agent edit as the web app sends it: flat, with tools comma separated."""

    island_id: str | None = None
    parent_id: str
    prompt: str | None = None
    tools: str | list[str] | None = None


class SettingsBody(BaseModel):
    """An island's evolution switches, one or both per call."""

    evolution_enabled: bool | None = None
    mutation_enabled: bool | None = None


class SpecBody(BaseModel):
    spec: dict[str, Any]
    note: str = ""
    dry_run: bool = False
    base_revision: int | None = None


class RestoreBody(BaseModel):
    dry_run: bool = False


class EvolveBody(BaseModel):
    island_id: str | None = None
    force: bool = False


def _refusal(status: int, code: str, message: str, field: str | None) -> JSONResponse:
    body = {"detail": message, "code": code, "field": field}
    return JSONResponse(body, status_code=status)


def create_app(
    config: BetaConfig | None = None,
    *,
    model_client: ModelClient | None = None,
    clock: Clock = utc_now,
    fetch: Fetcher | None = None,
    fetch_paper: PaperFetcher | None = None,
    sleep: Callable[[float], None] | None = None,
    fetch_text: TextFetcher | None = None,
) -> FastAPI:
    """Build the application over one database; migrates and seeds on the way.

    With no feed fetcher given, both arXiv fetchers are the network ones.
    A caller that supplies its own feed fetcher supplies its own text
    fetcher too, or papers keep their abstracts.
    """
    cfg = config or load_config()
    client = model_client
    if client is None and cfg.provider is not None:
        client = ChatCompletionsClient(cfg.provider)
    swarm = Swarm(
        cfg,
        client,
        clock,
        fetch or arxiv_fetcher(cfg.arxiv_api),
        fetch_paper=fetch_paper
        or (arxiv_paper_fetcher(cfg.arxiv_api) if fetch is None else None),
        fetch_text=fetch_text or (arxiv_html_fetcher() if fetch is None else None),
    )
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
        # The web app sends every request with credentials included.
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
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
        """The caller's session, from the bearer token every signed-in request sends."""
        header = request.headers.get("Authorization", "")
        if not header.lower().startswith("bearer "):
            raise Unauthenticated("sign in to an island first")
        return read_session(cfg, header[7:].strip(), clock())

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

    def swarm_budget(db: sqlite3.Connection, spec: Mapping[str, Any]) -> BudgetState:
        return budget_state(db, spec, clock(), cfg.provider is not None)

    def ok(
        data: Mapping[str, Any],
        budget: BudgetState,
        island_id: str | None = None,
        status: int = 200,
    ) -> JSONResponse:
        body = wire({**data, "budget": budget.compact(island_id)})
        return JSONResponse(body, status_code=status)

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
                    f"spec_changed: the spec is at revision {revision},"
                    f" not {body.base_revision}",
                    "base_revision",
                )
            proposed = propose(current)
            # A dry run first: it validates and names the changes before anything is written.
            preview = specs.apply_spec(
                db, proposed, actor=session.actor, now=clock(), dry_run=True
            )
            if not session.is_operator:
                for change in preview["changes"]:
                    outside = change["island_id"] != session.island_id
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
        return ok(record, budget, session.island_id)

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

    @app.get("/api/v1/public/brief", response_model=None)
    def brief(
        include: str | None = None,
        island: str | None = None,
        paper: str | None = None,
        limit: int = 40,
        format: str = "json",
    ) -> JSONResponse | PlainTextResponse:
        sections = None
        if include:
            sections = [part.strip() for part in include.split(",") if part.strip()]
            unknown = sorted(set(sections) - set(SECTIONS))
            if unknown:
                raise Invalid(
                    f"unknown sections {', '.join(unknown)}; known: {', '.join(SECTIONS)}",
                    "include",
                )
        if format not in ("json", "text"):
            raise Invalid("format is json or text", "format")
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            if island is not None and not any(
                i["id"] == island and not i["archived"] for i in spec["islands"]
            ):
                raise NotFound(f"no island {island}")
            budget = swarm_budget(db, spec)
            data = build_brief(
                db,
                spec,
                budget,
                clock(),
                sections=sections,
                island_id=island,
                paper_id=paper,
                limit=max(1, min(limit, 200)),
            )
        if format == "text":
            return PlainTextResponse(
                render_text(data), media_type="text/markdown; charset=utf-8"
            )
        return ok(data, budget)

    @app.get("/api/v1/public/papers/{paper_id}", response_model=None)
    def public_paper(
        paper_id: str, format: str = "json"
    ) -> JSONResponse | PlainTextResponse:
        if format not in ("json", "text"):
            raise Invalid("format is json or text", "format")
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            view = build_public_paper(
                db, paper_id, clock(), budget.levers.unread_paper_days
            )
            # Every public read of a paper's record counts as use of it.
            count_paper_use(db, paper_id, clock())
        if format == "text":
            return PlainTextResponse(
                render_paper_text(view), media_type="text/markdown; charset=utf-8"
            )
        return ok(view, budget)

    @app.get("/api/v1/public/activity")
    def activity(after: int = 0, limit: int = 60) -> JSONResponse:
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            data = build_activity(db, max(0, after), max(1, min(limit, 200)))
        return ok(data, budget)

    @app.post("/api/v1/login")
    def login(body: LoginBody) -> JSONResponse:
        credential = body.password or body.credential
        if not credential:
            raise Invalid("a credential is required", "password")
        _, spec, budget = swarm.state()
        known = frozenset(
            island["id"] for island in spec["islands"] if not island["archived"]
        )
        session = open_island_session(cfg, credential, clock(), body.island, known)
        data = {
            "island": session.island_id,
            "token": session.token,
            "role": session.role,
            "expires_at": session.expires_at,
        }
        return ok(data, budget, session.island_id)

    @app.get("/api/v1/session")
    def whoami(request: Request) -> JSONResponse:
        session = session_of(request)
        _, _, budget = swarm.state()
        data = {"role": session.role, "island": session.island_id}
        return ok(data, budget, session.island_id)

    @app.post("/api/v1/ingest/arxiv")
    def ingest(
        request: Request, body: IngestBody, background: BackgroundTasks
    ) -> JSONResponse:
        operator_of(request)
        categories = body.categories or ([body.category] if body.category else None)
        summary = swarm.ingest(categories, body.limit, body.advance)
        background.add_task(
            swarm.execute, [item["run_id"] for item in summary["advance"]["started"]]
        )
        _, _, budget = swarm.state()
        return ok(summary, budget)

    @app.post("/api/v1/swarm/advance")
    def advance(request: Request, background: BackgroundTasks) -> JSONResponse:
        operator_of(request)
        summary = swarm.advance()
        background.add_task(
            swarm.execute, [item["run_id"] for item in summary["started"]]
        )
        _, _, budget = swarm.state()
        return ok(summary, budget)

    @app.get("/api/v1/islands")
    def islands(request: Request) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            rows = [island_brief(db, island, budget) for island in spec["islands"]]
        return ok({"islands": rows}, budget, session.island_id)

    @app.get("/api/v1/islands/{island_id}")
    def island(request: Request, island_id: str) -> JSONResponse:
        session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            data = build_island_projection(db, spec, island_id, budget)
        return ok(data, budget, island_id)

    @app.post("/api/v1/islands/{island_id}")
    def edit_island(request: Request, island_id: str, body: EditBody) -> JSONResponse:
        return edit(
            request, lambda spec: specs.patch_island(spec, island_id, body.fields), body
        )

    @app.post("/api/v1/islands/{island_id}/settings")
    def island_settings(
        request: Request, island_id: str, body: SettingsBody
    ) -> JSONResponse:
        """Flip an island's evolution or mutation switch.

        A flip takes effect from the next cycle and rewrites no stored agent,
        run or record.
        """
        fields: Json = {}
        if body.evolution_enabled is not None:
            fields["evolve"] = body.evolution_enabled
        if body.mutation_enabled is not None:
            fields["mutate"] = body.mutation_enabled
        if not fields:
            raise Invalid("name evolution_enabled or mutation_enabled", None)

        def propose(spec: Json) -> Json:
            specs.find_island(spec, island_id)
            return specs.patch_island(spec, island_id, fields)

        return edit(request, propose, EditBody(fields=fields))

    @app.get("/api/v1/agents")
    def agents(request: Request, island: str | None = None) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            if island is not None:
                specs.find_island(spec, island)
            rows = agent_briefs(db, spec, budget, island)
        return ok({"agents": rows}, budget, island or session.island_id)

    @app.get("/api/v1/agents/{agent_id}")
    def agent(request: Request, agent_id: str) -> JSONResponse:
        session_of(request)
        genome_id = agent_id.split("@", 1)[0]
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            data = build_agent_projection(db, spec, genome_id, budget)
        return ok(data, budget, data["agent"]["island_id"])

    def edit_genome(
        request: Request, genome_id: str, fields: Mapping[str, Any], body: EditBody
    ) -> JSONResponse:
        def propose(spec: Json) -> Json:
            try:
                island_id = specs.find_genome(spec, genome_id)[0]["id"]
            except Refusal:
                # A new agent: the body names the island it is seated on.
                island_id = island_for(session_of(request), body.island_id)
            return specs.patch_genome(spec, island_id, genome_id, fields)

        return edit(request, propose, body)

    @app.post("/api/v1/agents/{agent_id}")
    def edit_agent(request: Request, agent_id: str, body: EditBody) -> JSONResponse:
        return edit_genome(request, agent_id.split("@", 1)[0], body.fields, body)

    @app.post("/api/v1/genomes")
    def save_genome(request: Request, body: GenomeBody) -> JSONResponse:
        """The same agent edit, in the flat shape the web app's form sends.

        The agent named by ``parent_id`` gets a new version; the version it
        had, and every run made under it, stay as they were.
        """
        fields: Json = {}
        if body.prompt is not None:
            fields["prompt"] = body.prompt
        if body.tools is not None:
            names = body.tools.split(",") if isinstance(body.tools, str) else body.tools
            fields["allowed_tools"] = [name.strip() for name in names if name.strip()]
        return edit_genome(
            request, body.parent_id.split("@", 1)[0], fields, EditBody(fields=fields)
        )

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
        return ok(data, budget, session.island_id)

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
                "INSERT INTO idempotency(key, scope, response, created_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    key,
                    f"{session.actor} {request.url.path}",
                    dumps(data),
                    iso(clock()),
                ),
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
                return ok(earlier, swarm_budget(db, spec), island_id, status=202)
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
        return ok(data, budget, island_id, status=202)

    @app.get("/api/v1/runs/{run_id}")
    def run(request: Request, run_id: str, after: int = 0) -> JSONResponse:
        session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
            data = build_run_projection(db, run_id, after)
        return ok(data, budget, data["run"]["island_id"])

    def may_let_go(db: sqlite3.Connection, session: Session, paper_id: str) -> None:
        """Letting go is swarm-wide: the operator, or an island the paper reached."""
        if session.is_operator:
            return
        reached = db.execute(
            "SELECT 1 FROM assignments WHERE paper_id = ? AND island_id = ?",
            (paper_id, session.island_id),
        ).fetchone()
        if reached is None:
            raise Forbidden("only an island the paper reached may let it go or hold it")

    @app.post("/api/v1/papers/{paper_id}/release")
    def release(paper_id: str, request: Request, body: ReleaseBody) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            get_paper(db, paper_id)
            may_let_go(db, session, paper_id)
            data = release_paper(
                db, paper_id, actor=session.actor, note=body.note, now=clock()
            )
            budget = swarm_budget(db, spec)
        return ok(data, budget, session.island_id)

    @app.post("/api/v1/papers/{paper_id}/hold")
    def hold(paper_id: str, request: Request, body: ReleaseBody) -> JSONResponse:
        session = session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            get_paper(db, paper_id)
            may_let_go(db, session, paper_id)
            data = hold_paper(db, paper_id)
            budget = swarm_budget(db, spec)
        return ok(data, budget, session.island_id)

    @app.post("/api/v1/feedback")
    def feedback(request: Request, body: FeedbackBody) -> JSONResponse:
        session = session_of(request)
        island_id = island_for(session, body.island_id)
        target_kind = body.target_kind or body.target_type
        if target_kind is None:
            raise Invalid("a feedback target needs its kind", "target_kind")
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            specs.find_island(spec, island_id)
            if target_kind == "island":
                specs.find_island(spec, body.target_id)
            key, earlier = remembered(db, request, session)
            if earlier is not None:
                return ok(earlier, swarm_budget(db, spec), island_id, status=201)
            data = {
                "feedback": record_feedback(
                    db,
                    island_id=island_id,
                    target_kind=target_kind,
                    target_id=body.target_id,
                    signal=body.signal,
                    note=body.note,
                    now=clock(),
                )
            }
            remember(db, request, session, key, data)
            budget = swarm_budget(db, spec)
        return ok(data, budget, island_id, status=201)

    @app.post("/api/v1/chat")
    def chat(request: Request, body: ChatBody) -> JSONResponse:
        session = session_of(request)
        if session.is_operator or session.island_id is None:
            raise Forbidden("chat belongs to an island session", "island_id")
        if body.island_id is not None and body.island_id != session.island_id:
            raise Forbidden("chat belongs to the session island", "island_id")
        island_id = session.island_id
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
        return ok(data, budget, island_id)

    @app.get("/api/v1/costs/budget")
    def budget_view(request: Request) -> JSONResponse:
        session = session_of(request)
        _, _, budget = swarm.state()
        return ok({"state": budget.full()}, budget, session.island_id)

    @app.post("/api/v1/costs/budget")
    def edit_budget(request: Request, body: EditBody) -> JSONResponse:
        return edit(request, lambda spec: specs.patch_budget(spec, body.fields), body)

    @app.post("/api/v1/swarm/evolution")
    def edit_evolution(request: Request, body: EditBody) -> JSONResponse:
        return edit(
            request, lambda spec: specs.patch_evolution(spec, body.fields), body
        )

    @app.post("/api/v1/swarm/evolve")
    def evolve(request: Request, body: EvolveBody) -> JSONResponse:
        operator_of(request)
        if body.island_id is not None:
            with connect(cfg.database) as db:
                specs.find_island(specs.current_spec(db)[1], body.island_id)
        generations = swarm.evolve(body.island_id, body.force)
        _, _, budget = swarm.state()
        return ok({"generations": generations}, budget)

    @app.get("/api/v1/swarm/spec")
    def spec_view(request: Request) -> JSONResponse:
        session_of(request)
        with connect(cfg.database) as db:
            revision, spec = specs.current_spec(db)
            budget = swarm_budget(db, spec)
        return ok({"revision": revision, "spec": spec}, budget)

    @app.post("/api/v1/swarm/spec")
    def edit_spec(request: Request, body: SpecBody) -> JSONResponse:
        return edit(request, lambda _: body.spec, body)

    @app.get("/api/v1/swarm/revisions")
    def revisions(request: Request) -> JSONResponse:
        session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            rows = specs.list_revisions(db)
            budget = swarm_budget(db, spec)
        return ok({"revisions": rows}, budget)

    @app.get("/api/v1/swarm/revisions/{revision}")
    def revision_view(request: Request, revision: int) -> JSONResponse:
        session_of(request)
        with connect(cfg.database) as db:
            _, spec = specs.current_spec(db)
            data = specs.get_revision(db, revision)
            budget = swarm_budget(db, spec)
        return ok(data, budget)

    @app.post("/api/v1/swarm/revisions/{revision}/restore")
    def restore(request: Request, revision: int, body: RestoreBody) -> JSONResponse:
        session = operator_of(request)
        with connect(cfg.database) as db:
            record = specs.restore_revision(
                db, revision, actor=session.actor, now=clock(), dry_run=body.dry_run
            )
            budget = swarm_budget(db, record["spec"])
        return ok(record, budget)

    return app
