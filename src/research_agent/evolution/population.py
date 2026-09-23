"""The population store: where admitted genomes and their archive persist.

The rest of this package decides from an explicit population snapshot; this
module is the caller that backs it with storage. A seeded genome or an
accepted child (AG-21) is written with its four hashed emphasis parts
(AG-20) and its admission record in one transaction; a select stage's
archive entries (FT-15) are written together in one transaction; and an
island's active and archived genomes are read back as the snapshot
``admit_child`` compares a child against. Each write appends one ledger
event, and a replay of identical content appends nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, sha256_hex
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
    validate_uuid4,
)
from research_agent.evolution.admission import AdmissionResult
from research_agent.evolution.genome import Genome
from research_agent.orchestration.scheduler import ISLANDS
from research_agent.orchestration.selection import SelectionEvent
from research_agent.storage.commands import DomainEvents
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput


class PopulationStore:
    """Persist genome admissions and archive entries; read an island back."""

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
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def record_seed(
        self,
        *,
        configuration_id: UUID,
        genome: Genome,
        profile_hash: str,
        command_id: UUID,
    ) -> None:
        """Admit a seeded genome, which has no parent."""

        if genome.parent_hash is not None:
            raise ContractValidationError("a seeded genome has no parent")
        validate_sha256(profile_hash)
        self._admit(configuration_id, genome, "seeded", profile_hash, command_id)

    def record_child(
        self,
        *,
        configuration_id: UUID,
        child: Genome,
        admission: AdmissionResult,
        command_id: UUID,
        within: Callable[[Connection[tuple[object, ...]]], None] | None = None,
    ) -> None:
        """Admit a child only on the accepted admission computed for it (AG-21).

        *within* runs on the admission's own connection after the genome rows
        are written, so a record that must exist with the genome commits with
        it or not at all. A replay of an identical admission skips it.
        """

        if admission.disposition != "accepted":
            raise ContractValidationError("only an accepted child is admitted")
        if admission.child_hash != child.configuration_hash:
            raise ContractValidationError("admission does not name this child")
        if child.parent_hash is None:
            raise ContractValidationError("an admitted child names its parent")
        self._admit(
            configuration_id,
            child,
            "accepted",
            admission.profile_hash,
            command_id,
            within,
        )

    def record_archive(self, event: SelectionEvent, *, command_id: UUID) -> None:
        """Write every archive entry of one select stage in one transaction (FT-13)."""

        if not event.archived:
            return
        validate_sha256(event.profile_hash)

        def write(connection: Connection[tuple[object, ...]]) -> None:
            pending: list[tuple[str, float, int]] = []
            for entry in event.archived:
                row = connection.execute(
                    """SELECT g.configuration_id, g.island, g.lineage_id,
                              a.cycle_id, a.skill, a.resolved_claim_count,
                              encode(a.profile_hash,'hex')
                       FROM genomes g
                       LEFT JOIN genome_archive a
                         ON a.configuration_id = g.configuration_id
                       WHERE g.configuration_hash = decode(%s,'hex')""",
                    (entry.genome_hash,),
                ).fetchone()
                if row is None:
                    raise UnavailableInput("archive names a genome never admitted")
                if row[1] != entry.island or row[2] != entry.lineage_id:
                    raise ContractValidationError(
                        "archive entry does not match the admitted genome"
                    )
                stored = (row[3], row[4], row[5], row[6])
                supplied = (
                    event.cycle_id,
                    float(entry.skill),
                    entry.resolved_claim_count,
                    event.profile_hash,
                )
                if row[3] is not None:
                    if stored != supplied:
                        raise StateConflict("genome already archived differently")
                    continue
                pending.append(
                    (str(row[0]), float(entry.skill), entry.resolved_claim_count)
                )
            if not pending:
                return
            self._events.append(
                connection,
                command_id=command_id,
                event_kind="genome_archived",
                payload={
                    "schema_version": 1,
                    "cycle_id": event.cycle_id,
                    "profile_hash": event.profile_hash,
                    "archived": [
                        {
                            "configuration_id": configuration_id,
                            "skill": skill,
                            "resolved_claim_count": count,
                        }
                        for configuration_id, skill, count in pending
                    ],
                },
                input_hashes=(),
            )
            archived_at = datetime.now(timezone.utc)
            for configuration_id, skill, count in pending:
                connection.execute(
                    """INSERT INTO genome_archive(
                           configuration_id, cycle_id, skill, resolved_claim_count,
                           profile_hash, archived_at
                       ) VALUES (%s, %s, %s, %s, decode(%s,'hex'), %s)""",
                    (
                        configuration_id,
                        event.cycle_id,
                        skill,
                        count,
                        event.profile_hash,
                        archived_at,
                    ),
                )

        self._database.serializable(write)

    def island_population(
        self, island: str
    ) -> tuple[tuple[Genome, ...], tuple[Genome, ...]]:
        """An island's active and archived genomes, oldest admission first."""

        if island not in ISLANDS:
            raise ContractValidationError(f"island must be one of {sorted(ISLANDS)}")

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                """SELECT g.configuration_id, g.lineage_id, g.founder,
                          encode(g.infra_hash,'hex'), encode(g.parent_hash,'hex'),
                          a.configuration_id IS NOT NULL
                   FROM genomes g
                   LEFT JOIN genome_archive a ON a.configuration_id = g.configuration_id
                   WHERE g.island = %s
                   ORDER BY g.admitted_at, g.configuration_id""",
                (island,),
            ).fetchall()

        def parts(
            connection: Connection[tuple[object, ...]],
        ) -> dict[str, dict[str, str]]:
            result: dict[str, dict[str, str]] = {}
            for configuration_id, part, value in connection.execute(
                """SELECT p.configuration_id, p.part, p.value
                   FROM genome_parts p
                   JOIN genomes g ON g.configuration_id = p.configuration_id
                   WHERE g.island = %s""",
                (island,),
            ).fetchall():
                result.setdefault(str(configuration_id), {})[cast(str, part)] = cast(
                    str, value
                )
            return result

        rows, emphasis = self._database.transaction(
            lambda connection: (read(connection), parts(connection))
        )
        active: list[Genome] = []
        archived: list[Genome] = []
        for row in rows:
            genome = Genome(
                lineage_id=cast(str, row[1]),
                island=island,
                infra_hash=cast(str, row[3]),
                emphasis=emphasis[str(row[0])],
                founder=cast(bool, row[2]),
                parent_hash=cast("str | None", row[4]),
            )
            (archived if row[5] else active).append(genome)
        return tuple(active), tuple(archived)

    def _admit(
        self,
        configuration_id: UUID,
        genome: Genome,
        admission: str,
        profile_hash: str,
        command_id: UUID,
        within: Callable[[Connection[tuple[object, ...]]], None] | None = None,
    ) -> None:
        validate_uuid4(str(configuration_id))
        configuration_hash = genome.configuration_hash

        def write(connection: Connection[tuple[object, ...]]) -> None:
            existing = connection.execute(
                """SELECT encode(configuration_hash,'hex'), admission,
                          encode(profile_hash,'hex')
                   FROM genomes WHERE configuration_id=%s""",
                (configuration_id,),
            ).fetchone()
            if existing is not None:
                if existing != (configuration_hash, admission, profile_hash):
                    raise StateConflict(
                        "configuration already admitted with a different genome"
                    )
                return
            duplicate = connection.execute(
                "SELECT 1 FROM genomes WHERE configuration_hash = decode(%s,'hex')",
                (configuration_hash,),
            ).fetchone()
            if duplicate is not None:
                raise StateConflict(
                    "genome hash equals an active or archived genome (AG-21)"
                )
            if genome.parent_hash is not None:
                parent = connection.execute(
                    "SELECT 1 FROM genomes WHERE configuration_hash = decode(%s,'hex')",
                    (genome.parent_hash,),
                ).fetchone()
                if parent is None:
                    raise UnavailableInput("child names a parent never admitted")
            part_hashes = {
                name: sha256_hex(value.encode("utf-8"))
                for name, value in sorted(genome.emphasis.items())
            }
            self._events.append(
                connection,
                command_id=command_id,
                event_kind="genome_admitted",
                payload={
                    "schema_version": 1,
                    "configuration_id": str(configuration_id),
                    "configuration_hash": configuration_hash,
                    "lineage_id": genome.lineage_id,
                    "island": genome.island,
                    "founder": genome.founder,
                    "infra_hash": genome.infra_hash,
                    "parent_hash": genome.parent_hash,
                    "part_hashes": part_hashes,
                    "admission": admission,
                    "profile_hash": profile_hash,
                },
                input_hashes=(),
            )
            connection.execute(
                """INSERT INTO genomes(
                       configuration_id, configuration_hash, lineage_id, island,
                       founder, infra_hash, parent_hash, admission, profile_hash,
                       admitted_at
                   ) VALUES (
                       %s, decode(%s,'hex'), %s, %s, %s, decode(%s,'hex'),
                       decode(%s,'hex'), %s, decode(%s,'hex'), %s
                   )""",
                (
                    configuration_id,
                    configuration_hash,
                    genome.lineage_id,
                    genome.island,
                    genome.founder,
                    genome.infra_hash,
                    genome.parent_hash,
                    admission,
                    profile_hash,
                    datetime.now(timezone.utc),
                ),
            )
            for name, value in sorted(genome.emphasis.items()):
                connection.execute(
                    """INSERT INTO genome_parts(configuration_id, part, value, value_hash)
                       VALUES (%s, %s, %s, decode(%s,'hex'))""",
                    (configuration_id, name, value, part_hashes[name]),
                )
            if within is not None:
                within(connection)

        self._database.serializable(write)
