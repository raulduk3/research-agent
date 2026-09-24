"""Quarantine a run whose configuration digest changed (IN-24, TDD-4.1.31).

At completion the worker's mounted configuration is hashed again and compared
with the ``genome_hash`` the run sealed at creation. A mismatch is an
integrity failure: the run takes the ordinary ``quarantine_run`` exclusion
step (ledger record and transition row) in one serializable transaction; the
record's evidence hash commits to the sealed and recomputed digests. A run that
matches changes nothing.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from psycopg import Connection

from research_agent.agents.configuration import (
    AgentConfiguration,
    verify_configuration_digest,
)
from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.exclusions import validate_exclusion_payload
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput
from research_agent.storage.exclusions import (
    ACTIVE,
    apply_exclusion,
    read_exclusion_state,
)
from research_agent.storage.idempotency import StoredResponse

DIGEST_MISMATCH = "configuration_digest_mismatch"


def entry_is_quarantined(
    connection: Connection[tuple[object, ...]], entry_id: str
) -> bool:
    """Whether every nomination behind a digest entry comes from a quarantined run.

    An entry that some unquarantined run also nominated stays readable; an
    entry with no nomination (a control or service entry) has no run output
    to quarantine.
    """

    row = connection.execute(
        """SELECT count(*),
                  count(*) FILTER (WHERE EXISTS (
                      SELECT 1 FROM exclusion_transitions et
                      WHERE et.scope = 'run' AND et.scope_id = rs.run_id
                        AND et.new_state = 'run_quarantined'))
           FROM digest_nominations n
           JOIN run_submissions rs ON rs.submission_id = n.submission_id
           WHERE n.entry_id = %s""",
        (entry_id,),
    ).fetchone()
    assert row is not None
    total, quarantined = cast(int, row[0]), cast(int, row[1])
    return total > 0 and total == quarantined


class QuarantineRepository:
    """Verifies a completed run's configuration digest and quarantines a mismatch."""

    def __init__(
        self,
        database: Database,
        store: ArtifactStore,
        *,
        producer: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
    ) -> None:
        self._commands = CommandTransaction(database)
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def verify_completion(
        self,
        *,
        identity: CommandIdentity,
        run_id: UUID,
        configuration: AgentConfiguration,
    ) -> StoredResponse:
        """Compare ``configuration`` with the run's sealed digest at completion."""

        recomputed = configuration.configuration_hash
        payload = {"run_id": str(run_id), "configuration_hash": recomputed}

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._verify(connection, identity, run_id, configuration)

        return self._commands.execute(
            identity,
            "/v1/runs/{id}/verify-configuration",
            {"id": str(run_id)},
            payload,
            mutate,
        )

    def _verify(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        run_id: UUID,
        configuration: AgentConfiguration,
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT encode(genome_hash, 'hex') FROM runs WHERE id=%s", (run_id,)
        ).fetchone()
        if row is None:
            raise UnavailableInput("run is not recorded")
        sealed = cast(str, row[0])
        recomputed = configuration.configuration_hash
        if verify_configuration_digest(configuration, sealed):
            return {"run_id": str(run_id), "verified": True, "state": ACTIVE}
        state = read_exclusion_state(connection, "run", str(run_id))
        if state != ACTIVE:
            return {"run_id": str(run_id), "verified": False, "state": state}
        evidence = sha256_hex(
            canonical_json(
                {
                    "reason": DIGEST_MISMATCH,
                    "run_id": str(run_id),
                    "sealed_hash": sealed,
                    "recomputed_hash": recomputed,
                }
            )
        )
        step = apply_exclusion(
            connection,
            self._events,
            identity,
            validate_exclusion_payload(
                {
                    "action": "quarantine_run",
                    "scope_id": str(run_id),
                    "evidence_hashes": [evidence],
                    "trigger_run_ids": [],
                    "authority": "system",
                    "operator_id": None,
                }
            ),
        )
        return {
            "run_id": str(run_id),
            "verified": False,
            "state": step["new_state"],
            "transition_id": step["transition_id"],
        }
