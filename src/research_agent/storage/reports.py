"""Stored qualification reports, one kind per producing command (#324).

A command that qualifies something (the inference battery, the Jev smoke
test, the retrieval comparison, the three-head fit) publishes its report as
an artifact and records it here: one immutable row naming the report's kind,
primary metric and its registration and execution instants, written in the
same transaction as a ``qualification_report_recorded`` ledger event whose
payload artifact cites the report. ``latest`` answers activation admission's
read: the most recently recorded report of a kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import cast
from uuid import UUID

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.storage.commands import DomainEvents
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput

__all__ = [
    "EVENT_KIND",
    "REPORT_KINDS",
    "QualificationReportRepository",
    "StoredQualificationReport",
]

EVENT_KIND = "qualification_report_recorded"

_SELECT = (
    "SELECT report_id, report_kind, encode(report_hash,'hex'), primary_metric,"
    " registered_at, executed_at, ledger_sequence FROM qualification_reports"
)

# Every kind activation admission requires, in the order it names a missing one.
REPORT_KINDS: tuple[str, ...] = (
    "inference_battery",
    "jev_smoke",
    "retrieval",
    "three_head",
)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _report_id(*parts: str) -> UUID:
    """A version-4-shaped id fixed by the report, so recording it again replays."""

    digest = bytearray(sha256(canonical_json(list(parts))).digest())
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(digest[:16]))


@dataclass(frozen=True, slots=True)
class StoredQualificationReport:
    """One recorded qualification report, as admission reads it."""

    report_id: str
    report_kind: str
    report_hash: str
    primary_metric: str
    registered_at: str
    executed_at: str
    ledger_sequence: int


class QualificationReportRepository:
    """Records each qualification report with its ledger event and reads them back."""

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
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def record(
        self,
        *,
        report_kind: str,
        report_hash: str,
        primary_metric: str,
        registered_at: str,
        executed_at: str,
    ) -> StoredQualificationReport:
        """Record the published report ``report_hash`` as the latest of its kind.

        The report's bytes must already be a stored artifact. Recording the
        same report with the same metric and instants again records nothing
        new and returns the first record.
        """

        if report_kind not in REPORT_KINDS:
            raise ContractValidationError(
                f"unknown qualification report kind: {report_kind}"
            )
        validate_sha256(report_hash)
        validate_non_empty_string(primary_metric)
        validate_utc_instant(registered_at)
        validate_utc_instant(executed_at)
        if registered_at > executed_at:
            raise ContractValidationError(
                "a report's registration must precede its execution"
            )
        report_id = _report_id(
            report_kind, report_hash, primary_metric, registered_at, executed_at
        )

        def insert(
            connection: Connection[tuple[object, ...]],
        ) -> StoredQualificationReport:
            existing = self._select(connection, report_id=report_id)
            if existing is not None:
                return existing
            row = connection.execute(
                """SELECT 1 FROM artifacts a
                   LEFT JOIN artifact_tombstones t ON t.artifact_hash = a.hash
                   WHERE a.hash = decode(%s,'hex') AND t.artifact_hash IS NULL""",
                (report_hash,),
            ).fetchone()
            if row is None:
                raise UnavailableInput("qualification report is not a stored artifact")
            receipt = self._events.append(
                connection,
                command_id=report_id,
                event_kind=EVENT_KIND,
                payload={
                    "report_id": str(report_id),
                    "report_kind": report_kind,
                    "report_hash": report_hash,
                    "primary_metric": primary_metric,
                    "registered_at": registered_at,
                    "executed_at": executed_at,
                },
                input_hashes=(report_hash,),
            )
            connection.execute(
                """INSERT INTO qualification_reports(
                       report_id, report_kind, report_hash, primary_metric,
                       registered_at, executed_at, ledger_sequence)
                   VALUES(%s, %s, decode(%s,'hex'), %s, %s, %s, %s)""",
                (
                    report_id,
                    report_kind,
                    report_hash,
                    primary_metric,
                    registered_at,
                    executed_at,
                    receipt["ledger_first"],
                ),
            )
            return StoredQualificationReport(
                str(report_id),
                report_kind,
                report_hash,
                primary_metric,
                registered_at,
                executed_at,
                cast(int, receipt["ledger_first"]),
            )

        return self._database.serializable(insert)

    def latest(self, report_kind: str) -> StoredQualificationReport | None:
        """The kind's most recently recorded report, or None when it has none."""

        if report_kind not in REPORT_KINDS:
            raise ContractValidationError(
                f"unknown qualification report kind: {report_kind}"
            )
        return self._database.transaction(
            lambda connection: self._select(connection, report_kind=report_kind)
        )

    @staticmethod
    def _select(
        connection: Connection[tuple[object, ...]],
        *,
        report_id: UUID | None = None,
        report_kind: str | None = None,
    ) -> StoredQualificationReport | None:
        if report_id is not None:
            row = connection.execute(
                _SELECT + " WHERE report_id=%s", (report_id,)
            ).fetchone()
        else:
            row = connection.execute(
                _SELECT + " WHERE report_kind=%s ORDER BY ledger_sequence DESC LIMIT 1",
                (report_kind,),
            ).fetchone()
        if row is None:
            return None
        return StoredQualificationReport(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            _utc(cast(datetime, row[4])),
            _utc(cast(datetime, row[5])),
            cast(int, row[6]),
        )
