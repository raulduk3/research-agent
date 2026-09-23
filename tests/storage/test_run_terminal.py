"""A run ends once: an accepted submission or void (AG-15, TDD-3.1.55)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.contracts.primitives import ContractValidationError
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
    "paper_card_manifest": "c" * 64,
    "prediction_head_bundles": {},
}


def identity() -> CommandIdentity:
    return CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class Storage:
    database: Database
    artifacts: ArtifactRepository
    sheets: SheetRepository
    snapshots: SnapshotRepository
    runs: RunRepository
    submissions: SubmissionRepository

    def artifact(self, payload: bytes) -> str:
        digest = sha256_hex(payload)
        return self.artifacts.publish(
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
        ).manifest_hash

    def create_run(self) -> str:
        sheet = self.sheets.execute(
            "seal",
            identity=identity(),
            payload={
                "questions": [
                    {
                        "question_id": question_id,
                        "target_definition_hash": "a" * 64,
                        "resolver_id": "citation-reach-v1",
                        "resolver_version": 1,
                        "horizon": "2027-09-01T00:00:00.000000Z",
                    }
                    for question_id in (QUESTION_A, QUESTION_B)
                ]
            },
        )
        snapshot = self.snapshots.execute(
            "seal",
            identity=identity(),
            payload={
                "paper_manifest_hash": self.artifact(b'{"papers":["p1"]}'),
                "index_identity_hashes": ["e" * 64],
            },
        )
        response = self.runs.execute(
            "create",
            identity=identity(),
            payload={
                "run_id": str(uuid4()),
                "slot": {
                    "batch_id": canonical_loads(sheet.body)["data"]["sheet_hash"],
                    "paper_id": "paper-a",
                    "configuration_id": str(uuid4()),
                    "attempt": 0,
                },
                "genome_hash": "f" * 64,
                "seed": 7,
                "snapshot_hash": canonical_loads(snapshot.body)["data"][
                    "snapshot_hash"
                ],
                "budgets": BUDGETS,
                "allowed_tools": ["query_cards", "submit"],
                "model_identity": MODEL_IDENTITY,
                "checkpoint_dates": [],
                "issued_question_ids": [QUESTION_A, QUESTION_B],
            },
        )
        return str(canonical_loads(response.body)["data"]["run_id"])

    def event(self, run_id: str, ordinal: int, kind: str, payload: bytes) -> None:
        self.runs.execute(
            "append_event",
            identity=identity(),
            payload={
                "run_id": run_id,
                "attempt": 1,
                "ordinal": ordinal,
                "kind": kind,
                "payload_hash": sha256_hex(payload),
            },
        )

    def void(self, run_id: str, reason: str) -> dict[str, Any]:
        response = self.runs.finish_without_submit(
            identity=identity(), payload={"run_id": run_id, "reason": reason}
        )
        return dict(canonical_loads(response.body)["data"])

    def accept(self, run_id: str, evidence: str, paper_id: str) -> dict[str, Any]:
        response = self.submissions.accept_submission(
            identity=identity(),
            payload={
                "run_id": run_id,
                "submission_id": str(uuid4()),
                "answers": [
                    {
                        "question_id": question_id,
                        "probability": 0.6,
                        "rationale": "the method section supports this",
                        "evidence_ids": [evidence],
                    }
                    for question_id in (QUESTION_A, QUESTION_B)
                ],
                "nomination": {
                    "paper_id": paper_id,
                    "recommend": True,
                    "preference": 0.7,
                    "rationale": "worth reading",
                },
            },
        )
        return dict(canonical_loads(response.body)["data"])

    def count(self, query: str, run_id: str) -> int:
        with self.database.connect() as connection:
            row = connection.execute(query, (run_id,)).fetchone()
        assert row is not None
        return int(row[0])

    def terminal(self, run_id: str) -> list[tuple[Any, ...]]:
        with self.database.connect() as connection:
            return connection.execute(
                """SELECT state, reason, last_event_attempt, last_event_ordinal, stamp
                   FROM run_terminal_states WHERE run_id=%s""",
                (run_id,),
            ).fetchall()

    def forecasts(self, run_id: str) -> int:
        return self.count("SELECT count(*) FROM run_forecasts WHERE run_id=%s", run_id)

    def ledger(self, event_kind: str) -> int:
        """Count ledger records of one kind in this test's own schema."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT count(*) FROM ledger_records WHERE event_kind=%s",
                (event_kind,),
            ).fetchone()
        assert row is not None
        return int(row[0])


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
        ArtifactRepository(database, store),
        SheetRepository(database, store, **kwargs),
        SnapshotRepository(database, store, **kwargs),
        RunRepository(database, store, **kwargs),
        SubmissionRepository(database, store, **kwargs),
    )


