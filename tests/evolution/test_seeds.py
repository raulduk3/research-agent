"""The launch population fixture and its admission command (#311)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from research_agent.agents.configuration import (
    ASSEMBLED_PROMPT_MAX_CHARS,
    POLICY_FIELD_MAX_CHARS,
)
from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.genome import EMPHASIS_FIELDS, Genome
from research_agent.evolution.population import PopulationStore
from research_agent.evolution.seeds import (
    FOUNDER_PROCEDURE,
    LAUNCH_EMPHASES,
    SeedRefused,
    admit_seeds,
    load_seeds,
    main,
)
from research_agent.orchestration.scheduler import ISLANDS
from research_agent.platform.profile import (
    BudgetGroup,
    DisabledCapabilities,
    EvaluationGroup,
    LaunchProfile,
    ModelGroup,
    PrivacyGroup,
    RecoveryGroup,
    RunGroup,
    RuntimeGroup,
    SourceGroup,
    StorageGroup,
)
from research_agent.storage.database import Database

FIXTURE = Path(__file__).resolve().parents[2] / "docs" / "launch" / "seeds.json"
PROFILE_HASH = "a" * 64
OWNER_PROCEDURES = {"base-rate", "simulator", "skimmer-skeptic-expert", "meta-analyzer"}


def _raw() -> bytes:
    return FIXTURE.read_bytes()


def _edited(**changes: str) -> bytes:
    """The fixture with one procedure's parts replaced, keyed by part name."""

    fixture = json.loads(_raw())
    procedure = next(p for p in fixture["procedures"] if p["name"] == "simulator")
    procedure.update(changes)
    return json.dumps(fixture).encode()


def test_the_fixture_is_eight_procedures_in_each_of_three_islands() -> None:
    seeds = load_seeds(_raw(), run=RunGroup())

    assert len(seeds) == 24
    for island in ISLANDS:
        members = [s for s in seeds if s.configuration.island == island]
        assert {s.procedure for s in members} == set(LAUNCH_EMPHASES) | OWNER_PROCEDURES
        assert [s.procedure for s in members if s.configuration.founder] == [
            FOUNDER_PROCEDURE
        ]
    assert len({s.configuration.infra_hash for s in seeds}) == 1


def test_every_prompt_opens_with_the_common_instruction_and_fits_its_bounds() -> None:
    fixture = json.loads(_raw())
    common = fixture["common_instruction"]
    for procedure in fixture["procedures"]:
        assert procedure["prompt"].startswith(common + "\n\n")
        parts = [procedure[field] for field in EMPHASIS_FIELDS]
        assert all(len(part) <= POLICY_FIELD_MAX_CHARS for part in parts)
        assert sum(len(part) for part in parts) <= ASSEMBLED_PROMPT_MAX_CHARS
        # Rules, never a role.
        assert not any(re.search(r"\byou are\b", part, re.I) for part in parts)


def test_the_fixture_names_no_paper_identifier() -> None:
    text = _raw().decode()
    assert re.search(r"\d{4}\.\d{4,5}", text) is None
    assert re.search(r"[a-z-]+(\.[A-Z]{2})?/\d{7}", text) is None


def test_a_fixture_missing_a_launch_emphasis_is_refused() -> None:
    fixture = json.loads(_raw())
    fixture["procedures"][1]["name"] = "renamed"
    with pytest.raises(ContractValidationError, match="include"):
        load_seeds(json.dumps(fixture).encode(), run=RunGroup())


def test_a_prompt_without_the_common_instruction_is_refused() -> None:
    with pytest.raises(ContractValidationError, match="common instruction"):
        load_seeds(_edited(prompt="Procedure: guess."), run=RunGroup())


def test_a_part_naming_an_exclusion_action_is_refused() -> None:
    with pytest.raises(ContractValidationError, match="exclusion-action"):
        load_seeds(
            _edited(read_policy="Skip any paper under quarantine."), run=RunGroup()
        )


@pytest.fixture
def population(postgres_dsn: str, artifact_root: Path) -> PopulationStore:
    return PopulationStore(
        Database(postgres_dsn),
        ArtifactStore(artifact_root),
        producer=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )


def _genome_count(postgres_dsn: str) -> int:
    with Database(postgres_dsn).connect() as connection:
        row = connection.execute("SELECT count(*) FROM genomes").fetchone()
    assert row is not None
    return cast(int, row[0])


