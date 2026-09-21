from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.authorization import JobScope, StorageAuthorization
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.jobs import JobRepository

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def _identity(principal=None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


def test_job_scope_resolves_exact_producing_dag_and_preserves_exact_replay(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    artifacts = ArtifactRepository(database, store)
    raw = b'{"admitted":1}'
    publication = artifacts.publish(
        [raw],
        expected_hash=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    jobs = JobRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    job_id, worker = uuid4(), uuid4()
    jobs.execute(
        "enqueue",
        identity=_identity(),
        payload={
            "job_id": str(job_id),
            "kind": "extract",
            "input_manifest": publication.manifest_hash,
            "scheduled_at": (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        },
    )
    jobs.execute(
        "claim",
        identity=_identity(worker),
        payload={"worker_id": str(worker), "kinds": ["extract"]},
    )
    authorization, scope = StorageAuthorization(database), JobScope(job_id, 1)
    assert authorization.job_scope_active(
        principal_id=worker, role_kinds=frozenset({"extract"}), scope=scope
    )
    assert not authorization.job_scope_active(
        principal_id=worker, role_kinds=frozenset({"fit"}), scope=scope
    )
    assert authorization.artifact_in_job_scope(
        principal_id=worker,
        role_kinds=frozenset({"extract"}),
        scope=scope,
        artifact_hash=publication.manifest_hash,
    )
    assert authorization.artifact_in_job_scope(
        principal_id=worker,
        role_kinds=frozenset({"extract"}),
        scope=scope,
        artifact_hash=publication.artifact_hash,
    )
    assert not authorization.artifact_in_job_scope(
        principal_id=worker,
        role_kinds=frozenset({"fit"}),
        scope=scope,
        artifact_hash=publication.artifact_hash,
    )

    renewal = _identity(worker)
    jobs.execute(
        "renew",
        identity=renewal,
        job_id=job_id,
        payload={"worker_id": str(worker), "lease_epoch": 1},
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
            (job_id,),
        )
    assert authorization.job_fence_allowed(
        principal_id=worker,
        role_kinds=frozenset({"extract"}),
        job_id=job_id,
        lease_epoch=1,
        command_id=renewal.command_id,
        idempotency_key=renewal.key,
    )
    assert not authorization.job_fence_allowed(
        principal_id=worker,
        role_kinds=frozenset({"fit"}),
        job_id=job_id,
        lease_epoch=1,
        command_id=renewal.command_id,
        idempotency_key=renewal.key,
    )
    fresh = _identity(worker)
    assert not authorization.job_fence_allowed(
        principal_id=worker,
        role_kinds=frozenset({"extract"}),
        job_id=job_id,
        lease_epoch=1,
        command_id=fresh.command_id,
        idempotency_key=fresh.key,
    )
