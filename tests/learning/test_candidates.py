"""The corpus candidate list, built from a pilot's committed stages (#321)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import canonical_json, sha256_hex
from research_agent.contracts.learning import (
    CitationFamilyRecord,
    CitationObservation,
    PaginationPage,
)
from research_agent.contracts.papers import PaperVersionRecord, SourceInterval
from research_agent.ingest.pilot import gate_identity
from research_agent.ingest.pilot_run import SNAPSHOT_LABELS
from research_agent.learning import candidates, release
from research_agent.learning.corpus import publication_week, selection_hash
from research_agent.outcomes.windows import instant, maturity_at, utc
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database

FROZEN_AT = "2022-06-01T00:00:00.000000Z"
T0 = "2020-06-15T00:00:00.000000Z"
_IDENTITY = release.Identity(release._TARGET_META.producer_version, "c" * 64, "f" * 64)


def _entry(family_id: str, t0: str = T0) -> dict[str, Any]:
    return {
        "family_id": family_id,
        "first_public_at": t0,
        "categories": ["cs.AI"],
        "license_url": None,
        "doi": None,
        "title": "Cafe\u0301 title",
        "abstract": "An abstract.",
        "author_count": 3,
        "version_count": 2,
    }


def _selection(
    entries: list[dict[str, Any]], intended: int = 100, seed: int = 20260920
) -> dict[str, Any]:
    return {
        "stage": "select",
        "frozen_at": FROZEN_AT,
        "population_hash": sha256_hex(b"population"),
        "intended_count": intended,
        "seed": seed,
        "population_rule": "rule",
        "selected": entries,
    }


def _citing(number: int, day: int) -> CitationFamilyRecord:
    return CitationFamilyRecord(
        schema_version=1,
        input_hashes=(),
        producer_version=_IDENTITY.producer,
        config_hash=_IDENTITY.config_hash,
        created_at=FROZEN_AT,
        canonical_family_id=f"family-{number}",
        provider_work_ids=(f"W{number}",),
        external_ids=(),
        identity_evidence_hashes=("d" * 64,),
        representative_work_id=f"W{number}",
        representative_rule="lowest_provider_id",
        identity_state="resolved",
        possible_identity_cluster=None,
        target_link_work_ids=("W1000",),
        publication_interval=SourceInterval(
            utc(instant(T0) + timedelta(days=day)),
            utc(instant(T0) + timedelta(days=day + 1)),
        ),
        alternative_publication_intervals=(),
        date_state="known",
        primary_subfield_id="A",
        alternative_subfield_ids=(),
        subfield_state="known",
        raw_response_hashes=("e" * 64,),
        is_target_family_self_link=False,
    )


def _observation(
    family_id: str, records: tuple[CitationFamilyRecord, ...]
) -> CitationObservation:
    paper_family_id, version_id, registry_hash = gate_identity(family_id)
    stored = tuple(sha256_hex(record.to_canonical_json()) for record in records)
    page = PaginationPage(
        0, "a" * 64, "b" * 64, None, None, len(records), FROZEN_AT, FROZEN_AT,
        "completed", None,
    )  # fmt: skip
    return CitationObservation(
        1,
        stored,
        _IDENTITY.producer,
        _IDENTITY.config_hash,
        FROZEN_AT,
        paper_family_id,
        version_id,
        T0,
        "automatic-citations-v1",
        registry_hash,
        "openalex",
        "historical_reconstructed",
        "matched",
        ("W1000",),
        "A",
        "known",
        "d" * 64,
        FROZEN_AT,
        FROZEN_AT,
        maturity_at(T0),
        (instant(FROZEN_AT) - instant(maturity_at(T0))).total_seconds(),
        (page,),
        True,
        stored,
        None,
    )


def _source(
    entries: list[dict[str, Any]],
    observed: dict[str, tuple[CitationFamilyRecord, ...]],
    intended: int = 100,
    seed: int = 20260920,
) -> candidates.PilotSource:
    """A pilot's committed selection and labels, as the pilot store holds them."""
    manifests: dict[str, dict[str, Any]] = {}
    contents: dict[str, bytes] = {}
    observations: dict[str, str] = {}
    for family_id, records in observed.items():
        for record in records:
            contents[sha256_hex(record.to_canonical_json())] = (
                record.to_canonical_json()
            )
        manifest = sha256_hex(family_id.encode())
        body = _observation(family_id, records).to_canonical_json()
        manifests[manifest] = json.loads(body)
        observations[family_id] = manifest
    return candidates.PilotSource(
        _selection(entries, intended, seed),
        observations,
        manifests.__getitem__,
        contents.__getitem__,
    )


