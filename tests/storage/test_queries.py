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
from research_agent.evolution.admission import AdmissionResult
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.orchestration.selection import ArchivedGenome, SelectionEvent
from research_agent.storage.errors import UnavailableInput
from research_agent.storage.queries import InspectorQueries
from research_agent.storage.resolutions import ResolutionRepository
from research_agent.storage.runs import RunRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository
from research_agent.storage.submissions import SubmissionRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
QUESTION_A = "123e4567-e89b-42d3-a456-426614174000"
QUESTION_B = "123e4567-e89b-42d3-a456-426614174001"
PAST_HORIZON = "2020-01-01T00:00:00.000000Z"
PROFILE_HASH = "9" * 64
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


def question(
    question_id: str, horizon: str = "2027-09-01T00:00:00.000000Z"
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "target_definition_hash": "a" * 64,
        "resolver_id": "citation-reach-v1",
        "resolver_version": 1,
        "horizon": horizon,
    }


def genome(lineage_id: str, *, parent_hash: str | None = None) -> Genome:
    return Genome(
        lineage_id=lineage_id,
        island="cs",
        infra_hash="b" * 64,
        emphasis={
            "prompt": f"evidence-first-{lineage_id}-{parent_hash is not None}",
            "scan_policy": "breadth-first",
            "read_policy": "cite-first",
            "probability_assignment_rule": "single-sample",
        },
        founder=parent_hash is None,
        parent_hash=parent_hash,
    )


