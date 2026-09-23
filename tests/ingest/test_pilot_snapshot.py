"""The snapshot stages read the OpenAlex works table once for the whole
corpus (#223), through the same publish/checkpoint path every other capture
stage uses: a pass over part ranges finds each family's own work, a second
keeps every edge landing on any of them, and one labels job commits an
observation per family, dated by the release rather than any range read's
own capture clock (#209).
"""

from __future__ import annotations

import io
from collections import Counter
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
from research_agent.ingest.pilot_local import (
    LocalStorage,
    local_storage,
    worker_principal,
)

pytestmark = pytest.mark.integration

IDENTITY = Identity(
    ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)
RELEASE = "2026-05-21"
KEYS = [
    "data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
    "data/parquet/works/updated_date=2026-05-21/part_0001.parquet",
]
T0 = "2024-01-01T00:00:00.000000Z"
FAMILIES = [
    {
        "family_id": family_id,
        "first_public_at": T0,
        "author_count": 1,
        "categories": ["cs.LG"],
        "version_count": 1,
    }
    for family_id in ("2503.00001", "2503.00002", "2503.00003", "2503.00004")
]


class _Killed(BaseException):
    """The worker process dies mid-job."""


def _unreachable(*_: object, **__: object) -> Any:
    raise AssertionError("the snapshot stages never touch another source")


def _arxiv(family_id: str) -> str:
    return f"https://doi.org/10.48550/arxiv.{family_id}"


