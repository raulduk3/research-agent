from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.storage.artifacts import ArtifactPublication, ArtifactRepository
from research_agent.storage.authorization import AgentOutputPolicy
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion(
    image_digest="a" * 64, source_commit="b" * 40, contract_version=1
)


def _publish(repository: ArtifactRepository, payload: bytes) -> ArtifactPublication:
    digest = hashlib.sha256(payload).hexdigest()
    return repository.publish(
        [payload],
        expected_hash=digest,
        byte_length=len(payload),
        maximum_length=1024,
        media_type="application/json",
        kind="tool_response",
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )


def test_agent_output_policy_admits_only_the_sealing_scoring_and_human_paths() -> None:
    policy = AgentOutputPolicy()
    for denied_role in ("extract", "embed", "fit", "calibrate", "capture", "other"):
        assert not policy.permitted(
            artifact_kind="tool_response", consumer_role=denied_role
        )
    for allowed_role in ("score", "audit", "human_presentation"):
        assert policy.permitted(
            artifact_kind="tool_response", consumer_role=allowed_role
        )
    assert policy.permitted(artifact_kind="manifest", consumer_role="extract")


def test_reading_agent_output_by_hash_is_refused_to_every_other_consumer(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    repository = ArtifactRepository(database, ArtifactStore(artifact_root))
    output = _publish(repository, b'{"forecast":1}')

    for denied_role in ("extract", "fit", "capture"):
        with pytest.raises(UnavailableInput):
            repository.read(output.artifact_hash, consumer_role=denied_role)

    for allowed_role in ("score", "audit", "human_presentation"):
        (metadata, stream) = repository.read(
            output.artifact_hash, consumer_role=allowed_role
        )
        with stream:
            assert metadata == (len(b'{"forecast":1}'), "application/json")
            assert stream.read() == b'{"forecast":1}'

    (metadata, stream) = repository.read(output.artifact_hash)
    with stream:
        assert metadata == (len(b'{"forecast":1}'), "application/json")


def test_reading_agent_output_denied_matches_an_absent_hash(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    repository = ArtifactRepository(database, ArtifactStore(artifact_root))
    output = _publish(repository, b'{"forecast":1}')

    denied: Exception | None = None
    absent: Exception | None = None
    try:
        repository.read(output.artifact_hash, consumer_role="extract")
    except UnavailableInput as error:
        denied = error
    try:
        repository.read("e" * 64, consumer_role="extract")
    except UnavailableInput as error:
        absent = error
    assert denied is not None and absent is not None
    assert str(denied) == str(absent)
