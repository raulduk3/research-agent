"""Read-only owner-inspector queries over durable storage, exactly as stored.

Every method here returns stored records unchanged: no aggregation, no
recomputation, no field invented to fill a gap the underlying tables do not
yet hold. A configuration's genome and a forecast's resolution are not
storage records yet (#162, #177), so no method here promises them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import canonical_loads
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput

PAGE_SIZE = 50
MAXIMUM_MANIFEST_BYTES = 1024 * 1024

_REPRESENTATION_MANIFEST_FIELDS = frozenset(
    {
        "model_id",
        "revision",
        "checkpoint_date",
        "dtype",
        "dimension",
        "pooling",
        "document_prefix",
        "query_prefix",
        "max_model_tokens",
        "tokenizer_hash",
        "weight_hash",
        "qualified",
    }
)
_DEPLOYMENT_MANIFEST_FIELDS = frozenset(
    {"provider", "model_id", "endpoint", "revision", "qualified"}
)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


def _decode_json(value: object) -> Any:
    return canonical_loads(bytes(cast("bytes | memoryview", value)))


class InspectorQueries:
    """Owner-facing reads over runs, submissions and manifest artifacts."""

    def __init__(self, database: Database, store: ArtifactStore) -> None:
        self._database = database
        self._store = store

    def run(self, run_id: str) -> dict[str, Any] | None:
        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            row = connection.execute(
                """SELECT id, encode(batch_id,'hex'), paper_id, configuration_id,
                          attempt, encode(genome_hash,'hex'), seed,
                          encode(snapshot_hash,'hex'), budgets, allowed_tools,
                          model_identity, checkpoint_dates, created_at
                   FROM runs WHERE id=%s""",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            events = connection.execute(
                """SELECT attempt, ordinal, kind, encode(payload_hash,'hex'),
                          recorded_at
                   FROM run_events WHERE run_id=%s ORDER BY attempt, ordinal""",
                (run_id,),
            ).fetchall()
            return {
                **_run_fields(row),
                "events": [_event_fields(event) for event in events],
            }

        return self._database.transaction(read)

    def runs_by_configuration(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]:
        before = (_parse_utc(cursor[0]), cursor[1]) if cursor is not None else None

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            if before is None:
                return connection.execute(
                    """SELECT id, encode(batch_id,'hex'), paper_id, configuration_id,
                              attempt, encode(genome_hash,'hex'), seed,
                              encode(snapshot_hash,'hex'), budgets, allowed_tools,
                              model_identity, checkpoint_dates, created_at
                       FROM runs WHERE configuration_id=%s
                       ORDER BY created_at DESC, id DESC LIMIT %s""",
                    (configuration_id, PAGE_SIZE + 1),
                ).fetchall()
            return connection.execute(
                """SELECT id, encode(batch_id,'hex'), paper_id, configuration_id,
                          attempt, encode(genome_hash,'hex'), seed,
                          encode(snapshot_hash,'hex'), budgets, allowed_tools,
                          model_identity, checkpoint_dates, created_at
                   FROM runs WHERE configuration_id=%s
                     AND (created_at, id) < (%s, %s)
                   ORDER BY created_at DESC, id DESC LIMIT %s""",
                (configuration_id, before[0], before[1], PAGE_SIZE + 1),
            ).fetchall()

        rows = self._database.transaction(read)
        page, has_more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
        next_cursor = None
        if has_more:
            last = page[-1]
            next_cursor = (_utc(cast(datetime, last[12])), str(last[0]))
        return tuple(_run_fields(row) for row in page), next_cursor

    def submissions_by_submitter(self, submitter_id: str) -> tuple[dict[str, Any], ...]:
        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[dict[str, Any]]:
            rows = connection.execute(
                """SELECT id, encode(sheet_hash,'hex'), question_id, status,
                          confidence, horizon, reason, sealed_at
                   FROM submissions WHERE submitter_id=%s
                   ORDER BY sealed_at, id""",
                (submitter_id,),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                evidence = connection.execute(
                    """SELECT encode(evidence_hash,'hex')
                       FROM submission_evidence
                       WHERE submission_id=%s ORDER BY ordinal""",
                    (row[0],),
                ).fetchall()
                result.append(
                    {
                        "submission_id": str(row[0]),
                        "sheet_hash": row[1],
                        "question_id": str(row[2]),
                        "status": row[3],
                        "confidence": row[4],
                        "horizon": _utc(cast(datetime, row[5]))
                        if row[5] is not None
                        else None,
                        "reason": row[6],
                        "sealed_at": _utc(cast(datetime, row[7])),
                        "evidence_hashes": [item[0] for item in evidence],
                    }
                )
            return result

        return tuple(self._database.transaction(read))

    def manifest(self, manifest_hash: str) -> dict[str, Any] | None:
        """Resolve a manifest reference to the domain artifact it names.

        Every ``*_manifest``/``*_hash`` reference elsewhere in storage (a
        run's ``agent_model_manifest``, a snapshot's ``paper_manifest_hash``)
        names the production-wrapped identity in ``artifact_productions``,
        not a payload's own content hash; this resolves the same way before
        reading the payload it wraps.
        """

        def check(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[str, str, int, datetime] | None:
            row = connection.execute(
                """SELECT encode(p.artifact_hash,'hex'), a.kind, a.media_type,
                          a.byte_length, a.created_at
                   FROM artifact_productions p
                   JOIN artifacts a ON a.hash = p.artifact_hash
                   LEFT JOIN artifact_tombstones mt ON mt.artifact_hash = p.manifest_hash
                   LEFT JOIN artifact_tombstones at ON at.artifact_hash = p.artifact_hash
                   WHERE p.manifest_hash = decode(%s,'hex')
                     AND mt.artifact_hash IS NULL AND at.artifact_hash IS NULL""",
                (manifest_hash,),
            ).fetchone()
            if row is None or row[1] != "manifest":
                return None
            return (
                cast(str, row[0]),
                cast(str, row[2]),
                cast(int, row[3]),
                cast(datetime, row[4]),
            )

        resolved = self._database.transaction(check)
        if resolved is None:
            return None
        artifact_hash, media_type, byte_length, created_at = resolved
        if byte_length > MAXIMUM_MANIFEST_BYTES:
            raise UnavailableInput(
                "manifest artifact exceeds the inspector's size bound"
            )
        with self._store.open_verified(artifact_hash) as stream:
            raw = stream.read()
        value = canonical_loads(raw)
        fields = value if isinstance(value, dict) else {}
        if set(fields) == _REPRESENTATION_MANIFEST_FIELDS:
            manifest_kind = "representation"
        elif set(fields) == _DEPLOYMENT_MANIFEST_FIELDS:
            manifest_kind = "deployment"
        else:
            manifest_kind = "unknown"
        return {
            "manifest_hash": manifest_hash,
            "artifact_hash": artifact_hash,
            "manifest_kind": manifest_kind,
            "media_type": media_type,
            "byte_length": byte_length,
            "created_at": _utc(created_at),
            "fields": fields,
        }


def _run_fields(row: tuple[object, ...]) -> dict[str, Any]:
    return {
        "run_id": str(row[0]),
        "batch_id": row[1],
        "paper_id": row[2],
        "configuration_id": str(row[3]),
        "attempt": row[4],
        "genome_hash": row[5],
        "seed": row[6],
        "snapshot_hash": row[7],
        "budgets": _decode_json(row[8]),
        "allowed_tools": list(cast(list[str], row[9])),
        "model_identity": _decode_json(row[10]),
        "checkpoint_dates": _decode_json(row[11]),
        "created_at": _utc(cast(datetime, row[12])),
    }


def _event_fields(row: tuple[object, ...]) -> dict[str, Any]:
    return {
        "attempt": row[0],
        "ordinal": row[1],
        "kind": row[2],
        "payload_hash": row[3],
        "recorded_at": _utc(cast(datetime, row[4])),
    }
