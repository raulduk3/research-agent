"""Configuration-digest verification at completion and quarantine (IN-24, TDD-4.1.31)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.agents.configuration import AgentConfiguration
from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_loads, sha256_hex
from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.runs import BUDGET_FIELDS
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.errors import StateConflict
from research_agent.storage.quarantine import QuarantineRepository
from research_agent.storage.ratings import RatingRepository
from tests.storage.test_digests import (
    entry,
    identity as digest_identity,
    seed_submission,
)
from tests.storage.test_digests import store_payload
from tests.storage.test_exclusions import (
    BUDGETS,
    MODEL_IDENTITY,
    PRODUCER,
    World,
    identity,
    step,
    world,
)

pytestmark = pytest.mark.integration

__all__ = ["world"]

SETTINGS: dict[str, Any] = {
    "producer": PRODUCER,
    "config_hash": "c" * 64,
    "retention_policy_hash": "d" * 64,
}


def configuration(**overrides: Any) -> AgentConfiguration:
    arguments: dict[str, Any] = {
        "island": "cs",
        "founder": True,
        "prompt": "evidence-first",
        "scan_policy": "scan",
        "read_policy": "read",
        "probability_assignment_rule": "one sample",
        "tools": ("query_cards", "submit"),
        "budgets": {name: 1 for name in BUDGET_FIELDS},
        "sampling": {"count": 1},
        "output_schema": {"note": "string"},
    }
    arguments.update(overrides)
    return AgentConfiguration(**arguments)


def sealed_run(world: World, sealed: AgentConfiguration) -> UUID:
    """Create a run sealed with ``sealed``'s configuration hash as its genome hash."""

    run_id = uuid4()
    world.runs.execute(
        "create",
        identity=identity(),
        payload={
            "run_id": str(run_id),
            "slot": {
                "batch_id": world.sheet_hash,
                "paper_id": "p1",
                "configuration_id": str(uuid4()),
                "attempt": 0,
            },
            "genome_hash": sealed.configuration_hash,
            "seed": 7,
            "snapshot_hash": world.snapshot_hash,
            "budgets": BUDGETS,
            "allowed_tools": ["query_cards", "submit"],
            "model_identity": MODEL_IDENTITY,
            "checkpoint_dates": [],
            "issued_question_ids": [],
        },
    )
    return run_id


@pytest.fixture
def quarantine(world: World, artifact_root: Path) -> QuarantineRepository:
    return QuarantineRepository(
        Database(world.dsn), ArtifactStore(artifact_root), **SETTINGS
    )


def verify(
    quarantine: QuarantineRepository, run_id: UUID, mounted: AgentConfiguration
) -> dict[str, Any]:
    response = quarantine.verify_completion(
        identity=identity(), run_id=run_id, configuration=mounted
    )
    return dict(canonical_loads(response.body)["data"])


def test_an_unchanged_configuration_verifies_and_leaves_the_run_active(
    world: World, quarantine: QuarantineRepository
) -> None:
    sealed = configuration()
    run_id = sealed_run(world, sealed)
    result = verify(quarantine, run_id, sealed)
    assert result["verified"] is True
    assert world.exclusions.state("run", run_id) == "active"
    assert world.ledger() == []


def test_a_changed_prompt_quarantines_the_run_with_one_ledger_record(
    world: World, quarantine: QuarantineRepository
) -> None:
    sealed = configuration()
    run_id = sealed_run(world, sealed)
    result = verify(quarantine, run_id, replace(sealed, prompt="edited mid-run"))
    assert result["verified"] is False
    assert result["state"] == "run_quarantined"
    assert world.exclusions.state("run", run_id) == "run_quarantined"
    assert len(world.ledger()) == 1
    tampered = replace(sealed, prompt="edited mid-run")
    with psycopg.connect(world.dsn) as connection:
        row = connection.execute(
            "SELECT id, encode(evidence_hashes[1], 'hex'), authority"
            " FROM exclusion_transitions WHERE scope_id=%s",
            (run_id,),
        ).fetchone()
    assert row == (
        UUID(result["transition_id"]),
        sha256_hex(
            canonical_json(
                {
                    "reason": "configuration_digest_mismatch",
                    "run_id": str(run_id),
                    "sealed_hash": sealed.configuration_hash,
                    "recomputed_hash": tampered.configuration_hash,
                }
            )
        ),
        "system",
    )


