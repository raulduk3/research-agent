"""Artifact publication after durable blob installation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, cast
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.errors import SerializationFailure

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import (
    ArtifactRef,
    ProducerVersion,
    canonical_loads,
    canonical_json,
    sha256_hex,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.contracts.storage import ArtifactPublicationReceipt
from research_agent.storage.database import Database
from research_agent.storage.commands import CommandIdentity, CommandTransaction
from research_agent.storage.errors import (
    IntegrityFailure,
    LeaseExpired,
    StaleLease,
    UnavailableInput,
)
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.ledger import LedgerEvent, LedgerRepository


@dataclass(frozen=True, slots=True)
class ArtifactPublication:
    artifact_hash: str
    manifest_hash: str
    byte_length: int
    created_at: str
    ledger: LedgerEvent
    receipt: ArtifactPublicationReceipt
    blob_created: bool


@dataclass(frozen=True, slots=True)
class PublicationAdmission:
    job_id: UUID
    lease_epoch: int
    worker_id: UUID
    job_kinds: frozenset[str]


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Immutable production identity for content-addressed payload bytes."""

    artifact_hash: str
    input_hashes: tuple[str, ...]
    producer_version: ProducerVersion
    config_hash: str
    retention_policy_hash: str
    created_at: str

    def to_canonical_json(self) -> bytes:
        return canonical_json(
            {
                "artifact_hash": self.artifact_hash,
                "config_hash": self.config_hash,
                "created_at": self.created_at,
                "input_hashes": list(self.input_hashes),
                "producer_version": {
                    "contract_version": self.producer_version.contract_version,
                    "image_digest": self.producer_version.image_digest,
                    "source_commit": self.producer_version.source_commit,
                },
                "retention_policy_hash": self.retention_policy_hash,
                "schema_version": 1,
            }
        )

    @classmethod
    def from_json(cls, raw: bytes) -> "ArtifactManifest":
        value = canonical_loads(raw)
        fields = {
            "artifact_hash",
            "config_hash",
            "created_at",
            "input_hashes",
            "producer_version",
            "retention_policy_hash",
            "schema_version",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise ContractValidationError(
                "artifact manifest fields do not match schema"
            )
        if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
            raise ContractValidationError("unsupported artifact manifest version")
        input_hashes = value["input_hashes"]
        if not isinstance(input_hashes, list) or len(input_hashes) > 1000:
            raise ContractValidationError("artifact manifest inputs are invalid")
        inputs = tuple(validate_sha256(item) for item in input_hashes)
        if len(set(inputs)) != len(inputs):
            raise ContractValidationError("artifact manifest inputs are duplicated")
        producer = value["producer_version"]
        if not isinstance(producer, dict):
            raise ContractValidationError("artifact manifest producer is invalid")
        return cls(
            validate_sha256(value["artifact_hash"]),
            inputs,
            ProducerVersion.from_json(canonical_json(producer)),
            validate_sha256(value["config_hash"]),
            validate_sha256(value["retention_policy_hash"]),
            validate_utc_instant(value["created_at"]),
        )


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class ArtifactRepository:
    """Coordinate blob-before-reference artifact publication."""

    def __init__(
        self,
        database: Database,
        store: ArtifactStore,
        ledger: LedgerRepository | None = None,
    ) -> None:
        self._database = database
        self._store = store
        self._ledger = ledger or LedgerRepository()
        self._commands = CommandTransaction(database)

    def publish(
        self,
        chunks: Iterable[bytes],
        *,
        expected_hash: str,
        byte_length: int,
        maximum_length: int,
        media_type: str,
        kind: str,
        input_hashes: tuple[str, ...],
        producer_version: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
        command_id: UUID,
        record_id: UUID | None = None,
    ) -> ArtifactPublication:
        transaction, _ = self._prepare_publication(
            chunks,
            expected_hash=expected_hash,
            byte_length=byte_length,
            maximum_length=maximum_length,
            media_type=media_type,
            kind=kind,
            input_hashes=input_hashes,
            producer_version=producer_version,
            config_hash=config_hash,
            retention_policy_hash=retention_policy_hash,
            command_id=command_id,
            record_id=record_id,
        )
        return self._database.serializable(transaction)

    def publish_command(
        self,
        chunks: Iterable[bytes],
        *,
        identity: CommandIdentity,
        expected_hash: str,
        byte_length: int,
        maximum_length: int,
        media_type: str,
        kind: str,
        input_hashes: tuple[str, ...],
        producer_version: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
        source_available_at: str | None,
        admission: PublicationAdmission,
    ) -> StoredResponse:
        """Publish through the command transaction after durable blob staging."""

        if source_available_at is not None:
            raise IntegrityFailure(
                "source_available_at requires capture-evidence validation"
            )
        if admission.worker_id != identity.principal_id:
            raise StaleLease("artifact publication principal is not lease worker")

        transaction, publication_created = self._prepare_publication(
            chunks,
            expected_hash=expected_hash,
            byte_length=byte_length,
            maximum_length=maximum_length,
            media_type=media_type,
            kind=kind,
            input_hashes=input_hashes,
            producer_version=producer_version,
            config_hash=config_hash,
            retention_policy_hash=retention_policy_hash,
            command_id=identity.command_id,
        )
        payload = {
            "schema_version": 1,
            "expected_hash": expected_hash,
            "byte_length": byte_length,
            "media_type": media_type,
            "kind": kind,
            "input_hashes": list(input_hashes),
            "producer_version": producer_version.to_dict(),
            "config_hash": config_hash,
            "source_available_at": source_available_at,
            "retention_policy_hash": retention_policy_hash,
        }

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, object]:
            self._check_publication_admission(connection, admission)
            publication = transaction(connection)
            self._check_publication_admission(connection, admission)
            return {
                "artifact_hash": publication.artifact_hash,
                "byte_length": publication.byte_length,
                "created_at": publication.created_at,
                "receipt": {
                    "record_ids": [str(publication.ledger.record_id)],
                    "artifact_hashes": [
                        publication.artifact_hash,
                        publication.manifest_hash,
                    ],
                    "ledger_first": publication.ledger.sequence,
                    "ledger_last": publication.ledger.sequence,
                    "committed_at": publication.ledger.created_at,
                },
            }

        return self._commands.execute(
            identity,
            "/v1/artifacts",
            {},
            payload,
            mutate,
            status_code=lambda _: 201 if publication_created() else 200,
        )

    @staticmethod
    def _check_publication_admission(
        connection: Connection[tuple[object, ...]], admission: PublicationAdmission
    ) -> None:
        row = connection.execute(
            """SELECT kind,state,worker_id,lease_epoch
               FROM jobs WHERE id=%s FOR UPDATE""",
            (admission.job_id,),
        ).fetchone()
        if (
            row is None
            or str(row[0]) not in admission.job_kinds
            or row[1] != "running"
            or row[2] != admission.worker_id
            or cast(int, row[3]) != admission.lease_epoch
        ):
            raise StaleLease("artifact publication lease is not admitted")
        current = connection.execute(
            "SELECT expires_at > clock_timestamp() FROM jobs WHERE id=%s",
            (admission.job_id,),
        ).fetchone()
        if current is None or not cast(bool, current[0]):
            raise LeaseExpired("artifact publication lease expired")

    def _prepare_publication(
        self,
        chunks: Iterable[bytes],
        *,
        expected_hash: str,
        byte_length: int,
        maximum_length: int,
        media_type: str,
        kind: str,
        input_hashes: tuple[str, ...],
        producer_version: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
        command_id: UUID,
        record_id: UUID | None = None,
    ) -> tuple[
        Callable[[Connection[tuple[object, ...]]], ArtifactPublication],
        Callable[[], bool],
    ]:
        with SpooledTemporaryFile(max_size=1024 * 1024) as staged:
            length = 0
            digest = hashlib.sha256()
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise TypeError("artifact chunks must be bytes")
                length += len(chunk)
                if length > byte_length or length > maximum_length:
                    raise IntegrityFailure("artifact length exceeds declaration")
                digest.update(chunk)
                staged.write(chunk)
            if length != byte_length or digest.hexdigest() != expected_hash:
                raise IntegrityFailure("artifact bytes do not match declaration")
            staged.seek(0)
            blob = self._store.commit(
                iter(lambda: staged.read(64 * 1024), b""),
                expected_hash=expected_hash,
                expected_length=byte_length,
                maximum_length=maximum_length,
            )
        created_at = datetime.now(timezone.utc)
        manifest_bytes = ArtifactManifest(
            expected_hash,
            input_hashes,
            producer_version,
            config_hash,
            retention_policy_hash,
            _utc(created_at),
        ).to_canonical_json()
        manifest_hash = sha256_hex(manifest_bytes)
        self._store.commit(
            [manifest_bytes],
            expected_hash=manifest_hash,
            expected_length=len(manifest_bytes),
            maximum_length=128 * 1024,
        )
        ledger_payload_bytes = ArtifactRef(1, manifest_hash).to_canonical_json()
        ledger_payload_hash = sha256_hex(ledger_payload_bytes)
        if ledger_payload_hash == expected_hash:
            raise IntegrityFailure("artifact identity collides with its ledger payload")
        self._store.commit(
            [ledger_payload_bytes],
            expected_hash=ledger_payload_hash,
            expected_length=len(ledger_payload_bytes),
            maximum_length=128 * 1024,
        )
        ledger_record_id = record_id or uuid4()
        metadata_created = False

        def transaction(
            connection: Connection[tuple[object, ...]],
        ) -> ArtifactPublication:
            nonlocal metadata_created
            existing = connection.execute(
                """
                SELECT a.byte_length, a.media_type, a.kind, a.created_at,
                       t.artifact_hash IS NOT NULL
                FROM artifacts a
                LEFT JOIN artifact_tombstones t ON t.artifact_hash = a.hash
                WHERE a.hash = decode(%s, 'hex')
                """,
                (expected_hash,),
            ).fetchone()
            if existing is not None:
                if (
                    cast(int, existing[0]) != byte_length
                    or str(existing[1]) != media_type
                    or str(existing[2]) != kind
                ):
                    raise IntegrityFailure("artifact identity has conflicting metadata")
                if cast(bool, existing[4]):
                    raise UnavailableInput("artifact identity is tombstoned")

            if expected_hash in input_hashes or len(set(input_hashes)) != len(
                input_hashes
            ):
                raise IntegrityFailure(
                    "artifact dependency list is cyclic or duplicated"
                )
            if input_hashes:
                inputs = connection.execute(
                    """
                    SELECT encode(a.hash, 'hex')
                    FROM artifacts a
                    LEFT JOIN artifact_tombstones t ON t.artifact_hash = a.hash
                    WHERE a.hash = ANY(%s) AND t.artifact_hash IS NULL
                    """,
                    ([bytes.fromhex(value) for value in input_hashes],),
                ).fetchall()
                found = {str(row[0]) for row in inputs}
                if found != set(input_hashes):
                    raise UnavailableInput(
                        "artifact dependency is absent or tombstoned"
                    )

            inserted = connection.execute(
                """
                INSERT INTO artifacts(
                    hash, byte_length, media_type, kind, created_at, available_at,
                    retention_policy_hash, producer_image_digest,
                    producer_source_commit, producer_contract_version, config_hash
                ) VALUES (
                    decode(%s, 'hex'), %s, %s, %s, %s, %s,
                    decode(%s, 'hex'), decode(%s, 'hex'), decode(%s, 'hex'), %s,
                    decode(%s, 'hex')
                )
                ON CONFLICT (hash) DO NOTHING
                RETURNING hash
                """,
                (
                    expected_hash,
                    byte_length,
                    media_type,
                    kind,
                    created_at,
                    created_at,
                    retention_policy_hash,
                    producer_version.image_digest,
                    producer_version.source_commit,
                    producer_version.contract_version,
                    config_hash,
                ),
            ).fetchone()
            metadata_created = inserted is not None
            if inserted is None and existing is None:
                raise SerializationFailure("artifact was published concurrently")
            connection.execute(
                """
                INSERT INTO artifacts(
                    hash, byte_length, media_type, kind, created_at, available_at,
                    retention_policy_hash, producer_image_digest,
                    producer_source_commit, producer_contract_version, config_hash
                ) VALUES (
                    decode(%s, 'hex'), %s, 'application/json', 'manifest', %s, %s,
                    decode(%s, 'hex'), decode(%s, 'hex'), decode(%s, 'hex'), %s,
                    decode(%s, 'hex')
                )
                """,
                (
                    manifest_hash,
                    len(manifest_bytes),
                    created_at,
                    created_at,
                    retention_policy_hash,
                    producer_version.image_digest,
                    producer_version.source_commit,
                    producer_version.contract_version,
                    config_hash,
                ),
            )
            connection.execute(
                """
                INSERT INTO artifact_productions(
                    manifest_hash, artifact_hash, created_at,
                    producer_image_digest, producer_source_commit,
                    producer_contract_version, config_hash, retention_policy_hash
                ) VALUES (
                    decode(%s, 'hex'), decode(%s, 'hex'), %s,
                    decode(%s, 'hex'), decode(%s, 'hex'), %s, decode(%s, 'hex'),
                    decode(%s, 'hex')
                )
                """,
                (
                    manifest_hash,
                    expected_hash,
                    created_at,
                    producer_version.image_digest,
                    producer_version.source_commit,
                    producer_version.contract_version,
                    config_hash,
                    retention_policy_hash,
                ),
            )
            for ordinal, input_hash in enumerate(input_hashes):
                connection.execute(
                    """
                    INSERT INTO artifact_production_edges(
                        manifest_hash, input_hash, ordinal
                    ) VALUES (decode(%s, 'hex'), decode(%s, 'hex'), %s)
                    """,
                    (manifest_hash, input_hash, ordinal),
                )
            payload_inserted = connection.execute(
                """
                INSERT INTO artifacts(
                    hash, byte_length, media_type, kind, created_at, available_at,
                    retention_policy_hash, producer_image_digest,
                    producer_source_commit, producer_contract_version, config_hash
                ) VALUES (
                    decode(%s, 'hex'), %s, 'application/json', 'manifest', %s, %s,
                    decode(%s, 'hex'), decode(%s, 'hex'), decode(%s, 'hex'), %s,
                    decode(%s, 'hex')
                )
                ON CONFLICT (hash) DO NOTHING
                RETURNING hash
                """,
                (
                    ledger_payload_hash,
                    len(ledger_payload_bytes),
                    created_at,
                    created_at,
                    retention_policy_hash,
                    producer_version.image_digest,
                    producer_version.source_commit,
                    producer_version.contract_version,
                    config_hash,
                ),
            ).fetchone()
            if payload_inserted is None:
                raise SerializationFailure("ledger payload was published concurrently")
            connection.execute(
                """
                INSERT INTO artifact_edges(output_hash, input_hash, ordinal)
                VALUES (decode(%s, 'hex'), decode(%s, 'hex'), 0)
                """,
                (ledger_payload_hash, manifest_hash),
            )
            ledger = self._ledger.append(
                connection,
                record_id=ledger_record_id,
                event_kind="artifact_committed",
                payload_hash=ledger_payload_hash,
                command_id=command_id,
            )
            published_row = connection.execute("SELECT clock_timestamp()").fetchone()
            assert published_row is not None
            published_at = cast(datetime, published_row[0])
            connection.execute(
                """
                INSERT INTO artifact_publication_receipts(
                    artifact_hash, committed_ledger_sequence, published_at
                ) VALUES
                    (decode(%s, 'hex'), %s, %s),
                    (decode(%s, 'hex'), %s, %s),
                    (decode(%s, 'hex'), %s, %s)
                ON CONFLICT (artifact_hash) DO NOTHING
                """,
                (
                    expected_hash,
                    ledger.sequence,
                    published_at,
                    manifest_hash,
                    ledger.sequence,
                    published_at,
                    ledger_payload_hash,
                    ledger.sequence,
                    published_at,
                ),
            )
            receipt = ArtifactPublicationReceipt(
                1, manifest_hash, ledger.sequence, _utc(published_at)
            )
            return ArtifactPublication(
                expected_hash,
                manifest_hash,
                byte_length,
                _utc(created_at),
                ledger,
                receipt,
                blob.created,
            )

        return transaction, lambda: metadata_created

    def read(self, artifact_hash: str) -> tuple[tuple[int, str], BinaryIO]:
        def check(connection: Connection[tuple[object, ...]]) -> tuple[int, str] | None:
            row = connection.execute(
                """
                SELECT a.byte_length, a.media_type
                FROM artifacts a
                LEFT JOIN artifact_tombstones t ON t.artifact_hash = a.hash
                WHERE a.hash = decode(%s, 'hex') AND t.artifact_hash IS NULL
                """,
                (artifact_hash,),
            ).fetchone()
            return None if row is None else (cast(int, row[0]), cast(str, row[1]))

        metadata = self._database.transaction(check)
        if metadata is None:
            raise UnavailableInput("artifact is absent or unavailable")
        stream = self._store.open_verified(artifact_hash)
        return metadata, stream
