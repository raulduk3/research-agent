"""``serve-owner`` and ``serve-rating``: the two web apps over HTTPS (#315).

Each launcher composes the app its package already defines
(``web/actions/app.py`` for the owner, ``web/app.py`` for raters) from the
role's checked configuration and serves it with uvicorn on the role's
certificate. Both apps set ``Secure`` session cookies, so neither is served
over plain HTTP.

The launcher adds ``GET /health`` to each app: it reads the dependency the
app's own sign-in needs (the owner principals for the owner app, the rater
principals through storage for the rating app) and answers 503 when that
read fails, so a started process is not reported ready while its sign-in
cannot work. The owner app's session-gated ``/api/v1/health`` monitor report
is wired from what the launcher reaches: storage over its client, the
database's schema version, and today's settled spend (#351).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from research_agent.artifacts import ArtifactStore
from research_agent.platform.services.config import (
    LaunchConfig,
    LaunchRefused,
    load_launch_config,
)
from research_agent.storage.client import (
    StorageClient,
    StorageClientError,
    StorageTransportError,
)
from research_agent.storage.database import Database
from research_agent.storage.migrate import SCHEMA_VERSION, require_schema
from research_agent.storage.owners import OwnerRepository
from research_agent.web.actions.app import ActionsAppConfig, CostCaps
from research_agent.web.actions.app import create_app as create_owner_app
from research_agent.web.app import RatingAppConfig
from research_agent.web.app import create_app as create_rating_app
from research_agent.web.auth import OwnerDirectory, RaterDirectory
from research_agent.web.digest import load_digest


def build_owner_app(config: LaunchConfig) -> FastAPI:
    """The owner actions app, its profile facts read from the checked launch profile."""

    database = Database(config.secret_text("database_dsn"))
    try:
        require_schema(database)
    except psycopg.OperationalError as error:
        # A refused or unresolvable connection is not a schema fault.
        raise LaunchRefused("storage database is unreachable") from error
    except (psycopg.Error, RuntimeError) as error:
        raise LaunchRefused("storage schema is not current") from error
    owners = OwnerRepository(
        database,
        ArtifactStore(Path(config.text("artifact_root"))),
        producer=config.producer(),
        config_hash=config.text("config_hash"),
        retention_policy_hash=config.text("retention_policy_hash"),
    )
    budget = config.profile.budget
    actions = config.storage_client()
    app = create_owner_app(
        ActionsAppConfig(
            actions=actions,
            directory=OwnerDirectory(owners),
            profile_hash=config.profile.compute_hash(),
            budget_funded=budget.funded,
            cost_caps=CostCaps(
                daily_cap_usd=budget.daily_cap_usd,
                monthly_cap_usd=budget.monthly_cap_usd,
                paid_execution_enabled=budget.paid_execution_enabled,
            ),
            front_end_origin=config.profile.host.front_end_origin,
            health=lambda: _owner_report(database, actions),
        )
    )
    _add_health(app, owners.list_principals, (psycopg.Error,))
    return app


def build_rating_app(config: LaunchConfig) -> FastAPI:
    """The rating app over the configured digest; a digest storage cannot read refuses."""

    storage = config.storage_client()
    island = config.text("island", section="digest")
    batch_id = config.text("batch_id", section="digest")
    try:
        loaded = load_digest(storage, island=island, batch_id=batch_id)
    except (StorageClientError, StorageTransportError, KeyError, ValueError) as error:
        raise LaunchRefused("the configured digest is unreadable") from error
    app = create_rating_app(
        RatingAppConfig(
            storage=storage,
            directory=RaterDirectory(storage),
            digest=loaded,
            public_origin=config.text("public_origin"),
        )
    )
    _add_health(app, storage.list_raters, (StorageClientError, StorageTransportError))
    return app


def build_web_server(config: LaunchConfig, app: FastAPI) -> uvicorn.Server:
    """Serve *app* over HTTPS on the role's certificate."""

    return uvicorn.Server(
        uvicorn.Config(
            app,
            host=config.text("host"),
            port=config.integer("port"),
            ssl_certfile=str(config.secret_path("tls_certificate")),
            ssl_keyfile=str(config.secret_path("tls_private_key")),
            access_log=False,
            log_level="warning",
        )
    )


def serve_owner(config_path: Path) -> None:
    config = load_launch_config(config_path, "owner")
    build_web_server(config, build_owner_app(config)).run()


def serve_rating(config_path: Path) -> None:
    config = load_launch_config(config_path, "rating")
    build_web_server(config, build_rating_app(config)).run()


def _add_health(
    app: FastAPI,
    probe: Callable[[], object],
    failures: tuple[type[Exception], ...],
) -> None:
    def health() -> JSONResponse:
        try:
            probe()
        except failures:
            return JSONResponse({"state": "unavailable"}, status_code=503)
        return JSONResponse({"state": "ready"})

    app.add_api_route("/health", health, methods=["GET"])


# Worst first: the report's state is the most severe state of any check.
_SEVERITY = ("operator_repair", "failed", "waiting", "healthy")
_CHECK_FAILURES = (
    StorageClientError,
    StorageTransportError,
    psycopg.Error,
    RuntimeError,
    KeyError,
)


def _owner_report(database: Database, actions: StorageClient) -> dict[str, object]:
    """The owner monitor report (``docs/contracts/api-v1/health.json``).

    Each check reads once; a read that fails is reported ``failed`` with the
    failure's type rather than failing the whole report.
    """

    now = datetime.now(timezone.utc)

    def storage() -> str:
        agents = actions.list_owner_agents().data["agents"]
        return f"reachable; {len(agents)} genomes"

    def database_schema() -> str:
        require_schema(database)
        return f"schema version {SCHEMA_VERSION}"

    def spend() -> str:
        totals = actions.read_costs(now.date().isoformat()).data["day_totals"]
        runs = totals["priced_runs"] + totals["unpriced_runs"]
        return f"{totals['priced_micros']} micros settled today over {runs} runs"

    probes: tuple[tuple[str, Callable[[], str]], ...] = (
        ("storage", storage),
        ("database", database_schema),
        ("spend", spend),
    )
    checks: list[dict[str, str]] = []
    for name, probe in probes:
        try:
            checks.append({"name": name, "state": "healthy", "detail": probe()})
        except _CHECK_FAILURES as error:
            checks.append(
                {"name": name, "state": "failed", "detail": type(error).__name__}
            )
    present = {check["state"] for check in checks}
    return {
        "state": next(state for state in _SEVERITY if state in present),
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "checks": checks,
    }
