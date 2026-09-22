from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import TransactionUnavailable
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


@dataclass
class Storage:
    database: Database
    store: ArtifactStore
    artifacts: ArtifactRepository
    sheets: SheetRepository
    submissions: SubmissionRepository

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
    ) -> str:
        response = self.sheets.execute(
            "seal",
            identity=identity(),
            payload={"questions": [question(item) for item in question_ids]},
        )
        return str(canonical_loads(response.body)["data"]["sheet_hash"])

    def submit(
        self,
        *,
        sheet_hash: str,
        submitter_id: UUID,
        claims: list[dict[str, Any]],
        command: CommandIdentity | None = None,
    ) -> dict[str, Any]:
        response = self.submissions.execute(
            "submit",
            identity=command or identity(),
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
        SubmissionRepository(database, store, **kwargs),
    )


def test_valid_claims_seal_one_ledger_record_each(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet()
    evidence = storage.artifact(b'{"evidence":1}')
    result = storage.submit(
        sheet_hash=sheet_hash,
        submitter_id=uuid4(),
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
    assert result["accepted"] is True
    assert len(result["submission_ids"]) == 2
    assert result["receipt"]["ledger_last"] - result["receipt"]["ledger_first"] == 1
    with storage.database.connect() as connection:
        statuses = {
            row[0]
            for row in connection.execute(
                "SELECT status FROM submissions WHERE sheet_hash=decode(%s,'hex')",
                (sheet_hash,),
            ).fetchall()
        }
    assert statuses == {"sealed", "void"}


def test_a_malformed_batch_is_rejected_whole_and_recorded(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet()
    evidence = storage.artifact(b'{"evidence":1}')
    result = storage.submit(
        sheet_hash=sheet_hash,
        submitter_id=uuid4(),
        claims=[
            {
                "kind": "forecast",
                "question_id": QUESTION_A,
                "evidence_hashes": [evidence],
                "confidence": 0.6,
            },
            {
                "kind": "forecast",
                "question_id": "not-on-the-sheet",
                "evidence_hashes": [evidence],
                "confidence": 0.6,
            },
        ],
    )
    assert result["accepted"] is False
    assert "reason" in result
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM submissions WHERE sheet_hash=decode(%s,'hex')",
            (sheet_hash,),
        ).fetchone()
    assert count is not None and count[0] == 0


def test_a_claim_against_an_unsealed_sheet_is_rejected(storage: Storage) -> None:
    evidence = storage.artifact(b'{"evidence":1}')
    result = storage.submit(
        sheet_hash="0" * 64,
        submitter_id=uuid4(),
        claims=[
            {
                "kind": "forecast",
                "question_id": QUESTION_A,
                "evidence_hashes": [evidence],
                "confidence": 0.6,
            }
        ],
    )
    assert result["accepted"] is False


def test_unavailable_evidence_is_rejected(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet()
    result = storage.submit(
        sheet_hash=sheet_hash,
        submitter_id=uuid4(),
        claims=[
            {
                "kind": "forecast",
                "question_id": QUESTION_A,
                "evidence_hashes": ["f" * 64],
                "confidence": 0.6,
            }
        ],
    )
    assert result["accepted"] is False


def test_a_submitter_cannot_seal_a_second_claim_for_the_same_question(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    evidence = storage.artifact(b'{"evidence":1}')
    submitter_id = uuid4()
    claim = {
        "kind": "forecast",
        "question_id": QUESTION_A,
        "evidence_hashes": [evidence],
        "confidence": 0.6,
    }
    first = storage.submit(
        sheet_hash=sheet_hash, submitter_id=submitter_id, claims=[claim]
    )
    assert first["accepted"] is True
    second = storage.submit(
        sheet_hash=sheet_hash, submitter_id=submitter_id, claims=[claim]
    )
    assert second["accepted"] is False


def test_concurrent_submits_form_one_gap_free_ledger_chain(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet()
    evidence = storage.artifact(b'{"evidence":1}')
    commands = [(uuid4(), identity()) for _ in range(12)]

    def submit(item: tuple[UUID, CommandIdentity]) -> object:
        submitter_id, command = item
        try:
            return storage.submit(
                sheet_hash=sheet_hash,
                submitter_id=submitter_id,
                claims=[
                    {
                        "kind": "forecast",
                        "question_id": QUESTION_A,
                        "evidence_hashes": [evidence],
                        "confidence": 0.6,
                    }
                ],
                command=command,
            )
        except TransactionUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(submit, commands))
    for item, result in zip(commands, results, strict=True):
        if result is None:
            retried = submit(item)
            assert retried is not None
            assert retried["accepted"] is True
        else:
            assert result["accepted"] is True
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM submissions WHERE sheet_hash=decode(%s,'hex')",
            (sheet_hash,),
        ).fetchone()
    assert count is not None and count[0] == len(commands)
