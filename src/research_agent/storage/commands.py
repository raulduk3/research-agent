"""One transaction owner for exact command replay and typed domain events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json, sha256_hex
from research_agent.contracts.primitives import validate_uuid4
from research_agent.storage.database import Database
from research_agent.storage.idempotency import (
    IdempotencyRepository,
    StoredResponse,
    command_content_hash,
)
from research_agent.storage.ledger import LedgerRepository


@dataclass(frozen=True, slots=True)
class CommandIdentity:
    principal_id: UUID
    key: UUID
    command_id: UUID
    request_id: UUID

    def __post_init__(self) -> None:
        for value in (self.principal_id, self.key, self.command_id, self.request_id):
            validate_uuid4(str(value))


class CommandTransaction:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.idempotency = IdempotencyRepository()

    def execute(
        self,
        identity: CommandIdentity,
        route: str,
        path_ids: dict[str, str],
        payload: object,
        mutate: Callable[[Connection[tuple[object, ...]]], dict[str, Any]],
        *,
        status_code: int | Callable[[dict[str, Any]], int] = 200,
    ) -> StoredResponse:
        content_hash = command_content_hash(route, path_ids, payload)

        def transaction(connection: Connection[tuple[object, ...]]) -> StoredResponse:
            replay = self.idempotency.begin(
                connection,
                principal_id=identity.principal_id,
                key=identity.key,
                command_id=identity.command_id,
                content_hash=content_hash,
            )
            if replay is not None:
                return replay
            data = mutate(connection)
            resolved_status = (
                status_code(data) if callable(status_code) else status_code
            )
            response = canonical_json(
                {
                    "schema_version": 1,
                    "request_id": str(identity.request_id),
                    "status": "ok",
                    "data": data,
                    "error": None,
                }
            )
            return self.idempotency.finish(
                connection,
                principal_id=identity.principal_id,
                key=identity.key,
                command_id=identity.command_id,
                content_hash=content_hash,
                status_code=resolved_status,
                response_body=response,
            )

        return self.database.serializable(transaction)


class DomainEvents:
    """Install canonical payload bytes before their atomic ledger references."""

    def __init__(
        self,
        store: ArtifactStore,
        producer: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
    ) -> None:
        self.store = store
        self.producer = producer
        self.config_hash = config_hash
        self.retention_policy_hash = retention_policy_hash
        self.ledger = LedgerRepository()

    def append(
        self,
        connection: Connection[tuple[object, ...]],
        *,
        command_id: UUID,
        payload: dict[str, Any],
        input_hashes: tuple[str, ...],
    ) -> dict[str, Any]:
        # Local import avoids a cycle with ArtifactRepository's command wrapper.
        from research_agent.storage.artifacts import ArtifactManifest

        body = canonical_json({**payload, "command_id": str(command_id)})
        digest = sha256_hex(body)
        self.store.commit(
            [body],
            expected_hash=digest,
            expected_length=len(body),
            maximum_length=1024 * 1024,
        )
        created_at = datetime.now(timezone.utc)
        manifest = ArtifactManifest(
            digest,
            input_hashes,
            self.producer,
            self.config_hash,
            self.retention_policy_hash,
            created_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )
        manifest_body = manifest.to_canonical_json()
        manifest_hash = sha256_hex(manifest_body)
        self.store.commit(
            [manifest_body],
            expected_hash=manifest_hash,
            expected_length=len(manifest_body),
            maximum_length=128 * 1024,
        )
        connection.execute(
            """INSERT INTO artifacts(hash, byte_length, media_type, kind,
               retention_policy_hash, producer_image_digest, producer_source_commit,
               producer_contract_version, config_hash)
               VALUES (decode(%s,'hex'), %s, 'application/json', 'manifest',
               decode(%s,'hex'), decode(%s,'hex'), decode(%s,'hex'), %s,
               decode(%s,'hex')) ON CONFLICT DO NOTHING""",
            (
                digest,
                len(body),
                self.retention_policy_hash,
                self.producer.image_digest,
                self.producer.source_commit,
                self.producer.contract_version,
                self.config_hash,
            ),
        )
        connection.execute(
            """INSERT INTO artifacts(hash,byte_length,media_type,kind,created_at,
               available_at,retention_policy_hash,producer_image_digest,
               producer_source_commit,producer_contract_version,config_hash)
               VALUES(decode(%s,'hex'),%s,'application/json','manifest',%s,%s,
               decode(%s,'hex'),decode(%s,'hex'),decode(%s,'hex'),%s,
               decode(%s,'hex'))""",
            (
                manifest_hash,
                len(manifest_body),
                created_at,
                created_at,
                self.retention_policy_hash,
                self.producer.image_digest,
                self.producer.source_commit,
                self.producer.contract_version,
                self.config_hash,
            ),
        )
        connection.execute(
            """INSERT INTO artifact_productions(manifest_hash,artifact_hash,created_at,
               producer_image_digest,producer_source_commit,producer_contract_version,
               config_hash,retention_policy_hash)
               VALUES(decode(%s,'hex'),decode(%s,'hex'),%s,decode(%s,'hex'),
               decode(%s,'hex'),%s,decode(%s,'hex'),decode(%s,'hex'))""",
            (
                manifest_hash,
                digest,
                created_at,
                self.producer.image_digest,
                self.producer.source_commit,
                self.producer.contract_version,
                self.config_hash,
                self.retention_policy_hash,
            ),
        )
        for ordinal, dependency in enumerate(dict.fromkeys(input_hashes)):
            connection.execute(
                """INSERT INTO artifact_production_edges(
                   manifest_hash,input_hash,ordinal)
                   VALUES(decode(%s,'hex'),decode(%s,'hex'),%s)""",
                (manifest_hash, dependency, ordinal),
            )
        event = self.ledger.append(
            connection,
            record_id=uuid4(),
            event_kind="job_transition",
            payload_hash=digest,
            command_id=command_id,
        )
        connection.execute(
            """INSERT INTO artifact_publication_receipts
               (artifact_hash,committed_ledger_sequence,published_at)
               VALUES(decode(%s,'hex'),%s,clock_timestamp()) ON CONFLICT DO NOTHING""",
            (digest, event.sequence),
        )
        connection.execute(
            """INSERT INTO artifact_publication_receipts
               (artifact_hash,committed_ledger_sequence,published_at)
               VALUES(decode(%s,'hex'),%s,clock_timestamp())""",
            (manifest_hash, event.sequence),
        )
        return {
            "record_ids": [str(event.record_id)],
            "artifact_hashes": [manifest_hash],
            "ledger_first": event.sequence,
            "ledger_last": event.sequence,
            "committed_at": event.created_at,
        }