def _part(rows: list[tuple[str, str | None, list[str]]]) -> bytes:
    table = pa.table(
        {
            "id": [f"https://openalex.org/{work}" for work, _, _ in rows],
            "doi": [doi for _, doi, _ in rows],
            "referenced_works": [
                [f"https://openalex.org/{ref}" for ref in refs] for _, _, refs in rows
            ],
            "referenced_works_count": [len(refs) for _, _, refs in rows],
        },
        schema=pa.schema(
            [
                ("id", pa.string()),
                ("doi", pa.string()),
                ("referenced_works", pa.list_(pa.string())),
                ("referenced_works_count", pa.int64()),
            ]
        ),
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


# 2503.00001 is W10, cited once, by W20. 2503.00002 is W11, which nothing
# cites. 2503.00003 has two works (ambiguous); 2503.00004 has none.
PARTS = {
    KEYS[0]: _part(
        [
            ("W10", _arxiv("2503.00001"), []),
            ("W20", "https://doi.org/10.1000/journal", ["W10"]),
        ]
    ),
    KEYS[1]: _part(
        [
            ("W11", _arxiv("2503.00002"), []),
            ("W12", _arxiv("2503.00003"), []),
            ("W13", _arxiv("2503.00003"), []),
            ("W30", None, ["W99"]),
        ]
    ),
}


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


def _sources(reads: Counter[str], *, kill_on: str | None = None) -> Sources:
    def snapshot_range(key: str, range_spec: str) -> FetchedSnapshotRange:
        if key == kill_on:
            raise _Killed
        reads[key] += 1
        data = PARTS[key]
        if range_spec.startswith("-"):
            start = max(0, len(data) - int(range_spec[1:]))
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


def _run(storage: LocalStorage, tls: Path, sources: Sources) -> dict[str, Any]:
    """Run the one queued job to commit and return its report."""
    pilot = PilotWorker(
        storage.client,
        worker_id=worker_principal(tls),
        identity=IDENTITY,
        sources=sources,
        gate_on_labels=True,
    )
    assert pilot.run().jobs_completed == 1
    _, state, manifest = storage.job_rows()[-1]
    assert state == "committed"
    assert manifest is not None
    return {"manifest": manifest, **storage.report(manifest)}


def _range(stage: str, **extra: Any) -> dict[str, Any]:
    return {
        "stage": stage,
        "release": RELEASE,
        "first_part": 0,
        "part_keys": KEYS,
        **extra,
    }


def test_one_pass_commits_an_observation_for_every_family(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    reads: Counter[str] = Counter()
    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tls,
        identity=IDENTITY,
    ) as storage:
        storage.enqueue(
            _range(
                "openalex_snapshot_match",
                family_ids=[f["family_id"] for f in FAMILIES],
            )
        )
        match = _run(storage, tls, _sources(reads))
        assert match["matches"] == {
            "2503.00001": ["W10"],
            "2503.00002": ["W11"],
            "2503.00003": ["W12", "W13"],
        }

        # The edge pass in two ranges of one part each, chained across the
        # boundary by the key just after the first range.
        scans = []
        for first in (0, 1):
            storage.enqueue(
                _range(
                    "openalex_snapshot",
                    first_part=first,
                    part_keys=KEYS[first : first + 1],
                    target_provider_ids=["W10", "W11"],
                    next_key=KEYS[1] if first == 0 else None,
                )
            )
            scans.append(_run(storage, tls, _sources(reads)))
        assert [len(scan["parts"]) for scan in scans] == [1, 1]

        storage.enqueue(
            {
                "stage": "openalex_snapshot_labels",
                "release": RELEASE,
                "families": FAMILIES,
                "matches": match["matches"],
                "match_capture": match["capture"],
                "match_reports": [match["manifest"]],
                "scan_reports": [scan["manifest"] for scan in scans],
            },
            (match["manifest"], *(scan["manifest"] for scan in scans)),
        )
        labels = _run(storage, tls, _sources(reads))

        assert labels["release"] == RELEASE
        observed = labels["families"]
        assert set(observed) == {f["family_id"] for f in FAMILIES}
        assert {k: v["target_match_state"] for k, v in observed.items()} == {
            "2503.00001": "matched",
            "2503.00002": "matched",
            "2503.00003": "ambiguous",
            "2503.00004": "unmatched",
        }
        assert observed["2503.00001"]["citation_families"] == 1
        assert all("gate" in entry for entry in observed.values())

        cited = storage.report(observed["2503.00001"]["observation"])
        assert cited["created_at"] == "2026-05-21T00:00:00.000000Z"
        assert cited["created_at"] != cited["capture_completed_at"]
        assert cited["target_provider_ids"] == ["W10"]
        assert len(cited["pages"]) == 2
        assert cited["pagination_complete"] is True

        # Nothing cites W11: a complete pass that found nothing is an
        # observed zero, not a missing observation.
        zero = storage.report(observed["2503.00002"]["observation"])
        assert zero["citation_family_hashes"] == []
        assert zero["pagination_complete"] is True
        assert zero["failure"] is None

        unmatched = storage.report(observed["2503.00004"]["observation"])
        assert unmatched["target_match_state"] == "unmatched"
        assert unmatched["pages"] == []


def test_a_killed_range_job_resumes_without_rereading_its_finished_parts(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    reads: Counter[str] = Counter()
    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tls,
        identity=IDENTITY,
    ) as storage:
        storage.enqueue(
            _range(
                "openalex_snapshot",
                target_provider_ids=["W10"],
                next_key=None,
            )
        )
        dying = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=IDENTITY,
            sources=_sources(reads, kill_on=KEYS[1]),
        )
        with pytest.raises(_Killed):
            dying.run()
        first_reads = reads[KEYS[0]]
        assert first_reads > 0
        storage.database.transaction(
            lambda connection: connection.execute(
                "UPDATE jobs SET expires_at = clock_timestamp() - interval '1 second'"
                " WHERE state = 'running'"
            )
        )

        scan = _run(storage, tls, _sources(reads))

        # The first part was checkpointed: the resumed job neither reads nor
        # republishes it, and still reports both parts in order.
        assert reads[KEYS[0]] == first_reads
        assert reads[KEYS[1]] > 0
        assert len(scan["parts"]) == 2
        assert storage.report(scan["parts"][0])["key"] == KEYS[0]
        assert storage.report(scan["parts"][1])["key"] == KEYS[1]
