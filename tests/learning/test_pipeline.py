from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.corpus import CorpusRelease, CorpusRow
from research_agent.contracts.learning import (
    EMBEDDING_DIMENSION,
    EMBEDDING_FEATURE_DIMENSION,
    PRIMARY_CATEGORY_IDS,
    AutomaticLabel,
    CombinedFeatureRecord,
    CountBounds,
    LabelCounts,
    TrainingArrays,
)
from research_agent.learning import pipeline
from research_agent.learning.features import UnrecordedCardMetadata
from research_agent.learning.fit import FitError
from research_agent.learning.release import _TARGET_META
from research_agent.learning.smoke import build_engineering_slice, load_slice
from research_agent.learning.tensors import encode_tensor
from research_agent.outcomes.targets import registry as target_registry
from research_agent.outcomes.windows import instant, utc
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate

T0 = "2020-01-06T12:00:00.000000Z"
CUTOFF = "2023-01-01T00:00:00.000000Z"
CREATED = "2023-02-01T00:00:00.000000Z"
REPRESENTATION = sha256(b"representation").hexdigest()
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, CREATED)
Blobs = dict[str, tuple[bytes, str, str]]


def _uuid(*parts: object) -> str:
    return str(UUID(bytes=sha256(repr(parts).encode()).digest()[:16], version=4))


def _put(blobs: Blobs, payload: bytes, media: str, kind: str) -> str:
    digest = sha256(payload).hexdigest()
    blobs[digest] = (payload, media, kind)
    return digest


def _json(blobs: Blobs, payload: bytes) -> str:
    return _put(blobs, payload, "application/json", "manifest")


def _tensor(blobs: Blobs, values: np.ndarray) -> str:  # type: ignore[type-arg]
    reference, payload = encode_tensor(values)
    _put(blobs, payload, "application/octet-stream", "vector_payload")
    return reference.payload_hash


def _label(family_id: str, index: int, value: int) -> AutomaticLabel:
    target = target_registry(_TARGET_META).definitions[index]
    empty = CountBounds(0, 0)
    state = "true" if value else "false"
    return AutomaticLabel(
        1,
        (),
        META.producer_version,
        META.config_hash,
        CREATED,
        family_id,
        target.target_id,
        sha256(target.to_canonical_json()).hexdigest(),
        state,
        "sufficient_positive_witnesses" if value else "complete_negative_evidence",
        "d" * 64,
        LabelCounts(empty, empty, empty, empty),
        (),
        (),
        (),
        "2021-01-06T12:00:00.000000Z",
        CREATED,
        None,
        None,
    )


def _feature(blobs: Blobs, family_id: str, embedding: np.ndarray) -> str:  # type: ignore[type-arg]
    combined = embedding.astype(np.float32)
    pooled = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
    pooled[0] = 1.0
    combined_ref, combined_bytes = encode_tensor(combined)
    pooled_ref, pooled_bytes = encode_tensor(pooled)
    _put(blobs, combined_bytes, "application/octet-stream", "vector_payload")
    _put(blobs, pooled_bytes, "application/octet-stream", "vector_payload")
    record = CombinedFeatureRecord(
        1,
        (),
        META.producer_version,
        META.config_hash,
        CREATED,
        family_id,
        _uuid("version", family_id),
        "5" * 64,
        "6" * 64,
        REPRESENTATION,
        "7" * 64,
        ("8" * 64,),
        (1.0,),
        pooled_ref,
        combined_ref,
        "overview_passage_sqrt2_v1",
        CREATED,
    )
    return _json(blobs, record.to_canonical_json())