def test_budget_expiry_voids_the_run_with_reason_last_event_and_stamp(
    storage: Storage,
) -> None:
    run_id = storage.create_run()
    storage.event(run_id, 0, "request", b'{"messages":[]}')
    storage.event(run_id, 1, "response", b'{"tool_calls":[]}')

    result = storage.void(run_id, "budget_exhausted:tool_calls")

    assert result["voided"] is True
    [(state, reason, attempt, ordinal, stamp)] = storage.terminal(run_id)
    assert (state, reason, attempt, ordinal) == (
        "void",
        "budget_exhausted:tool_calls",
        1,
        1,
    )
    with storage.database.connect() as connection:
        snapshot = connection.execute(
            "SELECT encode(snapshot_hash,'hex') FROM runs WHERE id=%s", (run_id,)
        ).fetchone()
    assert snapshot is not None
    assert canonical_loads(bytes(stamp)) == {
        "genome_hash": "f" * 64,
        "seed": 7,
        "snapshot_hash": snapshot[0],
        **MODEL_IDENTITY,
    }
    assert storage.ledger("run_voided") == 1
    assert storage.forecasts(run_id) == 0
    with pytest.raises(StateConflict):
        storage.event(run_id, 2, "request", b'{"messages":[1]}')


def test_a_model_stop_with_prose_probabilities_seals_no_forecast(
    storage: Storage,
) -> None:
    run_id = storage.create_run()
    storage.event(run_id, 0, "request", b'{"messages":[]}')
    storage.event(
        run_id,
        1,
        "response",
        b'{"content":"Q1: 0.8, Q2: 0.3. I nominate paper-a.","tool_calls":[]}',
    )

    assert storage.void(run_id, "model_stopped")["voided"] is True

    assert [row[0] for row in storage.terminal(run_id)] == ["void"]
    assert storage.forecasts(run_id) == 0
    assert (
        storage.count("SELECT count(*) FROM run_nominations WHERE run_id=%s", run_id)
        == 0
    )
    assert storage.ledger("submission_accepted") == 0


def test_refused_submits_then_void_leave_no_forecast_and_no_later_submit(
    storage: Storage,
) -> None:
    run_id = storage.create_run()
    evidence = storage.artifact(b'{"evidence":1}')
    refused = storage.accept(run_id, evidence, "another-paper")
    assert refused["accepted"] is False
    assert storage.terminal(run_id) == []

    assert storage.void(run_id, "submissions_refused")["voided"] is True

    with pytest.raises(StateConflict):
        storage.accept(run_id, evidence, "paper-a")
    assert storage.forecasts(run_id) == 0
    assert [row[0] for row in storage.terminal(run_id)] == ["void"]


def test_void_after_an_accepted_submission_records_nothing(storage: Storage) -> None:
    run_id = storage.create_run()
    evidence = storage.artifact(b'{"evidence":1}')
    assert storage.accept(run_id, evidence, "paper-a")["accepted"] is True

    result = storage.void(run_id, "model_stopped")

    assert result == {"voided": False, "run_id": run_id, "state": "submitted"}
    assert [row[0] for row in storage.terminal(run_id)] == ["submitted"]
    assert storage.forecasts(run_id) == 2
    assert storage.ledger("run_voided") == 0


def test_a_second_void_is_not_recorded_again(storage: Storage) -> None:
    run_id = storage.create_run()
    assert storage.void(run_id, "model_stopped")["voided"] is True

    again = storage.void(run_id, "recording_failed")

    assert again == {"voided": False, "run_id": run_id, "state": "void"}
    assert [row[1] for row in storage.terminal(run_id)] == ["model_stopped"]
    assert storage.ledger("run_voided") == 1


def test_a_void_racing_an_accepted_submit_leaves_exactly_one_terminal_state(
    storage: Storage,
) -> None:
    evidence = storage.artifact(b'{"evidence":1}')

    def void(run_id: str, barrier: Barrier) -> bool:
        barrier.wait()
        try:
            return bool(storage.void(run_id, "budget_exhausted:wall_time")["voided"])
        except (StateConflict, TransactionUnavailable):
            return False

    def accept(run_id: str, barrier: Barrier) -> bool:
        barrier.wait()
        try:
            return bool(storage.accept(run_id, evidence, "paper-a")["accepted"])
        except (StateConflict, TransactionUnavailable):
            return False

    for _ in range(6):
        run_id = storage.create_run()
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            voided = executor.submit(void, run_id, barrier)
            accepted = executor.submit(accept, run_id, barrier)
            won = (voided.result(), accepted.result())

        states = [row[0] for row in storage.terminal(run_id)]
        assert len(states) == 1
        if states == ["void"]:
            assert won == (True, False)
            assert storage.forecasts(run_id) == 0
            assert (
                storage.count(
                    "SELECT count(*) FROM run_submissions WHERE run_id=%s", run_id
                )
                == 0
            )
        else:
            assert states == ["submitted"] and won == (False, True)
            assert storage.forecasts(run_id) == 2


@pytest.mark.parametrize(
    "reason", ["", "Q1: 0.8, Q2: 0.3", "budget_exhausted:", "a" * 64 + ":b"]
)
def test_a_void_reason_is_a_code_not_prose(storage: Storage, reason: str) -> None:
    run_id = storage.create_run()
    with pytest.raises(ContractValidationError):
        storage.void(run_id, reason)
    assert storage.terminal(run_id) == []
