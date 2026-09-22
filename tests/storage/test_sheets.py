from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads
from research_agent.contracts.questions import sheet_identity
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.sheets import SheetRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
QUESTION = {
    "question_id": "123e4567-e89b-42d3-a456-426614174000",
    "target_definition_hash": "a" * 64,
    "resolver_id": "citation-reach-v1",
    "resolver_version": 1,
    "horizon": "2027-09-01T00:00:00.000000Z",
}


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class Storage:
    database: Database
    sheets: SheetRepository

    def seal(self, payload: object) -> dict[str, Any]:
        response = self.sheets.execute("seal", identity=identity(), payload=payload)
        return dict(canonical_loads(response.body)["data"])


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> Storage:
    database = Database(postgres_dsn)
    return Storage(
        database,
        SheetRepository(
            database,
            ArtifactStore(artifact_root),
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
    )


def test_seal_is_content_addressed_and_idempotent(storage: Storage) -> None:
    payload = {"questions": [QUESTION]}
    first = storage.seal(payload)
    assert first["sheet_hash"] == sheet_identity([QUESTION])
    second = storage.seal(payload)
    assert second["sheet_hash"] == first["sheet_hash"]
    assert second["sealed_at"] == first["sealed_at"]
    with storage.database.connect() as connection:
        sheets = connection.execute("SELECT count(*) FROM sheets").fetchone()
        questions = connection.execute(
            "SELECT count(*) FROM sheet_questions"
        ).fetchone()
    assert sheets is not None and sheets[0] == 1
    assert questions is not None and questions[0] == 1


def test_altering_a_question_seals_a_different_sheet(storage: Storage) -> None:
    original = storage.seal({"questions": [QUESTION]})
    altered_question = {**QUESTION, "resolver_version": 2}
    altered = storage.seal({"questions": [altered_question]})
    assert original["sheet_hash"] != altered["sheet_hash"]
    with storage.database.connect() as connection:
        count = connection.execute("SELECT count(*) FROM sheets").fetchone()
    assert count is not None and count[0] == 2
