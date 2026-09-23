from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "storage"))

from test_http import Jobs, _tls_material, server  # noqa: E402

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json, canonical_loads
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.client import StorageClient
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.queries import InspectorQueries
from research_agent.storage.runs import RunRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository
from research_agent.storage.submissions import SubmissionRepository
from research_agent.web.inspect.app import InspectorAppConfig, create_app

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
INSPECTOR_SCOPES = frozenset(
    {
        "runs:read",
        "submissions:read",
        "manifests:read",
        "configurations:read",
        "forecasts:read",
    }
)
PROFILE_HASH = "9" * 64
QUESTION_A = "123e4567-e89b-42d3-a456-426614174000"
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


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


class Seed:
    def __init__(
        self,
        artifacts: ArtifactRepository,
        sheets: SheetRepository,
        snapshots: SnapshotRepository,
        runs: RunRepository,
        submissions: SubmissionRepository,
        population: PopulationStore,
    ) -> None:
        self.artifacts = artifacts
        self.sheets = sheets
        self.snapshots = snapshots
        self.runs = runs
        self.submissions = submissions
        self.population = population

    def seed_genome(self, configuration_id: UUID, prompt: str) -> Genome:
        genome = Genome(
            lineage_id="lineage-1",
            island="quant-ph",
            infra_hash="b" * 64,
            emphasis={
                "prompt": prompt,
                "scan_policy": "breadth-first",
                "read_policy": "cite-first",
                "probability_assignment_rule": "single-sample",
            },
            founder=True,
        )
        self.population.record_seed(
            configuration_id=configuration_id,
            genome=genome,
            profile_hash=PROFILE_HASH,
            command_id=uuid4(),
        )
        return genome

    def seal_forecast(self, *, sheet_hash: str, submitter_id: UUID) -> None:
        evidence = self.artifact(b'{"evidence":1}', kind="study_evidence")
        self.submissions.execute(
            "submit",
            identity=identity(),
            payload={
                "sheet_hash": sheet_hash,
                "submitter_id": str(submitter_id),
                "claims": [
                    {
                        "kind": "forecast",
                        "question_id": QUESTION_A,
                        "evidence_hashes": [evidence],
                        "confidence": 0.6,
                    }
                ],
            },
        )

    def artifact(self, payload: bytes, *, kind: str = "manifest") -> str:
        publication = self.artifacts.publish(
            [payload],
            expected_hash=hashlib.sha256(payload).hexdigest(),
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

    def seal_sheet(self) -> str:
        response = self.sheets.execute(
            "seal",
            identity=identity(),
            payload={
                "questions": [
                    {
                        "question_id": QUESTION_A,
                        "target_definition_hash": "a" * 64,
                        "resolver_id": "citation-reach-v1",
                        "resolver_version": 1,
                        "horizon": "2027-09-01T00:00:00.000000Z",
                    }
                ]
            },
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
        configuration_id: UUID,
    ) -> str:
        response = self.runs.execute(
            "create",
            identity=identity(),
            payload={
                "run_id": str(uuid4()),
                "slot": {
                    "batch_id": sheet_hash,
                    "paper_id": "paper-0",
                    "configuration_id": str(configuration_id),
                    "attempt": 0,
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
        return str(canonical_loads(response.body)["data"]["run_id"])

    def submit(self, *, sheet_hash: str, submitter_id: UUID) -> None:
        self.submissions.execute(
            "submit",
            identity=identity(),
            payload={
                "sheet_hash": sheet_hash,
                "submitter_id": str(submitter_id),
                "claims": [
                    {
                        "kind": "void",
                        "question_id": QUESTION_A,
                        "reason": "no resolver",
                    }
                ],
            },
        )


@pytest.fixture
def seed(
    postgres_dsn: str, artifact_root: Path
) -> tuple[Seed, Database, ArtifactStore]:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    kwargs: dict[str, Any] = {
        "producer": PRODUCER,
        "config_hash": "c" * 64,
        "retention_policy_hash": "d" * 64,
    }
    return (
        Seed(
            ArtifactRepository(database, store),
            SheetRepository(database, store, **kwargs),
            SnapshotRepository(database, store, **kwargs),
            RunRepository(database, store, **kwargs),
            SubmissionRepository(database, store, **kwargs),
            PopulationStore(database, store, **kwargs),
        ),
        database,
        store,
    )


@pytest.fixture
def inspector_server(
    seed: tuple[Seed, Database, ArtifactStore], tmp_path: Path
) -> Iterator[tuple[tuple[str, int], Path]]:
    _, database, store = seed
    queries = InspectorQueries(database, store)
    tls = _tls_material(tmp_path)
    with server(
        Jobs(),
        tls,
        role="inspector",
        extra_scopes=INSPECTOR_SCOPES,
        queries=queries,
    ) as (address, _context, _wrong_context, _no_certificate_context):
        yield address, tmp_path


@pytest.fixture
def inspector_client(
    inspector_server: tuple[tuple[str, int], Path],
) -> TestClient:
    address, tmp_path = inspector_server
    storage = StorageClient(
        connect_host=address[0],
        port=address[1],
        server_hostname="localhost",
        ca_file=tmp_path / "ca.pem",
        client_cert_file=tmp_path / "client.pem",
        client_key_file=tmp_path / "client.key",
        scopes=INSPECTOR_SCOPES,
        timeout_seconds=5,
    )
    app = create_app(InspectorAppConfig(storage=storage))
    return TestClient(app, base_url="https://testserver")


def test_the_run_page_shows_stored_fields_events_and_its_own_submissions(
    seed: tuple[Seed, Database, ArtifactStore], inspector_client: TestClient
) -> None:
    fixture, _, _ = seed
    sheet_hash = fixture.seal_sheet()
    snapshot_hash = fixture.seal_snapshot()
    configuration_id = uuid4()
    run_id = fixture.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=configuration_id,
    )
    fixture.submit(sheet_hash=sheet_hash, submitter_id=UUID(run_id))

    response = inspector_client.get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert run_id in response.text
    assert str(configuration_id) in response.text
    assert "no resolver" in response.text


def test_the_run_page_404s_for_an_unknown_run(inspector_client: TestClient) -> None:
    response = inspector_client.get(f"/runs/{uuid4()}")
    assert response.status_code == 404


def test_the_agent_page_lists_only_its_configurations_runs(
    seed: tuple[Seed, Database, ArtifactStore], inspector_client: TestClient
) -> None:
    fixture, _, _ = seed
    sheet_hash = fixture.seal_sheet()
    snapshot_hash = fixture.seal_snapshot()
    configuration_id = uuid4()
    other_configuration_id = uuid4()
    run_id = fixture.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=configuration_id,
    )
    other_run_id = fixture.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=other_configuration_id,
    )

    response = inspector_client.get(f"/agents/{configuration_id}")

    assert response.status_code == 200
    assert "population record and resolutions: not yet stored" not in response.text
    assert "no population record for this configuration" in response.text
    assert run_id in response.text
    assert other_run_id not in response.text


def test_the_agent_page_shows_its_genome_and_a_pending_verdict(
    seed: tuple[Seed, Database, ArtifactStore], inspector_client: TestClient
) -> None:
    fixture, _, _ = seed
    sheet_hash = fixture.seal_sheet()
    snapshot_hash = fixture.seal_snapshot()
    configuration_id = uuid4()
    genome = fixture.seed_genome(configuration_id, "hypothesis-led reading")
    run_id = fixture.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        configuration_id=configuration_id,
    )
    fixture.seal_forecast(sheet_hash=sheet_hash, submitter_id=UUID(run_id))

    response = inspector_client.get(f"/agents/{configuration_id}")

    assert response.status_code == 200
    assert "population record and resolutions: not yet stored" not in response.text
    assert "no population record" not in response.text
    assert genome.configuration_hash in response.text
    assert "quant-ph" in response.text
    assert "hypothesis-led reading" in response.text
    assert f"seeded under profile {PROFILE_HASH}" in response.text
    assert QUESTION_A in response.text
    assert "pending until 2027-09-01T00:00:00.000000Z" in response.text
    assert "Brier contribution: not stored yet" in response.text


def test_the_population_page_lists_a_configuration_that_has_never_run(
    seed: tuple[Seed, Database, ArtifactStore], inspector_client: TestClient
) -> None:
    fixture, _, _ = seed
    configuration_id = uuid4()
    fixture.seed_genome(configuration_id, "never run")

    response = inspector_client.get("/agents")

    assert response.status_code == 200
    assert f'href="/agents/{configuration_id}"' in response.text
    assert "seeded" in response.text


def test_the_models_page_types_a_representation_manifest(
    seed: tuple[Seed, Database, ArtifactStore], inspector_client: TestClient
) -> None:
    fixture, _, _ = seed
    manifest_hash = fixture.artifact(canonical_json(REPRESENTATION_MANIFEST))

    response = inspector_client.get(f"/models/{manifest_hash}")

    assert response.status_code == 200
    assert "representation" in response.text
    assert "nomic-ai/modernbert-embed-base" in response.text


def test_the_models_page_404s_for_an_unknown_hash(inspector_client: TestClient) -> None:
    response = inspector_client.get(f"/models/{'0' * 64}")
    assert response.status_code == 404
