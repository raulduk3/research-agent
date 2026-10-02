"""Fixtures for the swarm beta: a migrated, seeded store on a temporary file."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_agent.beta.config import BetaConfig
from research_agent.beta.db import connect, migrate
from research_agent.beta.spec import ensure_seed
from tests.beta.helpers import FakeClock, config


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cfg(tmp_path: Path) -> BetaConfig:
    return config(tmp_path)


@pytest.fixture
def db(cfg: BetaConfig, clock: FakeClock) -> Iterator[sqlite3.Connection]:
    migrate(cfg.database)
    with connect(cfg.database) as connection:
        ensure_seed(connection, clock())
        connection.commit()
        yield connection
