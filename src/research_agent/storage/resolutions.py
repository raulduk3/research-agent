"""Append-only settlement state: a resolution never edits, only supersedes (EN-04, EN-08).

``append_resolution`` accepts a frozen resolver identity, target identity,
observation hash, tri-state result and evidence for one sealed forecast, and
appends exactly one ``resolution_recorded`` ledger event per accepted call.
``validate_resolver_identity`` pins that identity tuple on a question's first
resolution and refuses any later drift under the same resolver name, so a
resolution can never resettle under a mutable "latest build" alias.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json, sha256_hex
from research_agent.contracts.outcomes import validate_resolution_store_payload
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_positive_int,
    validate_sha256,
)
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.idempotency import StoredResponse


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate_resolver_identity(
    existing: Mapping[str, Any] | None, supplied: Mapping[str, Any]
) -> dict[str, Any]:
    """Pin a question's resolver build on its first resolution; refuse any later drift (EN-08).

    ``resolver_version`` alone never settles a question: this compares the
    complete ``(resolver_id, resolver_build_digest, target_definition_hash,
    observation_protocol_version)`` tuple. A question's first resolution
    pins that tuple; every later resolution or correction for the same
    question must reproduce it exactly -- a resolver build change under the
    same ``resolver_id`` is rejected rather than silently resettling the
    question against a newer build.
    """
    resolver_id = supplied.get("resolver_id")
    build_digest = validate_sha256(supplied.get("resolver_build_digest"))
    definition_hash = validate_sha256(supplied.get("target_definition_hash"))
    protocol_version = validate_positive_int(
        supplied.get("observation_protocol_version")
    )
    if not isinstance(resolver_id, str) or not resolver_id:
        raise ContractValidationError("resolver_id is missing")
    identity = {
        "resolver_id": resolver_id,
        "resolver_build_digest": build_digest,
        "target_definition_hash": definition_hash,
        "observation_protocol_version": protocol_version,
    }
    if existing is not None and dict(existing) != identity:
        raise ContractValidationError(
            "resolver identity differs from the identity this question already settled under"
        )
    return identity


class ResolutionRepository:
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
        value = validate_resolution_store_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._append(connection, identity, value)

        return self._commands.execute(identity, "/v1/resolutions", {}, value, mutate)

    def _append(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        forecast = connection.execute(
            """SELECT status, question_id, horizon FROM submissions
               WHERE id=%s FOR UPDATE""",
            (value["forecast_id"],),
        ).fetchone()
        if forecast is None:
            raise UnavailableInput("resolution names an unknown forecast")
        status, question_id, horizon = (
            cast(str, forecast[0]),
            str(forecast[1]),
            cast(datetime, forecast[2]),
        )
        if status != "sealed":
            raise ContractValidationError(
                "resolution names a forecast that is not sealed"
            )
        if question_id != value["question_id"]:
            raise ContractValidationError(
                "resolution question does not match the sealed forecast"
            )
        as_of = datetime.strptime(value["as_of"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
        if as_of < horizon:
            raise ContractValidationError(
                "outcome capture is not eligible before the forecast horizon"
            )

        prior_identity_row = connection.execute(
            """SELECT resolver_id, encode(resolver_build_digest,'hex'),
                      encode(target_definition_hash,'hex'), observation_protocol_version
               FROM resolutions WHERE forecast_id=%s
               ORDER BY resolution_version DESC LIMIT 1 FOR UPDATE""",
            (value["forecast_id"],),
        ).fetchone()
        existing_identity = (
            None
            if prior_identity_row is None
            else {
                "resolver_id": prior_identity_row[0],
                "resolver_build_digest": prior_identity_row[1],
                "target_definition_hash": prior_identity_row[2],
                "observation_protocol_version": prior_identity_row[3],
            }
        )
        validate_resolver_identity(existing_identity, value)

        request_hash = sha256_hex(canonical_json(value))
        replay = connection.execute(
            """SELECT id, encode(request_hash,'hex'), resolved_at FROM resolutions
               WHERE forecast_id=%s AND resolution_version=%s""",
            (value["forecast_id"], value["resolution_version"]),
        ).fetchone()
        if replay is not None:
            if str(replay[1]) != request_hash:
                raise StateConflict(
                    "resolution version already recorded with different content"
                )
            return {
                "resolution_id": str(replay[0]),
                "resolved_at": _utc(cast(datetime, replay[2])),
                "receipt": {"replay": True},
            }
        if value["resolution_version"] > 1:
            supersedes = connection.execute(
                """SELECT 1 FROM resolutions
                   WHERE id=%s AND forecast_id=%s AND resolution_version=%s""",
                (
                    value["supersedes_resolution_id"],
                    value["forecast_id"],
                    value["resolution_version"] - 1,
                ),
            ).fetchone()
            if supersedes is None:
                raise ContractValidationError(
                    "correction does not supersede the forecast's prior resolution"
                )

        resolution_id = uuid4()
        resolved_at = datetime.now(timezone.utc)
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="resolution_recorded",
            payload={"schema_version": 1, "resolution_id": str(resolution_id), **value},
            input_hashes=(),
        )
        connection.execute(
            """INSERT INTO resolutions(
                   id, forecast_id, question_id, resolver_id, resolver_build_digest,
                   target_definition_hash, observation_protocol_version,
                   observation_hash, status, resolution_version,
                   supersedes_resolution_id, request_hash, resolved_at
               ) VALUES(
                   %s, %s, %s, %s, decode(%s,'hex'), decode(%s,'hex'), %s,
                   decode(%s,'hex'), %s, %s, %s, decode(%s,'hex'), %s
               )""",
            (
                resolution_id,
                value["forecast_id"],
                value["question_id"],
                value["resolver_id"],
                value["resolver_build_digest"],
                value["target_definition_hash"],
                value["observation_protocol_version"],
                value["observation_hash"],
                value["status"],
                value["resolution_version"],
                value["supersedes_resolution_id"],
                request_hash,
                resolved_at,
            ),
        )
        return {
            "resolution_id": str(resolution_id),
            "resolved_at": _utc(resolved_at),
            "receipt": receipt,
        }


def append_resolution(
    repository: ResolutionRepository,
    *,
    identity: CommandIdentity,
    payload: Mapping[str, Any],
) -> StoredResponse:
    """Append one resolution event for a sealed forecast (EN-04).

    A thin, named entry point over :meth:`ResolutionRepository.execute`,
    mirroring ``storage/forecasts.py#seal_forecasts`` over
    ``SubmissionRepository``.
    """
    return repository.execute("append", identity=identity, payload=dict(payload))
