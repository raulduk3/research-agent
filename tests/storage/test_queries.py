from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import (
    ProducerVersion,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.storage import queries as queries_module
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput
from research_agent.storage.queries import InspectorQueries
from research_agent.storage.runs import RunRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository
from research_agent.storage.submissions import SubmissionRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
QUESTION_A = "123e4567-e89b-42d3-a456-426614174000"
QUESTION_B = "123e4567-e89b-42d3-a456-426614174001"
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
REPRESENTATION_MANIFEST = {
    "model_id": "nomic-ai/modernbert-embed-base",
    "revision": "d" * 40,
    "checkpoint_date": "2026-09-21",
    "dtype": "float32",
    "dimension": 768,
    "pooling": "attention_masked_mean",
    "document_prefix": "search_document: ",
    "query_prefix": "search_query: ",
    "max_model_tokens": 8192,
    "tokenizer_hash": "a" * 64,
    "weight_hash": "b" * 64,
    "qualified": True,
}
DEPLOYMENT_MANIFEST = {
    "provider": "zai",
    "model_id": "glm-5.3-flash",
    "endpoint": "https://example.invalid/v1",
    "revision": "unpinned",
    "qualified": True,
}


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


def question(question_id: str) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "target_definition_hash": "a" * 64,
        "resolver_id": "citation-reach-v1",
        "resolver_version": 1,
        "horizon": "2027-09-01T00:00:00.000000Z",
    }


