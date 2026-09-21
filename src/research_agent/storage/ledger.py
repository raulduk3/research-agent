"""Serializable append-only hash-chain ledger."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from psycopg import Connection

from research_agent.contracts import canonical_json
from research_agent.storage.errors import IntegrityFailure, StateConflict

GENESIS_HASH = "0" * 64


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    sequence: int
    record_id: UUID
    previous_record_hash: str
    record_hash: str
    event_kind: str
    payload_hash: str
    created_at: str
    command_id: UUID


class LedgerRepository:
    """Append records inside an existing serializable transaction."""

    def append(
        self,
        connection: Connection[tuple[object, ...]],
        *,
        record_id: UUID,
        event_kind: str,
        payload_hash: str,
        command_id: UUID,
        expected_head: str | None = None,
    ) -> LedgerEvent:
        row = connection.execute(
            "SELECT sequence, encode(record_hash, 'hex') FROM ledger_head WHERE singleton FOR UPDATE"
        ).fetchone()
        if row is None:
            raise IntegrityFailure("ledger head is absent")
        head_sequence, previous_hash = cast(int, row[0]), cast(str, row[1])
        if expected_head is not None and previous_hash != expected_head:
            raise StateConflict("ledger head changed")

        created_row = connection.execute("SELECT clock_timestamp()").fetchone()
        assert created_row is not None
        created_at_datetime = cast(datetime, created_row[0])
        sequence = head_sequence + 1
        created_at = _utc(created_at_datetime)
        preimage = {
            "schema_version": 1,
            "sequence": sequence,
            "record_id": str(record_id),
            "previous_record_hash": previous_hash,
            "event_kind": event_kind,
            "payload_hash": payload_hash,
            "created_at": created_at,
            "command_id": str(command_id),
        }
        record_hash = hashlib.sha256(canonical_json(preimage)).hexdigest()
        connection.execute(
            """
            INSERT INTO ledger_records(
                sequence, record_id, previous_record_hash, record_hash,
                event_kind, payload_hash, created_at, command_id
            ) VALUES (%s, %s, decode(%s, 'hex'), decode(%s, 'hex'), %s,
                      decode(%s, 'hex'), %s, %s)
            """,
            (
                sequence,
                record_id,
                previous_hash,
                record_hash,
                event_kind,
                payload_hash,
                created_at_datetime,
                command_id,
            ),
        )
        connection.execute(
            "UPDATE ledger_head SET sequence = %s, record_hash = decode(%s, 'hex') WHERE singleton",
            (sequence, record_hash),
        )
        return LedgerEvent(
            sequence,
            record_id,
            previous_hash,
            record_hash,
            event_kind,
            payload_hash,
            created_at,
            command_id,
        )

    def verify(self, connection: Connection[tuple[object, ...]]) -> int:
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        records = connection.execute(
            """
            SELECT sequence, record_id, encode(previous_record_hash, 'hex'),
                   encode(record_hash, 'hex'), event_kind, encode(payload_hash, 'hex'),
                   created_at, command_id
            FROM ledger_records ORDER BY sequence
            """
        ).fetchall()
        for row in records:
            sequence = cast(int, row[0])
            if sequence != expected_sequence or str(row[2]) != previous_hash:
                raise IntegrityFailure(f"ledger chain breaks at sequence {sequence}")
            preimage = {
                "schema_version": 1,
                "sequence": sequence,
                "record_id": str(row[1]),
                "previous_record_hash": str(row[2]),
                "event_kind": str(row[4]),
                "payload_hash": str(row[5]),
                "created_at": _utc(cast(datetime, row[6])),
                "command_id": str(row[7]),
            }
            actual_hash = hashlib.sha256(canonical_json(preimage)).hexdigest()
            if actual_hash != str(row[3]):
                raise IntegrityFailure(
                    f"ledger record hash fails at sequence {sequence}"
                )
            previous_hash = actual_hash
            expected_sequence += 1

        head = connection.execute(
            "SELECT sequence, encode(record_hash, 'hex') FROM ledger_head WHERE singleton"
        ).fetchone()
        if (
            head is None
            or cast(int, head[0]) != len(records)
            or str(head[1]) != previous_hash
        ):
            raise IntegrityFailure("ledger head does not match the record chain")
        return len(records)
