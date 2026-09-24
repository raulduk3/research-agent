"""Admit the launch population from a committed fixture (AG-03, AG-16, AG-38).

The fixture (``docs/launch/seeds.json``) names eight procedures, each
written once and admitted into every island, so each island holds the
same eight and the population twenty-four. Four are Appendix A's launch
emphases, whose twelve configurations pass the seed manifest's own boundary
(``agents/configuration.py#validate_seeded_population``); the other four are
owner-written variants admitted under AG-03 before the first cycle. Every
genome shares the launch profile's per-run tools and budgets, one sample
and the protected output core, so only the four emphasis parts vary.

Admission runs the same checks the owner's seed form does: the AG-16
bounds, no exclusion action named in the assembled prompt (AG-24), no
corpus paper identifier in any part (AG-31), and a hash comparison against
the island's active and archived genomes. A genome already admitted is
reported, not written again, so a second run admits nothing. The whole
fixture is checked before anything is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from research_agent.agents.admission import reject_paper_identifiers
from research_agent.agents.configuration import (
    LAUNCH_SAMPLING_COUNT,
    AgentConfiguration,
    validate_seeded_population,
)
from research_agent.agents.messages import assemble_system_prompt
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
)
from research_agent.contracts.turns import PROTECTED_CORE_SCHEMA
from research_agent.evolution.genome import EMPHASIS_FIELDS, Genome
from research_agent.evolution.population import PopulationStore
from research_agent.orchestration.scheduler import ISLANDS
from research_agent.platform.producer import source_commit
from research_agent.platform.profile import RunGroup

FIXTURE_SCHEMA_VERSION = 1

#: Appendix A's four launch emphases; the first is each island's founder (AG-38).
LAUNCH_EMPHASES = (
    "evidence-first",
    "methods-and-assumptions",
    "earlier-related-work",
    "limitations-and-alternatives",
)
FOUNDER_PROCEDURE = LAUNCH_EMPHASES[0]
PROCEDURES_PER_ISLAND = 8

_PROCEDURE_FIELDS = frozenset({"name", *EMPHASIS_FIELDS})


@dataclass(frozen=True, slots=True)
class SeedGenome:
    """One fixture procedure placed in one island."""

    procedure: str
    lineage_id: str
    configuration: AgentConfiguration

    @property
    def genome(self) -> Genome:
        return self.configuration.to_genome(lineage_id=self.lineage_id)


@dataclass(frozen=True, slots=True)
class SeedOutcome:
    """What one seed run did with one genome."""

    island: str
    lineage_id: str
    configuration_hash: str
    founder: bool
    admitted: bool


class SeedRefused(Exception):
    """The fixture, or one genome in it, may not enter the population."""


def _closed(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} must hold exactly {sorted(fields)}")
    return value


def load_seeds(raw: bytes, *, run: RunGroup) -> tuple[SeedGenome, ...]:
    """Parse and validate the fixture into every island's genomes.

    Refuses the whole fixture when it is not exactly eight distinct
    procedures including the four launch emphases, when a prompt does not
    begin with the common instruction, when an assembled prompt exceeds its
    bounds or names an exclusion action (AG-24), or when the launch
    emphases do not form AG-03's seeded population.
    """

    fixture = _closed(
        json.loads(raw),
        frozenset({"schema_version", "common_instruction", "procedures"}),
        "seed fixture",
    )
    if fixture["schema_version"] != FIXTURE_SCHEMA_VERSION:
        raise ContractValidationError(
            f"seed fixture schema_version must be {FIXTURE_SCHEMA_VERSION}"
        )
    common = validate_non_empty_string(fixture["common_instruction"])
    procedures = fixture["procedures"]
    if not isinstance(procedures, list) or len(procedures) != PROCEDURES_PER_ISLAND:
        raise ContractValidationError(
            f"seed fixture must hold exactly {PROCEDURES_PER_ISLAND} procedures"
        )
    names = [
        _closed(item, _PROCEDURE_FIELDS, "procedure")["name"] for item in procedures
    ]
    if len(set(names)) != len(names) or not set(LAUNCH_EMPHASES) <= set(names):
        raise ContractValidationError(
            f"procedures must be distinct and include {list(LAUNCH_EMPHASES)}"
        )

    seeds: list[SeedGenome] = []
    for procedure in procedures:
        name = validate_non_empty_string(procedure["name"])
        parts = {field: procedure[field] for field in sorted(EMPHASIS_FIELDS)}
        if not isinstance(parts["prompt"], str) or not parts["prompt"].startswith(
            common
        ):
            raise ContractValidationError(
                f"procedure {name!r} prompt must begin with the common instruction"
            )
        assemble_system_prompt(
            "\n\n".join(str(parts[field]) for field in sorted(EMPHASIS_FIELDS))
        )
        for island in sorted(ISLANDS):
            configuration = AgentConfiguration(
                island=island,
                founder=name == FOUNDER_PROCEDURE,
                tools=tuple(sorted(run.allowed_tools)),
                budgets=run.budgets(),
                sampling={"count": LAUNCH_SAMPLING_COUNT},
                output_schema=PROTECTED_CORE_SCHEMA,
                **parts,
            )
            seeds.append(SeedGenome(name, f"{island}-{name}", configuration))

    validate_seeded_population(
        [seed.configuration for seed in seeds if seed.procedure in LAUNCH_EMPHASES]
    )
    if len({seed.configuration.configuration_hash for seed in seeds}) != len(seeds):
        raise ContractValidationError("seed fixture must not repeat a configuration")
    return tuple(seeds)


def admit_seeds(
    population: PopulationStore,
    seeds: Sequence[SeedGenome],
    *,
    corpus_identifiers: Collection[str],
    profile_hash: str,
    islands: Collection[str] = ISLANDS,
) -> tuple[SeedOutcome, ...]:
    """Admit every seed of *islands* not already in the population.

    Refuses before writing anything when any genome carries a corpus paper
    identifier (AG-31) or when an island already holds a founder other than
    the fixture's own. A genome whose hash an island already holds, active
    or archived, is reported as present rather than written again.
    """

    chosen = [seed for seed in seeds if seed.configuration.island in islands]
    for seed in chosen:
        offending = reject_paper_identifiers(
            seed.configuration.emphasis, corpus_identifiers=corpus_identifiers
        )
        if offending:
            raise SeedRefused(
                f"{seed.lineage_id} carries a corpus paper identifier in "
                + ", ".join(offending)
            )

    held: dict[str, set[str]] = {}
    for island in sorted({seed.configuration.island for seed in chosen}):
        active, archived = population.island_population(island)
        held[island] = {genome.configuration_hash for genome in (*active, *archived)}
        founders = {
            genome.configuration_hash
            for genome in (*active, *archived)
            if genome.founder
        }
        fixture_founders = {
            seed.configuration.configuration_hash
            for seed in chosen
            if seed.configuration.island == island and seed.configuration.founder
        }
        if founders - fixture_founders:
            raise SeedRefused(f"island {island} already has another founder")

    outcomes: list[SeedOutcome] = []
    for seed in chosen:
        configuration = seed.configuration
        present = configuration.configuration_hash in held[configuration.island]
        if not present:
            population.record_seed(
                configuration_id=uuid4(),
                genome=seed.genome,
                profile_hash=profile_hash,
                command_id=uuid4(),
            )
        outcomes.append(
            SeedOutcome(
                island=configuration.island,
                lineage_id=seed.lineage_id,
                configuration_hash=configuration.configuration_hash,
                founder=configuration.founder,
                admitted=not present,
            )
        )
    return tuple(outcomes)


def main(argv: list[str] | None = None) -> int:
    from research_agent.artifacts.store import ArtifactStore
    from research_agent.contracts import ProducerVersion
    from research_agent.platform.producer import SourceCommitUnavailable
    from research_agent.platform.profile import LaunchProfile
    from research_agent.storage.database import Database
    from research_agent.storage.migrate import require_schema

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--island", choices=sorted(ISLANDS))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--corpus-ids",
        type=Path,
        help="a file of corpus paper identifiers, one per line (AG-31)",
    )
    args = parser.parse_args(argv)

    try:
        producer = ProducerVersion(
            hashlib.sha256(b"local-process").hexdigest(), source_commit(), 1
        )
    except SourceCommitUnavailable as error:
        print(f"seed refused: {error}", file=sys.stderr)
        return 1
    raw = cast(Path, args.file).read_bytes()
    profile = LaunchProfile.from_json(cast(Path, args.profile).read_bytes())
    database = Database(args.dsn)
    require_schema(database)
    identifiers = {
        str(row[0])
        for row in database.transaction(
            lambda connection: connection.execute(
                "SELECT DISTINCT paper_id FROM runs"
            ).fetchall()
        )
    }
    if args.corpus_ids is not None:
        identifiers |= {
            line.strip()
            for line in cast(Path, args.corpus_ids).read_text().splitlines()
            if line.strip()
        }
    population = PopulationStore(
        database,
        ArtifactStore(cast(Path, args.state) / "artifacts"),
        producer=producer,
        config_hash=hashlib.sha256(raw).hexdigest(),
        retention_policy_hash=hashlib.sha256(
            b"Genome admissions are retained with the ledger for this research."
        ).hexdigest(),
    )
    try:
        outcomes = admit_seeds(
            population,
            load_seeds(raw, run=profile.run),
            corpus_identifiers=identifiers,
            profile_hash=profile.compute_hash(),
            islands=ISLANDS if args.island is None else {args.island},
        )
    except (ContractValidationError, SeedRefused) as error:
        print(f"seed refused: {error}", file=sys.stderr)
        return 1
    for outcome in outcomes:
        print(
            "admitted" if outcome.admitted else "present ",
            outcome.configuration_hash,
            outcome.lineage_id,
            "founder" if outcome.founder else "",
        )
    for island in sorted({outcome.island for outcome in outcomes}):
        active, archived = population.island_population(island)
        founders = [genome.lineage_id for genome in active if genome.founder]
        print(
            f"island {island}: {len(active)} active, {len(archived)} archived, "
            f"founder {', '.join(founders) or 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
