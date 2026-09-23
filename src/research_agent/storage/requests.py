"""Paper requests an agent's tools record for families its snapshot lacks.

Decision 0025: a ``deep_read`` or ``graph`` naming a family outside the
run's snapshot records a request -- family, requesting run, snapshot hash,
requested at -- that the acquisition side later fulfils for the next
snapshot. The request is a row, never a fetch. Only the tool service records
one, on behalf of a run; only the ingest role lists the open ones. No route
lets a run read or change a request.

One serializable transaction decides the outcome, so concurrent calls and a
restarted tool service agree: a family that already has a request that has
not failed answers ``already_requested`` and records nothing; a run that has
made ``PAPER_REQUESTS_PER_RUN`` requests answers ``request_budget_exhausted``
and records nothing; otherwise the row and its ``paper_requested`` ledger
event commit together and the answer is ``requested``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID, uuid4

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
    validate_uuid4,
)
from research_agent.contracts.tools import PAPER_REQUESTS_PER_RUN
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.idempotency import StoredResponse

PAPER_REQUEST_STATUSES = frozenset({"requested", "acquiring", "acquired", "failed"})
OPEN_PAPER_REQUEST_STATUSES = frozenset({"requested", "acquiring"})


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate_paper_request_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for recording a paper request."""

    if operation != "record":
        raise ContractValidationError("unknown paper request operation")
    if not isinstance(payload, dict) or set(payload) != {
        "run_id",
        "family_id",
        "snapshot_hash",
    }:
        raise ContractValidationError(
            "paper request payload has unknown or missing fields"
        )
    return {
        "run_id": validate_uuid4(payload["run_id"]),
        "family_id": validate_uuid4(payload["family_id"]),
        "snapshot_hash": validate_sha256(payload["snapshot_hash"]),
    }


class PaperRequestRepository:
    """Records a run's paper requests and lists the open ones (decision 0025)."""

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
        self._commands = CommandTransaction(database)
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        value = validate_paper_request_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._record(connection, identity, value)

        return self._commands.execute(identity, "/v1/paper-requests", {}, value, mutate)

    def _record(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        run = connection.execute(
            "SELECT encode(snapshot_hash,'hex') FROM runs WHERE id=%s",
            (value["run_id"],),
        ).fetchone()
        if run is None:
            raise UnavailableInput("run is not recorded")
        if run[0] != value["snapshot_hash"]:
            raise StateConflict(
                "paper request names a snapshot other than the run's own"
            )
        held = connection.execute(
            """SELECT 1 FROM snapshot_items
               WHERE snapshot_hash=decode(%s,'hex') AND paper_family_id=%s LIMIT 1""",
            (value["snapshot_hash"], value["family_id"]),
        ).fetchone()
        if held is not None:
            raise StateConflict("the run's snapshot holds the requested family")
        existing = connection.execute(
            """SELECT id FROM paper_requests
               WHERE family_id=%s AND status <> 'failed'""",
            (value["family_id"],),
        ).fetchone()
        if existing is not None:
            return self._answer(value, "already_requested", cast(UUID, existing[0]))
        made = connection.execute(
            "SELECT count(*) FROM paper_requests WHERE run_id=%s", (value["run_id"],)
        ).fetchone()
        assert made is not None
        if cast(int, made[0]) >= PAPER_REQUESTS_PER_RUN:
            return self._answer(value, "request_budget_exhausted", None)
        request_id = uuid4()
        requested_at = datetime.now(timezone.utc)
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="paper_requested",
            payload={
                "schema_version": 1,
                "request_id": str(request_id),
                "family_id": value["family_id"],
                "run_id": value["run_id"],
                "snapshot_hash": value["snapshot_hash"],
                "requested_at": _utc(requested_at),
            },
            input_hashes=(),
        )
        connection.execute(
            """INSERT INTO paper_requests(id, family_id, run_id, snapshot_hash,
                   requested_at, status, reason, ledger_sequence)
               VALUES(%s, %s, %s, decode(%s,'hex'), %s, 'requested', NULL, %s)""",
            (
                request_id,
                value["family_id"],
                value["run_id"],
                value["snapshot_hash"],
                requested_at,
                receipt["ledger_last"],
            ),
        )
        return {**self._answer(value, "requested", request_id), "receipt": receipt}

    @staticmethod
    def _answer(
        value: dict[str, Any], outcome: str, request_id: UUID | None
    ) -> dict[str, Any]:
        return {
            "outcome": outcome,
            "request_id": None if request_id is None else str(request_id),
            "family_id": value["family_id"],
            "receipt": None,
        }

    def open_requests(self) -> tuple[dict[str, Any], ...]:
        """Every request not yet acquired or failed, oldest first."""

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[dict[str, Any], ...]:
            rows = connection.execute(
                """SELECT id, family_id, run_id, encode(snapshot_hash,'hex'),
                          requested_at, status
                   FROM paper_requests
                   WHERE status IN ('requested', 'acquiring')
                   ORDER BY requested_at, id"""
            ).fetchall()
            return tuple(
                {
                    "request_id": str(cast(UUID, row[0])),
                    "family_id": str(cast(UUID, row[1])),
                    "run_id": str(cast(UUID, row[2])),
                    "snapshot_hash": row[3],
                    "requested_at": _utc(cast(datetime, row[4])),
                    "status": row[5],
                }
                for row in rows
            )

        return self._database.transaction(read)
