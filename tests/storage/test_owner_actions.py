"""An owner's genome admission is one transaction (#233)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.storage.actions import OwnerActionResult, OwnerActions
from research_agent.storage.commands import CommandIdentity, DomainEvents
from research_agent.storage.database import Database
from research_agent.storage.owners import OwnerRepository

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
PROFILE_HASH = "a" * 64
OWNER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


@pytest.fixture
def world(postgres_dsn: str, artifact_root: Path) -> tuple[OwnerActions, UUID]:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    settings: dict[str, Any] = {
        "producer": PRODUCER,
        "config_hash": "c" * 64,
        "retention_policy_hash": "d" * 64,
    }
    OwnerRepository(database, store, **settings).execute(
        "provision",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "owner_id": str(OWNER_ID),
            "salt": "a" * 32,
            "credential_hash": "b" * 64,
        },
    )
    founder_id = uuid4()
    PopulationStore(database, store, **settings).record_seed(
        configuration_id=founder_id,
        genome=Genome(
            lineage_id="cs-founder",
            island="cs",
            infra_hash="b" * 64,
            emphasis={
                "prompt": "prompt",
                "scan_policy": "scan",
                "read_policy": "read",
                "probability_assignment_rule": "one sample",
            },
            founder=True,
            parent_hash=None,
        ),
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    return OwnerActions(database, store, **settings), founder_id


def _edit(actions: OwnerActions, founder_id: UUID, new_id: UUID) -> OwnerActionResult:
    return actions.admit_edited_genome(
        owner_id=OWNER_ID,
        source_configuration_id=founder_id,
        new_configuration_id=new_id,
        changes={"prompt": "a rewritten prompt"},
        lineage_id="cs-child",
        corpus_identifiers=(),
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )


def _ledger_kinds(dsn: str) -> list[str]:
    with Database(dsn).connect() as connection:
        rows = connection.execute(
            "SELECT event_kind FROM ledger_records ORDER BY sequence"
        ).fetchall()
    return [str(row[0]) for row in rows]


def test_a_failure_after_the_genome_write_leaves_no_genome_and_no_record(
    world: tuple[OwnerActions, UUID],
    postgres_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, founder_id = world
    real_append = DomainEvents.append

    def append(self: DomainEvents, connection: Any, **kwargs: Any) -> Any:
        if kwargs["event_kind"] == "genome_owner_admission_recorded":
            raise RuntimeError("injected after the genome write")
        return real_append(self, connection, **kwargs)

    monkeypatch.setattr(DomainEvents, "append", append)
    new_id = uuid4()
    with pytest.raises(RuntimeError):
        _edit(actions, founder_id, new_id)

    with Database(postgres_dsn).connect() as connection:
        genomes = connection.execute(
            "SELECT count(*) FROM genomes WHERE configuration_id=%s", (new_id,)
        ).fetchone()
        records = connection.execute(
            "SELECT count(*) FROM genome_owner_admissions WHERE configuration_id=%s",
            (new_id,),
        ).fetchone()
    assert genomes == (0,) and records == (0,)
    assert _ledger_kinds(postgres_dsn) == ["owner_provisioned", "genome_admitted"]


def test_a_successful_admission_commits_the_genome_and_its_owner_record_together(
    world: tuple[OwnerActions, UUID], postgres_dsn: str
) -> None:
    actions, founder_id = world
    new_id = uuid4()
    assert _edit(actions, founder_id, new_id).accepted is True

    with Database(postgres_dsn).connect() as connection:
        row = connection.execute(
            """SELECT o.owner_id, o.kind, o.source_configuration_id
               FROM genomes g
               JOIN genome_owner_admissions o USING (configuration_id)
               WHERE g.configuration_id=%s""",
            (new_id,),
        ).fetchone()
    assert row == (OWNER_ID, "edit", founder_id)
    assert _ledger_kinds(postgres_dsn)[-2:] == [
        "genome_admitted",
        "genome_owner_admission_recorded",
    ]
