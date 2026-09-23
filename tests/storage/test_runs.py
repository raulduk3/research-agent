from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.runs import RunRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
QUESTION = {
    "question_id": "123e4567-e89b-42d3-a456-426614174000",
    "target_definition_hash": "a" * 64,
    "resolver_id": "citation-reach-v1",
    "resolver_version": 1,
    "horizon": "2027-09-01T00:00:00.000000Z",
}
BUDGETS = {
    "context_tokens": 8000,
    "generation_tokens": 2000,
    "tool_calls": 40,
    "deep_reads": 10,
    "images": 5,
    "timeout_seconds": 30,
    "retries": 2,
    "wall_time_seconds": 600,
    "spend_micros": 500_000,
}
MODEL_IDENTITY = {
    "agent_model_manifest": "a" * 64,
    "service_image_versions": {"reader": "b" * 64},
    "paper_card_manifest": "a" * 64,
    "prediction_head_bundles": {},
}


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class Storage:
    database: Database
    store: ArtifactStore
    artifacts: ArtifactRepository
    sheets: SheetRepository
    snapshots: SnapshotRepository
    runs: RunRepository

    def artifact(self, payload: bytes) -> str:
        digest = sha256_hex(payload)
        publication = self.artifacts.publish(
            [payload],
            expected_hash=digest,
            byte_length=len(payload),
            maximum_length=1024 * 1024,
            media_type="application/json",
            kind="manifest",
            input_hashes=(),
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            command_id=uuid4(),
        )
        return publication.manifest_hash

    def seal_sheet(self) -> str:
        response = self.sheets.execute(
            "seal", identity=identity(), payload={"questions": [QUESTION]}
        )
        return str(canonical_loads(response.body)["data"]["sheet_hash"])

    def seal_snapshot(self) -> str:
        paper_manifest = self.artifact(b'{"papers":["p1"]}')
        response = self.snapshots.execute(
            "seal",
            identity=identity(),
            payload={
                "paper_manifest_hash": paper_manifest,
                "index_identity_hashes": ["e" * 64],
            },
        )
        return str(canonical_loads(response.body)["data"]["snapshot_hash"])

    def create_run(
        self,
        *,
        sheet_hash: str,
        snapshot_hash: str,
        run_id: UUID | None = None,
        configuration_id: UUID | None = None,
        paper_id: str = "paper-0",
        issued_question_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        response = self.runs.execute(
            "create",
            identity=identity(),
            payload={
                "run_id": str(run_id or uuid4()),
                "slot": {
                    "batch_id": sheet_hash,
                    "paper_id": paper_id,
                    "configuration_id": str(configuration_id or uuid4()),
                    "attempt": 0,
                },
                "genome_hash": "f" * 64,
                "seed": 7,
                "snapshot_hash": snapshot_hash,
                "budgets": BUDGETS,
                "allowed_tools": ["query_cards", "submit"],
                "model_identity": MODEL_IDENTITY,
                "checkpoint_dates": [],
                "issued_question_ids": issued_question_ids or [],
            },
        )
        return dict(canonical_loads(response.body)["data"])

    def append_event(
        self, *, run_id: str, attempt: int, ordinal: int, kind: str
    ) -> dict[str, Any]:
        response = self.runs.execute(
            "append_event",
            identity=identity(),
            payload={
                "run_id": run_id,
                "attempt": attempt,
                "ordinal": ordinal,
                "kind": kind,
                "payload_hash": "1" * 64,
            },
        )
        return dict(canonical_loads(response.body)["data"])


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> Storage:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    kwargs = {
        "producer": PRODUCER,
        "config_hash": "c" * 64,
        "retention_policy_hash": "d" * 64,
    }
    return Storage(
        database,
        store,
        ArtifactRepository(database, store),
        SheetRepository(database, store, **kwargs),
        SnapshotRepository(database, store, **kwargs),
        RunRepository(database, store, **kwargs),
    )


def test_create_requires_a_sealed_sheet_and_snapshot(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    with pytest.raises(UnavailableInput):
        storage.create_run(sheet_hash="0" * 64, snapshot_hash=snapshot_hash)
    with pytest.raises(UnavailableInput):
        storage.create_run(sheet_hash=sheet_hash, snapshot_hash="0" * 64)
    created = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    assert UUID(created["run_id"])


def test_a_slot_may_only_be_assigned_to_one_run(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    configuration_id = uuid4()
    storage.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=configuration_id,
    )
    with pytest.raises(StateConflict):
        storage.create_run(
            sheet_hash=sheet_hash,
            snapshot_hash=snapshot_hash,
            configuration_id=configuration_id,
        )


def test_run_is_immutable_once_created(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    created = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        with storage.database.connect() as connection:
            connection.execute(
                "UPDATE runs SET seed=99 WHERE id=%s", (created["run_id"],)
            )


def test_events_must_append_in_order_and_name_a_known_run(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    created = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    run_id = created["run_id"]
    first = storage.append_event(run_id=run_id, attempt=1, ordinal=0, kind="request")
    assert first["ordinal"] == 0
    with pytest.raises(StateConflict):
        storage.append_event(run_id=run_id, attempt=1, ordinal=0, kind="response")
    with pytest.raises(StateConflict):
        storage.append_event(run_id=run_id, attempt=1, ordinal=2, kind="response")
    second = storage.append_event(run_id=run_id, attempt=1, ordinal=1, kind="response")
    assert second["ordinal"] == 1
    with pytest.raises(UnavailableInput):
        storage.append_event(run_id=str(uuid4()), attempt=1, ordinal=0, kind="request")
