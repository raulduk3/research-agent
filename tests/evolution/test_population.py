from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from tests.evolution.genome_fixtures import PROFILE_HASH, genome

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.admission import AdmissionResult, admit_child
from research_agent.evolution.population import PopulationStore
from research_agent.orchestration.selection import ArchivedGenome, SelectionEvent
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput

pytestmark = pytest.mark.integration


@pytest.fixture
def population(postgres_dsn: str, artifact_root: Path) -> PopulationStore:
    return PopulationStore(
        Database(postgres_dsn),
        ArtifactStore(artifact_root),
        producer=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )


def _ledger_kinds(postgres_dsn: str) -> list[str]:
    with Database(postgres_dsn).connect() as connection:
        rows = connection.execute(
            "SELECT event_kind FROM ledger_records ORDER BY sequence"
        ).fetchall()
    return [str(row[0]) for row in rows]


def _event(*archived: ArchivedGenome, cycle_id: str = "cycle-3") -> SelectionEvent:
    return SelectionEvent(
        cycle_id=cycle_id,
        profile_hash=PROFILE_HASH,
        disposition="selected",
        results={},
        archived=archived,
    )


def test_a_stored_island_feeds_admission_and_refuses_an_archived_repeat(
    population: PopulationStore,
) -> None:
    founder = genome(lineage_id="lineage-1", founder=True)
    population.record_seed(
        configuration_id=uuid4(),
        genome=founder,
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    population.record_archive(
        _event(ArchivedGenome(founder.configuration_hash, "cs", "lineage-1", 0.3, 30)),
        command_id=uuid4(),
    )
    active, archived = population.island_population("cs")
    assert active == ()
    assert archived == (founder,)

    repeat = genome(lineage_id="lineage-1", founder=True)
    result = admit_child(
        child=repeat,
        active_genomes=active,
        archived_genomes=archived,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert result.disposition == "rejected"
    assert result.matched_hash == founder.configuration_hash


def test_an_accepted_child_is_stored_with_its_parent_and_returned_active(
    population: PopulationStore,
) -> None:
    founder = genome(lineage_id="lineage-1", founder=True)
    population.record_seed(
        configuration_id=uuid4(),
        genome=founder,
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    child = genome(
        lineage_id="lineage-1", prompt="child", parent_hash=founder.configuration_hash
    )
    active, archived = population.island_population("cs")
    admission = admit_child(
        child=child,
        active_genomes=active,
        archived_genomes=archived,
        completed_weekly_cycles=2,
        profile_hash=PROFILE_HASH,
    )
    assert admission.disposition == "accepted"

    population.record_child(
        configuration_id=uuid4(),
        child=child,
        admission=admission,
        command_id=uuid4(),
    )

    assert population.island_population("cs") == ((founder, child), ())
    assert population.island_population("quant-ph") == ((), ())


def test_only_an_accepted_admission_for_this_child_is_stored(
    population: PopulationStore,
) -> None:
    founder = genome(lineage_id="lineage-1", founder=True)
    child = genome(
        lineage_id="lineage-1", prompt="child", parent_hash=founder.configuration_hash
    )
    with pytest.raises(ContractValidationError):
        population.record_child(
            configuration_id=uuid4(),
            child=child,
            admission=AdmissionResult(
                "rejected", PROFILE_HASH, child.configuration_hash
            ),
            command_id=uuid4(),
        )
    with pytest.raises(ContractValidationError):
        population.record_child(
            configuration_id=uuid4(),
            child=child,
            admission=AdmissionResult("accepted", PROFILE_HASH, "0" * 64),
            command_id=uuid4(),
        )
    with pytest.raises(UnavailableInput):
        population.record_child(
            configuration_id=uuid4(),
            child=child,
            admission=AdmissionResult(
                "accepted", PROFILE_HASH, child.configuration_hash
            ),
            command_id=uuid4(),
        )
    with pytest.raises(ContractValidationError):
        population.record_seed(
            configuration_id=uuid4(),
            genome=child,
            profile_hash=PROFILE_HASH,
            command_id=uuid4(),
        )


def test_a_replayed_admission_appends_nothing_and_a_changed_one_conflicts(
    population: PopulationStore, postgres_dsn: str
) -> None:
    configuration_id = uuid4()
    founder = genome(lineage_id="lineage-1", founder=True)
    for _ in range(2):
        population.record_seed(
            configuration_id=configuration_id,
            genome=founder,
            profile_hash=PROFILE_HASH,
            command_id=uuid4(),
        )
    assert _ledger_kinds(postgres_dsn) == ["genome_admitted"]

    with pytest.raises(StateConflict):
        population.record_seed(
            configuration_id=configuration_id,
            genome=genome(lineage_id="lineage-2", founder=True),
            profile_hash=PROFILE_HASH,
            command_id=uuid4(),
        )
    with pytest.raises(StateConflict):
        population.record_seed(
            configuration_id=uuid4(),
            genome=founder,
            profile_hash=PROFILE_HASH,
            command_id=uuid4(),
        )


def test_an_archive_is_written_once_and_a_differing_replay_conflicts(
    population: PopulationStore, postgres_dsn: str
) -> None:
    founders = [
        genome(lineage_id=f"lineage-{index}", founder=True) for index in range(2)
    ]
    for founder in founders:
        population.record_seed(
            configuration_id=uuid4(),
            genome=founder,
            profile_hash=PROFILE_HASH,
            command_id=uuid4(),
        )
    entries = tuple(
        ArchivedGenome(founder.configuration_hash, "cs", founder.lineage_id, 0.3, 30)
        for founder in founders
    )

    population.record_archive(_event(*entries), command_id=uuid4())
    population.record_archive(_event(*entries), command_id=uuid4())

    assert _ledger_kinds(postgres_dsn).count("genome_archived") == 1
    assert population.island_population("cs") == ((), tuple(founders))
    with pytest.raises(StateConflict):
        population.record_archive(
            _event(*entries, cycle_id="cycle-4"), command_id=uuid4()
        )


def test_an_archive_naming_an_unadmitted_or_mismatched_genome_is_refused(
    population: PopulationStore, postgres_dsn: str
) -> None:
    founder = genome(lineage_id="lineage-1", founder=True)
    with pytest.raises(UnavailableInput):
        population.record_archive(
            _event(
                ArchivedGenome(founder.configuration_hash, "cs", "lineage-1", 0.3, 30)
            ),
            command_id=uuid4(),
        )
    population.record_seed(
        configuration_id=uuid4(),
        genome=founder,
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    with pytest.raises(ContractValidationError):
        population.record_archive(
            _event(
                ArchivedGenome(founder.configuration_hash, "cs", "lineage-9", 0.3, 30)
            ),
            command_id=uuid4(),
        )
    assert _ledger_kinds(postgres_dsn) == ["genome_admitted"]


def test_a_record_written_within_the_admission_fails_with_it(
    population: PopulationStore, postgres_dsn: str
) -> None:
    founder = genome(lineage_id="lineage-1", founder=True)
    population.record_seed(
        configuration_id=uuid4(),
        genome=founder,
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    child = genome(
        lineage_id="lineage-1", prompt="child", parent_hash=founder.configuration_hash
    )
    admission = AdmissionResult("accepted", PROFILE_HASH, child.configuration_hash)

    def fail(connection: object) -> None:
        raise RuntimeError("injected after the genome write")

    with pytest.raises(RuntimeError):
        population.record_child(
            configuration_id=uuid4(),
            child=child,
            admission=admission,
            command_id=uuid4(),
            within=fail,
        )

    assert population.island_population("cs") == ((founder,), ())
    assert _ledger_kinds(postgres_dsn) == ["genome_admitted"]
