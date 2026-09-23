"""Exclusion action steps: order, ledger records, window and replay (AG-22, AG-23)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.exclusions import ExclusionRepository
from research_agent.storage.ledger import LedgerRepository
from research_agent.storage.owners import OwnerRepository
from research_agent.storage.runs import RunRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
OPERATOR_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
EVIDENCE = ["1" * 64]
QUESTION = {
    "question_id": "123e4567-e89b-42d3-a456-426614174000",
    "target_definition_hash": "a" * 64,
    "resolver_id": "citation-reach-v1",
    "resolver_version": 1,
    "horizon": "2027-09-01T00:00:00.000000Z",
}
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


SENDER = uuid4()


def identity(key: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(SENDER, key or uuid4(), uuid4(), uuid4())


def step(action: str, scope_id: UUID, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": action,
        "scope_id": str(scope_id),
        "evidence_hashes": EVIDENCE,
        "trigger_run_ids": [],
        "authority": "system",
        "operator_id": None,
    }
    payload.update(overrides)
    return payload


@dataclass
class World:
    dsn: str
    exclusions: ExclusionRepository
    runs: RunRepository
    sheet_hash: str
    snapshot_hash: str

    def run(self, configuration_id: UUID, paper_id: str) -> UUID:
        run_id = uuid4()
        self.runs.execute(
            "create",
            identity=identity(),
            payload={
                "run_id": str(run_id),
                "slot": {
                    "batch_id": self.sheet_hash,
                    "paper_id": paper_id,
                    "configuration_id": str(configuration_id),
                    "attempt": 0,
                },
                "genome_hash": "f" * 64,
                "seed": 7,
                "snapshot_hash": self.snapshot_hash,
                "budgets": BUDGETS,
                "allowed_tools": ["query_cards", "submit"],
                "model_identity": MODEL_IDENTITY,
                "checkpoint_dates": [],
                "issued_question_ids": [],
            },
        )
        return run_id

    def apply(self, payload: dict[str, Any], key: UUID | None = None) -> dict[str, Any]:
        response = self.exclusions.execute(identity=identity(key), payload=payload)
        return dict(canonical_loads(response.body)["data"])

    def quarantine_configuration(self, configuration_id: UUID, runs: list[UUID]) -> Any:
        return self.apply(
            step(
                "quarantine_configuration",
                configuration_id,
                trigger_run_ids=[str(run) for run in runs],
            )
        )

    def revoke(self, configuration_id: UUID) -> dict[str, Any]:
        return self.apply(
            step(
                "revoke_authority",
                configuration_id,
                authority="operator",
                operator_id=str(OPERATOR_ID),
            )
        )

    def ledger(self) -> list[tuple[str, str]]:
        with psycopg.connect(self.dsn) as connection:
            rows = connection.execute(
                "SELECT event_kind, encode(payload_hash,'hex') FROM ledger_records"
                " WHERE event_kind='exclusion_action_recorded' ORDER BY sequence"
            ).fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    def verify_chain(self) -> None:
        with psycopg.connect(self.dsn) as connection:
            LedgerRepository().verify(connection)

    def count(self, table: str) -> int:
        with psycopg.connect(self.dsn) as connection:
            row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
        assert row is not None
        return int(str(row[0]))


@pytest.fixture
def world(postgres_dsn: str, artifact_root: Path) -> World:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    settings = {
        "producer": PRODUCER,
        "config_hash": "c" * 64,
        "retention_policy_hash": "d" * 64,
    }
    OwnerRepository(database, store, **settings).execute(
        "provision",
        identity=identity(),
        payload={
            "owner_id": str(OPERATOR_ID),
            "salt": "a" * 32,
            "credential_hash": "b" * 64,
        },
    )
    artifacts = ArtifactRepository(database, store)
    sheet = SheetRepository(database, store, **settings).execute(
        "seal", identity=identity(), payload={"questions": [QUESTION]}
    )
    manifest = b'{"papers":["p1"]}'
    paper_manifest = artifacts.publish(
        [manifest],
        expected_hash=sha256_hex(manifest),
        byte_length=len(manifest),
        maximum_length=1024 * 1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    ).manifest_hash
    snapshot = SnapshotRepository(database, store, **settings).execute(
        "seal",
        identity=identity(),
        payload={
            "paper_manifest_hash": paper_manifest,
            "index_identity_hashes": ["e" * 64],
        },
    )
    return World(
        postgres_dsn,
        ExclusionRepository(database, store, **settings),
        RunRepository(database, store, **settings),
        str(canonical_loads(sheet.body)["data"]["sheet_hash"]),
        str(canonical_loads(snapshot.body)["data"]["snapshot_hash"]),
    )


def test_one_configuration_takes_the_three_steps_with_one_record_each(
    world: World,
) -> None:
    configuration = uuid4()
    runs = [world.run(configuration, f"paper-{index}") for index in range(3)]
    assert world.exclusions.state("configuration", configuration) == "active"
    for run in runs:
        assert world.apply(step("quarantine_run", run))["new_state"] == (
            "run_quarantined"
        )
        assert world.exclusions.state("run", run) == "run_quarantined"
    assert len(world.ledger()) == 3
    world.quarantine_configuration(configuration, runs)
    assert world.exclusions.state("configuration", configuration) == (
        "configuration_quarantined"
    )
    world.revoke(configuration)
    assert world.exclusions.state("configuration", configuration) == "authority_revoked"

    assert len(world.ledger()) == 5
    with psycopg.connect(world.dsn) as connection:
        rows = connection.execute(
            "SELECT new_state FROM exclusion_transitions t JOIN ledger_records l"
            " ON l.sequence = t.ledger_sequence WHERE t.configuration_id=%s"
            " ORDER BY l.sequence",
            (configuration,),
        ).fetchall()
    assert [row[0] for row in rows] == [
        "run_quarantined",
        "run_quarantined",
        "run_quarantined",
        "configuration_quarantined",
        "authority_revoked",
    ]
    world.verify_chain()


def test_a_run_quarantine_names_an_existing_run_and_repeats_no_step(
    world: World,
) -> None:
    with pytest.raises(UnavailableInput):
        world.apply(step("quarantine_run", uuid4()))
    run = world.run(uuid4(), "paper-0")
    world.apply(step("quarantine_run", run))
    with pytest.raises(StateConflict):
        world.apply(step("quarantine_run", run))
    assert world.count("exclusion_transitions") == 1
    assert len(world.ledger()) == 1


def test_purge_is_refused_before_the_configuration_is_quarantined(
    world: World,
) -> None:
    configuration = uuid4()
    run = world.run(configuration, "paper-0")
    world.apply(step("quarantine_run", run))
    with pytest.raises(StateConflict):
        world.revoke(configuration)
    with pytest.raises(StateConflict):
        world.quarantine_configuration(configuration, [run, uuid4(), uuid4()])
    assert world.exclusions.state("configuration", configuration) == "active"
    assert world.count("exclusion_transitions") == 1


def test_revoking_authority_needs_a_provisioned_operator(world: World) -> None:
    configuration = uuid4()
    runs = [world.run(configuration, f"paper-{index}") for index in range(3)]
    for run in runs:
        world.apply(step("quarantine_run", run))
    world.quarantine_configuration(configuration, runs)
    with pytest.raises(UnavailableInput):
        world.apply(
            step(
                "revoke_authority",
                configuration,
                authority="operator",
                operator_id=str(uuid4()),
            )
        )
    assert world.exclusions.state("configuration", configuration) == (
        "configuration_quarantined"
    )


def quarantined_runs(world: World, configuration: UUID, count: int) -> list[UUID]:
    runs = [world.run(configuration, f"paper-{index}") for index in range(count)]
    for run in runs:
        world.apply(step("quarantine_run", run))
    return runs


def test_a_run_of_another_configuration_does_not_count(world: World) -> None:
    configuration = uuid4()
    runs = quarantined_runs(world, configuration, 2)
    runs += quarantined_runs(world, uuid4(), 1)
    with pytest.raises(StateConflict):
        world.quarantine_configuration(configuration, runs)
    assert world.exclusions.state("configuration", configuration) == "active"


def test_an_unquarantined_run_does_not_count(world: World) -> None:
    configuration = uuid4()
    runs = quarantined_runs(world, configuration, 2)
    runs.append(world.run(configuration, "paper-unquarantined"))
    with pytest.raises(StateConflict):
        world.quarantine_configuration(configuration, runs)


def shift(world: World, run: UUID, days: int) -> None:
    """Move a run quarantine's recorded time; the rows are otherwise immutable."""

    with psycopg.connect(world.dsn, autocommit=True) as connection:
        connection.execute(
            "ALTER TABLE exclusion_transitions DISABLE TRIGGER exclusion_transitions_immutable"
        )
        connection.execute(
            "UPDATE exclusion_transitions SET recorded_at = recorded_at + %s"
            " WHERE scope_id=%s",
            (timedelta(days=days), run),
        )
        connection.execute(
            "ALTER TABLE exclusion_transitions ENABLE TRIGGER exclusion_transitions_immutable"
        )


