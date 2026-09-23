"""The daily job runs the requested-paper pass and seals the next snapshot
with what it acquired before it seals its batch.

Decision 0025: requested papers ride the daily worker and arXiv gate, after
the day's own documents and before the day's batch record is sealed, and
stay out of that batch record. Same real storage, worker and loopback arXiv
as the daily ingest tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from research_agent.ingest.daily import run_once
from research_agent.ingest.pilot import PilotWorker
from research_agent.ingest.pilot_local import local_storage, worker_principal
from research_agent.ingest.requests import AcquisitionReport

sys.path.insert(0, str(Path(__file__).parents[1] / "corpus"))
from test_daily_ingest import IDENTITY, WINDOW, _remote, _sources  # noqa: E402

pytestmark = pytest.mark.integration


def test_acquisition_runs_after_the_days_documents_and_before_the_seal(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    events: list[str] = []
    report = AcquisitionReport(
        acquired=(
            {
                "paper_family_id": "0b0a9c6e-4d1f-4c67-9a8e-2f1f7b7f0a11",
                "paper_version_id": "1b0a9c6e-4d1f-4c67-9a8e-2f1f7b7f0a11",
                "card_hash": "a" * 64,
                "overview_hash": None,
                "passage_index_hash": None,
                "graph_hash": None,
            },
        )
    )
    with (
        _remote(tmp_path) as (_, port, context),
        local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):
        publish = storage.publish_spec

        def recording_publish(
            spec: dict[str, Any], inputs: tuple[str, ...] = ()
        ) -> str:
            events.append(str(spec.get("kind", spec.get("stage"))))
            return publish(spec, inputs)

        storage.publish_spec = recording_publish  # type: ignore[method-assign]

        def acquisition() -> AcquisitionReport:
            states = storage.database.transaction(
                lambda connection: connection.execute(
                    "SELECT DISTINCT state FROM jobs"
                ).fetchall()
            )
            assert states == [("committed",)]
            events.append("acquisition")
            return report

        def seal_snapshot(items: tuple[dict[str, Any], ...]) -> str:
            assert items == report.acquired
            events.append("snapshot")
            return "f" * 64

        run = run_once(
            storage,
            window=WINDOW,
            worker=PilotWorker(
                storage.client,
                worker_id=worker_principal(tls),
                identity=IDENTITY,
                sources=_sources(port, context),
            ),
            acquisition=acquisition,
            seal_snapshot=seal_snapshot,
        )

    assert (
        events.index("acquisition")
        < events.index("snapshot")
        < events.index("daily_ingest_batch")
    )
    assert "documents" in events[: events.index("acquisition")]
    assert run.acquired is report
    assert run.snapshot_hash == "f" * 64
    batch_families = {f["family_id"] for f in run.batch["eligible_families"]}
    assert batch_families == {"2601.00001", "2601.00002", "2601.00003"}