def _releases(tmp_path: Path, *, recorded: bool = True) -> tuple[Blobs, str, str]:
    """The preserved head-smoke slice as an initial-fit release and its pilot."""

    slice_path = tmp_path / "slice.npz"
    if not slice_path.exists():
        build_engineering_slice(slice_path)
    data = load_slice(slice_path)
    blobs: Blobs = {}
    rows = []
    for index, family_id in enumerate(data.family_ids):
        t0 = utc(instant(T0) + timedelta(days=3 * index))
        label_hashes = tuple(
            _json(
                blobs,
                _label(
                    family_id, column, int(data.labels[index, column])
                ).to_canonical_json(),
            )
            if data.known_mask[index, column]
            else None
            for column in range(3)
        )
        rows.append(
            CorpusRow(
                paper_family_id=family_id,
                original_version_id=_uuid("version", family_id),
                t0=t0,
                publication_week=f"{instant(t0).isocalendar().year:04d}-W"
                f"{instant(t0).isocalendar().week:02d}",
                source_subfield="A",
                selection_rank=index,
                feature_hash=_feature(
                    blobs, family_id, data.features[index, :EMBEDDING_FEATURE_DIMENSION]
                ),
                label_hashes=(label_hashes[0], label_hashes[1], label_hashes[2]),
                known_mask=(
                    bool(data.known_mask[index, 0]),
                    bool(data.known_mask[index, 1]),
                    bool(data.known_mask[index, 2]),
                ),
                partition=data.partition[index],
                exclusion_reasons=(),
                author_count=1 + index % 5,
                categories=(PRIMARY_CATEGORY_IDS[index % len(PRIMARY_CATEGORY_IDS)],),
                version_count=1,
                abstract_tokens=120 + index if recorded else None,
                title_tokens=8 + index % 4 if recorded else None,
                first_available_weekday=instant(t0).weekday() if recorded else None,
                code_link=index % 3 == 0 if recorded else None,
            )
        )
    corpus = CorpusRelease(
        1,
        (),
        META.producer_version,
        META.config_hash,
        CREATED,
        "initial_fit",
        sha256(target_registry(_TARGET_META).to_canonical_json()).hexdigest(),
        REPRESENTATION,
        20260920,
        T0,
        CUTOFF,
        2000,
        "e" * 64,
        tuple(rows),
        1900,
        "f" * 64,
        "1" * 64,
        (),
        None,
    )
    pilot = CorpusRelease(
        1,
        (),
        META.producer_version,
        META.config_hash,
        CREATED,
        "acquisition_pilot",
        corpus.target_registry_hash,
        REPRESENTATION,
        20260920,
        T0,
        CUTOFF,
        100,
        "2" * 64,
        tuple(
            CorpusRow(
                _uuid("pilot", index),
                _uuid("pilot-version", index),
                T0,
                "2020-W02",
                "A",
                index,
                "3" * 64,
                ("4" * 64, "4" * 64, "4" * 64),
                (True, True, True),
                "pilot",
                (),
                1,
                ("cs.AI",),
                1,
            )
            for index in range(80)
        ),
        20,
        "9" * 64,
        "1" * 64,
        (),
        None,
    )
    return (
        blobs,
        _json(blobs, corpus.to_canonical_json()),
        _json(blobs, pilot.to_canonical_json()),
    )


def _publish_all(dsn: str, root: Path, blobs: Blobs) -> None:
    artifacts = ArtifactRepository(Database(dsn), ArtifactStore(root))
    for digest, (payload, media, kind) in blobs.items():
        artifacts.publish(
            [payload],
            expected_hash=digest,
            byte_length=len(payload),
            maximum_length=len(payload),
            media_type=media,
            kind=kind,
            input_hashes=(),
            producer_version=META.producer_version,
            config_hash=META.config_hash,
            retention_policy_hash="f" * 64,
            command_id=uuid4(),
        )


@pytest.fixture
def other_postgres_dsn() -> Iterator[str]:
    dsn = os.environ.get("RESEARCH_AGENT_TEST_DSN")
    if not dsn:
        pytest.skip("Set RESEARCH_AGENT_TEST_DSN to run PostgreSQL integration tests")
    schema = "test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            scoped = make_conninfo(dsn, options=f"-csearch_path={schema}")
            migrate(Database(scoped))
            yield scoped
        finally:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


