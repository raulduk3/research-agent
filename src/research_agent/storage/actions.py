"""Owner commands over the population store: admit, retire, seed (#139).

Three owner-authored writes layered over the population store
``evolution/population.py#PopulationStore`` already owns: admit an edited
genome as a new child (AG-16, AG-20, SR-19), retire a genome at the next
selection cycle, and seed a variant into a chosen island (AG-03). Each
records that an owner, not FT-14's automatic selection or the initial seed
activation, requested it (``genome_owner_admissions``,
``genome_retirements``), naming the owner and the time. Nothing already
stored changes: the source genome of an edit stays untouched, and a
retirement names no run, claim or score -- it only marks a genome for
removal from the active population at the next selection cycle; the
diversity archive still follows FT-15's own rule whenever that cycle
retires the genome's lineage.

This module reaches storage directly through :class:`Database`, the same
boundary ``PopulationStore`` and ``RaterRepository`` already draw, rather
than through the mutually-authenticated HTTP client boundary
``storage/http.py`` exposes for the rating and inspector apps: the owner
actions app is single-host, owner-only tooling on the same application host
as storage (Appendix A), not a second network-facing service.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import UUID

from psycopg import Connection

from research_agent.agents.admission import reject_paper_identifiers
from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.admission import admit_child
from research_agent.evolution.genome import Genome
from research_agent.evolution.mutation import propose_mutation
from research_agent.evolution.population import PopulationStore
from research_agent.orchestration.scheduler import ISLANDS
from research_agent.storage.commands import DomainEvents
from research_agent.storage.database import Database

#: SDD Appendix A: "the floor is four genomes per island"; a retirement
#: request is refused, never queued, when it would cross it.
POPULATION_FLOOR = 4

RefusalReason = Literal[
    "not_owner",
    "unknown_source_genome",
    "cycle_disabled",
    "invalid_edit",
    "corpus_identifier",
    "duplicate_genome",
    "unknown_genome",
    "already_retired",
    "founder_not_retirable",
    "population_floor",
    "budget_not_funded",
]


@dataclass(frozen=True, slots=True)
class OwnerActionResult:
    """What an owner sees after one command; never filled in speculatively."""

    accepted: bool
    configuration_id: str | None
    reason: RefusalReason | None


@dataclass(frozen=True, slots=True)
class OwnerAdmissionRecord:
    configuration_id: str
    owner_id: str
    kind: Literal["edit", "seed"]
    source_configuration_id: str | None
    requested_at: str


@dataclass(frozen=True, slots=True)
class RetirementRecord:
    configuration_id: str
    owner_id: str
    requested_at: str


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class OwnerActions:
    """The owner's three commands over the population store, and their history."""

    def __init__(
        self,
        database: Database,
        store: ArtifactStore,
        *,
        producer: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
    ) -> None:
        self._database = database
        self._population = PopulationStore(
            database,
            store,
            producer=producer,
            config_hash=config_hash,
            retention_policy_hash=retention_policy_hash,
        )
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def admit_edited_genome(
        self,
        *,
        owner_id: UUID,
        source_configuration_id: UUID,
        new_configuration_id: UUID,
        changes: Mapping[str, str],
        lineage_id: str,
        corpus_identifiers: Collection[str],
        completed_weekly_cycles: int | None,
        profile_hash: str | None,
        command_id: UUID,
    ) -> OwnerActionResult:
        """Admit *changes* to one emphasis part of a stored genome as a new genome.

        The form is prefilled from the stored genome named by
        *source_configuration_id*; submitting more than one changed part, or
        a part outside AG-20's four emphasis-carrying parts, is refused
        whole by the same cycle-gated mutation boundary FT-14's own
        performance mutation uses -- no separate owner-only mutation rule
        exists. The source genome is never written to.
        """

        if not self._is_owner(owner_id):
            return OwnerActionResult(False, None, "not_owner")
        source = self._read_genome(source_configuration_id)
        if source is None:
            return OwnerActionResult(False, None, "unknown_source_genome")
        try:
            mutation = propose_mutation(
                parent=source,
                changes=changes,
                lineage_id=lineage_id,
                completed_weekly_cycles=completed_weekly_cycles,
                profile_hash=profile_hash,
            )
        except ContractValidationError:
            return OwnerActionResult(False, None, "cycle_disabled")
        if mutation.disposition == "disabled_by_profile":
            return OwnerActionResult(False, None, "cycle_disabled")
        if mutation.disposition != "accepted" or mutation.child is None:
            return OwnerActionResult(False, None, "invalid_edit")
        child = mutation.child

        if reject_paper_identifiers(
            dict(child.emphasis), corpus_identifiers=corpus_identifiers
        ):
            return OwnerActionResult(False, None, "corpus_identifier")

        active, archived = self._population.island_population(child.island)
        admission = admit_child(
            child=child,
            active_genomes=active,
            archived_genomes=archived,
            completed_weekly_cycles=completed_weekly_cycles,
            profile_hash=profile_hash,
        )
        if admission.disposition != "accepted":
            return OwnerActionResult(False, None, "duplicate_genome")

        self._population.record_child(
            configuration_id=new_configuration_id,
            child=child,
            admission=admission,
            command_id=command_id,
        )
        self._record_owner_admission(
            configuration_id=new_configuration_id,
            owner_id=owner_id,
            kind="edit",
            source_configuration_id=source_configuration_id,
            command_id=command_id,
        )
        return OwnerActionResult(True, str(new_configuration_id), None)

    def seed_variant(
        self,
        *,
        owner_id: UUID,
        new_configuration_id: UUID,
        island: str,
        lineage_id: str,
        emphasis: Mapping[str, str],
        template_configuration_id: UUID,
        corpus_identifiers: Collection[str],
        profile_hash: str,
        budget_funded: bool,
        command_id: UUID,
    ) -> OwnerActionResult:
        """Admit a blank or copied form as a new, parentless genome in *island*.

        *emphasis* is the owner's four policy parts; every other part
        (tools, budgets, sampling, output schema) is copied from the
        genome named by *template_configuration_id*, since AG-03 permits
        only the declared reading emphasis to vary. Refused with
        ``budget_not_funded`` when the launch profile's funded-inference
        gate is not met -- the budget ceiling this command enforces, ahead
        of the per-island spend-share ceiling a future weekly-cycle
        integration computes (orchestration/selection.py#select_population).
        """

        if island not in ISLANDS:
            raise ContractValidationError(f"island must be one of {sorted(ISLANDS)}")
        if not self._is_owner(owner_id):
            return OwnerActionResult(False, None, "not_owner")
        if not budget_funded:
            return OwnerActionResult(False, None, "budget_not_funded")
        template = self._read_genome(template_configuration_id)
        if template is None:
            return OwnerActionResult(False, None, "unknown_source_genome")

        genome = Genome(
            lineage_id=lineage_id,
            island=island,
            infra_hash=template.infra_hash,
            emphasis=emphasis,
            founder=False,
            parent_hash=None,
        )
        if reject_paper_identifiers(
            dict(genome.emphasis), corpus_identifiers=corpus_identifiers
        ):
            return OwnerActionResult(False, None, "corpus_identifier")

        active, archived = self._population.island_population(island)
        if any(
            existing.configuration_hash == genome.configuration_hash
            for existing in (*active, *archived)
        ):
            return OwnerActionResult(False, None, "duplicate_genome")

        self._population.record_seed(
            configuration_id=new_configuration_id,
            genome=genome,
            profile_hash=profile_hash,
            command_id=command_id,
        )
        self._record_owner_admission(
            configuration_id=new_configuration_id,
            owner_id=owner_id,
            kind="seed",
            source_configuration_id=None,
            command_id=command_id,
        )
        return OwnerActionResult(True, str(new_configuration_id), None)

    def retire_genome(
        self, *, owner_id: UUID, configuration_id: UUID, command_id: UUID
    ) -> OwnerActionResult:
        """Record an owner's request to remove *configuration_id* at the next cycle.

        Refuses a founder (AG-38 exempts it from replacement), a genome
        already requested, and a request that would leave its island below
        the population floor of four genomes. Names no run, claim or score:
        those stay exactly as sealed, and the diversity archive keeps this
        genome under FT-15's existing rule whenever a select stage later
        retires its lineage.
        """

        def act(connection: Connection[tuple[object, ...]]) -> OwnerActionResult:
            owner = connection.execute(
                "SELECT 1 FROM owner_principals WHERE owner_id=%s", (owner_id,)
            ).fetchone()
            if owner is None:
                return OwnerActionResult(False, None, "not_owner")
            row = connection.execute(
                "SELECT island, founder FROM genomes WHERE configuration_id=%s",
                (configuration_id,),
            ).fetchone()
            if row is None:
                return OwnerActionResult(False, None, "unknown_genome")
            island, founder = cast(str, row[0]), cast(bool, row[1])
            if founder:
                return OwnerActionResult(False, None, "founder_not_retirable")
            already = connection.execute(
                "SELECT 1 FROM genome_retirements WHERE configuration_id=%s",
                (configuration_id,),
            ).fetchone()
            if already is not None:
                return OwnerActionResult(False, None, "already_retired")
            count_row = connection.execute(
                """SELECT count(*) FROM genomes g
                   WHERE g.island = %s
                     AND NOT EXISTS (
                         SELECT 1 FROM genome_archive a
                         WHERE a.configuration_id = g.configuration_id)
                     AND NOT EXISTS (
                         SELECT 1 FROM genome_retirements r
                         WHERE r.configuration_id = g.configuration_id)""",
                (island,),
            ).fetchone()
            assert count_row is not None
            if cast(int, count_row[0]) <= POPULATION_FLOOR:
                return OwnerActionResult(False, None, "population_floor")

            requested_at = datetime.now(timezone.utc)
            self._events.append(
                connection,
                command_id=command_id,
                event_kind="genome_retirement_requested",
                payload={
                    "schema_version": 1,
                    "configuration_id": str(configuration_id),
                    "owner_id": str(owner_id),
                    "requested_at": _utc(requested_at),
                },
                input_hashes=(),
            )
            connection.execute(
                """INSERT INTO genome_retirements(configuration_id, owner_id, requested_at)
                   VALUES (%s, %s, %s)""",
                (configuration_id, owner_id, requested_at),
            )
            return OwnerActionResult(True, str(configuration_id), None)

        return self._database.serializable(act)

    def read_genome_view(self, configuration_id: UUID) -> dict[str, object] | None:
        """A plain projection of one genome's identity, for prefilling a form.

        Returns exactly the fields an edit-and-admit or seed-a-variant form
        needs -- island, founder, the four emphasis parts and the
        configuration hash -- and nothing storage does not hold; ``None``
        when the population store admits no such configuration.
        """

        genome = self._read_genome(configuration_id)
        if genome is None:
            return None
        return {
            "configuration_id": str(configuration_id),
            "configuration_hash": genome.configuration_hash,
            "island": genome.island,
            "founder": genome.founder,
            "lineage_id": genome.lineage_id,
            "emphasis": dict(genome.emphasis),
        }

    def admission_history(self, configuration_id: UUID) -> OwnerAdmissionRecord | None:
        """The owner admission record naming *configuration_id*, if any."""

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[object, ...] | None:
            return connection.execute(
                """SELECT configuration_id, owner_id, kind,
                          source_configuration_id, requested_at
                   FROM genome_owner_admissions WHERE configuration_id=%s""",
                (configuration_id,),
            ).fetchone()

        row = self._database.transaction(read)
        return None if row is None else _admission_from_row(row)

    def retirement_status(self, configuration_id: UUID) -> RetirementRecord | None:
        """The owner retirement record naming *configuration_id*, if any."""

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[object, ...] | None:
            return connection.execute(
                """SELECT configuration_id, owner_id, requested_at
                   FROM genome_retirements WHERE configuration_id=%s""",
                (configuration_id,),
            ).fetchone()

        row = self._database.transaction(read)
        return None if row is None else _retirement_from_row(row)

    def retrospective(
        self,
    ) -> tuple[tuple[OwnerAdmissionRecord, ...], tuple[RetirementRecord, ...]]:
        """Every owner admission and retirement recorded so far, newest first."""

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
            admissions = connection.execute(
                """SELECT configuration_id, owner_id, kind,
                          source_configuration_id, requested_at
                   FROM genome_owner_admissions ORDER BY requested_at DESC"""
            ).fetchall()
            retirements = connection.execute(
                """SELECT configuration_id, owner_id, requested_at
                   FROM genome_retirements ORDER BY requested_at DESC"""
            ).fetchall()
            return admissions, retirements

        admissions, retirements = self._database.transaction(read)
        return (
            tuple(_admission_from_row(row) for row in admissions),
            tuple(_retirement_from_row(row) for row in retirements),
        )

    def _is_owner(self, owner_id: UUID) -> bool:
        def read(connection: Connection[tuple[object, ...]]) -> bool:
            return (
                connection.execute(
                    "SELECT 1 FROM owner_principals WHERE owner_id=%s", (owner_id,)
                ).fetchone()
                is not None
            )

        return self._database.transaction(read)

    def _record_owner_admission(
        self,
        *,
        configuration_id: UUID,
        owner_id: UUID,
        kind: Literal["edit", "seed"],
        source_configuration_id: UUID | None,
        command_id: UUID,
    ) -> None:
        def write(connection: Connection[tuple[object, ...]]) -> None:
            requested_at = datetime.now(timezone.utc)
            self._events.append(
                connection,
                command_id=command_id,
                event_kind="genome_owner_admission_recorded",
                payload={
                    "schema_version": 1,
                    "configuration_id": str(configuration_id),
                    "owner_id": str(owner_id),
                    "kind": kind,
                    "source_configuration_id": (
                        str(source_configuration_id)
                        if source_configuration_id is not None
                        else None
                    ),
                    "requested_at": _utc(requested_at),
                },
                input_hashes=(),
            )
            connection.execute(
                """INSERT INTO genome_owner_admissions(
                       configuration_id, owner_id, kind,
                       source_configuration_id, requested_at
                   ) VALUES (%s, %s, %s, %s, %s)""",
                (
                    configuration_id,
                    owner_id,
                    kind,
                    source_configuration_id,
                    requested_at,
                ),
            )

        self._database.serializable(write)

    def _read_genome(self, configuration_id: UUID) -> Genome | None:
        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[object, ...] | None:
            return connection.execute(
                """SELECT lineage_id, island, founder,
                          encode(infra_hash,'hex'), encode(parent_hash,'hex')
                   FROM genomes WHERE configuration_id=%s""",
                (configuration_id,),
            ).fetchone()

        def parts(
            connection: Connection[tuple[object, ...]],
        ) -> dict[str, str]:
            rows = connection.execute(
                """SELECT part, value FROM genome_parts WHERE configuration_id=%s""",
                (configuration_id,),
            ).fetchall()
            return {cast(str, part): cast(str, value) for part, value in rows}

        row, emphasis = self._database.transaction(
            lambda connection: (read(connection), parts(connection))
        )
        if row is None:
            return None
        return Genome(
            lineage_id=cast(str, row[0]),
            island=cast(str, row[1]),
            infra_hash=cast(str, row[3]),
            emphasis=emphasis,
            founder=cast(bool, row[2]),
            parent_hash=cast("str | None", row[4]),
        )


def _admission_from_row(row: tuple[object, ...]) -> OwnerAdmissionRecord:
    return OwnerAdmissionRecord(
        configuration_id=str(cast(UUID, row[0])),
        owner_id=str(cast(UUID, row[1])),
        kind=cast('Literal["edit", "seed"]', row[2]),
        source_configuration_id=(None if row[3] is None else str(cast(UUID, row[3]))),
        requested_at=_utc(cast(datetime, row[4])),
    )


def _retirement_from_row(row: tuple[object, ...]) -> RetirementRecord:
    return RetirementRecord(
        configuration_id=str(cast(UUID, row[0])),
        owner_id=str(cast(UUID, row[1])),
        requested_at=_utc(cast(datetime, row[2])),
    )
