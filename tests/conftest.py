"""Disposable schemas for real PostgreSQL transaction tests."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--require-postgres", action="store_true", default=False)


def pytest_sessionstart(session: pytest.Session) -> None:
    if session.config.getoption("--require-postgres") and not os.environ.get(
        "RESEARCH_AGENT_TEST_DSN"
    ):
        raise pytest.UsageError(
            "RESEARCH_AGENT_TEST_DSN is required for database checks"
        )


@pytest.fixture
def unmigrated_postgres_dsn() -> Iterator[str]:
    dsn = os.environ.get("RESEARCH_AGENT_TEST_DSN")
    if not dsn:
        pytest.skip("Set RESEARCH_AGENT_TEST_DSN to run PostgreSQL integration tests")
    schema = "test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        if connection.info.server_version // 10000 != 17:
            pytest.fail("The storage contract requires PostgreSQL 17")
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            yield make_conninfo(dsn, options=f"-csearch_path={schema}")
        finally:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.fixture
def postgres_dsn(unmigrated_postgres_dsn: str) -> str:
    migrate(Database(unmigrated_postgres_dsn))
    return unmigrated_postgres_dsn


@pytest.fixture
def artifact_root(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    root.mkdir()
    return root