def _corpus(dsn: str, state: Path) -> candidates.CorpusStore:
    database = Database(dsn)
    return candidates.CorpusStore(
        database, ArtifactRepository(database, ArtifactStore(state / "artifacts"))
    )


def _build_args(dsn: str, state: Path, path: Path, purpose: str) -> list[str]:
    return [
        "run",
        "--state", str(state),
        "--dsn", dsn,
        "--population-rule", "rule",
        "--representation-hash", sha256_hex(b"representation"),
        "--purpose", purpose,
        "--release-id", purpose,
        "--candidates", str(path),
    ]  # fmt: skip


@pytest.mark.integration
def test_a_pilot_selection_becomes_a_release_with_its_observed_labels(
    postgres_dsn: str, tmp_path: Path
) -> None:
    state = tmp_path / "corpus"
    records = (_citing(1, 10), _citing(2, 20))
    source = _source(
        [_entry("2006.00001"), _entry("2006.00002"), _entry("2006.00003")],
        {"2006.00001": records, "2006.00003": ()},
    )
    corpus = _corpus(postgres_dsn, state)
    document, counts = candidates.build_candidates(
        source, corpus, purpose="acquisition_pilot", identity=_IDENTITY
    )

    assert (counts["candidates"], counts["observed"], counts["unobserved"]) == (3, 2, 1)
    assert (counts["intended"], counts["shortfall"]) == (100, 97)
    assert document["candidates_hash"] == candidates.candidates_hash(document)
    assert document["fitting_cutoff"] == FROZEN_AT
    assert document["enumerated_population_hash"] == sha256_hex(b"population")
    listed = document["candidates"]
    assert [c["selection_rank"] for c in listed] == [0, 1, 2]
    # Drawn in the contract's seeded rank within the month, not listing order.
    drawn = sorted(("2006.00001", "2006.00002", "2006.00003"), key=selection_hash)
    assert [c["paper_family_id"] for c in listed] == [
        gate_identity(family_id)[0] for family_id in drawn
    ]
    # The unobserved family is a candidate with no observation, not a made-up one.
    unobserved = drawn.index("2006.00002")
    assert "observation_artifact_hash" not in listed[unobserved]
    # Rebuilding publishes nothing new and writes the same list.
    assert candidates.build_candidates(
        source, corpus, purpose="acquisition_pilot", identity=_IDENTITY
    ) == (document, counts)

    path = tmp_path / "candidates.json"
    path.write_bytes(canonical_json(document))
    assert (
        release.main(_build_args(postgres_dsn, state, path, "acquisition_pilot")) == 0
    )
    [(_, job_state, report)] = release._job_rows(Database(postgres_dsn))
    assert job_state == "committed" and report is not None
    store = ArtifactStore(state / "artifacts")
    summary = json.loads(_manifest_bytes(postgres_dsn, store, report))
    record = json.loads(_manifest_bytes(postgres_dsn, store, summary["release_hash"]))
    rows = record["rows"]
    assert [row["partition"] for row in rows] == ["pilot"] * 3
    assert rows[drawn.index("2006.00001")]["known_mask"] == [True, True, True]
    assert rows[unobserved]["known_mask"] == [False, False, False]
    assert record["enumerated_population_hash"] == sha256_hex(b"population")
    paper = PaperVersionRecord.from_json(
        _manifest_bytes(postgres_dsn, store, listed[0]["paper_artifact_hash"])
    )
    assert paper.title == "Caf\u00e9 title" and paper.version_count == 2


