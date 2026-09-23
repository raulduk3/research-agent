from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
from research_agent.contracts.submissions import validate_accept_submission_payload
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, TransactionUnavailable
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
    "tool_calls": 12,
    "deep_reads": 3,
    "images": 3,
    "timeout_seconds": 30,
    "retries": 1,
    "wall_time_seconds": 300,
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
        paper_id: str = "paper-a",
        issued_question_ids: tuple[str, ...] = (QUESTION_A, QUESTION_B),
    ) -> str:
        response = self.runs.execute(
            "create",
            identity=identity(),
            payload={
                "run_id": str(uuid4()),
                "slot": {
                    "batch_id": sheet_hash,
                    "paper_id": paper_id,
                    "configuration_id": str(uuid4()),
                    "attempt": 0,
                },
                "genome_hash": "f" * 64,
                "seed": 7,
                "snapshot_hash": snapshot_hash,
                "budgets": BUDGETS,
                "allowed_tools": ["query_cards", "submit"],
                "model_identity": MODEL_IDENTITY,
                "checkpoint_dates": [],
                "issued_question_ids": list(issued_question_ids),
            },
        )
        return str(canonical_loads(response.body)["data"]["run_id"])

    def accept(
        self,
        *,
        run_id: str,
        submission_id: str | None = None,
        answers: list[dict[str, Any]],
        nomination: dict[str, Any],
        command: CommandIdentity | None = None,
    ) -> dict[str, Any]:
        response = self.submissions.accept_submission(
            identity=command or identity(),
            payload={
                "run_id": run_id,
                "submission_id": submission_id or str(uuid4()),
                "answers": answers,
                "nomination": nomination,
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


# -- accept_submission (AG-26, TDD-3.1.57) --------------------------------


def _answer(
    question_id: str, evidence: str, probability: float = 0.6
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "probability": probability,
        "rationale": "the method section supports this",
        "evidence_ids": [evidence],
    }


def _nomination(paper_id: str, *, recommend: bool = True) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "recommend": recommend,
        "preference": 0.7,
        "rationale": "worth reading",
    }


def test_accept_submission_seals_answers_and_nomination(storage: Storage) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}')
    run_id = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    result = storage.accept(
        run_id=run_id,
        answers=[_answer(QUESTION_A, evidence), _answer(QUESTION_B, evidence)],
        nomination=_nomination("paper-a"),
    )
    assert result["accepted"] is True
    with storage.database.connect() as connection:
        forecasts = connection.execute(
            "SELECT count(*) FROM run_forecasts WHERE run_id=%s", (run_id,)
        ).fetchone()
        nominations = connection.execute(
            "SELECT paper_id FROM run_nominations WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert forecasts is not None and forecasts[0] == 2
    assert nominations is not None and nominations[0] == "paper-a"


def test_accept_submission_admits_an_empty_question_engineering_slot(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    run_id = storage.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        issued_question_ids=(),
    )
    result = storage.accept(
        run_id=run_id, answers=[], nomination=_nomination("paper-a")
    )
    assert result["accepted"] is True


def test_accept_submission_rejects_a_nomination_naming_another_paper(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}')
    run_id = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    result = storage.accept(
        run_id=run_id,
        answers=[_answer(QUESTION_A, evidence), _answer(QUESTION_B, evidence)],
        nomination=_nomination("some-other-paper"),
    )
    assert result["accepted"] is False
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM run_submissions WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert count is not None and count[0] == 0


def test_accept_submission_rolls_back_a_partial_invalid_answer_set(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}')
    run_id = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    result = storage.accept(
        run_id=run_id,
        answers=[_answer(QUESTION_A, evidence)],
        nomination=_nomination("paper-a"),
    )
    assert result["accepted"] is False
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM run_forecasts WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert count is not None and count[0] == 0


def test_accept_submission_a_missing_nomination_is_a_structural_error(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    run_id = storage.create_run(
        sheet_hash=sheet_hash, snapshot_hash=snapshot_hash, issued_question_ids=()
    )
    with pytest.raises(Exception):
        storage.submissions.accept_submission(
            identity=identity(),
            payload={
                "run_id": run_id,
                "submission_id": str(uuid4()),
                "answers": [],
            },
        )


def test_accept_submission_retry_with_identical_bytes_returns_the_original_result(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}')
    run_id = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    submission_id = str(uuid4())
    answers = [_answer(QUESTION_A, evidence), _answer(QUESTION_B, evidence)]
    nomination = _nomination("paper-a")
    first = storage.accept(
        run_id=run_id,
        submission_id=submission_id,
        answers=answers,
        nomination=nomination,
        command=identity(),
    )
    second = storage.accept(
        run_id=run_id,
        submission_id=submission_id,
        answers=answers,
        nomination=nomination,
        command=identity(),
    )
    assert first["accepted"] is True
    assert second["accepted"] is True
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM run_submissions WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert count is not None and count[0] == 1


def test_accept_submission_changed_bytes_after_acceptance_conflicts(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}')
    run_id = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    answers = [_answer(QUESTION_A, evidence), _answer(QUESTION_B, evidence)]
    storage.accept(run_id=run_id, answers=answers, nomination=_nomination("paper-a"))
    with pytest.raises(StateConflict):
        storage.accept(
            run_id=run_id, answers=answers, nomination=_nomination("paper-a")
        )


def test_accept_submission_simultaneous_submissions_yield_one_accepted_result(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}')
    run_id = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    answers = [_answer(QUESTION_A, evidence), _answer(QUESTION_B, evidence)]

    def attempt(_: int) -> object:
        try:
            return storage.accept(
                run_id=run_id,
                submission_id=str(uuid4()),
                answers=answers,
                nomination=_nomination("paper-a"),
            )
        except (StateConflict, TransactionUnavailable):
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(4)))
    accepted = [
        result for result in results if result is not None and result["accepted"]
    ]
    assert len(accepted) == 1
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM run_submissions WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert count is not None and count[0] == 1


