"""Paper requests an agent's tools record for families its snapshot lacks.

Decision 0025: a ``deep_read`` or ``graph`` naming a family outside the
run's snapshot records a request -- family, requesting run, snapshot hash,
requested at -- that the acquisition side later fulfils for the next
snapshot. The request is a row, never a fetch. Only the tool service records
one, on behalf of a run; only the ingest role lists the open ones and moves
them. No route lets a run read or change a request.

One serializable transaction decides each outcome, so concurrent calls and a
restarted service agree. Recording: a family with an open (requested or
acquiring) request answers ``already_requested`` and records nothing; a run
that has made ``PAPER_REQUESTS_PER_RUN`` requests answers
``request_budget_exhausted`` and records a refused row; otherwise the answer
is ``requested``. Every new row commits with its ``paper_requested`` ledger
event.

Acquisition moves a row requested -> acquiring -> acquired | failed, or
requested -> refused, one ``paper_request_transitioned`` ledger event per
move (TDD-3.1.78). Beginning an acquisition once
``MAX_ACQUISITIONS_PER_UTC_DAY`` have started in the current UTC day refuses
the row with ``request_budget_exhausted`` instead, in the same transaction
that counts the day.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

PAPER_REQUEST_STATUSES = frozenset(
    {"requested", "acquiring", "acquired", "failed", "refused"}
)
OPEN_PAPER_REQUEST_STATUSES = frozenset({"requested", "acquiring"})
MAX_ACQUISITIONS_PER_UTC_DAY = 200
BUDGET_EXHAUSTED = "request_budget_exhausted"
# The one status each transition may start from.
_TRANSITION_FROM: dict[str, str] = {
    "acquiring": "requested",
    "refused": "requested",
    "acquired": "acquiring",
    "failed": "acquiring",
}


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _reason(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ContractValidationError("paper request reason is invalid")
    return value


def validate_paper_request_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a paper request operation."""

    if operation == "transition":
        return _validate_transition(payload)
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


def _validate_transition(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "request_id",
        "status",
        "reason",
        "paper_version_id",
    }:
        raise ContractValidationError(
            "paper request transition has unknown or missing fields"
        )
    status = payload["status"]
    if status not in _TRANSITION_FROM:
        raise ContractValidationError("paper request transition status is invalid")
    reason, version = payload["reason"], payload["paper_version_id"]
    if (status in {"failed", "refused"}) != (reason is not None):
        raise ContractValidationError("only a failed or refused request has a reason")
    if (status == "acquired") != (version is not None):
        raise ContractValidationError("only an acquired request names its paper")
    return {
        "request_id": validate_uuid4(payload["request_id"]),
        "status": status,
        "reason": None if reason is None else _reason(reason),
        "paper_version_id": None if version is None else validate_uuid4(version),
    }


class PaperRequestRepository:
    """Records, lists and moves paper requests (decision 0025)."""

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
        if operation == "transition":

            def move(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
                return self._transition(connection, identity, value)

            return self._commands.execute(
                identity, "/v1/paper-requests/transitions", {}, value, move
            )

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
               WHERE family_id=%s AND status IN ('requested', 'acquiring')""",
            (value["family_id"],),
        ).fetchone()
        if existing is not None:
            return self._answer(value, "already_requested", cast(UUID, existing[0]))
        made = connection.execute(
            """SELECT count(*) FROM paper_requests
               WHERE run_id=%s AND status <> 'refused'""",
            (value["run_id"],),
        ).fetchone()
        assert made is not None
        if cast(int, made[0]) >= PAPER_REQUESTS_PER_RUN:
            # The refusal is recorded; the run's answer still carries no id.
            _, receipt = self._insert(
                connection, identity, value, "refused", BUDGET_EXHAUSTED
            )
            return {**self._answer(value, BUDGET_EXHAUSTED, None), "receipt": receipt}
        request_id, receipt = self._insert(
            connection, identity, value, "requested", None
        )
        return {**self._answer(value, "requested", request_id), "receipt": receipt}

    def _insert(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
        status: str,
        reason: str | None,
    ) -> tuple[UUID, dict[str, Any]]:
        request_id = uuid4()
        requested_at = datetime.now(timezone.utc)
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="paper_requested",
            payload={
                "schema_version": 2,
                "request_id": str(request_id),
                "family_id": value["family_id"],
                "run_id": value["run_id"],
                "snapshot_hash": value["snapshot_hash"],
                "requested_at": _utc(requested_at),
                "status": status,
                "reason": reason,
            },
            input_hashes=(),
        )
        connection.execute(
            """INSERT INTO paper_requests(id, family_id, run_id, snapshot_hash,
                   requested_at, status, reason, ledger_sequence,
                   last_ledger_sequence)
               VALUES(%s, %s, %s, decode(%s,'hex'), %s, %s, %s, %s, %s)""",
            (
                request_id,
                value["family_id"],
                value["run_id"],
                value["snapshot_hash"],
                requested_at,
                status,
                reason,
                receipt["ledger_last"],
                receipt["ledger_last"],
            ),
        )
        return request_id, receipt

    def _transition(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT status FROM paper_requests WHERE id=%s FOR UPDATE",
            (value["request_id"],),
        ).fetchone()
        if row is None:
            raise UnavailableInput("paper request is not recorded")
        current = cast(str, row[0])
        status, reason = value["status"], value["reason"]
        if current != _TRANSITION_FROM[status]:
            raise StateConflict(f"a {current} paper request cannot become {status}")
        now = datetime.now(timezone.utc)
        if status == "acquiring":
            day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            started = connection.execute(
                """SELECT count(*) FROM paper_requests
                   WHERE started_at >= %s AND started_at < %s""",
                (day, day + timedelta(days=1)),
            ).fetchone()
            assert started is not None
            if cast(int, started[0]) >= MAX_ACQUISITIONS_PER_UTC_DAY:
                status, reason = "refused", BUDGET_EXHAUSTED
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="paper_request_transitioned",
            payload={
                "schema_version": 1,
                "request_id": value["request_id"],
                "from": current,
                "to": status,
                "reason": reason,
                "paper_version_id": value["paper_version_id"],
                "at": _utc(now),
            },
            input_hashes=(),
        )
        connection.execute(
            """UPDATE paper_requests
               SET status=%s, reason=%s, paper_version_id=%s,
                   started_at=CASE WHEN %s THEN %s ELSE started_at END,
                   last_ledger_sequence=%s
               WHERE id=%s""",
            (
                status,
                reason,
                value["paper_version_id"],
                status == "acquiring",
                now,
                receipt["ledger_last"],
                value["request_id"],
            ),
        )
        return {
            "request_id": value["request_id"],
            "status": status,
            "reason": reason,
            "paper_version_id": value["paper_version_id"],
            "receipt": receipt,
        }

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
        """Every requested or acquiring request, oldest first, ties by family."""

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[dict[str, Any], ...]:
            rows = connection.execute(
                """SELECT id, family_id, run_id, encode(snapshot_hash,'hex'),
                          requested_at, status
                   FROM paper_requests
                   WHERE status IN ('requested', 'acquiring')
                   ORDER BY requested_at, family_id"""
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