@dataclass
class Storage:
    database: Database
    store: ArtifactStore
    artifacts: ArtifactRepository
    sheets: SheetRepository
    snapshots: SnapshotRepository
    runs: RunRepository
    submissions: SubmissionRepository
    resolutions: ResolutionRepository
    population: PopulationStore
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
        self,
        question_ids: tuple[str, ...] = (QUESTION_A, QUESTION_B),
        horizon: str = "2027-09-01T00:00:00.000000Z",
    ) -> str:
        response = self.sheets.execute(
            "seal",
            identity=identity(),
            payload={"questions": [question(item, horizon) for item in question_ids]},
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
        paper_id: str = "paper-0",
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
        ResolutionRepository(database, store, **kwargs),
        PopulationStore(database, store, **kwargs),
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


def test_run_specification_is_what_the_tool_service_applies(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    run_id = storage.create_run(
        sheet_hash=sheet_hash, snapshot_hash=snapshot_hash, paper_id="paper-7"
    )["run_id"]

    active = storage.inspector.run_specification(run_id)
    storage.runs.finish_without_submit(
        identity=identity(), payload={"run_id": run_id, "reason": "model_stopped"}
    )
    ended = storage.inspector.run_specification(run_id)

    assert active == {
        "run_id": run_id,
        "snapshot_hash": snapshot_hash,
        "allowed_tools": ["query_cards", "submit"],
        "paper_id": "paper-7",
        "issued_question_ids": [],
        "active": True,
    }
    # A run holding a terminal state admits no further tool call.
    assert ended == {**active, "active": False}
    assert storage.inspector.run_specification(str(uuid4())) is None


def test_run_worker_carries_the_stored_run_and_its_genome_prompt(
    storage: Storage,
) -> None:
    configuration_id = uuid4()
    founder = genome("lineage-1")
    storage.population.record_seed(
        configuration_id=configuration_id,
        genome=founder,
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    run_id = storage.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=configuration_id,
        attempt=2,
        paper_id="paper-7",
    )["run_id"]
    promptless = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)

    assert storage.inspector.run_worker(run_id) == {
        "run_id": run_id,
        "configuration_id": str(configuration_id),
        "attempt": 2,
        "genome_hash": "f" * 64,
        "snapshot_hash": snapshot_hash,
        "budgets": BUDGETS,
        "allowed_tools": ["query_cards", "submit"],
        "paper_id": "paper-7",
        "issued_question_ids": [],
        "prompt": founder.emphasis["prompt"],
    }
    # A run whose configuration names no stored genome has no prompt to run.
    with pytest.raises(UnavailableInput):
        storage.inspector.run_worker(promptless["run_id"])
    assert storage.inspector.run_worker(str(uuid4())) is None


def test_snapshot_describes_its_seal_pinned_families_and_sheets(
    storage: Storage,
) -> None:
    snapshot_hash = storage.seal_snapshot()
    empty = storage.inspector.snapshot(snapshot_hash)
    card = storage.artifact(b'{"card":1}')
    family = str(uuid4())
    sheets = sorted(
        storage.seal_sheet(question_ids=(question_id,))
        for question_id in (QUESTION_A, QUESTION_B)
    )
    for sheet_hash, version in zip(sheets, (uuid4(), uuid4())):
        storage.snapshots.execute(
            "pin_items",
            identity=identity(),
            payload={
                "snapshot_hash": snapshot_hash,
                "sheet_hash": sheet_hash,
                "items": [
                    {
                        "paper_family_id": family,
                        "paper_version_id": str(version),
                        "card_hash": card,
                        "overview_hash": None,
                        "passage_index_hash": None,
                        "graph_hash": None,
                    }
                ],
            },
        )
    other_family = {
        "paper_family_id": str(uuid4()),
        "paper_version_id": str(uuid4()),
        "card_hash": card,
        "overview_hash": None,
        "passage_index_hash": None,
        "graph_hash": None,
    }
    storage.snapshots.execute(
        "pin_items",
        identity=identity(),
        payload={
            "snapshot_hash": snapshot_hash,
            "sheet_hash": sheets[0],
            "items": [other_family],
        },
    )

    described = storage.inspector.snapshot(snapshot_hash)

    assert empty is not None
    assert empty["pinned_family_count"] == 0 and empty["sheet_hashes"] == []
    # Two versions of one family count once.
    assert described == {
        "snapshot_hash": snapshot_hash,
        "sealed_at": empty["sealed_at"],
        "pinned_family_count": 2,
        "sheet_hashes": sheets,
    }
    assert storage.inspector.snapshot("0" * 64) is None


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


def test_runs_by_batch_return_every_configuration_of_one_batch_only(
    storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries_module, "PAGE_SIZE", 2)
    sheet_hash = storage.seal_sheet()
    other_sheet = storage.seal_sheet((QUESTION_A,))
    snapshot_hash = storage.seal_snapshot()
    run_ids = [
        storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)["run_id"]
        for _ in range(3)
    ]
    storage.create_run(sheet_hash=other_sheet, snapshot_hash=snapshot_hash)

    first_page, next_cursor = storage.inspector.runs_by_batch(sheet_hash, cursor=None)
    second_page, final_cursor = storage.inspector.runs_by_batch(
        sheet_hash, cursor=next_cursor
    )

    assert [run["run_id"] for run in first_page + second_page] == list(
        reversed(run_ids)
    )
    assert {run["batch_id"] for run in first_page + second_page} == {sheet_hash}
    assert len({run["configuration_id"] for run in first_page + second_page}) == 3
    assert final_cursor is None