def _event_payload(storage: Storage, receipt: dict[str, Any]) -> dict[str, Any]:
    with storage.database.connect() as connection:
        row = connection.execute(
            """SELECT encode(payload_hash, 'hex'), event_kind FROM ledger_records
               WHERE record_id=%s""",
            (receipt["record_ids"][0],),
        ).fetchone()
    assert row is not None
    with storage.store.open_verified(str(row[0])) as stream:
        return {"event_kind": row[1], **canonical_loads(stream.read())}


def _forecast_count(storage: Storage, run_id: str) -> int:
    with storage.database.connect() as connection:
        row = connection.execute(
            "SELECT count(*) FROM run_forecasts WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_accept_submission_rejection_records_the_attempt_request_hash(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}')
    run_id = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    payload = {
        "run_id": run_id,
        "submission_id": str(uuid4()),
        "answers": [_answer(QUESTION_A, evidence), _answer(QUESTION_B, evidence)],
        "nomination": _nomination("some-other-paper"),
    }
    response = storage.submissions.accept_submission(
        identity=identity(), payload=payload
    )
    result = canonical_loads(response.body)["data"]
    assert result["accepted"] is False
    event = _event_payload(storage, result["receipt"])
    assert event["event_kind"] == "submission_rejected"
    assert event["run_id"] == run_id
    assert event["request_hash"] == sha256_hex(
        canonical_json(validate_accept_submission_payload("accept_submission", payload))
    )
    assert event["reason"] == result["reason"]


def test_accept_submission_a_rejected_attempt_is_corrected_within_the_deadline(
    storage: Storage,
) -> None:
    sheet_hash = storage.seal_sheet()
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}')
    run_id = storage.create_run(sheet_hash=sheet_hash, snapshot_hash=snapshot_hash)
    rejected = storage.accept(
        run_id=run_id,
        answers=[_answer(QUESTION_A, evidence)],
        nomination=_nomination("paper-a"),
    )
    corrected = storage.accept(
        run_id=run_id,
        answers=[_answer(QUESTION_A, evidence), _answer(QUESTION_B, evidence)],
        nomination=_nomination("paper-a"),
    )
    assert rejected["accepted"] is False
    assert corrected["accepted"] is True
    assert _forecast_count(storage, run_id) == 2


def test_accept_submission_after_the_deadline_is_refused_and_seals_nothing(
    storage: Storage,
) -> None:
    response = storage.sheets.execute(
        "seal",
        identity=identity(),
        payload={
            "questions": [
                {**question(QUESTION_A), "horizon": "2020-01-01T00:00:00.000000Z"}
            ]
        },
    )
    sheet_hash = str(canonical_loads(response.body)["data"]["sheet_hash"])
    snapshot_hash = storage.seal_snapshot()
    evidence = storage.artifact(b'{"evidence":1}')
    run_id = storage.create_run(
        sheet_hash=sheet_hash,
        snapshot_hash=snapshot_hash,
        issued_question_ids=(QUESTION_A,),
    )
    for _ in range(2):
        result = storage.accept(
            run_id=run_id,
            answers=[_answer(QUESTION_A, evidence)],
            nomination=_nomination("paper-a"),
        )
        assert result["accepted"] is False
        assert "deadline" in result["reason"]
    assert _forecast_count(storage, run_id) == 0
    with storage.database.connect() as connection:
        ended = connection.execute(
            "SELECT count(*) FROM run_terminal_states WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert ended is not None and ended[0] == 0