def test_three_quarantines_count_only_inside_a_rolling_seven_days(
    world: World,
) -> None:
    configuration = uuid4()
    runs = quarantined_runs(world, configuration, 3)
    shift(world, runs[0], -8)
    with pytest.raises(StateConflict):
        world.quarantine_configuration(configuration, runs)
    assert world.exclusions.state("configuration", configuration) == "active"
    shift(world, runs[0], 2)
    world.quarantine_configuration(configuration, runs)
    assert world.exclusions.state("configuration", configuration) == (
        "configuration_quarantined"
    )


def test_a_repeated_delivery_appends_one_step(world: World) -> None:
    run = world.run(uuid4(), "paper-0")
    key = uuid4()
    first = world.apply(step("quarantine_run", run), key)
    again = world.apply(step("quarantine_run", run), key)
    assert again == first
    assert world.count("exclusion_transitions") == 1
    assert len(world.ledger()) == 1


def test_a_failed_append_leaves_no_transition_and_no_state(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = world.run(uuid4(), "paper-0")
    before = world.count("ledger_records")

    def refuse(*_: object, **__: object) -> None:
        raise RuntimeError("ledger append unavailable")

    monkeypatch.setattr(
        "research_agent.storage.commands.LedgerRepository.append", refuse
    )
    with pytest.raises(RuntimeError):
        world.apply(step("quarantine_run", run))
    monkeypatch.undo()
    assert world.exclusions.state("run", run) == "active"
    assert world.count("exclusion_transitions") == 0
    assert world.count("ledger_records") == before
    world.apply(step("quarantine_run", run))
    assert world.exclusions.state("run", run) == "run_quarantined"


def test_a_transition_row_cannot_be_rewritten_or_deleted(world: World) -> None:
    run = world.run(uuid4(), "paper-0")
    world.apply(step("quarantine_run", run))
    with psycopg.connect(world.dsn) as connection:
        with pytest.raises(psycopg.errors.Error):
            connection.execute("DELETE FROM exclusion_transitions")
