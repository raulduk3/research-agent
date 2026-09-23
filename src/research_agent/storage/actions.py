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

This module is storage's own side of the owner boundary: it reaches the
database through :class:`Database`, as ``PopulationStore`` and
``RaterRepository`` do, and ``storage/http.py`` serves it to the owner
actions app under the ``owner`` role (#234). The app holds a
``StorageClient``; the result and record types it reads back are defined in
``storage/client.py`` so it imports nothing from here.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Literal, cast
from uuid import UUID

from psycopg import Connection

from research_agent.agents.admission import reject_paper_identifiers
from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.primitives import ContractValidationError, validate_uuid4
from research_agent.evolution.admission import admit_child
from research_agent.evolution.genome import Genome
from research_agent.evolution.mutation import propose_mutation
from research_agent.evolution.population import PopulationStore
from research_agent.orchestration.scheduler import ISLANDS
from research_agent.storage.client import (
    OwnerActionResult,
    OwnerAdmissionRecord,
    RetirementRecord,
)
from research_agent.storage.commands import DomainEvents
from research_agent.storage.database import Database

#: SDD Appendix A: "the floor is four genomes per island"; a retirement
#: request is refused, never queued, when it would cross it.
POPULATION_FLOOR = 4


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

    def execute(
        self, operation: str, *, command_id: UUID, payload: object
    ) -> dict[str, Any]:
        """Run one owner command from its wire payload, as the storage route does.

        A payload that is not exactly the command's closed shape raises
        :class:`ContractValidationError`; every other refusal is a result.
        """

        if operation == "admit":
            body = _closed(
                payload,
                {
                    "owner_id",
                    "source_configuration_id",
                    "new_configuration_id",
                    "changes",
                    "lineage_id",
                    "corpus_identifiers",
                    "completed_weekly_cycles",
                    "profile_hash",
                },
            )
            result = self.admit_edited_genome(
                owner_id=_uuid(body["owner_id"]),
                source_configuration_id=_uuid(body["source_configuration_id"]),
                new_configuration_id=_uuid(body["new_configuration_id"]),
                changes=_text_map(body["changes"]),
                lineage_id=_text(body["lineage_id"]),
                corpus_identifiers=_text_list(body["corpus_identifiers"]),
                completed_weekly_cycles=_optional_count(
                    body["completed_weekly_cycles"]
                ),
                profile_hash=_optional_text(body["profile_hash"]),
                command_id=command_id,
            )
        elif operation == "seed":
            body = _closed(
                payload,
                {
                    "owner_id",
                    "new_configuration_id",
                    "island",
                    "lineage_id",
                    "emphasis",
                    "template_configuration_id",
                    "corpus_identifiers",
                    "profile_hash",
                    "budget_funded",
                },
            )
            if not isinstance(body["budget_funded"], bool):
                raise ContractValidationError("budget_funded must be a boolean")
            result = self.seed_variant(
                owner_id=_uuid(body["owner_id"]),
                new_configuration_id=_uuid(body["new_configuration_id"]),
                island=_text(body["island"]),
                lineage_id=_text(body["lineage_id"]),
                emphasis=_text_map(body["emphasis"]),
                template_configuration_id=_uuid(body["template_configuration_id"]),
                corpus_identifiers=_text_list(body["corpus_identifiers"]),
                profile_hash=_text(body["profile_hash"]),
                budget_funded=body["budget_funded"],
                command_id=command_id,
            )
        elif operation == "retire":
            body = _closed(payload, {"owner_id", "configuration_id"})
            result = self.retire_genome(
                owner_id=_uuid(body["owner_id"]),
                configuration_id=_uuid(body["configuration_id"]),
                command_id=command_id,
            )
        else:
            raise ContractValidationError("owner operation is not admitted")
        return asdict(result)

    def read(self, kind: str, configuration_id: UUID | None) -> dict[str, Any]:
        """One owner read as the storage route returns it; ``None`` when absent."""

        if kind == "retrospective":
            admissions, retirements = self.retrospective()
            return {
                "admissions": [asdict(record) for record in admissions],
                "retirements": [asdict(record) for record in retirements],
            }
        if configuration_id is None:
            raise ContractValidationError("configuration_id is required")
        if kind == "genome":
            return {"genome": self.read_genome_view(configuration_id)}
        if kind == "admission":
            admission = self.admission_history(configuration_id)
            return {"admission": None if admission is None else asdict(admission)}
        if kind == "retirement":
            retirement = self.retirement_status(configuration_id)
            return {"retirement": None if retirement is None else asdict(retirement)}
        raise ContractValidationError("owner read is not admitted")

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


def _closed(payload: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ContractValidationError("owner command has unknown or missing fields")
    return payload


def _uuid(value: object) -> UUID:
    return UUID(validate_uuid4(value))


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ContractValidationError("owner command text field must be a string")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _optional_count(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError("cycle count must be a non-negative integer")
    return value


def _text_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ContractValidationError("owner command mapping must be an object")
    return {_text(name): _text(text) for name, text in value.items()}


def _text_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractValidationError("owner command list must be an array")
    return tuple(_text(item) for item in value)


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