def test_runs_by_batch_is_an_empty_page_for_a_batch_with_no_runs(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    assert storage.inspector.runs_by_batch(sheet_hash, cursor=None) == ((), None)
    assert storage.inspector.runs_by_batch("0" * 64, cursor=None) == ((), None)


def test_runs_by_paper_return_only_the_runs_that_read_that_paper(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    read = storage.create_run(
        sheet_hash=sheet_hash, snapshot_hash=snapshot_hash, paper_id="paper-1"
    )
    storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)

    runs, cursor = storage.inspector.runs_by_paper("paper-1", cursor=None)

    assert [run["run_id"] for run in runs] == [read["run_id"]]
    assert runs[0]["paper_id"] == "paper-1"
    assert cursor is None
    assert storage.inspector.runs_by_paper("paper-9", cursor=None) == ((), None)


def test_sheet_returns_its_sealed_questions_in_order(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet((QUESTION_B, QUESTION_A))

    sheet = storage.inspector.sheet(sheet_hash)

    assert sheet is not None
    assert sheet["sheet_hash"] == sheet_hash
    assert sheet["questions"] == [question(QUESTION_B), question(QUESTION_A)]
    assert storage.inspector.sheet("0" * 64) is None


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


def test_configurations_enumerate_a_genome_that_has_never_run(
    storage: Storage,
) -> None:
    configuration_id = uuid4()
    founder = genome("lineage-1")
    storage.population.record_seed(
        configuration_id=configuration_id,
        genome=founder,
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )

    listing, cursor = storage.inspector.configurations(cursor=None)
    configuration = storage.inspector.configuration(str(configuration_id))

    assert [item["configuration_id"] for item in listing] == [str(configuration_id)]
    assert cursor is None
    assert configuration == listing[0]
    assert configuration["configuration_hash"] == founder.configuration_hash
    assert configuration["island"] == "cs"
    assert configuration["lineage_id"] == "lineage-1"
    assert configuration["founder"] is True
    assert configuration["parent_hash"] is None
    assert configuration["admission"] == {
        "disposition": "seeded",
        "profile_hash": PROFILE_HASH,
    }
    assert configuration["archive"] is None
    assert {part["part"]: part["value"] for part in configuration["parts"]} == dict(
        founder.emphasis
    )
    assert all(
        part["value_hash"] == sha256_hex(part["value"].encode("utf-8"))
        for part in configuration["parts"]
    )
    runs, _ = storage.inspector.runs_by_configuration(
        str(configuration_id), cursor=None
    )
    assert runs == ()


def test_configuration_is_none_for_an_unknown_id(storage: Storage) -> None:
    assert storage.inspector.configuration(str(uuid4())) is None


def test_configuration_carries_its_admission_and_archive_as_stored(
    storage: Storage,
) -> None:
    parent_id, child_id = uuid4(), uuid4()
    parent = genome("lineage-1")
    child = genome("lineage-1", parent_hash=parent.configuration_hash)
    storage.population.record_seed(
        configuration_id=parent_id,
        genome=parent,
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    storage.population.record_child(
        configuration_id=child_id,
        child=child,
        admission=AdmissionResult("accepted", PROFILE_HASH, child.configuration_hash),
        command_id=uuid4(),
    )
    storage.population.record_archive(
        SelectionEvent(
            cycle_id="cycle-3",
            profile_hash=PROFILE_HASH,
            disposition="selected",
            results={},
            archived=(
                ArchivedGenome(parent.configuration_hash, "cs", "lineage-1", 0.25, 31),
            ),
        ),
        command_id=uuid4(),
    )

    stored_parent = storage.inspector.configuration(str(parent_id))
    stored_child = storage.inspector.configuration(str(child_id))

    assert stored_parent is not None and stored_child is not None
    assert stored_parent["archive"]["cycle_id"] == "cycle-3"
    assert stored_parent["archive"]["skill"] == 0.25
    assert stored_parent["archive"]["resolved_claim_count"] == 31
    assert stored_child["archive"] is None
    assert stored_child["parent_hash"] == parent.configuration_hash
    assert stored_child["admission"]["disposition"] == "accepted"


def test_configurations_are_newest_first_and_cursor_paginated(
    storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries_module, "PAGE_SIZE", 2)
    configuration_ids = [uuid4() for _ in range(3)]
    for index, configuration_id in enumerate(configuration_ids):
        storage.population.record_seed(
            configuration_id=configuration_id,
            genome=genome(f"lineage-{index}"),
            profile_hash=PROFILE_HASH,
            command_id=uuid4(),
        )
    newest_first = [str(item) for item in reversed(configuration_ids)]

    first_page, next_cursor = storage.inspector.configurations(cursor=None)
    assert [item["configuration_id"] for item in first_page] == newest_first[:2]
    assert next_cursor is not None

    second_page, final_cursor = storage.inspector.configurations(cursor=next_cursor)
    assert [item["configuration_id"] for item in second_page] == newest_first[2:]
    assert final_cursor is None


def test_forecasts_pair_sealed_claims_with_their_latest_resolution(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet(horizon=PAST_HORIZON)
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}', kind="study_evidence")
    configuration_id = uuid4()
    run = storage.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=configuration_id,
    )
    other_run = storage.create_run(
        sheet_hash=sheet_hash, snapshot_hash=snapshot_hash, attempt=1
    )
    claims = [
        {
            "kind": "forecast",
            "question_id": item,
            "evidence_hashes": [evidence],
            "confidence": 0.6,
        }
        for item in (QUESTION_A, QUESTION_B)
    ]
    storage.submit(
        sheet_hash=sheet_hash, submitter_id=UUID(run["run_id"]), claims=claims
    )
    storage.submit(
        sheet_hash=sheet_hash, submitter_id=UUID(other_run["run_id"]), claims=claims
    )
    sealed = {
        item["question_id"]: item["submission_id"]
        for item in storage.inspector.submissions_by_submitter(run["run_id"])
    }
    first = storage.resolutions.execute(
        "append",
        identity=identity(),
        payload=_unresolvable(sealed[QUESTION_A], QUESTION_A),
    )
    first_id = canonical_loads(first.body)["data"]["resolution_id"]
    storage.resolutions.execute(
        "append",
        identity=identity(),
        payload=_unresolvable(
            sealed[QUESTION_A], QUESTION_A, version=2, supersedes=first_id
        ),
    )

    forecasts, cursor = storage.inspector.forecasts_by_configuration(
        str(configuration_id), cursor=None
    )

    assert cursor is None
    by_question = {item["question_id"]: item for item in forecasts}
    assert set(by_question) == {QUESTION_A, QUESTION_B}
    assert {item["run_id"] for item in forecasts} == {run["run_id"]}
    resolved = by_question[QUESTION_A]
    assert resolved["submission_id"] == sealed[QUESTION_A]
    assert resolved["resolution"]["resolution_version"] == 2
    assert resolved["resolution"]["status"] == "unresolvable"
    assert resolved["resolution"]["resolver_id"] == "citation-reach-v1"
    assert resolved["resolution"]["resolver_build_digest"] == "e" * 64
    assert resolved["resolver_version"] == 1
    pending = by_question[QUESTION_B]
    assert pending["resolution"] is None
    assert pending["horizon"] == PAST_HORIZON
    assert pending["confidence"] == 0.6


def test_forecasts_are_cursor_paginated(
    storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries_module, "PAGE_SIZE", 1)
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}', kind="study_evidence")
    configuration_id = uuid4()
    run = storage.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=configuration_id,
    )
    storage.submit(
        sheet_hash=sheet_hash,
        submitter_id=UUID(run["run_id"]),
        claims=[
            {
                "kind": "forecast",
                "question_id": item,
                "evidence_hashes": [evidence],
                "confidence": 0.6,
            }
            for item in (QUESTION_A, QUESTION_B)
        ],
    )

    first_page, next_cursor = storage.inspector.forecasts_by_configuration(
        str(configuration_id), cursor=None
    )
    assert len(first_page) == 1 and next_cursor is not None
    second_page, final_cursor = storage.inspector.forecasts_by_configuration(
        str(configuration_id), cursor=next_cursor
    )
    assert len(second_page) == 1 and final_cursor is None
    assert {first_page[0]["question_id"], second_page[0]["question_id"]} == {
        QUESTION_A,
        QUESTION_B,
    }


def _unresolvable(
    forecast_id: str,
    question_id: str,
    *,
    version: int = 1,
    supersedes: str | None = None,
) -> dict[str, Any]:
    return {
        "forecast_id": forecast_id,
        "question_id": question_id,
        "as_of": "2020-06-01T00:00:00.000000Z",
        "resolver_id": "citation-reach-v1",
        "resolver_build_digest": "e" * 64,
        "target_definition_hash": "a" * 64,
        "observation_protocol_version": 1,
        "observation_hash": "f" * 64,
        "status": "unresolvable",
        "witness_ids": [],
        "completion_proof_hash": None,
        "lower_bound": 0,
        "upper_bound": None,
        "reason": "incomplete_capture",
        "resolution_version": version,
        "supersedes_resolution_id": supersedes,
    }
