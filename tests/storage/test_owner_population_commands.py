"""The owner's three commands over the population store (#139)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.storage.actions import (
    POPULATION_FLOOR,
    OwnerActionResult,
    OwnerActions,
)
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.owners import OwnerRepository

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
PROFILE_HASH = "a" * 64
INFRA_HASH = "b" * 64
OWNER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
CORPUS = ("2301.12345v1",)


def genome(
    lineage: str,
    *,
    island: str = "cs",
    founder: bool = False,
    prompt: str | None = None,
    parent_hash: str | None = None,
) -> Genome:
    return Genome(
        lineage_id=lineage,
        island=island,
        infra_hash=INFRA_HASH,
        emphasis={
            "prompt": prompt if prompt is not None else f"prompt-{lineage}",
            "scan_policy": "scan",
            "read_policy": "read",
            "probability_assignment_rule": "one sample",
        },
        founder=founder,
        parent_hash=parent_hash,
    )


@dataclass
class World:
    dsn: str
    population: PopulationStore
    actions: OwnerActions
    founder_id: UUID

    def seed_members(self, count: int, *, island: str = "cs") -> list[UUID]:
        ids: list[UUID] = []
        for index in range(count):
            configuration_id = uuid4()
            self.population.record_seed(
                configuration_id=configuration_id,
                genome=genome(f"{island}-extra-{index}", island=island),
                profile_hash=PROFILE_HASH,
                command_id=uuid4(),
            )
            ids.append(configuration_id)
        return ids

    def ledger_kinds(self) -> list[str]:
        with Database(self.dsn).connect() as connection:
            rows = connection.execute(
                "SELECT event_kind FROM ledger_records ORDER BY sequence"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def count(self, table: str) -> int:
        with Database(self.dsn).connect() as connection:
            row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
        assert row is not None
        return int(str(row[0]))


@pytest.fixture
def world(postgres_dsn: str, artifact_root: Path) -> World:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    settings = {
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
    population = PopulationStore(database, store, **settings)
    founder_id = uuid4()
    population.record_seed(
        configuration_id=founder_id,
        genome=genome("cs-founder", founder=True),
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    return World(
        postgres_dsn, population, OwnerActions(database, store, **settings), founder_id
    )


def seed(world: World, **overrides: object) -> OwnerActionResult:
    arguments: dict[str, object] = {
        "owner_id": OWNER_ID,
        "new_configuration_id": uuid4(),
        "island": "quant-ph",
        "lineage_id": "owner-variant",
        "emphasis": genome("owner-variant").emphasis,
        "template_configuration_id": world.founder_id,
        "corpus_identifiers": CORPUS,
        "profile_hash": PROFILE_HASH,
        "budget_funded": True,
        "command_id": uuid4(),
    }
    arguments.update(overrides)
    return world.actions.seed_variant(**arguments)  # type: ignore[arg-type]


def edit(world: World, **overrides: object) -> OwnerActionResult:
    arguments: dict[str, object] = {
        "owner_id": OWNER_ID,
        "source_configuration_id": world.founder_id,
        "new_configuration_id": uuid4(),
        "changes": {"prompt": "a rewritten prompt"},
        "lineage_id": "cs-child",
        "corpus_identifiers": CORPUS,
        "completed_weekly_cycles": 2,
        "profile_hash": PROFILE_HASH,
        "command_id": uuid4(),
    }
    arguments.update(overrides)
    return world.actions.admit_edited_genome(**arguments)  # type: ignore[arg-type]


def test_a_seeded_variant_is_admitted_into_the_named_island_naming_the_owner(
    world: World,
) -> None:
    new_id = uuid4()
    result = seed(world, new_configuration_id=new_id)
    assert result.accepted is True

    active, _archived = world.population.island_population("quant-ph")
    assert [member.lineage_id for member in active] == ["owner-variant"]
    assert active[0].parent_hash is None and active[0].founder is False

    record = world.actions.admission_history(new_id)
    assert record is not None
    assert (record.kind, record.owner_id, record.source_configuration_id) == (
        "seed",
        str(OWNER_ID),
        None,
    )
    assert record.requested_at
    assert world.ledger_kinds()[-2:] == [
        "genome_admitted",
        "genome_owner_admission_recorded",
    ]


def test_a_seed_is_refused_while_the_budget_is_not_funded_and_stores_nothing(
    world: World,
) -> None:
    before = world.count("genomes")
    result = seed(world, budget_funded=False)
    assert result.reason == "budget_not_funded"
    assert world.count("genomes") == before
    assert world.count("genome_owner_admissions") == 0


def test_a_seed_naming_a_corpus_paper_is_refused(world: World) -> None:
    emphasis = {**genome("x").emphasis, "prompt": "as in 2301.12345v1 the answer is"}
    result = seed(world, emphasis=emphasis)
    assert result.reason == "corpus_identifier"
    assert world.count("genome_owner_admissions") == 0


def test_a_seed_repeating_an_existing_genome_is_refused(world: World) -> None:
    assert seed(world).accepted is True
    repeat = seed(world, new_configuration_id=uuid4(), lineage_id="another-lineage")
    assert repeat.reason == "duplicate_genome"
    assert world.count("genome_owner_admissions") == 1


def test_a_seed_from_an_unknown_template_is_refused(world: World) -> None:
    result = seed(world, template_configuration_id=uuid4())
    assert result.reason == "unknown_source_genome"


def test_an_edit_admits_a_new_genome_linked_to_its_untouched_source(
    world: World,
) -> None:
    source_before = world.actions.read_genome_view(world.founder_id)
    new_id = uuid4()
    result = edit(world, new_configuration_id=new_id)
    assert result.accepted is True

    assert world.actions.read_genome_view(world.founder_id) == source_before
    child = world.actions.read_genome_view(new_id)
    assert child is not None
    assert child["configuration_hash"] != source_before["configuration_hash"]  # type: ignore[index]

    active, _ = world.population.island_population("cs")
    child_genome = next(member for member in active if member.lineage_id == "cs-child")
    assert child_genome.parent_hash == source_before["configuration_hash"]  # type: ignore[index]

    record = world.actions.admission_history(new_id)
    assert record is not None
    assert (record.kind, record.owner_id, record.source_configuration_id) == (
        "edit",
        str(OWNER_ID),
        str(world.founder_id),
    )


@pytest.mark.parametrize("cycles", [0, 1, None])
def test_an_edit_before_the_population_may_change_is_refused(
    world: World, cycles: int | None
) -> None:
    result = edit(world, completed_weekly_cycles=cycles)
    assert result.reason == "cycle_disabled"
    assert world.count("genome_owner_admissions") == 0
    assert world.count("genomes") == 1


def test_an_edit_changing_two_parts_is_refused_whole(world: World) -> None:
    result = edit(world, changes={"prompt": "one", "scan_policy": "two"})
    assert result.reason == "invalid_edit"
    assert world.count("genomes") == 1


def test_an_edit_naming_a_corpus_paper_is_refused(world: World) -> None:
    result = edit(world, changes={"prompt": "see 2301.12345v1"})
    assert result.reason == "corpus_identifier"
    assert world.count("genomes") == 1


def test_an_edit_equal_to_an_existing_genome_is_refused(world: World) -> None:
    assert edit(world).accepted is True
    repeat = edit(world, lineage_id="cs-child-again")
    assert repeat.reason == "duplicate_genome"
    assert world.count("genome_owner_admissions") == 1


def test_an_edit_of_an_unknown_source_is_refused(world: World) -> None:
    result = edit(world, source_configuration_id=uuid4())
    assert result.reason == "unknown_source_genome"


def test_a_retirement_records_the_request_and_removes_nothing_stored(
    world: World,
) -> None:
    members = world.seed_members(POPULATION_FLOOR)
    genomes_before = world.count("genomes")
    result = world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=members[0], command_id=uuid4()
    )
    assert result.accepted is True

    record = world.actions.retirement_status(members[0])
    assert record is not None and record.owner_id == str(OWNER_ID)
    assert world.count("genomes") == genomes_before
    assert world.actions.read_genome_view(members[0]) is not None
    assert world.ledger_kinds()[-1] == "genome_retirement_requested"


def test_a_retirement_that_would_cross_the_population_floor_is_refused(
    world: World,
) -> None:
    members = world.seed_members(POPULATION_FLOOR - 1)
    result = world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=members[0], command_id=uuid4()
    )
    assert result.reason == "population_floor"
    assert world.count("genome_retirements") == 0


def test_retirements_already_requested_count_against_the_floor(world: World) -> None:
    members = world.seed_members(POPULATION_FLOOR)
    first = world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=members[0], command_id=uuid4()
    )
    second = world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=members[1], command_id=uuid4()
    )
    assert (first.accepted, second.reason) == (True, "population_floor")


def test_a_founder_is_never_retired(world: World) -> None:
    world.seed_members(POPULATION_FLOOR + 2)
    result = world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=world.founder_id, command_id=uuid4()
    )
    assert result.reason == "founder_not_retirable"


def test_a_genome_is_retired_at_most_once(world: World) -> None:
    members = world.seed_members(POPULATION_FLOOR + 2)
    world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=members[0], command_id=uuid4()
    )
    again = world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=members[0], command_id=uuid4()
    )
    assert again.reason == "already_retired"


def test_retiring_an_unknown_genome_is_refused(world: World) -> None:
    result = world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=uuid4(), command_id=uuid4()
    )
    assert result.reason == "unknown_genome"


def test_every_command_is_refused_for_an_identity_that_is_not_the_owner(
    world: World,
) -> None:
    members = world.seed_members(POPULATION_FLOOR + 1)
    stranger = uuid4()
    genomes_before = world.count("genomes")

    assert seed(world, owner_id=stranger).reason == "not_owner"
    assert edit(world, owner_id=stranger).reason == "not_owner"
    retired = world.actions.retire_genome(
        owner_id=stranger, configuration_id=members[0], command_id=uuid4()
    )
    assert retired.reason == "not_owner"

    assert world.count("genomes") == genomes_before
    assert world.count("genome_owner_admissions") == 0
    assert world.count("genome_retirements") == 0


def test_the_retrospective_lists_every_owner_action(world: World) -> None:
    members = world.seed_members(POPULATION_FLOOR + 1)
    seed(world)
    edit(world)
    world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=members[0], command_id=uuid4()
    )
    admissions, retirements = world.actions.retrospective()
    assert sorted(record.kind for record in admissions) == ["edit", "seed"]
    assert [record.configuration_id for record in retirements] == [str(members[0])]


def test_owner_records_cannot_be_changed_or_removed(world: World) -> None:
    members = world.seed_members(POPULATION_FLOOR + 1)
    seed(world)
    world.actions.retire_genome(
        owner_id=OWNER_ID, configuration_id=members[0], command_id=uuid4()
    )
    with psycopg.connect(world.dsn, autocommit=True) as connection:
        for table in ("genome_owner_admissions", "genome_retirements"):
            with pytest.raises(psycopg.Error, match="immutable"):
                connection.execute(f"UPDATE {table} SET requested_at = now()")  # noqa: S608
            with pytest.raises(psycopg.Error, match="immutable"):
                connection.execute(f"DELETE FROM {table}")  # noqa: S608
