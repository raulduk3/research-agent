"""Operator-provisioned rater principals persisted through storage (PL-22)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
    validate_uuid4,
)
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict
from research_agent.storage.idempotency import StoredResponse

RATER_ISLANDS = frozenset({"cs", "quant_ph"})
_SALT = re.compile(r"[0-9a-f]{32}\Z")


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _validate_salt(value: object) -> str:
    if not isinstance(value, str) or _SALT.fullmatch(value) is None:
        raise ContractValidationError(
            "salt must be 32 lowercase hexadecimal characters"
        )
    return value


def validate_rater_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a rater-provision operation."""

    if operation != "provision":
        raise ContractValidationError("unknown rater operation")
    value = _closed(
        payload,
        {"rater_id", "island", "salt", "credential_hash"},
        "provision payload",
    )
    island = value["island"]
    if not isinstance(island, str) or island not in RATER_ISLANDS:
        raise ContractValidationError("island is not an admitted value")
    return {
        "rater_id": validate_uuid4(value["rater_id"]),
        "island": island,
        "salt": _validate_salt(value["salt"]),
        "credential_hash": validate_sha256(value["credential_hash"]),
    }


class RaterRepository:
    """Provisions and resolves the two pseudonymous rater principals (PL-22).

    No route admits self-registration; only the operator role may provision a
    principal, and provisioning is the only write this repository performs.
    """

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
        value = validate_rater_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._provision(connection, identity, value)

        return self._commands.execute(identity, "/v1/raters", {}, value, mutate)

    def _provision(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        inserted = connection.execute(
            """INSERT INTO rater_principals(rater_id, island, salt, credential_hash)
               VALUES(%s, %s, decode(%s,'hex'), decode(%s,'hex'))
               ON CONFLICT DO NOTHING RETURNING provisioned_at""",
            (
                value["rater_id"],
                value["island"],
                value["salt"],
                value["credential_hash"],
            ),
        ).fetchone()
        if inserted is None:
            raise StateConflict("rater identity or island is already provisioned")
        provisioned_at = _utc(cast(datetime, inserted[0]))
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="rater_provisioned",
            payload={
                "schema_version": 1,
                "rater_id": value["rater_id"],
                "island": value["island"],
                "provisioned_at": provisioned_at,
            },
            input_hashes=(),
        )
        return {
            "rater_id": value["rater_id"],
            "provisioned_at": provisioned_at,
            "receipt": receipt,
        }

    def list_principals(self) -> tuple[dict[str, Any], ...]:
        """Read every provisioned principal for constant-time credential checks.

        Every field a rating app needs to authenticate a presented credential
        travels here: no partial view lets a caller guess at a hash it cannot
        also verify against.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[dict[str, Any], ...]:
            rows = connection.execute(
                """SELECT rater_id, island, encode(salt,'hex'),
                          encode(credential_hash,'hex')
                   FROM rater_principals"""
            ).fetchall()
            return tuple(
                {
                    "rater_id": str(cast(UUID, row[0])),
                    "island": row[1],
                    "salt": row[2],
                    "credential_hash": row[3],
                }
                for row in rows
            )

        return self._database.transaction(read)
