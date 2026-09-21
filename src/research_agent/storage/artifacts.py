"""Artifact publication after durable blob installation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO, cast
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.errors import SerializationFailure

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ArtifactRef, ProducerVersion, sha256_hex
from research_agent.contracts.storage import ArtifactPublicationReceipt
from research_agent.storage.database import Database
from research_agent.storage.errors import IntegrityFailure, UnavailableInput
from research_agent.storage.ledger import LedgerEvent, LedgerRepository


@dataclass(frozen=True, slots=True)
class ArtifactPublication:
    artifact_hash: str
    byte_length: int
    created_at: str
    ledger: LedgerEvent
    receipt: ArtifactPublicationReceipt
    blob_created: bool


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
        blob = self._store.commit(
            chunks,
            expected_hash=expected_hash,
            expected_length=byte_length,
            maximum_length=maximum_length,
        )
        ledger_payload_bytes = ArtifactRef(1, expected_hash).to_canonical_json()
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

        def transaction(
            connection: Connection[tuple[object, ...]],
        ) -> ArtifactPublication:
            existing = connection.execute(
                """
                SELECT a.byte_length, a.media_type, a.kind, a.created_at,
                       encode(a.retention_policy_hash, 'hex'),
                       encode(a.producer_image_digest, 'hex'),
                       encode(a.producer_source_commit, 'hex'),
                       a.producer_contract_version, encode(a.config_hash, 'hex'),
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
                    or str(existing[4]) != retention_policy_hash
                    or str(existing[5]) != producer_version.image_digest
                    or str(existing[6]) != producer_version.source_commit
                    or cast(int, existing[7]) != producer_version.contract_version
                    or str(existing[8]) != config_hash
                ):
                    raise IntegrityFailure("artifact identity has conflicting metadata")
                if cast(bool, existing[9]):
                    raise UnavailableInput("artifact identity is tombstoned")
                edges = connection.execute(
                    """
                    SELECT encode(input_hash, 'hex') FROM artifact_edges
                    WHERE output_hash = decode(%s, 'hex') ORDER BY ordinal
                    """,
                    (expected_hash,),
                ).fetchall()
                if tuple(str(edge[0]) for edge in edges) != input_hashes:
                    raise IntegrityFailure(
                        "artifact identity has conflicting dependencies"
                    )
                ledger_row = connection.execute(
                    """
                    SELECT sequence, record_id, encode(previous_record_hash, 'hex'),
                           encode(record_hash, 'hex'), event_kind,
                           encode(payload_hash, 'hex'), created_at, command_id,
                           r.published_at
                    FROM artifact_publication_receipts r
                    JOIN ledger_records l
                      ON l.sequence = r.committed_ledger_sequence
                    WHERE r.artifact_hash = decode(%s, 'hex')
                    """,
                    (expected_hash,),
                ).fetchone()
                if ledger_row is None:
                    raise IntegrityFailure(
                        "artifact metadata lacks publication ledger record"
                    )
                ledger = LedgerEvent(
                    cast(int, ledger_row[0]),
                    cast(UUID, ledger_row[1]),
                    str(ledger_row[2]),
                    str(ledger_row[3]),
                    str(ledger_row[4]),
                    str(ledger_row[5]),
                    _utc(cast(datetime, ledger_row[6])),
                    cast(UUID, ledger_row[7]),
                )
                receipt = ArtifactPublicationReceipt(
                    1,
                    expected_hash,
                    ledger.sequence,
                    _utc(cast(datetime, ledger_row[8])),
                )
                return ArtifactPublication(
                    expected_hash,
                    byte_length,
                    _utc(cast(datetime, existing[3])),
                    ledger,
                    receipt,
                    blob.created,
                )

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

            created_row = connection.execute("SELECT clock_timestamp()").fetchone()
            assert created_row is not None
            created_at = cast(datetime, created_row[0])
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
            if inserted is None:
                raise SerializationFailure("artifact was published concurrently")
            for ordinal, input_hash in enumerate(input_hashes):
                connection.execute(
                    """
                    INSERT INTO artifact_edges(output_hash, input_hash, ordinal)
                    VALUES (decode(%s, 'hex'), decode(%s, 'hex'), %s)
                    """,
                    (expected_hash, input_hash, ordinal),
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
                (ledger_payload_hash, expected_hash),
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
                    (decode(%s, 'hex'), %s, %s)
                """,
                (
                    expected_hash,
                    ledger.sequence,
                    published_at,
                    ledger_payload_hash,
                    ledger.sequence,
                    published_at,
                ),
            )
            receipt = ArtifactPublicationReceipt(
                1, expected_hash, ledger.sequence, _utc(published_at)
            )
            return ArtifactPublication(
                expected_hash,
                byte_length,
                _utc(created_at),
                ledger,
                receipt,
                blob.created,
            )

        return self._database.serializable(transaction)

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
