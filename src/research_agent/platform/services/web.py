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
is unchanged and stays unavailable until a monitor is wired.
"""

from __future__ import annotations

from collections.abc import Callable
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
    StorageClientError,
    StorageTransportError,
)
from research_agent.storage.database import Database
from research_agent.storage.migrate import require_schema
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
    app = create_owner_app(
        ActionsAppConfig(
            actions=config.storage_client(),
            directory=OwnerDirectory(owners),
            profile_hash=config.profile.compute_hash(),
            budget_funded=budget.funded,
            cost_caps=CostCaps(
                daily_cap_usd=budget.daily_cap_usd,
                monthly_cap_usd=budget.monthly_cap_usd,
                paid_execution_enabled=budget.paid_execution_enabled,
            ),
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
