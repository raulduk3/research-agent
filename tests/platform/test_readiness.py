"""Activation admission over stored qualification reports (#324, SR-17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.platform.readiness import LayerAdmission
from research_agent.platform.reports import (
    REPORT_KINDS,
    admit_activation,
    record,
    report_repository,
)
from research_agent.storage.database import Database

pytestmark = pytest.mark.integration

METRIC = "citation_reach_365d_brier"
REGISTERED = "2026-09-01T00:00:00.000000Z"
EXECUTED = "2026-09-02T00:00:00.000000Z"


def _record(database: Database, store: ArtifactStore, tmp: Path, kind: str) -> str:
    report = tmp / f"{kind}.md"
    report.write_text(f"# {kind} qualification report\n", encoding="utf-8")
    return record(
        database,
        store,
        kind=kind,
        report=report,
        primary_metric=METRIC,
        registered_at=REGISTERED,
        executed_at=EXECUTED,
    ).report_id


def _admit(database: Database, store: ArtifactStore) -> LayerAdmission:
    return admit_activation(
        report_repository(database, store),
        layer_id="retrieval",
        baseline_config_hash="a" * 64,
        candidate_config_hash="b" * 64,
        registered_primary_metric=METRIC,
        activation_scope="study",
        jev_admitted=False,
    )


def test_a_full_set_of_stored_reports_admits_citing_each(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    report_ids = tuple(
        _record(database, store, tmp_path, kind) for kind in REPORT_KINDS
    )

    admission = _admit(database, store)

    assert admission.admitted
    assert admission.comparison_report_ids == report_ids


def test_a_missing_retrieval_report_refuses_admission_by_name(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    for kind in REPORT_KINDS:
        if kind != "retrieval":
            _record(database, store, tmp_path, kind)

    admission = _admit(database, store)

    assert not admission.admitted
    assert admission.denial_reasons == ("missing_report:retrieval",)
