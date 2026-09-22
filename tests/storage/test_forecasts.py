from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    canonical_loads,
    sha256_hex,
)
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.forecasts import seal_forecasts
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.submissions import SubmissionRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
QUESTION_A = "123e4567-e89b-42d3-a456-426614174000"
QUESTION_B = "123e4567-e89b-42d3-a456-426614174001"


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


class _Storage:
    def __init__(self, database: Database, artifact_root: Path) -> None:
        self.database = database
        self.store = ArtifactStore(artifact_root)
        kwargs = {
            "producer": PRODUCER,
            "config_hash": "c" * 64,
            "retention_policy_hash": "d" * 64,
        }
        self.artifacts = ArtifactRepository(database, self.store)
        self.sheets = SheetRepository(database, self.store, **kwargs)
        self.submissions = SubmissionRepository(database, self.store, **kwargs)

    def artifact(self, payload: bytes) -> str:
        digest = sha256_hex(payload)
        publication = self.artifacts.publish(
            [payload],
            expected_hash=digest,
            byte_length=len(payload),
            maximum_length=1024 * 1024,
            media_type="application/json",
            kind="study_evidence",
            input_hashes=(),
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            command_id=uuid4(),
        )
        return publication.manifest_hash

    def seal_sheet(
        self, question_ids: tuple[str, ...] = (QUESTION_A, QUESTION_B)
    ) -> tuple[str, dict[str, dict[str, Any]]]:
        response = self.sheets.execute(
            "seal",
            identity=identity(),
            payload={"questions": [question(item) for item in question_ids]},
        )
        sheet_hash = str(canonical_loads(response.body)["data"]["sheet_hash"])
        questions = {item: question(item) for item in question_ids}
        return sheet_hash, questions


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> _Storage:
    return _Storage(Database(postgres_dsn), artifact_root)


def test_seal_forecasts_accepts_a_claim_citing_only_retrieved_evidence(
    storage: _Storage,
) -> None:
    sheet_hash, questions = storage.seal_sheet()
    evidence = storage.artifact(b'{"evidence":1}')
    result = seal_forecasts(
        storage.submissions,
        identity=identity(),
        sheet_hash=sheet_hash,
        submitter_id=str(uuid4()),
        claims=[
            {
                "kind": "forecast",
                "question_id": QUESTION_A,
                "evidence_hashes": [evidence],
                "confidence": 0.6,
            }
        ],
        questions=questions,
        retrieved_evidence_ids=frozenset({evidence}),
    )
    data = dict(canonical_loads(result.body)["data"])
    assert data["accepted"] is True


def test_seal_forecasts_rejects_evidence_this_run_never_retrieved(
    storage: _Storage,
) -> None:
    sheet_hash, questions = storage.seal_sheet()
    evidence = storage.artifact(b'{"evidence":1}')
    with pytest.raises(ContractValidationError):
        seal_forecasts(
            storage.submissions,
            identity=identity(),
            sheet_hash=sheet_hash,
            submitter_id=str(uuid4()),
            claims=[
                {
                    "kind": "forecast",
                    "question_id": QUESTION_A,
                    "evidence_hashes": [evidence],
                    "confidence": 0.6,
                }
            ],
            questions=questions,
            retrieved_evidence_ids=frozenset(),
        )
    with storage.database.connect() as connection:
        count = connection.execute("SELECT count(*) FROM submissions").fetchone()
    assert count is not None and count[0] == 0


def test_seal_forecasts_rejects_a_question_this_runs_sheet_never_issued(
    storage: _Storage,
) -> None:
    sheet_hash, questions = storage.seal_sheet(question_ids=(QUESTION_A,))
    evidence = storage.artifact(b'{"evidence":1}')
    with pytest.raises(ContractValidationError):
        seal_forecasts(
            storage.submissions,
            identity=identity(),
            sheet_hash=sheet_hash,
            submitter_id=str(uuid4()),
            claims=[
                {
                    "kind": "forecast",
                    "question_id": QUESTION_B,
                    "evidence_hashes": [evidence],
                    "confidence": 0.6,
                }
            ],
            questions=questions,
            retrieved_evidence_ids=frozenset({evidence}),
        )


def test_seal_forecasts_seals_a_void_claim_without_requiring_evidence(
    storage: _Storage,
) -> None:
    sheet_hash, questions = storage.seal_sheet(question_ids=(QUESTION_A,))
    result = seal_forecasts(
        storage.submissions,
        identity=identity(),
        sheet_hash=sheet_hash,
        submitter_id=str(uuid4()),
        claims=[
            {
                "kind": "void",
                "question_id": QUESTION_A,
                "reason": "no resolver is registered for this target",
            }
        ],
        questions=questions,
        retrieved_evidence_ids=frozenset(),
    )
    data = dict(canonical_loads(result.body)["data"])
    assert data["accepted"] is True
