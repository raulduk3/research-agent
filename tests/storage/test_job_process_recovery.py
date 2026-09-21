"""A terminated storage process cannot lose or repeat committed checkpoint effects."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.contracts.jobs import JobCheckpoint
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.jobs import JobRepository

pytestmark = pytest.mark.integration


def test_killed_process_recovers_exact_checkpoint_with_new_epoch(
    postgres_dsn: str, artifact_root: Path
) -> None:
    producer = ProducerVersion("a" * 64, "b" * 40, 1)
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    artifacts = ArtifactRepository(database, store)
    jobs = JobRepository(
        database,
        store,
        producer=producer,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    raw = b'{"source":1}'
    admitted = artifacts.publish(
        [raw],
        expected_hash=sha256_hex(raw),
        byte_length=len(raw),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=producer,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    job_id, worker = uuid4(), uuid4()
    jobs.execute(
        "enqueue",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "job_id": str(job_id),
            "kind": "extract",
            "input_manifest": admitted.manifest_hash,
            "scheduled_at": "2020-01-01T00:00:00.000000Z",
        },
    )
    checkpoint_body = JobCheckpoint(
        1,
        str(job_id),
        "extract",
        (admitted.manifest_hash,),
        "c" * 64,
        (sha256_hex(b"unit-1"),),
        "unit-2",
        (),
    ).to_canonical_json()
    checkpoint = artifacts.publish(
        [checkpoint_body],
        expected_hash=sha256_hex(checkpoint_body),
        byte_length=len(checkpoint_body),
        maximum_length=4096,
        media_type="application/json",
        kind="manifest",
        input_hashes=(admitted.manifest_hash,),
        producer_version=producer,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    child = r"""
import os, sys, time
from pathlib import Path
from uuid import UUID, uuid4
from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.jobs import JobRepository
jobs = JobRepository(Database(os.environ['TEST_PROCESS_DSN']), ArtifactStore(Path(sys.argv[1])),
    producer=ProducerVersion('a'*64,'b'*40,1), config_hash='c'*64, retention_policy_hash='d'*64)
jobs.LEASE_SECONDS = 1
worker, job_id = UUID(sys.argv[2]), UUID(sys.argv[3])
claim = jobs.execute('claim', identity=CommandIdentity(worker,uuid4(),uuid4(),uuid4()),
    payload={'worker_id':str(worker),'kinds':['extract']})
lease = canonical_loads(claim.body)['data']['lease']
command = CommandIdentity(worker,UUID(sys.argv[5]),UUID(sys.argv[6]),UUID(sys.argv[7]))
reply = jobs.execute('checkpoint', identity=command, job_id=job_id,
    payload={'fence':{'worker_id':str(worker),'lease_epoch':lease['lease_epoch']},'checkpoint':sys.argv[4]})
print(reply.body.hex(), flush=True)
while True:
    time.sleep(1)
"""
    command = CommandIdentity(worker, uuid4(), uuid4(), uuid4())
    environment = {**os.environ, "TEST_PROCESS_DSN": postgres_dsn}
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child,
            str(artifact_root),
            str(worker),
            str(job_id),
            checkpoint.manifest_hash,
            str(command.key),
            str(command.command_id),
            str(command.request_id),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        # The checkpoint response is emitted only after PostgreSQL COMMIT.
        import selectors

        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=10), "checkpoint process did not commit"
        response = bytes.fromhex(process.stdout.readline().strip())
        assert response
        process.terminate()
        process.wait(timeout=5)
        time.sleep(1.1)
        replay = jobs.execute(
            "checkpoint",
            identity=command,
            job_id=job_id,
            payload={
                "fence": {"worker_id": str(worker), "lease_epoch": 1},
                "checkpoint": checkpoint.manifest_hash,
            },
        )
        assert replay.replayed and replay.body == response
        successor = uuid4()
        resumed = jobs.execute(
            "claim",
            identity=CommandIdentity(successor, uuid4(), uuid4(), uuid4()),
            payload={"worker_id": str(successor), "kinds": ["extract"]},
        )
        lease = canonical_loads(resumed.body)["data"]["lease"]
        assert (
            lease["lease_epoch"] == 2
            and lease["checkpoint"] == checkpoint.manifest_hash
        )
        assert UUID(lease["job_id"]) == job_id
        with database.connect() as connection:
            assert connection.execute(
                "SELECT count(*) FROM job_checkpoints"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT status,duration_complete FROM job_attempts WHERE lease_epoch=1"
            ).fetchone() == ("expired", False)
            verified = jobs._verifier.verify(connection, lease["checkpoint"])
        with store.open_verified(verified.raw_hash) as stream:
            restored = JobCheckpoint.from_json(stream.read())
        assert restored.completed_work_keys == (sha256_hex(b"unit-1"),)
        assert restored.continuation_cursor == "unit-2"
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