@dataclass
class Storage:
    database: Database
    store: ArtifactStore
    artifacts: ArtifactRepository
    sheets: SheetRepository
    snapshots: SnapshotRepository
    runs: RunRepository
    submissions: SubmissionRepository
    inspector: InspectorQueries

    def artifact(self, payload: bytes, *, kind: str = "manifest") -> str:
        digest = sha256_hex(payload)
        publication = self.artifacts.publish(
            [payload],
            expected_hash=digest,
            byte_length=len(payload),
            maximum_length=1024 * 1024,
            media_type="application/json",
            kind=kind,
            input_hashes=(),
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            command_id=uuid4(),
        )
        return publication.manifest_hash

    def seal_sheet(
        self, question_ids: tuple[str, ...] = (QUESTION_A, QUESTION_B)
    ) -> str:
        response = self.sheets.execute(
            "seal",
            identity=identity(),
            payload={"questions": [question(item) for item in question_ids]},
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
        attempt: int = 0,
    ) -> dict[str, Any]:
        response = self.runs.execute(
            "create",
            identity=identity(),
            payload={
                "run_id": str(run_id or uuid4()),
                "slot": {
                    "batch_id": sheet_hash,
                    "paper_id": "paper-0",
                    "configuration_id": str(configuration_id or uuid4()),
                    "attempt": attempt,
                },
                "genome_hash": "f" * 64,
                "seed": 7,
                "snapshot_hash": snapshot_hash,
                "budgets": BUDGETS,
                "allowed_tools": ["query_cards", "submit"],
                "model_identity": MODEL_IDENTITY,
                "checkpoint_dates": [],
                "issued_question_ids": [],
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

    def submit(
        self, *, sheet_hash: str, submitter_id: UUID, claims: list[dict[str, Any]]
    ) -> dict[str, Any]:
        response = self.submissions.execute(
            "submit",
            identity=identity(),
            payload={
                "sheet_hash": sheet_hash,
                "submitter_id": str(submitter_id),
                "claims": claims,
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
        SubmissionRepository(database, store, **kwargs),
        InspectorQueries(database, store),
    )


def test_run_returns_none_for_an_unknown_run(storage: Storage) -> None:
    assert storage.inspector.run(str(uuid4())) is None


def test_run_returns_stored_fields_and_events_in_ordinal_order(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    created = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    run_id = created["run_id"]
    storage.append_event(run_id=run_id, attempt=1, ordinal=0, kind="request")
    storage.append_event(run_id=run_id, attempt=1, ordinal=1, kind="response")

    run = storage.inspector.run(run_id)

    assert run is not None
    assert run["run_id"] == run_id
    assert run["paper_id"] == "paper-0"
    assert run["seed"] == 7
    assert run["budgets"] == BUDGETS
    assert run["model_identity"] == MODEL_IDENTITY
    assert [event["ordinal"] for event in run["events"]] == [0, 1]
    assert [event["kind"] for event in run["events"]] == ["request", "response"]


def test_runs_by_configuration_are_newest_first_and_cursor_paginated(
    storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries_module, "PAGE_SIZE", 2)
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    configuration_id = uuid4()
    created = [
        storage.create_run(
            sheet_hash=sheet_hash,
            snapshot_hash=snapshot_hash,
            configuration_id=configuration_id,
            attempt=attempt,
        )
        for attempt in range(3)
    ]
    run_ids = [entry["run_id"] for entry in created]

    first_page, next_cursor = storage.inspector.runs_by_configuration(
        str(configuration_id), cursor=None
    )
    assert [run["run_id"] for run in first_page] == list(reversed(run_ids))[:2]
    assert next_cursor is not None

    second_page, final_cursor = storage.inspector.runs_by_configuration(
        str(configuration_id), cursor=next_cursor
    )
    assert [run["run_id"] for run in second_page] == list(reversed(run_ids))[2:]
    assert final_cursor is None


def test_runs_by_configuration_excludes_other_configurations(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    configuration_id = uuid4()
    storage.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=uuid4(),
    )
    runs, cursor = storage.inspector.runs_by_configuration(
        str(configuration_id), cursor=None
    )
    assert runs == ()
    assert cursor is None


def test_submissions_by_submitter_carry_claims_and_evidence_as_stored(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    evidence = storage.artifact(b'{"evidence":1}', kind="study_evidence")
    submitter_id = uuid4()
    storage.submit(
        sheet_hash=sheet_hash,
        submitter_id=submitter_id,
        claims=[
            {
                "kind": "forecast",
                "question_id": QUESTION_A,
                "evidence_hashes": [evidence],
                "confidence": 0.6,
            },
            {"kind": "void", "question_id": QUESTION_B, "reason": "no resolver"},
        ],
    )

    submissions = storage.inspector.submissions_by_submitter(str(submitter_id))

    assert len(submissions) == 2
    sealed = next(item for item in submissions if item["status"] == "sealed")
    void = next(item for item in submissions if item["status"] == "void")
    assert sealed["confidence"] == 0.6
    assert sealed["evidence_hashes"] == [evidence]
    assert void["reason"] == "no resolver"
    assert void["evidence_hashes"] == []


def test_submissions_by_submitter_is_empty_for_an_unknown_submitter(
    storage: Storage,
) -> None:
    assert storage.inspector.submissions_by_submitter(str(uuid4())) == ()


def test_manifest_returns_none_for_an_unknown_hash(storage: Storage) -> None:
    assert storage.inspector.manifest("0" * 64) is None


def test_manifest_types_a_representation_manifest(storage: Storage) -> None:
    payload = canonical_json(REPRESENTATION_MANIFEST)
    manifest_hash = storage.artifact(payload)

    manifest = storage.inspector.manifest(manifest_hash)

    assert manifest is not None
    assert manifest["manifest_kind"] == "representation"
    assert manifest["fields"] == REPRESENTATION_MANIFEST
    assert manifest["manifest_hash"] == manifest_hash
    assert manifest["artifact_hash"] == sha256_hex(payload)


def test_manifest_types_a_deployment_manifest(storage: Storage) -> None:
    payload = canonical_json(DEPLOYMENT_MANIFEST)
    manifest_hash = storage.artifact(payload)

    manifest = storage.inspector.manifest(manifest_hash)

    assert manifest is not None
    assert manifest["manifest_kind"] == "deployment"
    assert manifest["fields"] == DEPLOYMENT_MANIFEST


def test_manifest_marks_an_unrecognized_shape_unknown(storage: Storage) -> None:
    manifest_hash = storage.artifact(b'{"unexpected_field":1}')

    manifest = storage.inspector.manifest(manifest_hash)

    assert manifest is not None
    assert manifest["manifest_kind"] == "unknown"
    assert manifest["fields"] == {"unexpected_field": 1}


def test_manifest_ignores_a_non_manifest_artifact_kind(storage: Storage) -> None:
    evidence_hash = storage.artifact(b'{"unexpected_field":1}', kind="study_evidence")
    assert storage.inspector.manifest(evidence_hash) is None


def test_manifest_refuses_a_blob_over_the_inspector_size_bound(
    storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries_module, "MAXIMUM_MANIFEST_BYTES", 4)
    manifest_hash = storage.artifact(b'{"unexpected_field":1}')

    with pytest.raises(UnavailableInput):
        storage.inspector.manifest(manifest_hash)
