"""The `openalex_snapshot` stage commits a family's citations from the
snapshot's works table, through the same publish/checkpoint path every other
capture stage uses, carrying its release as provenance rather than any
range read's own capture clock (#209).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_agent.contracts import sha256_hex
from research_agent.contracts.papers import SourceAccess
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.fetch import FetchedSnapshotRange
from research_agent.ingest.pilot import Identity, PilotWorker, RateGate, Sources
from research_agent.ingest.pilot_local import local_storage, worker_principal

pytestmark = pytest.mark.integration

IDENTITY = Identity(
    ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)


def _unreachable(*_: object, **__: object) -> Any:
    raise AssertionError("the snapshot stage never touches another source")


def _part_bytes() -> bytes:
    table = pa.table(
        {
            "id": [
                "https://openalex.org/W20",
                "https://openalex.org/W30",
            ],
            "referenced_works": [
                ["https://openalex.org/W10"],
                ["https://openalex.org/W99"],
            ],
            "referenced_works_count": [1, 1],
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def _access(payload: bytes) -> SourceAccess:
    return SourceAccess(
        schema_version=1,
        input_hashes=(),
        producer_version=IDENTITY.producer,
        config_hash=IDENTITY.config_hash,
        created_at="2026-05-21T09:00:00.000000Z",
        source="openalex",
        requested_url="https://openalex.s3.amazonaws.com/data/parquet/works/part.parquet",
        request_parameters_hash="4" * 64,
        adapter_version="openalex-snapshot-range-v1",
        capture_started_at="2026-05-21T09:00:00.000000Z",
        capture_completed_at="2026-05-21T09:00:00.500000Z",
        http_status=206,
        retained_payload_hash=sha256_hex(payload),
        retention_policy_hash=IDENTITY.retention_policy_hash,
        license_expression="CC0-1.0",
        permission_evidence_hash=IDENTITY.permission_evidence_hash,
        failure=None,
    )


def _sources() -> Sources:
    data = _part_bytes()

    def snapshot_range(key: str, range_spec: str) -> FetchedSnapshotRange:
        if range_spec.startswith("-"):
            length = int(range_spec[1:])
            start = max(0, len(data) - length)
            end = len(data) - 1
        else:
            start_text, end_text = range_spec.split("-", 1)
            start = int(start_text)
            end = int(end_text) if end_text else len(data) - 1
        end = min(end, len(data) - 1)
        chunk = data[start : end + 1]
        return FetchedSnapshotRange(_access(chunk), chunk, (start, end, len(data)))

    return Sources(
        listing=_unreachable,
        document=_unreachable,
        openalex_match=_unreachable,
        openalex_cites=_unreachable,
        arxiv_gate=RateGate(0.001),
        openalex_gate=RateGate(0.001),
        snapshot_range=snapshot_range,
    )


def test_openalex_snapshot_stage_commits_an_observation_dated_by_the_release(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tls,
        identity=IDENTITY,
    ) as storage:
        worker = worker_principal(tls)
        storage.enqueue(
            {
                "stage": "openalex_snapshot",
                "family": {
                    "family_id": "2503.00001",
                    "first_public_at": "2024-01-01T00:00:00.000000Z",
                },
                "target_provider_ids": ["W10"],
                "release": "2026-05-21",
                "part_keys": [
                    "data/parquet/works/updated_date=2026-05-21/part_0000.parquet"
                ],
            }
        )
        pilot = PilotWorker(
            storage.client, worker_id=worker, identity=IDENTITY, sources=_sources()
        )
        summary = pilot.run()
        assert summary.jobs_completed == 1
        rows = storage.job_rows()
        assert len(rows) == 1
        _, state, manifest = rows[0]
        assert state == "committed"
        assert manifest is not None
        body = storage.report(manifest)

        assert body["stage"] == "openalex_snapshot"
        assert body["citation_families"] == 1
        assert body["pagination_complete"] is True

        observation = storage.report(body["observation"])
        assert observation["created_at"] == "2026-05-21T00:00:00.000000Z"
        assert observation["created_at"] != observation["capture_completed_at"]
        assert observation["provider"] == "openalex"
        assert observation["target_match_state"] == "matched"
