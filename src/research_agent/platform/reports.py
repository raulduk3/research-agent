"""Qualification reports as activation admission's stored evidence (#324).

The commands that qualify something store their report through ``record``:
``bin/qualify-inference`` (inference battery) and ``bin/fit-heads`` (three
heads) call it, and the Jev smoke and retrieval commands record theirs the
same way. ``admit_activation`` reads the latest stored report of every kind
in ``REPORT_KINDS``, turns each into the ``ComparisonReport`` SR-17's gate
takes, and names every kind that has none, so admission never runs over
evidence the operator typed in.

    python -m research_agent.platform.reports record --dsn DSN \\
        --artifact-root DIR --kind KIND --report FILE \\
        --primary-metric METRIC --registered-at UTC [--executed-at UTC]
    python -m research_agent.platform.reports admit --dsn DSN \\
        --artifact-root DIR --layer ID --candidate SHA256 [--baseline SHA256] \\
        --primary-metric METRIC --scope SCOPE [--jev-admitted]

``record`` publishes the report file's bytes unless the store already holds
them (JSON as a manifest, anything else as plain-text study evidence) and
records them; ``--executed-at`` defaults to the moment of recording.
``admit`` prints the admission record and exits 1 when it denies.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json
from research_agent.platform.readiness import (
    ComparisonReport,
    LayerAdmission,
    evaluate_admission,
)
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput
from research_agent.storage.reports import (
    REPORT_KINDS,
    QualificationReportRepository,
    StoredQualificationReport,
)

__all__ = [
    "REPORT_KINDS",
    "admit_activation",
    "main",
    "record",
    "report_repository",
    "stored_comparison_reports",
]

_RETENTION = (
    b"Qualification reports and their recording events are retained privately "
    b"for this research as activation evidence and are not redistributed."
)
_ROOT = Path(__file__).resolve().parents[3]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _producer() -> ProducerVersion:
    commit = subprocess.run(
        ("git", "-C", str(_ROOT), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return ProducerVersion(sha256(b"local-process").hexdigest(), commit, 1)


def _config_hash() -> str:
    return sha256(
        canonical_json(
            {"command": "qualification_reports", "kinds": list(REPORT_KINDS)}
        )
    ).hexdigest()


def report_repository(
    database: Database, store: ArtifactStore
) -> QualificationReportRepository:
    """The report repository under this command's local producer identity."""

    return QualificationReportRepository(
        database,
        store,
        producer=_producer(),
        config_hash=_config_hash(),
        retention_policy_hash=sha256(_RETENTION).hexdigest(),
    )


def record(
    database: Database,
    store: ArtifactStore,
    *,
    kind: str,
    report: Path,
    primary_metric: str,
    registered_at: str,
    executed_at: str,
) -> StoredQualificationReport:
    """Publish the report file's bytes and record them as the latest ``kind``."""

    body = report.read_bytes()
    digest = sha256(body).hexdigest()
    artifacts = ArtifactRepository(database, store)
    try:
        # A report its producing job already published (the three-head fit's)
        # keeps that publication; only a file the store lacks is published.
        _, stream = artifacts.read(digest)
        stream.close()
    except UnavailableInput:
        is_json = report.suffix == ".json"
        artifacts.publish(
            [body],
            expected_hash=digest,
            byte_length=len(body),
            maximum_length=max(len(body), 1),
            media_type="application/json" if is_json else "text/plain",
            kind="manifest" if is_json else "study_evidence",
            input_hashes=(),
            producer_version=_producer(),
            config_hash=_config_hash(),
            retention_policy_hash=sha256(_RETENTION).hexdigest(),
            command_id=uuid4(),
        )
    return report_repository(database, store).record(
        report_kind=kind,
        report_hash=digest,
        primary_metric=primary_metric,
        registered_at=registered_at,
        executed_at=executed_at,
    )


def stored_comparison_reports(
    repository: QualificationReportRepository,
) -> tuple[tuple[ComparisonReport, ...], tuple[str, ...]]:
    """The latest stored report of each kind, and every kind that has none."""

    reports: list[ComparisonReport] = []
    missing: list[str] = []
    for kind in REPORT_KINDS:
        stored = repository.latest(kind)
        if stored is None:
            missing.append(kind)
            continue
        reports.append(
            ComparisonReport(
                report_id=stored.report_id,
                primary_metric=stored.primary_metric,
                registered_at=stored.registered_at,
                executed_at=stored.executed_at,
            )
        )
    return tuple(reports), tuple(missing)


def admit_activation(
    repository: QualificationReportRepository,
    *,
    layer_id: str,
    baseline_config_hash: str | None,
    candidate_config_hash: str,
    registered_primary_metric: str,
    activation_scope: str,
    jev_admitted: bool,
) -> LayerAdmission:
    """Run SR-17's gate over the stored reports; a missing kind denies by name."""

    reports, missing = stored_comparison_reports(repository)
    return evaluate_admission(
        layer_id=layer_id,
        baseline_config_hash=baseline_config_hash,
        candidate_config_hash=candidate_config_hash,
        registered_primary_metric=registered_primary_metric,
        reports=reports,
        activation_scope=activation_scope,
        jev_admitted=jev_admitted,
        missing_report_kinds=missing,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "admit"):
        command = commands.add_parser(name)
        command.add_argument("--dsn", required=True)
        command.add_argument("--artifact-root", type=Path, required=True)
        command.add_argument("--primary-metric", required=True)
    record_command = commands.choices["record"]
    record_command.add_argument("--kind", choices=REPORT_KINDS, required=True)
    record_command.add_argument("--report", type=Path, required=True)
    record_command.add_argument("--registered-at", required=True)
    record_command.add_argument("--executed-at", default=None)
    admit_command = commands.choices["admit"]
    admit_command.add_argument("--layer", required=True)
    admit_command.add_argument("--candidate", required=True)
    admit_command.add_argument("--baseline", default=None)
    admit_command.add_argument("--scope", required=True)
    admit_command.add_argument("--jev-admitted", action="store_true")
    args = parser.parse_args(argv)

    database = Database(args.dsn)
    store = ArtifactStore(args.artifact_root)
    if args.command == "record":
        stored = record(
            database,
            store,
            kind=args.kind,
            report=args.report,
            primary_metric=args.primary_metric,
            registered_at=args.registered_at,
            executed_at=args.executed_at or _now(),
        )
        print(
            json.dumps(
                {
                    "report_id": stored.report_id,
                    "report_kind": stored.report_kind,
                    "report_hash": stored.report_hash,
                    "ledger_sequence": stored.ledger_sequence,
                }
            )
        )
        return 0
    admission = admit_activation(
        report_repository(database, store),
        layer_id=args.layer,
        baseline_config_hash=args.baseline,
        candidate_config_hash=args.candidate,
        registered_primary_metric=args.primary_metric,
        activation_scope=args.scope,
        jev_admitted=args.jev_admitted,
    )
    print(json.dumps({**admission.to_dict(), "record_hash": admission.record_hash()}))
    return 0 if admission.admitted else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
