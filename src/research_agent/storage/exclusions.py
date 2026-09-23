"""Graduated exclusion actions recorded in the ledger (AG-22, AG-23, TDD-3.1.69).

A run is quarantined; three integrity quarantines of runs issued for one
immutable configuration inside seven days quarantine that configuration; an
operator then revokes its execution authority, which is the purge. Every step
appends one ``exclusion_action_recorded`` ledger record and one
``exclusion_transitions`` row in the same serializable transaction, so a step
whose record cannot be appended has no effect, and a repeated delivery of a
command replays the first result instead of appending a second step. State is
the latest transition of a scope. No step removes or rewrites a run, forecast
or ledger record.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID, uuid4

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.exclusions import (
    CONFIGURATION_QUARANTINE_DAYS,
    CONFIGURATION_QUARANTINE_RUNS,
    TRANSITIONS,
    validate_exclusion_payload,
)
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.idempotency import StoredResponse

ACTIVE = "active"
_STATE_RANK = {
    "active": 0,
    "run_quarantined": 1,
    "configuration_quarantined": 1,
    "authority_revoked": 2,
}


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def read_exclusion_state(
    connection: Connection[tuple[object, ...]], scope: str, scope_id: str
) -> str:
    """The state of one run or configuration: its most advanced transition."""

    rows = connection.execute(
        "SELECT new_state FROM exclusion_transitions WHERE scope=%s AND scope_id=%s",
        (scope, scope_id),
    ).fetchall()
    states = [cast(str, row[0]) for row in rows]
    return max(states, key=_STATE_RANK.__getitem__, default=ACTIVE)


def append_exclusion_transition(
    connection: Connection[tuple[object, ...]],
    events: DomainEvents,
    *,
    command_id: UUID,
    value: dict[str, Any],
    configuration_id: str,
    prior_state: str,
) -> dict[str, Any]:
    """Append the ledger record for one step, then its transition row.

    Both writes belong to the caller's serializable transaction: when either
    fails, neither is visible and the scope stays at ``prior_state``.
    """

    scope, expected_prior, new_state = TRANSITIONS[value["action"]]
    if prior_state != expected_prior:
        raise StateConflict(
            f"{value['action']} applies from {expected_prior}, not {prior_state}"
        )
    transition_id = uuid4()
    recorded_at = datetime.now(timezone.utc)
    receipt = events.append(
        connection,
        command_id=command_id,
        event_kind="exclusion_action_recorded",
        payload={
            "schema_version": 1,
            "transition_id": str(transition_id),
            "action": value["action"],
            "scope": scope,
            "scope_id": value["scope_id"],
            "configuration_id": configuration_id,
            "prior_state": prior_state,
            "new_state": new_state,
            "trigger_run_ids": value["trigger_run_ids"],
            "evidence_hashes": value["evidence_hashes"],
            "authority": value["authority"],
            "operator_id": value["operator_id"],
            "recorded_at": _utc(recorded_at),
        },
        input_hashes=(),
    )
    connection.execute(
        """INSERT INTO exclusion_transitions(
               id, action, scope, scope_id, configuration_id, prior_state, new_state,
               run_id, trigger_run_ids, evidence_hashes, authority, operator_id,
               ledger_sequence, recorded_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[],
                   ARRAY(SELECT decode(h, 'hex') FROM unnest(%s::text[]) AS h),
                   %s, %s, %s, %s)""",
        (
            transition_id,
            value["action"],
            scope,
            value["scope_id"],
            configuration_id,
            prior_state,
            new_state,
            value["scope_id"] if scope == "run" else None,
            value["trigger_run_ids"],
            value["evidence_hashes"],
            value["authority"],
            value["operator_id"],
            receipt["ledger_first"],
            recorded_at,
        ),
    )
    return {
        "transition_id": str(transition_id),
        "action": value["action"],
        "scope": scope,
        "scope_id": value["scope_id"],
        "prior_state": prior_state,
        "new_state": new_state,
        "receipt": receipt,
    }


def apply_exclusion(
    connection: Connection[tuple[object, ...]],
    events: DomainEvents,
    identity: CommandIdentity,
    value: dict[str, Any],
) -> dict[str, Any]:
    """Apply one step in order, refusing a skipped, repeated or unsupported one."""

    action = value["action"]
    scope, _, _ = TRANSITIONS[action]
    scope_id = value["scope_id"]
    if value["operator_id"] is not None:
        operator = connection.execute(
            "SELECT 1 FROM owner_principals WHERE owner_id=%s", (value["operator_id"],)
        ).fetchone()
        if operator is None:
            raise UnavailableInput("operator principal is not provisioned")
    if action == "quarantine_run":
        run = connection.execute(
            "SELECT configuration_id FROM runs WHERE id=%s", (scope_id,)
        ).fetchone()
        if run is None:
            raise UnavailableInput("run is not recorded")
        configuration_id = str(cast(UUID, run[0]))
    else:
        configuration_id = scope_id
        if action == "quarantine_configuration":
            _require_run_quarantines(connection, configuration_id, value)
    prior_state = read_exclusion_state(connection, scope, scope_id)
    return append_exclusion_transition(
        connection,
        events,
        command_id=identity.command_id,
        value=value,
        configuration_id=configuration_id,
        prior_state=prior_state,
    )


def _require_run_quarantines(
    connection: Connection[tuple[object, ...]],
    configuration_id: str,
    value: dict[str, Any],
) -> None:
    """The cited runs are quarantined runs of this configuration, inside seven days."""

    cited = value["trigger_run_ids"]
    rows = connection.execute(
        """SELECT scope_id, recorded_at FROM exclusion_transitions
           WHERE new_state='run_quarantined' AND configuration_id=%s
             AND scope_id = ANY(%s::uuid[])""",
        (configuration_id, cited),
    ).fetchall()
    if len(rows) != len(cited):
        raise StateConflict(
            "a configuration quarantine cites only quarantined runs of that configuration"
        )
    recorded = [cast(datetime, row[1]) for row in rows]
    if len(cited) < CONFIGURATION_QUARANTINE_RUNS or max(recorded) - min(
        recorded
    ) > timedelta(days=CONFIGURATION_QUARANTINE_DAYS):
        raise StateConflict(
            f"{CONFIGURATION_QUARANTINE_RUNS} run quarantines inside "
            f"{CONFIGURATION_QUARANTINE_DAYS} days are required"
        )


class ExclusionRepository:
    """Applies exclusion action steps and reads the state they leave."""

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

    def execute(self, *, identity: CommandIdentity, payload: object) -> StoredResponse:
        value = validate_exclusion_payload(payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return apply_exclusion(connection, self._events, identity, value)

        return self._commands.execute(identity, "/v1/exclusions", {}, value, mutate)

    def state(self, scope: str, scope_id: UUID) -> str:
        """The current exclusion state of ``scope`` (``run`` or ``configuration``)."""

        def read(connection: Connection[tuple[object, ...]]) -> str:
            return read_exclusion_state(connection, scope, str(scope_id))

        return self._database.transaction(read)