def _manifest_bytes(dsn: str, store: ArtifactStore, manifest: str) -> bytes:
    row = Database(dsn).transaction(
        lambda connection: connection.execute(
            "SELECT encode(artifact_hash,'hex') FROM artifact_productions "
            "WHERE manifest_hash=decode(%s,'hex')",
            (manifest,),
        ).fetchone()
    )
    assert row is not None
    with store.open_verified(str(row[0])) as handle:
        return handle.read()


@pytest.mark.integration
def test_a_fitting_purpose_splits_the_candidates_publication_weeks(
    postgres_dsn: str, tmp_path: Path
) -> None:
    start = datetime(2020, 1, 6, tzinfo=timezone.utc)
    entries = [
        _entry(f"2001.{index:05d}", utc(start + timedelta(weeks=index)))
        for index in range(41)
    ]
    pilot = {"candidates": [{"paper_family_id": gate_identity("2001.00040")[0]}]}
    state = tmp_path / "corpus"
    document, report = candidates.build_candidates(
        # Acquired with its own seed and cap; neither governs the release.
        _source(entries, {}, 10000, 20260922),
        _corpus(postgres_dsn, state),
        purpose="initial_fit",
        identity=_IDENTITY,
        exclude=candidates.excluded_families(pilot),
    )
    assert document["selection_seed"] == 20260920
    assert document["intended_population_count"] == 2000
    assert (report["pool"], report["excluded"], report["candidates"]) == (41, 1, 40)
    assert report["shortfall"] == 1960
    assert document["draw"]["acquisition_seed"] == 20260922
    assert document["draw"]["acquisition_intended_count"] == 10000
    entries = entries[:40]
    split = [
        document[name]
        for name in (
            "fit_weeks",
            "development_weeks",
            "calibration_weeks",
            "locked_evaluation_weeks",
        )
    ]
    assert [len(weeks) for weeks in split] == [24, 6, 4, 6]
    weeks = [week for part in split for week in part]
    assert weeks == sorted(publication_week(e["first_public_at"]) for e in entries)

    path = tmp_path / "candidates.json"
    path.write_bytes(canonical_json(document))
    assert release.main(_build_args(postgres_dsn, state, path, "initial_fit")) == 0
    # A list is built for one purpose; another purpose's release refuses it.
    with pytest.raises(SystemExit):
        release.main(_build_args(postgres_dsn, state, path, "acquisition_pilot"))
    assert len(release._job_rows(Database(postgres_dsn))) == 1


class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def execute(self, *_args: object) -> "_Rows":
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _Database:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def transaction(self, operation: Any) -> Any:
        return operation(_Rows(self._rows))


class _Storage:
    def __init__(self, rows: list[tuple[Any, ...]], reports: dict[str, Any]) -> None:
        self.database = _Database(rows)
        self.report = reports.__getitem__


def test_pilot_source_reads_the_committed_selection_and_the_latest_labels() -> None:
    now = datetime.now(timezone.utc)
    key = uuid4().hex
    labels = {"stage": SNAPSHOT_LABELS}
    reports = {
        f"select-spec-{key}": {"stage": "select"},
        f"select-{key}": _selection([_entry("2006.00001")]),
        f"labels-spec-a-{key}": labels,
        f"labels-a-{key}": {"families": {"2006.00001": {"observation": "old"}}},
        f"labels-spec-b-{key}": labels,
        f"labels-b-{key}": {"families": {"2006.00001": {"observation": "new"}}},
        f"labels-spec-c-{key}": labels,
    }
    rows = [
        (uuid4(), "committed", now, f"select-spec-{key}", f"select-{key}"),
        (uuid4(), "committed", now, f"labels-spec-a-{key}", f"labels-a-{key}"),
        (uuid4(), "committed", now, f"labels-spec-b-{key}", f"labels-b-{key}"),
        (uuid4(), "running", now, f"labels-spec-c-{key}", None),
    ]
    source = candidates.pilot_source(cast(Any, _Storage(rows, reports)))
    assert source.selection["selected"][0]["family_id"] == "2006.00001"
    assert source.observations == {"2006.00001": "new"}
