"""SDD-SR-24, TDD-2.1.13: a submitted forecast carries a bounded rationale.

The rationale is a required field of the strict submit schema, at most 2000
code points, recorded unchanged on the sealed forecast. A submit call that
omits it or exceeds the bound is refused whole, before anything of that call
is sealed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.submissions import (
    parse_answers,
    parse_nomination,
    parse_submit_args,
)
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.runs import RunRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository
from research_agent.storage.submissions import SubmissionRepository

QUESTION = "123e4567-e89b-42d3-a456-426614174000"
EVIDENCE = "e" * 64
PAPER = "paper-a"
# U+00E9 is one NFC code point and two UTF-8 bytes, so a bound counted in
# bytes rather than code points would refuse the admitted maximum.
AT_BOUND = "é" * 2000
OVER_BOUND = AT_BOUND + "é"


def _answer(**overrides: Any) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "question_id": QUESTION,
        "probability": 0.6,
        "rationale": "the method section supports this",
        "evidence_ids": [EVIDENCE],
    }
    answer.update(overrides)
    return answer


def _without_rationale(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "rationale"}


def _nomination(**overrides: Any) -> dict[str, Any]:
    nomination: dict[str, Any] = {
        "paper_id": PAPER,
        "recommend": True,
        "preference": 0.7,
        "rationale": "worth reading",
    }
    nomination.update(overrides)
    return nomination


def test_a_rationale_at_the_bound_is_recorded_unchanged() -> None:
    [answer] = parse_answers([_answer(rationale=AT_BOUND)])
    assert answer["rationale"] == AT_BOUND
    assert parse_nomination(_nomination(rationale=AT_BOUND))["rationale"] == AT_BOUND


@pytest.mark.parametrize(
    "answer",
    [
        _without_rationale(_answer()),
        _answer(rationale=OVER_BOUND),
        _answer(rationale=""),
        _answer(rationale=None),
    ],
    ids=["missing", "overlong", "empty", "null"],
)
def test_an_answer_without_a_bounded_rationale_is_refused(
    answer: dict[str, Any],
) -> None:
    with pytest.raises(ContractValidationError):
        parse_answers([answer])


@pytest.mark.parametrize(
    "nomination",
    [_without_rationale(_nomination()), _nomination(rationale=OVER_BOUND)],
    ids=["missing", "overlong"],
)
def test_a_nomination_without_a_bounded_rationale_is_refused(
    nomination: dict[str, Any],
) -> None:
    with pytest.raises(ContractValidationError):
        parse_nomination(nomination)


def test_one_bad_rationale_refuses_the_whole_submit_call() -> None:
    sibling = _answer(question_id="123e4567-e89b-42d3-a456-426614174001")
    with pytest.raises(ContractValidationError):
        parse_submit_args(
            {
                "submission_id": str(uuid4()),
                "answers": [sibling, _answer(rationale=OVER_BOUND)],
                "nomination": _nomination(),
            }
        )


# -- sealing: a refused call seals nothing ---------------------------------

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
REPOSITORY_ARGS: dict[str, Any] = {
    "producer": PRODUCER,
    "config_hash": "c" * 64,
    "retention_policy_hash": "d" * 64,
}
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


def _identity() -> CommandIdentity:
    return CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4())


def _data(body: bytes) -> dict[str, Any]:
    return dict(canonical_loads(body)["data"])


def _sealed_run(database: Database, store: ArtifactStore) -> tuple[str, str]:
    """A run issued QUESTION on PAPER, and one stored evidence id."""

    payload = b'{"evidence":1}'
    evidence = (
        ArtifactRepository(database, store)
        .publish(
            [payload],
            expected_hash=sha256_hex(payload),
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
        .manifest_hash
    )
    sheet_hash = _data(
        SheetRepository(database, store, **REPOSITORY_ARGS)
        .execute(
            "seal",
            identity=_identity(),
            payload={
                "questions": [
                    {
                        "question_id": QUESTION,
                        "target_definition_hash": "a" * 64,
                        "resolver_id": "citation-reach-v1",
                        "resolver_version": 1,
                        "horizon": "2027-09-01T00:00:00.000000Z",
                    }
                ]
            },
        )
        .body
    )["sheet_hash"]
    snapshots = SnapshotRepository(database, store, **REPOSITORY_ARGS)
    snapshot_hash = _data(
        snapshots.execute(
            "seal",
            identity=_identity(),
            payload={
                "paper_manifest_hash": evidence,
                "index_identity_hashes": ["e" * 64],
            },
        ).body
    )["snapshot_hash"]
    run_id = _data(
        RunRepository(database, store, **REPOSITORY_ARGS)
        .execute(
            "create",
            identity=_identity(),
            payload={
                "run_id": str(uuid4()),
                "slot": {
                    "batch_id": sheet_hash,
                    "paper_id": PAPER,
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
                "issued_question_ids": [QUESTION],
            },
        )
        .body
    )["run_id"]
    return str(run_id), str(evidence)


def _sealed_counts(database: Database, run_id: str) -> list[object]:
    with database.connect() as connection:
        rows = [
            connection.execute(
                f"SELECT count(*) FROM {table} WHERE run_id=%s", (run_id,)
            ).fetchone()
            for table in ("run_submissions", "run_forecasts", "run_nominations")
        ]
    return [row[0] if row is not None else None for row in rows]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("answer_rationale", "nomination_rationale"),
    [(None, "worth reading"), (OVER_BOUND, "worth reading"), ("fine", None)],
    ids=["missing-answer", "overlong-answer", "missing-nomination"],
)
def test_a_refused_rationale_seals_nothing_and_a_correction_records_it(
    postgres_dsn: str,
    artifact_root: Path,
    answer_rationale: str | None,
    nomination_rationale: str | None,
) -> None:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    submissions = SubmissionRepository(database, store, **REPOSITORY_ARGS)
    run_id, evidence = _sealed_run(database, store)

    answer = _answer(evidence_ids=[evidence], rationale=answer_rationale)
    nomination = _nomination(rationale=nomination_rationale)
    if answer_rationale is None:
        answer = _without_rationale(answer)
    if nomination_rationale is None:
        nomination = _without_rationale(nomination)
    with pytest.raises(ContractValidationError):
        submissions.accept_submission(
            identity=_identity(),
            payload={
                "run_id": run_id,
                "submission_id": str(uuid4()),
                "answers": [answer],
                "nomination": nomination,
            },
        )
    assert _sealed_counts(database, run_id) == [0, 0, 0]

    accepted = _data(
        submissions.accept_submission(
            identity=_identity(),
            payload={
                "run_id": run_id,
                "submission_id": str(uuid4()),
                "answers": [_answer(evidence_ids=[evidence], rationale=AT_BOUND)],
                "nomination": _nomination(),
            },
        ).body
    )
    assert accepted["accepted"] is True
    with database.connect() as connection:
        stored = connection.execute(
            "SELECT rationale FROM run_forecasts WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert stored is not None and stored[0] == AT_BOUND