@pytest.mark.integration
def test_the_fixture_admits_into_an_empty_population_once(
    population: PopulationStore, postgres_dsn: str
) -> None:
    seeds = load_seeds(_raw(), run=RunGroup())

    first = admit_seeds(
        population, seeds, corpus_identifiers=(), profile_hash=PROFILE_HASH
    )
    assert len(first) == 24 and all(outcome.admitted for outcome in first)
    for island in ISLANDS:
        active, archived = population.island_population(island)
        assert len(active) == 8 and archived == ()
        founders = [genome for genome in active if genome.founder]
        assert [genome.lineage_id for genome in founders] == [
            f"{island}-{FOUNDER_PROCEDURE}"
        ]

    second = admit_seeds(
        population, seeds, corpus_identifiers=(), profile_hash=PROFILE_HASH
    )
    assert not any(outcome.admitted for outcome in second)
    assert [o.configuration_hash for o in second] == [
        o.configuration_hash for o in first
    ]
    assert _genome_count(postgres_dsn) == 24


@pytest.mark.integration
def test_one_island_admits_only_its_own_eight(
    population: PopulationStore, postgres_dsn: str
) -> None:
    outcomes = admit_seeds(
        population,
        load_seeds(_raw(), run=RunGroup()),
        corpus_identifiers=(),
        profile_hash=PROFILE_HASH,
        islands={"q-bio"},
    )
    assert {outcome.island for outcome in outcomes} == {"q-bio"}
    assert _genome_count(postgres_dsn) == 8


@pytest.mark.integration
def test_a_genome_carrying_a_paper_identifier_admits_nothing(
    population: PopulationStore, postgres_dsn: str
) -> None:
    seeds = load_seeds(
        _edited(scan_policy="Compare against 2409.01234 first."), run=RunGroup()
    )
    with pytest.raises(SeedRefused, match="scan_policy"):
        admit_seeds(
            population,
            seeds,
            corpus_identifiers=("2409.01234",),
            profile_hash=PROFILE_HASH,
        )
    assert _genome_count(postgres_dsn) == 0


@pytest.mark.integration
def test_an_island_with_another_founder_admits_nothing(
    population: PopulationStore, postgres_dsn: str
) -> None:
    seeds = load_seeds(_raw(), run=RunGroup())
    population.record_seed(
        configuration_id=uuid4(),
        genome=Genome(
            lineage_id="cs-earlier",
            island="cs",
            infra_hash=seeds[0].configuration.infra_hash,
            emphasis={field: "earlier founder" for field in EMPHASIS_FIELDS},
            founder=True,
        ),
        profile_hash=PROFILE_HASH,
        command_id=uuid4(),
    )
    with pytest.raises(SeedRefused, match="another founder"):
        admit_seeds(population, seeds, corpus_identifiers=(), profile_hash=PROFILE_HASH)
    assert _genome_count(postgres_dsn) == 1


def _profile_file(tmp_path: Path) -> Path:
    profile = LaunchProfile(
        profile_version="launch-v2",
        runtime=RuntimeGroup(python_version="3.12.12", uv_version="0.8.22"),
        storage=StorageGroup(
            postgres_version="17",
            backup_endpoint_bound=True,
            anchor_endpoint_bound=True,
        ),
        model=ModelGroup(
            agent_model_id="glm-5.3-flash",
            agent_provider="z.ai",
            embedding_model_revision="d556a88e332558790b210f7bdbe87da2fa94a8d8",
            agent_qualification_passed=True,
        ),
        source=SourceGroup(licensed_source_ids=frozenset({"arxiv"})),
        budget=BudgetGroup(
            paid_execution_enabled=False,
            daily_cap_usd="8",
            monthly_cap_usd="200",
            funded=False,
        ),
        evaluation=EvaluationGroup(replay_integrity_verified=True),
        privacy=PrivacyGroup(retention_years=2),
        recovery=RecoveryGroup(backup_verified=True),
        disabled_capabilities=DisabledCapabilities(capability_ids=frozenset()),
    )
    path = tmp_path / "profile.json"
    path.write_bytes(canonical_json(profile.to_dict()))
    return path


@pytest.mark.integration
def test_the_command_prints_each_hash_and_refuses_a_listed_identifier(
    postgres_dsn: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    common = [
        "--file",
        str(FIXTURE),
        "--state",
        str(tmp_path),
        "--dsn",
        postgres_dsn,
        "--profile",
        str(_profile_file(tmp_path)),
    ]
    assert main([*common, "--island", "cs"]) == 0
    out = capsys.readouterr().out
    assert out.count("admitted ") == 8
    assert "island cs: 8 active, 0 archived, founder cs-evidence-first" in out

    assert main([*common, "--island", "cs"]) == 0
    assert "admitted " not in capsys.readouterr().out

    identifiers = tmp_path / "ids.txt"
    identifiers.write_text("Procedure\n")
    assert main([*common, "--corpus-ids", str(identifiers)]) == 1
    assert "corpus paper identifier" in capsys.readouterr().err
    assert _genome_count(postgres_dsn) == 8
