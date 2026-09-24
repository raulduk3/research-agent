from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.contracts.jobs import JOB_KINDS
from research_agent.contracts.primitives import ContractValidationError
from research_agent.orchestration.scheduler import WorkScheduler
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.jobs import (
    FOREGROUND_JOB_KINDS,
    HEAVY_JOB_KINDS,
    JobRepository,
)

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def test_every_job_kind_belongs_to_exactly_one_lane() -> None:
    assert FOREGROUND_JOB_KINDS | HEAVY_JOB_KINDS == JOB_KINDS
    assert not FOREGROUND_JOB_KINDS & HEAVY_JOB_KINDS
    scheduler = WorkScheduler()
    assert {scheduler.lane_of(kind) for kind in FOREGROUND_JOB_KINDS} == {"foreground"}
    assert {scheduler.lane_of(kind) for kind in HEAVY_JOB_KINDS} == {"heavy"}
    with pytest.raises(ContractValidationError):
        scheduler.lane_of("unknown")


def test_a_heavy_job_cannot_take_a_foreground_lane() -> None:
    scheduler = WorkScheduler()
    assert scheduler.admit(uuid4(), "fit") == "admitted"
    assert scheduler.admit(uuid4(), "embed") == "lane_full"
    # Both foreground lanes are still free after the heavy lane filled.
    assert scheduler.admit(uuid4(), "capture") == "admitted"
    assert scheduler.admit(uuid4(), "predict") == "admitted"
    assert scheduler.admit(uuid4(), "score") == "lane_full"


def test_pause_hysteresis_follows_the_policy_thresholds() -> None:
    scheduler = WorkScheduler()
    assert not scheduler.observe_foreground_memory(48.0)
    assert scheduler.observe_foreground_memory(48.5)
    assert scheduler.observe_foreground_memory(44.0)
    assert scheduler.observe_foreground_memory(40.0)
    assert not scheduler.observe_foreground_memory(39.9)


def test_release_frees_only_the_lane_the_job_held() -> None:
    scheduler = WorkScheduler()
    heavy, foreground = uuid4(), uuid4()
    scheduler.admit(heavy, "fit")
    scheduler.admit(foreground, "capture")
    scheduler.release(heavy)
    assert scheduler.admit(uuid4(), "label") == "admitted"
    with pytest.raises(ContractValidationError):
        scheduler.release(uuid4())
    with pytest.raises(ContractValidationError):
        scheduler.admit(foreground, "capture")


# -- real jobs ------------------------------------------------------------


@dataclass
class Storage:
    artifacts: ArtifactRepository
    jobs: JobRepository
    sequence: int = 0

    def enqueue(self, kind: str) -> UUID:
        job_id = uuid4()
        self.sequence += 1
        digest = sha256_hex(kind.encode() + job_id.bytes)
        manifest = self.artifacts.publish(
            [kind.encode() + job_id.bytes],
            expected_hash=digest,
            byte_length=len(kind) + 16,
            maximum_length=1024,
            media_type="application/json",
            kind="manifest",
            input_hashes=(),
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            command_id=uuid4(),
        ).manifest_hash
        self.command(
            "enqueue",
            {
                "job_id": str(job_id),
                "kind": kind,
                "input_manifest": manifest,
                "scheduled_at": f"2020-01-01T00:00:{self.sequence:02d}.000000Z",
            },
        )
        return job_id

    def command(
        self, operation: str, payload: object, principal: UUID | None = None
    ) -> dict[str, Any]:
        principal = principal or uuid4()
        identity = CommandIdentity(principal, uuid4(), uuid4(), uuid4())
        response = self.jobs.execute(operation, identity=identity, payload=payload)
        return dict(canonical_loads(response.body)["data"])

    def claim_through(self, scheduler: WorkScheduler) -> dict[str, Any] | None:
        kinds = scheduler.claimable_kinds()
        if not kinds:
            return None
        worker = uuid4()
        lease = self.command(
            "claim", {"worker_id": str(worker), "kinds": list(kinds)}, worker
        )["lease"]
        if lease is None:
            return None
        decision = scheduler.admit(UUID(lease["job_id"]), lease["kind"])
        assert decision == "admitted"
        return dict(lease)


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> Storage:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    return Storage(
        ArtifactRepository(database, store),
        JobRepository(
            database,
            store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
    )


@pytest.mark.integration
def test_foreground_jobs_run_beside_a_heavy_job_and_a_pause(storage: Storage) -> None:
    scheduler = WorkScheduler()
    heavy = [storage.enqueue("fit"), storage.enqueue("embed")]
    foreground = [storage.enqueue(kind) for kind in ("capture", "predict", "score")]

    first = storage.claim_through(scheduler)
    assert first is not None and first["job_id"] == str(heavy[0])
    # The heavy lane is full: a second heavy job is never offered to a claim.
    assert not set(scheduler.claimable_kinds()) & HEAVY_JOB_KINDS

    # Memory pressure pauses heavy admission; foreground claims continue.
    assert scheduler.observe_foreground_memory(50.0)
    started = [storage.claim_through(scheduler), storage.claim_through(scheduler)]
    assert [lease["job_id"] for lease in started if lease] == [
        str(foreground[0]),
        str(foreground[1]),
    ]
    # Both foreground lanes are full and heavy is paused: nothing more is claimable.
    assert scheduler.claimable_kinds() == ()
    assert storage.claim_through(scheduler) is None

    # Finishing the heavy job frees its lane, but the pause still holds it back.
    scheduler.release(UUID(first["job_id"]))
    assert not set(scheduler.claimable_kinds()) & HEAVY_JOB_KINDS
    scheduler.release(UUID(started[0]["job_id"]))
    third = storage.claim_through(scheduler)
    assert third is not None and third["job_id"] == str(foreground[2])

    # Resume: the queued heavy job is claimable again.
    assert not scheduler.observe_foreground_memory(39.0)
    resumed = storage.claim_through(scheduler)
    assert resumed is not None and resumed["job_id"] == str(heavy[1])
