from __future__ import annotations

from pathlib import Path

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.storage.database import Database

from service_harness import World


@pytest.fixture
def world(postgres_dsn: str, artifact_root: Path, tmp_path: Path) -> World:
    return World(Database(postgres_dsn), ArtifactStore(artifact_root), tmp_path)
