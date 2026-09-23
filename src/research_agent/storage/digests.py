"""Persist a built digest, its entries and their nominations (EN-40, #179).

The orchestrator supplies an already-built manifest (``digest/build.py``)
resolved to real paper hashes; this module only stores it, idempotent by
``digest_hash``, and serves the two shapes storage now owes a reader: a
blind read for the rating app (SR-21, SR-22 -- no origin, no nomination)
and a full read with origin and nominations for the inspector and report.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.digests import validate_digest_store_payload
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict
from research_agent.storage.idempotency import StoredResponse


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class DigestRepository:
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
        value = validate_digest_store_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._store(connection, identity, value)

        return self._commands.execute(identity, "/v1/digests", {}, value, mutate)

    def _store(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        existing = connection.execute(
            """SELECT encode(hash,'hex') FROM digests
               WHERE batch_id=decode(%s,'hex') AND island=%s""",
            (value["batch_id"], value["island"]),
        ).fetchone()
        if existing is not None:
            if existing[0] != value["digest_hash"]:
                raise StateConflict(
                    "island already has a digest built for this batch"
                    " with different content"
                )
            return self._read_committed(connection, value["digest_hash"])

        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="digest_created",
            payload={
                "schema_version": 1,
                "digest_hash": value["digest_hash"],
                "batch_id": value["batch_id"],
                "island": value["island"],
                "source_watermark": value["source_watermark"],
                "shuffle_seed": value["shuffle_seed"],
                "entries": value["entries"],
                "nominations": value["nominations"],
            },
            input_hashes=(),
        )
        manifest_hash = cast(str, receipt["artifact_hashes"][0])
        inserted = connection.execute(
            """INSERT INTO digests(
                   hash, batch_id, island, source_watermark, shuffle_seed,
                   manifest_hash, built_at
               ) VALUES(
                   decode(%s,'hex'), decode(%s,'hex'), %s, %s, decode(%s,'hex'),
                   decode(%s,'hex'), clock_timestamp()
               ) RETURNING built_at""",
            (
                value["digest_hash"],
                value["batch_id"],
                value["island"],
                value["source_watermark"],
                value["shuffle_seed"],
                manifest_hash,
            ),
        ).fetchone()
        assert inserted is not None
        built_at = inserted[0]
        for entry in value["entries"]:
            connection.execute(
                """INSERT INTO digest_entries(
                       entry_id, digest_hash, paper_hash, origin, display_position,
                       service_source, candidate_pool_hash, inclusion_probability
                   ) VALUES(
                       %s, decode(%s,'hex'), decode(%s,'hex'), %s, %s, %s,
                       decode(%s,'hex'), %s
                   )""",
                (
                    entry["entry_id"],
                    value["digest_hash"],
                    entry["paper_hash"],
                    entry["origin"],
                    entry["display_position"],
                    entry["service_source"],
                    entry["candidate_pool_hash"],
                    entry["inclusion_probability"],
                ),
            )
        for nomination in value["nominations"]:
            connection.execute(
                """INSERT INTO digest_nominations(
                       entry_id, configuration_id, submission_id, preference
                   ) VALUES(%s, %s, %s, %s)""",
                (
                    nomination["entry_id"],
                    nomination["configuration_id"],
                    nomination["submission_id"],
                    nomination["preference"],
                ),
            )
        return {
            "digest_hash": value["digest_hash"],
            "built_at": _utc(cast(datetime, built_at)),
            "receipt": receipt,
        }

    def _read_committed(
        self, connection: Connection[tuple[object, ...]], digest_hash: str
    ) -> dict[str, Any]:
        """Return the already-stored result of an earlier, identical build.

        A retried build carries a fresh command id and idempotency key -- a
        crash-recovery rebuild, not a replayed HTTP request -- so the outer
        per-command idempotency store never sees it; this reconstructs the
        same response shape from what committing the first build already
        recorded, without appending a second ``digest_created`` event.
        """

        row = connection.execute(
            """SELECT built_at, encode(manifest_hash,'hex') FROM digests
               WHERE hash=decode(%s,'hex')""",
            (digest_hash,),
        ).fetchone()
        assert row is not None
        built_at, manifest_hash = cast(datetime, row[0]), cast(str, row[1])
        receipt_row = connection.execute(
            """SELECT lr.record_id, lr.created_at, pr.committed_ledger_sequence
               FROM artifact_publication_receipts pr
               JOIN ledger_records lr ON lr.sequence = pr.committed_ledger_sequence
               WHERE pr.artifact_hash = decode(%s,'hex')""",
            (manifest_hash,),
        ).fetchone()
        assert receipt_row is not None
        record_id, committed_at, sequence = (
            cast(UUID, receipt_row[0]),
            cast(datetime, receipt_row[1]),
            cast(int, receipt_row[2]),
        )
        return {
            "digest_hash": digest_hash,
            "built_at": _utc(built_at),
            "receipt": {
                "record_ids": [str(record_id)],
                "artifact_hashes": [manifest_hash],
                "ledger_first": sequence,
                "ledger_last": sequence,
                "committed_at": _utc(committed_at),
            },
        }

    def read_for_rater(self, *, island: str, batch_id: str) -> dict[str, Any] | None:
        """Blind read: an island's digest entries, never origin or nomination.

        Everything a shuffle needs to reproduce the rater's display order --
        the entries and the recorded seed -- is here; what would unblind a
        control, a service pick or a genome (SR-21, SR-22) never is.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> dict[str, Any] | None:
            digest = connection.execute(
                """SELECT encode(hash,'hex'), source_watermark,
                          encode(shuffle_seed,'hex'), built_at
                   FROM digests WHERE batch_id=decode(%s,'hex') AND island=%s""",
                (batch_id, island),
            ).fetchone()
            if digest is None:
                return None
            entries = connection.execute(
                """SELECT entry_id, encode(paper_hash,'hex'), display_position
                   FROM digest_entries WHERE digest_hash=decode(%s,'hex')
                   ORDER BY display_position""",
                (digest[0],),
            ).fetchall()
            return {
                "digest_hash": digest[0],
                "batch_id": batch_id,
                "island": island,
                "source_watermark": digest[1],
                "shuffle_seed": digest[2],
                "built_at": _utc(cast(datetime, digest[3])),
                "entries": [
                    {
                        "entry_id": str(row[0]),
                        "paper_hash": row[1],
                        "display_position": row[2],
                    }
                    for row in entries
                ],
            }

        return self._database.transaction(read)

    def read_with_provenance(self, digest_hash: str) -> dict[str, Any] | None:
        """Full read: entries with origin and their nominating configurations.

        For the inspector and the weekly report, never for a rater.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> dict[str, Any] | None:
            digest = connection.execute(
                """SELECT encode(batch_id,'hex'), island, source_watermark,
                          encode(shuffle_seed,'hex'), built_at
                   FROM digests WHERE hash=decode(%s,'hex')""",
                (digest_hash,),
            ).fetchone()
            if digest is None:
                return None
            entries = connection.execute(
                """SELECT entry_id, encode(paper_hash,'hex'), origin, display_position,
                          service_source, encode(candidate_pool_hash,'hex'),
                          inclusion_probability
                   FROM digest_entries WHERE digest_hash=decode(%s,'hex')
                   ORDER BY display_position""",
                (digest_hash,),
            ).fetchall()
            nominations = connection.execute(
                """SELECT n.entry_id, n.configuration_id, n.submission_id, n.preference
                   FROM digest_nominations n
                   JOIN digest_entries e ON e.entry_id = n.entry_id
                   WHERE e.digest_hash = decode(%s,'hex')
                   ORDER BY n.entry_id, n.configuration_id""",
                (digest_hash,),
            ).fetchall()
            by_entry: dict[str, list[dict[str, Any]]] = {}
            for row in nominations:
                by_entry.setdefault(str(row[0]), []).append(
                    {
                        "configuration_id": str(row[1]),
                        "submission_id": str(row[2]),
                        "preference": row[3],
                    }
                )
            return {
                "digest_hash": digest_hash,
                "batch_id": digest[0],
                "island": digest[1],
                "source_watermark": digest[2],
                "shuffle_seed": digest[3],
                "built_at": _utc(cast(datetime, digest[4])),
                "entries": [
                    {
                        "entry_id": str(row[0]),
                        "paper_hash": row[1],
                        "origin": row[2],
                        "display_position": row[3],
                        "service_source": row[4],
                        "candidate_pool_hash": row[5],
                        "inclusion_probability": row[6],
                        "nominations": by_entry.get(str(row[0]), []),
                    }
                    for row in entries
                ],
            }

        return self._database.transaction(read)