def _run(
    dsn: str, state: Path, corpus: str, pilot: str, capsys: pytest.CaptureFixture[str]
) -> dict[str, str]:
    assert (
        pipeline.main(
            [
                "--state",
                str(state),
                "--dsn",
                dsn,
                "--release",
                corpus,
                "--pilot-release",
                pilot,
                "--permutations",
                "2",
            ]
        )
        == 0
    )
    printed = dict(
        line.split(": ", 1) for line in capsys.readouterr().out.strip().splitlines()
    )
    return printed


@pytest.mark.integration
def test_fit_heads_writes_a_stable_bundle_and_promotes_nothing_unqualified(
    postgres_dsn: str,
    other_postgres_dsn: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blobs, corpus, pilot = _releases(tmp_path)
    runs = []
    for dsn, state in (
        (postgres_dsn, tmp_path / "first"),
        (other_postgres_dsn, tmp_path / "second"),
    ):
        _publish_all(dsn, state / "artifacts", blobs)
        runs.append(_run(dsn, state, corpus, pilot, capsys))

    first, second = runs
    bundle = json.loads(Path(first["bundle file"]).read_bytes())
    assert bundle["bundle_id"] == first["bundle"]
    assert [entry["status"] for entry in bundle["entries"]] == ["unavailable"] * 3
    assert bundle["corpus_release_hash"] == corpus
    # Two independent runs, in separate stores and schemas, commit the same
    # bundle id and the same bundle bytes.
    assert second["bundle"] == first["bundle"]
    assert (
        Path(second["bundle file"]).read_bytes()
        == Path(first["bundle file"]).read_bytes()
    )

    report = json.loads(Path(first["qualification report"]).read_bytes())
    assert report["pilot"]["passed"] is True
    assert [outcome["qualified"] for outcome in report["outcomes"]] == [False] * 3
    decision = json.loads(Path(first["promotion decision"]).read_bytes())
    assert decision["activated"] is False
    assert decision["bundle_id"] == first["bundle"]
    assert [item["promoted"] for item in decision["decisions"]] == [False] * 3
    assert {item["reason"] for item in decision["decisions"]} == {"unavailable"}
    assert first["promoted targets"] == "none"

    # A rerun on the same state replays the committed job instead of refitting.
    assert _run(postgres_dsn, tmp_path / "first", corpus, pilot, capsys) == first


@pytest.mark.integration
def test_fit_heads_resumes_from_committed_partitions(
    postgres_dsn: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blobs, corpus, pilot = _releases(tmp_path)
    state = tmp_path / "state"
    _publish_all(postgres_dsn, state / "artifacts", blobs)
    built: list[str] = []
    original_arrays = pipeline.training_arrays

    def counted(releases, partition, **kwargs):  # type: ignore[no-untyped-def]
        built.append(partition)
        return original_arrays(releases, partition, **kwargs)

    def killed(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("worker died")

    monkeypatch.setattr(pipeline, "training_arrays", counted)
    monkeypatch.setattr(pipeline, "fit_and_qualify", killed)
    with pytest.raises(RuntimeError):
        pipeline.main(
            [
                "--state",
                str(state),
                "--dsn",
                postgres_dsn,
                "--release",
                corpus,
                "--pilot-release",
                pilot,
                "--permutations",
                "2",
            ]
        )
    assert built == list(pipeline.PARTITIONS)
    Database(postgres_dsn).transaction(
        lambda connection: connection.execute(
            "UPDATE jobs SET expires_at = clock_timestamp() - interval '1 second' "
            "WHERE state = 'running'"
        )
    )
    monkeypatch.undo()
    monkeypatch.setattr(pipeline, "training_arrays", counted)
    resumed = _run(postgres_dsn, state, corpus, pilot, capsys)
    # Every partition was committed before the crash and is read back.
    assert built == list(pipeline.PARTITIONS)
    assert (
        json.loads(Path(resumed["bundle file"]).read_bytes())["bundle_id"]
        == (resumed["bundle"])
    )


def _stages(
    tmp_path: Path, **kwargs: bool
) -> tuple[pipeline.Releases, Blobs, dict[str, TrainingArrays]]:
    blobs, corpus, pilot = _releases(tmp_path, **kwargs)

    def read(digest: str) -> bytes:
        return blobs[digest][0]

    releases = pipeline.load_releases(read, corpus, pilot)
    arrays = {}
    for partition in pipeline.PARTITIONS:
        digest = pipeline.training_arrays(
            releases,
            partition,
            read=read,
            publish=lambda payload, media, kind: _put(blobs, payload, media, kind),
            producer=META.producer_version,
            config_hash=META.config_hash,
        )
        arrays[partition] = TrainingArrays.from_json(read(digest))
    return releases, blobs, arrays


def test_materialized_partitions_match_the_release_rows(tmp_path: Path) -> None:
    releases, blobs, arrays = _stages(tmp_path)
    fit_hash = sha256(arrays["fit"].to_canonical_json()).hexdigest()
    partition = pipeline.materialize(
        fit_hash,
        releases,
        read=lambda digest: blobs[digest][0],
        requested_family_ids=frozenset(),
    )
    rows = [row for row in releases.corpus.rows if row.partition == "fit"]
    assert partition.family_ids == tuple(row.paper_family_id for row in rows)
    assert partition.known_mask.tolist() == [
        [int(value) for value in row.known_mask] for row in rows
    ]
    # A requested paper refuses the whole partition (decision 0025).
    with pytest.raises(FitError, match="agent-requested"):
        pipeline.materialize(
            fit_hash,
            releases,
            read=lambda digest: blobs[digest][0],
            requested_family_ids=frozenset({rows[0].paper_family_id}),
        )


def test_a_release_without_recorded_card_fields_is_refused_by_name(
    tmp_path: Path,
) -> None:
    blobs, corpus, pilot = _releases(tmp_path, recorded=False)
    releases = pipeline.load_releases(lambda digest: blobs[digest][0], corpus, pilot)
    with pytest.raises(UnrecordedCardMetadata, match="abstract_tokens"):
        pipeline.training_arrays(
            releases,
            "fit",
            read=lambda digest: blobs[digest][0],
            publish=lambda payload, media, kind: _put(blobs, payload, media, kind),
            producer=META.producer_version,
            config_hash=META.config_hash,
        )


def test_releases_are_refused_for_the_wrong_purpose(tmp_path: Path) -> None:
    blobs, corpus, pilot = _releases(tmp_path)

    def read(digest: str) -> bytes:
        return blobs[digest][0]

    with pytest.raises(pipeline.PipelineError, match="initial-fit"):
        pipeline.load_releases(read, pilot, pilot)
    with pytest.raises(pipeline.PipelineError, match="acquisition pilot"):
        pipeline.load_releases(read, corpus, corpus)


def test_coverage_counts_shortfalls_against_the_intended_population(
    tmp_path: Path,
) -> None:
    releases, _, _ = _stages(tmp_path)
    overall, slices = pipeline.coverage_slices(releases.corpus, 0)
    assert (overall.intended_count, overall.covered_count) == (2000, 100)
    assert sum(item.intended_count for item in slices) == 100
    # A row without a feature record is not covered.
    stripped = replace(
        releases.corpus,
        rows=tuple(
            replace(row, feature_hash=None) if index == 0 else row
            for index, row in enumerate(releases.corpus.rows)
        ),
    )
    assert pipeline.coverage_slices(stripped, 0)[0].covered_count == 99


def test_pilot_feasibility_needs_seventy_eligible_papers(tmp_path: Path) -> None:
    releases, _, _ = _stages(tmp_path)
    assert pipeline.pilot_feasibility(releases.pilot).passed
    short = replace(
        releases.pilot,
        rows=tuple(
            replace(row, feature_hash=None) if index < 11 else row
            for index, row in enumerate(releases.pilot.rows)
        ),
    )
    report = pipeline.pilot_feasibility(short)
    assert (report.intended_count, report.eligible_count) == (100, 69)
    assert not report.passed
