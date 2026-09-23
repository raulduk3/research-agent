"""The stored embedding view of each paper family, on PostgreSQL (#298)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json
from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.artifacts import ArtifactPublication, ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.embedding_views import EmbeddingViewRepository
from research_agent.storage.errors import UnavailableInput

pytestmark = pytest.mark.integration

FAMILY = "123e4567-e89b-42d3-a456-426614174030"
FIRST = "123e4567-e89b-42d3-a456-426614174031"
SECOND = "123e4567-e89b-42d3-a456-426614174032"


def _publish(
    artifacts: ArtifactRepository, body: dict[str, Any]
) -> ArtifactPublication:
    payload = canonical_json(body)
    return artifacts.publish(
        [payload],
        expected_hash=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
        maximum_length=1024 * 1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )


def _view(version: str, dims: int) -> dict[str, Any]:
    return {"paper_id": FAMILY, "paper_version_id": version, "dims": dims}


def test_a_familys_current_view_is_the_one_recorded_last(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    artifacts = ArtifactRepository(database, ArtifactStore(artifact_root))
    views = EmbeddingViewRepository(database, artifacts)
    assert views.current(FAMILY) is None

    first = _publish(artifacts, _view(FIRST, 1)).manifest_hash
    views.record(first)
    assert views.current(FAMILY) == _view(FIRST, 1)
    views.record(_publish(artifacts, _view(SECOND, 2)).manifest_hash)
    assert views.current(FAMILY) == _view(SECOND, 2)
    # Recording a view again records nothing new.
    views.record(first)
    assert views.current(FAMILY) == _view(SECOND, 2)
    with psycopg.connect(postgres_dsn) as connection:
        rows = connection.execute(
            "SELECT paper_version_id::text FROM embedding_views ORDER BY recorded_at"
        ).fetchall()
        assert rows == [(FIRST,), (SECOND,)]
        # The pointer rows are history: none is edited or removed.
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM embedding_views")


def test_a_view_is_recorded_only_against_the_paper_it_names(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    artifacts = ArtifactRepository(database, ArtifactStore(artifact_root))
    views = EmbeddingViewRepository(database, artifacts)
    with pytest.raises(ContractValidationError):
        views.record(_publish(artifacts, {"paper_version_id": FIRST}).manifest_hash)
    # A view's body hash is not its manifest: it names no provenance.
    body = _publish(artifacts, _view(FIRST, 1)).artifact_hash
    with pytest.raises(UnavailableInput):
        views.record(body)
    assert views.current(FAMILY) is None
