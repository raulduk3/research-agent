"""Stored qualification reports with their ledger events, on PostgreSQL (#324)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage import migrations
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput
from research_agent.storage.ledger import LedgerRepository
from research_agent.storage.reports import EVENT_KIND, QualificationReportRepository

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
REGISTERED = "2026-09-01T00:00:00.000000Z"
EXECUTED = "2026-09-02T00:00:00.000000Z"


def _repositories(
    dsn: str, root: Path
) -> tuple[ArtifactRepository, QualificationReportRepository]:
    database = Database(dsn)
    store = ArtifactStore(root)
    reports = QualificationReportRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    return ArtifactRepository(database, store), reports


def _publish(artifacts: ArtifactRepository, body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    artifacts.publish(
        [body],
        expected_hash=digest,
        byte_length=len(body),
        maximum_length=len(body),
        media_type="text/plain",
        kind="study_evidence",
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    return digest


def test_a_kinds_latest_report_is_the_one_recorded_last_with_its_event(
    postgres_dsn: str, artifact_root: Path
) -> None:
    artifacts, reports = _repositories(postgres_dsn, artifact_root)
    assert reports.latest("retrieval") is None

    first = _publish(artifacts, b"# retrieval comparison, first\n")
    recorded = reports.record(
        report_kind="retrieval",
        report_hash=first,
        primary_metric="evidence_support",
        registered_at=REGISTERED,
        executed_at=EXECUTED,
    )
    assert reports.latest("retrieval") == recorded
    # Recording the same report again records nothing new.
    assert (
        reports.record(
            report_kind="retrieval",
            report_hash=first,
            primary_metric="evidence_support",
            registered_at=REGISTERED,
            executed_at=EXECUTED,
        )
        == recorded
    )
    second = _publish(artifacts, b"# retrieval comparison, second\n")
    rerun = reports.record(
        report_kind="retrieval",
        report_hash=second,
        primary_metric="evidence_support",
        registered_at=REGISTERED,
        executed_at="2026-09-03T00:00:00.000000Z",
    )
    assert reports.latest("retrieval") == rerun
    assert reports.latest("three_head") is None

    with psycopg.connect(postgres_dsn) as connection:
        events = connection.execute(
            "SELECT sequence FROM ledger_records WHERE event_kind=%s ORDER BY sequence",
            (EVENT_KIND,),
        ).fetchall()
        assert events == [(recorded.ledger_sequence,), (rerun.ledger_sequence,)]
        assert LedgerRepository().verify(connection) > 0
        # A recorded report is history: none is edited or removed.
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM qualification_reports")


def test_a_report_is_recorded_only_over_a_stored_artifact_and_a_known_kind(
    postgres_dsn: str, artifact_root: Path
) -> None:
    artifacts, reports = _repositories(postgres_dsn, artifact_root)
    with pytest.raises(UnavailableInput):
        reports.record(
            report_kind="retrieval",
            report_hash="e" * 64,
            primary_metric="evidence_support",
            registered_at=REGISTERED,
            executed_at=EXECUTED,
        )
    stored = _publish(artifacts, b"# report\n")
    with pytest.raises(ContractValidationError):
        reports.record(
            report_kind="encoder_fine_tuning",
            report_hash=stored,
            primary_metric="evidence_support",
            registered_at=REGISTERED,
            executed_at=EXECUTED,
        )
    # A registration after the execution is post hoc and never stored.
    with pytest.raises(ContractValidationError):
        reports.record(
            report_kind="retrieval",
            report_hash=stored,
            primary_metric="evidence_support",
            registered_at=EXECUTED,
            executed_at=REGISTERED,
        )
    assert reports.latest("retrieval") is None


def test_the_report_event_kind_keeps_every_kind_an_earlier_migration_admitted(
    postgres_dsn: str,
) -> None:
    marker = "ledger_records_event_kind_check CHECK (event_kind IN ("
    earlier: set[str] = set()
    for migration in sorted(Path(migrations.__file__).parent.glob("*.sql")):
        text = migration.read_text()
        if migration.name.startswith("0024") or marker not in text:
            continue
        body = text.split(marker, 1)[1].split("))", 1)[0]
        earlier |= set(re.findall(r"'([a-z_]+)'", body))
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname='ledger_records_event_kind_check' "
            "AND conrelid='ledger_records'::regclass"
        ).fetchone()
    assert row is not None
    admitted = set(re.findall(r"'([a-z_]+)'::text", row[0]))
    assert "trace_call_recorded" in earlier
    assert earlier | {EVENT_KIND} == admitted