def test_a_changed_budget_is_a_mismatch_too(
    world: World, quarantine: QuarantineRepository
) -> None:
    sealed = configuration()
    run_id = sealed_run(world, sealed)
    widened = replace(sealed, budgets={name: 2 for name in BUDGET_FIELDS})
    assert verify(quarantine, run_id, widened)["verified"] is False


def test_verifying_an_already_quarantined_run_appends_nothing(
    world: World, quarantine: QuarantineRepository
) -> None:
    sealed = configuration()
    run_id = sealed_run(world, sealed)
    tampered = replace(sealed, scan_policy="edited mid-run")
    verify(quarantine, run_id, tampered)
    again = verify(quarantine, run_id, tampered)
    assert again["state"] == "run_quarantined"
    assert len(world.ledger()) == 1


def test_a_run_quarantined_by_another_path_is_not_stepped_again(
    world: World, quarantine: QuarantineRepository
) -> None:
    sealed = configuration()
    run_id = sealed_run(world, sealed)
    world.apply(step("quarantine_run", run_id))
    assert verify(quarantine, run_id, replace(sealed, prompt="x"))["verified"] is False
    assert len(world.ledger()) == 1


def _nominate_run_output(
    world: World, artifact_root: Path, run_id: UUID
) -> tuple[UUID, DigestRepository]:
    """Accept a submission for the run and nominate it in a stored digest entry."""

    database = Database(world.dsn)
    submission_id = seed_submission(database)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO run_submissions(run_id, submission_id, request_hash, accepted_at)"
            " VALUES (%s, %s, decode(%s,'hex'), now())",
            (run_id, submission_id, "a" * 64),
        )
    return submission_id, DigestRepository(
        database, ArtifactStore(artifact_root), **SETTINGS
    )


def _digest_with_nomination(digests: DigestRepository, submission_id: UUID) -> UUID:
    entry_id = uuid4()
    digests.execute(
        "store",
        identity=digest_identity(),
        payload=store_payload(
            entries=(entry(entry_id),),
            nominations=(
                {
                    "entry_id": str(entry_id),
                    "configuration_id": str(uuid4()),
                    "submission_id": str(submission_id),
                    "preference": 3,
                },
            ),
        ),
    )
    return entry_id


def test_a_quarantined_runs_submission_cannot_be_nominated_into_a_digest(
    world: World, quarantine: QuarantineRepository, artifact_root: Path
) -> None:
    sealed = configuration()
    run_id = sealed_run(world, sealed)
    submission_id, digests = _nominate_run_output(world, artifact_root, run_id)
    verify(quarantine, run_id, replace(sealed, prompt="edited"))
    with pytest.raises(psycopg.errors.CheckViolation, match="quarantined run"):
        _digest_with_nomination(digests, submission_id)


def test_a_clean_runs_submission_is_still_nominated(
    world: World, artifact_root: Path
) -> None:
    run_id = sealed_run(world, configuration())
    submission_id, digests = _nominate_run_output(world, artifact_root, run_id)
    assert _digest_with_nomination(digests, submission_id)


def test_an_entry_whose_only_nominator_was_quarantined_cannot_be_rated(
    world: World, quarantine: QuarantineRepository, artifact_root: Path
) -> None:
    sealed = configuration()
    run_id = sealed_run(world, sealed)
    submission_id, digests = _nominate_run_output(world, artifact_root, run_id)
    entry_id = _digest_with_nomination(digests, submission_id)
    ratings = RatingRepository(
        Database(world.dsn), ArtifactStore(artifact_root), **SETTINGS
    )
    payload = {
        "rater_id": str(uuid4()),
        "paper_hash": "a" * 64,
        "digest_entry_id": str(entry_id),
        "value": "like",
    }
    ratings.execute("record", identity=identity(), payload=payload)

    verify(quarantine, run_id, replace(sealed, prompt="edited"))
    with pytest.raises(StateConflict, match="quarantined"):
        ratings.execute(
            "record",
            identity=identity(),
            payload={**payload, "rater_id": str(uuid4())},
        )
