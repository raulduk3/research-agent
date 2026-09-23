from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytest

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
    canonical_json,
    sha256_hex,
)
from research_agent.contracts.corpus import CorpusRelease, CorpusRow
from research_agent.contracts.learning import (
    AutomaticLabel,
    CitationFamilyRecord,
    CitationObservation,
    CombinedFeatureRecord,
    PaginationPage,
)
from research_agent.contracts.papers import (
    ExternalIdentifier,
    PaperVersionRecord,
    SourceInterval,
)
from research_agent.learning import release
from research_agent.learning.corpus import publication_week, split_weeks
from research_agent.learning.features import PassageEmbedding
from research_agent.outcomes.resolve import Resolver
from research_agent.outcomes.targets import definitions, registry
from research_agent.outcomes.windows import instant, maturity_at, utc
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate

T0 = "2020-06-15T00:00:00.000000Z"
AS_OF = "2022-01-01T00:00:00.000000Z"
_META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, AS_OF)


def _meta(created_at: str = AS_OF) -> RecordMeta:
    return RecordMeta(1, (), _META.producer_version, _META.config_hash, created_at)


def _paper(
    family_id: str,
    version_id: str,
    t0: str | None,
    *,
    subfield: str | None = "A",
) -> PaperVersionRecord:
    return PaperVersionRecord(
        1,
        (),
        _META.producer_version,
        _META.config_hash,
        AS_OF,
        family_id,
        version_id,
        (ExternalIdentifier("openalex", "W1000"),),
        True,
        t0,
        None
        if t0 is not None
        else SourceInterval(
            "2020-06-01T00:00:00.000000Z", "2020-07-01T00:00:00.000000Z"
        ),
        ("d" * 64,),
        ("e" * 64,),
        "Title",
        "Abstract",
        (),
        subfield,
        "f" * 64,
        "metadata",
        "v1",
        3,
        ("cs.AI",),
        1,
    )


def _family(number: int, day: int, field: str = "A") -> CitationFamilyRecord:
    return CitationFamilyRecord(
        schema_version=1,
        input_hashes=(),
        producer_version=_META.producer_version,
        config_hash=_META.config_hash,
        created_at=AS_OF,
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
        primary_subfield_id=field,
        alternative_subfield_ids=(),
        subfield_state="known",
        raw_response_hashes=("e" * 64,),
        is_target_family_self_link=False,
    )


def _observation(
    paper: PaperVersionRecord,
    families: tuple[CitationFamilyRecord, ...],
    *,
    registry_hash: str,
    complete: bool = True,
) -> CitationObservation:
    stored = tuple(sha256_hex(record.to_canonical_json()) for record in families)
    page = PaginationPage(
        0,
        "a" * 64,
        "b" * 64,
        None,
        None if complete else "next",
        len(families),
        AS_OF,
        AS_OF,
        "completed",
        None,
    )
    assert paper.first_public_at is not None
    return CitationObservation(
        1,
        stored,
        _META.producer_version,
        _META.config_hash,
        AS_OF,
        paper.family_id,
        paper.version_id,
        paper.first_public_at,
        "automatic-citations-v1",
        registry_hash,
        "openalex",
        "historical_reconstructed",
        "matched",
        ("W1000",),
        "A",
        "known",
        "d" * 64,
        AS_OF,
        AS_OF,
        maturity_at(paper.first_public_at),
        (instant(AS_OF) - instant(maturity_at(paper.first_public_at))).total_seconds(),
        (page,),
        complete,
        stored,
        None,
    )


def _candidate(
    family_id: str,
    version_id: str,
    t0: str,
    *,
    rank: int = 0,
    paper_artifact_hash: str | None = None,
    observation_artifact_hash: str | None = None,
) -> release.ReleaseCandidate:
    return release.ReleaseCandidate(
        family_id,
        version_id,
        rank,
        t0,
        "A",
        paper_artifact_hash,
        observation_artifact_hash,
        None,
    )


# --- pure assembly -------------------------------------------------------


def test_label_fields_reports_content_hash_and_known_state() -> None:
    meta = _meta()
    targets = definitions(meta)
    reg = registry(meta)
    paper = _paper(str(uuid4()), str(uuid4()), T0)
    families = tuple(_family(index, 10) for index in range(1, 6))
    observation = _observation(
        paper, families, registry_hash=sha256_hex(reg.to_canonical_json())
    )
    stored = {sha256_hex(record.to_canonical_json()): record for record in families}
    resolver = Resolver(stored.__getitem__, meta, registry=reg)
    label = resolver.resolve_target(targets[0], paper, observation, AS_OF)
    label_hash, known = release.label_fields(label)
    assert label_hash == sha256_hex(label.to_canonical_json())
    assert known is True
    assert release.label_fields(None) == (None, False)


def test_week_partition_maps_known_weeks_and_rejects_others() -> None:
    start = instant("2020-01-06T00:00:00.000000Z")
    weeks = tuple(publication_week(utc(start + timedelta(weeks=i))) for i in range(40))
    split = split_weeks(weeks)
    assert release.week_partition(utc(start), split) == "fit"
    assert (
        release.week_partition(utc(start + timedelta(weeks=39)), split)
        == "locked_evaluation"
    )
    with pytest.raises(ValueError):
        release.week_partition(utc(start + timedelta(weeks=200)), split)


def test_build_row_excludes_missing_source_and_unknown_first_public_time() -> None:
    candidate = _candidate(str(uuid4()), str(uuid4()), T0)
    row = release.build_row(
        candidate,
        rank=0,
        paper=None,
        labels=(None, None, None),
        purpose="acquisition_pilot",
        split=None,
        fitting_cutoff=AS_OF,
    )
    assert row.partition == "excluded"
    assert row.exclusion_reasons == ("source_unavailable",)

    paper = _paper(candidate.paper_family_id, candidate.original_version_id, None)
    row = release.build_row(
        candidate,
        rank=0,
        paper=paper,
        labels=(None, None, None),
        purpose="acquisition_pilot",
        split=None,
        fitting_cutoff=AS_OF,
    )
    assert row.partition == "excluded"
    assert row.exclusion_reasons == ("unknown_t0",)


def test_build_row_admits_a_resolved_pilot_row_with_its_selection_rank() -> None:
    meta = _meta()
    targets = definitions(meta)
    reg = registry(meta)
    family_id, version_id = str(uuid4()), str(uuid4())
    paper = _paper(family_id, version_id, T0)
    families = tuple(_family(index, 10) for index in range(1, 6))
    observation = _observation(
        paper, families, registry_hash=sha256_hex(reg.to_canonical_json())
    )
    stored = {sha256_hex(record.to_canonical_json()): record for record in families}
    resolver = Resolver(stored.__getitem__, meta, registry=reg)
    labels = tuple(
        resolver.resolve_target(target, paper, observation, AS_OF) for target in targets
    )
    candidate = _candidate(family_id, version_id, T0, rank=7)
    row = release.build_row(
        candidate,
        rank=candidate.selection_rank,
        paper=paper,
        labels=(labels[0], labels[1], labels[2]),
        purpose="acquisition_pilot",
        split=None,
        fitting_cutoff=AS_OF,
    )
    assert row.partition == "pilot"
    assert row.exclusion_reasons == ()
    assert row.selection_rank == 7
    # Five families in the first ten days, all subfield A: reach true, late and
    # breadth false, all three decisively known (Appendix B conformance row).
    assert row.known_mask == (True, True, True)
    assert (row.author_count, row.categories, row.version_count) == (
        paper.author_count,
        paper.categories,
        paper.version_count,
    )


def test_build_row_leaves_declared_metadata_null_without_a_paper() -> None:
    candidate = _candidate(str(uuid4()), str(uuid4()), T0)
    row = release.build_row(
        candidate,
        rank=0,
        paper=None,
        labels=(None, None, None),
        purpose="acquisition_pilot",
        split=None,
        fitting_cutoff=AS_OF,
    )
    assert (row.author_count, row.categories, row.version_count) == (None, None, None)


def test_build_row_records_card_fields_only_with_the_token_count() -> None:
    family_id, version_id = str(uuid4()), str(uuid4())
    paper = replace(
        _paper(family_id, version_id, T0),
        title="Two words",
        abstract="Code at https://github.com/example/repo today",
    )
    candidate = _candidate(family_id, version_id, T0)
    common: dict[str, Any] = {
        "rank": 0,
        "paper": paper,
        "labels": (None, None, None),
        "purpose": "acquisition_pilot",
        "split": None,
        "fitting_cutoff": AS_OF,
    }
    row = release.build_row(
        candidate,
        **common,
        count_tokens=lambda text: len(text.split()),
        feature_hash="a" * 64,
    )
    assert (
        row.title_tokens,
        row.abstract_tokens,
        row.first_available_weekday,
        row.code_link,
        row.feature_hash,
    ) == (2, 4, instant(T0).weekday(), True, "a" * 64)

    # Without the pinned tokenizer nothing is guessed: the four fields stay
    # unrecorded and the row's bytes carry none of them.
    legacy = release.build_row(candidate, **common)
    assert (legacy.title_tokens, legacy.code_link) == (None, None)
    assert b"title_tokens" not in legacy.to_canonical_json()


def test_build_row_rejects_an_immature_family_in_a_labeled_split() -> None:
    start = instant("2020-01-06T00:00:00.000000Z")
    weeks = tuple(publication_week(utc(start + timedelta(weeks=i))) for i in range(40))
    split = split_weeks(weeks)
    # The last frozen week, but only 100 of the required 455 days have
    # elapsed by the fitting cutoff: not mature enough for a labeled split.
    last_week_t0 = utc(start + timedelta(weeks=39))
    fitting_cutoff = utc(instant(last_week_t0) + timedelta(days=100))
    candidate = _candidate(str(uuid4()), str(uuid4()), last_week_t0)
    paper = _paper(
        candidate.paper_family_id, candidate.original_version_id, last_week_t0
    )
    with pytest.raises(ValueError, match="label horizon end"):
        release.build_row(
            candidate,
            rank=0,
            paper=paper,
            labels=(None, None, None),
            purpose="initial_fit",
            split=split,
            fitting_cutoff=fitting_cutoff,
        )


def test_coverage_report_reflects_admitted_rows() -> None:
    row = CorpusRow(
        paper_family_id=str(uuid4()),
        original_version_id=str(uuid4()),
        t0=T0,
        publication_week=publication_week(T0),
        source_subfield="A",
        selection_rank=0,
        feature_hash=None,
        label_hashes=(sha256_hex(b"x"), sha256_hex(b"y"), None),
        known_mask=(True, True, False),
        partition="pilot",
        exclusion_reasons=(),
        author_count=None,
        categories=None,
        version_count=None,
    )
    payload = json.loads(release.coverage_report_bytes((row,), intended=1))
    assert payload["selected"] == 1
    assert payload["known_labels"] == [1, 1, 0]
    assert payload["shortfall"] == 0


def test_assemble_release_refuses_a_blank_population_rule() -> None:
    with pytest.raises(ValueError, match="population rule"):
        release.assemble_release(
            purpose="acquisition_pilot",
            population_rule="   ",
            selection_seed=20260920,
            selection_frozen_at=T0,
            fitting_cutoff=AS_OF,
            intended_population_count=0,
            enumerated_population_hash=sha256_hex(b"population"),
            rows=(),
            target_registry_hash=sha256_hex(b"registry"),
            representation_hash=sha256_hex(b"representation"),
            source_observation_hashes=(),
            prior_release_hash=None,
            meta=_meta(),
        )


def test_assemble_release_rejects_an_immature_family_in_a_labeled_split() -> None:
    near_cutoff = utc(instant(AS_OF) - timedelta(days=10))
    row = CorpusRow(
        paper_family_id=str(uuid4()),
        original_version_id=str(uuid4()),
        t0=near_cutoff,
        publication_week=publication_week(near_cutoff),
        source_subfield="A",
        selection_rank=0,
        feature_hash=None,
        label_hashes=(None, None, None),
        known_mask=(False, False, False),
        partition="fit",
        exclusion_reasons=(),
        author_count=None,
        categories=None,
        version_count=None,
    )
    with pytest.raises(ValueError, match="label horizon end"):
        release.assemble_release(
            purpose="initial_fit",
            population_rule="latest cs.AI/cs.LG families",
            selection_seed=20260920,
            selection_frozen_at=T0,
            fitting_cutoff=AS_OF,
            intended_population_count=1,
            enumerated_population_hash=sha256_hex(b"population"),
            rows=(row,),
            target_registry_hash=sha256_hex(b"registry"),
            representation_hash=sha256_hex(b"representation"),
            source_observation_hashes=(),
            prior_release_hash=None,
            meta=_meta(),
        )


def test_assemble_release_builds_a_pilot_release_with_shortfall() -> None:
    rows = tuple(
        CorpusRow(
            paper_family_id=str(uuid4()),
            original_version_id=str(uuid4()),
            t0=None,
            publication_week=None,
            source_subfield=None,
            selection_rank=index,
            feature_hash=None,
            label_hashes=(None, None, None),
            known_mask=(False, False, False),
            partition="excluded",
            exclusion_reasons=("source_unavailable",),
            author_count=None,
            categories=None,
            version_count=None,
        )
        for index in range(3)
    )
    record, coverage_bytes = release.assemble_release(
        purpose="acquisition_pilot",
        population_rule="latest cs.AI/cs.LG arXiv families",
        selection_seed=20260920,
        selection_frozen_at=T0,
        fitting_cutoff=AS_OF,
        intended_population_count=100,
        enumerated_population_hash=sha256_hex(b"population"),
        rows=rows,
        target_registry_hash=sha256_hex(b"registry"),
        representation_hash=sha256_hex(b"representation"),
        source_observation_hashes=(),
        prior_release_hash=None,
        meta=_meta(),
    )
    assert record.shortfall_count == 97
    assert record.coverage_report_hash == sha256_hex(coverage_bytes)
    assert json.loads(coverage_bytes)["shortfall"] == 97
    assert [row.selection_rank for row in record.rows] == [0, 1, 2]


# --- resumable worker ------------------------------------------------------


class _Killed(Exception):
    """Stands in for the worker process dying between two candidates."""


def _publish_json(
    artifacts: ArtifactRepository, payload: bytes, *, config_hash: str
) -> str:
    digest = sha256_hex(payload)
    return artifacts.publish(
        [payload],
        expected_hash=digest,
        byte_length=len(payload),
        maximum_length=16 * 1024 * 1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=_META.producer_version,
        config_hash=config_hash,
        retention_policy_hash="f" * 64,
        command_id=uuid4(),
    ).manifest_hash


def _read_manifest(dsn: str, artifact_root: Path, manifest_hash: str) -> bytes:
    database = Database(dsn)
    row = database.transaction(
        lambda connection: connection.execute(
            "SELECT encode(artifact_hash,'hex') FROM artifact_productions "
            "WHERE manifest_hash=decode(%s,'hex')",
            (manifest_hash,),
        ).fetchone()
    )
    assert row is not None
    store = ArtifactStore(artifact_root)
    with store.open_verified(str(row[0])) as handle:
        return handle.read()


@pytest.mark.integration
def test_worker_resumes_after_interruption_without_repeating_committed_work(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidates = [
        {
            "paper_family_id": str(uuid4()),
            "original_version_id": str(uuid4()),
            "selection_rank": index,
            "t0": utc(instant(T0) + timedelta(days=index)),
        }
        for index in range(4)
    ]
    spec_path = tmp_path / "candidates.json"
    spec_path.write_text(
        json.dumps(
            {
                "selection_seed": 20260920,
                "selection_frozen_at": T0,
                "fitting_cutoff": AS_OF,
                "intended_population_count": 100,
                "enumerated_population_hash": sha256_hex(b"population"),
                "candidates": candidates,
            }
        )
    )
    state = tmp_path / "state"
    args = [
        "run",
        "--state",
        str(state),
        "--dsn",
        postgres_dsn,
        "--population-rule",
        "latest cs.AI/cs.LG arXiv families",
        "--representation-hash",
        sha256_hex(b"representation"),
        "--candidates",
        str(spec_path),
    ]

    calls: list[str] = []
    original = release.ReleaseWorker._row

    def wrapper(self, lease, candidate, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(candidate.paper_family_id)
        if len(calls) == 3:
            raise _Killed()
        return original(self, lease, candidate, **kwargs)

    monkeypatch.setattr(release.ReleaseWorker, "_row", wrapper)

    with pytest.raises(_Killed):
        release.main(args)

    # Nothing committed yet: the job produced no output before the crash.
    jobs_before_resume = release._job_rows(Database(postgres_dsn))
    assert len(jobs_before_resume) == 1
    _, state_before_resume, report_before_resume = jobs_before_resume[0]
    assert state_before_resume == "running"
    assert report_before_resume is None

    Database(postgres_dsn).transaction(
        lambda connection: connection.execute(
            "UPDATE jobs SET expires_at = clock_timestamp() - interval '1 second' "
            "WHERE state = 'running'"
        )
    )

    assert release.main(args) == 0

    assert calls.count(candidates[0]["paper_family_id"]) == 1
    assert calls.count(candidates[1]["paper_family_id"]) == 1
    assert calls.count(candidates[3]["paper_family_id"]) == 1

    rows = release._job_rows(Database(postgres_dsn))
    assert len(rows) == 1
    _, job_state, report_manifest = rows[0]
    assert job_state == "committed" and report_manifest is not None
    summary = json.loads(
        _read_manifest(postgres_dsn, state / "artifacts", report_manifest)
    )
    assert summary["rows"] == 4
    assert summary["shortfall_count"] == 96
    record = json.loads(
        _read_manifest(postgres_dsn, state / "artifacts", summary["release_hash"])
    )
    assert [row["selection_rank"] for row in record["rows"]] == [0, 1, 2, 3]
    assert all(row["partition"] == "excluded" for row in record["rows"])
    assert all(
        row["exclusion_reasons"] == ["source_unavailable"] for row in record["rows"]
    )


@pytest.mark.integration
def test_worker_resolves_real_labels_through_a_published_release(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = release._identity(
        population_rule="latest cs.AI/cs.LG arXiv families",
        purpose="acquisition_pilot",
        representation_hash=sha256_hex(b"representation"),
    )
    # The worker resolves labels against its own fixed registry identity,
    # independent of any one job's input manifest or fitting cutoff.
    reg = registry(release._TARGET_META)
    family_id, version_id = str(uuid4()), str(uuid4())
    paper = _paper(family_id, version_id, T0)
    families = tuple(_family(index, 10) for index in range(1, 6))
    observation = _observation(
        paper, families, registry_hash=sha256_hex(reg.to_canonical_json())
    )

    database = Database(postgres_dsn)
    migrate(database)
    store = ArtifactStore(tmp_path / "state" / "artifacts")
    artifacts = ArtifactRepository(database, store)

    def publish(payload: bytes) -> str:
        return _publish_json(artifacts, payload, config_hash=identity.config_hash)

    for record in families:
        # Resolver reads citation families by their own content hash, which
        # publishing under its own digest already makes retrievable.
        publish(record.to_canonical_json())
    paper_hash = publish(paper.to_canonical_json())
    observation_hash = publish(observation.to_canonical_json())

    candidate = {
        "paper_family_id": family_id,
        "original_version_id": version_id,
        "selection_rank": 0,
        "t0": T0,
        "paper_artifact_hash": paper_hash,
        "observation_artifact_hash": observation_hash,
    }
    spec_path = tmp_path / "candidates.json"
    spec_path.write_text(
        json.dumps(
            {
                "selection_seed": 20260920,
                "selection_frozen_at": T0,
                "fitting_cutoff": AS_OF,
                "intended_population_count": 100,
                "enumerated_population_hash": sha256_hex(b"population"),
                "candidates": [candidate],
            }
        )
    )
    state = tmp_path / "state"
    args = [
        "run",
        "--state",
        str(state),
        "--dsn",
        postgres_dsn,
        "--population-rule",
        "latest cs.AI/cs.LG arXiv families",
        "--representation-hash",
        sha256_hex(b"representation"),
        "--candidates",
        str(spec_path),
        "--embeddings",
        str(tmp_path / "embeddings"),
        "--text",
        str(tmp_path / "text"),
    ]
    overview = (1.0,) + (0.0,) * 767
    passage = (0.0, 1.0) + (0.0,) * 766

    def embedded(record: PaperVersionRecord) -> release.EmbeddedVersion:
        return release.EmbeddedVersion(
            "9" * 64,
            "complete",
            overview,
            (PassageEmbedding(0, 0, 12, sha256_hex(b"representation"), passage),),
            AS_OF,
            "8" * 64,
        )

    # The pinned tokenizer and the embedding files are stood in for; the
    # worker's own row, label and feature publication is what runs.
    monkeypatch.setattr(
        release,
        "local_embedding_inputs",
        lambda *args, **kwargs: (lambda text: len(text.split()), embedded),
    )
    assert release.main(args) == 0
    rows = release._job_rows(database)
    assert len(rows) == 1
    _, job_state, report_manifest = rows[0]
    assert job_state == "committed" and report_manifest is not None
    summary = json.loads(
        _read_manifest(postgres_dsn, state / "artifacts", report_manifest)
    )
    raw = _read_manifest(postgres_dsn, state / "artifacts", summary["release_hash"])
    assert sha256_hex(raw) == summary["release_artifact_hash"]
    record = json.loads(raw)
    row = record["rows"][0]
    assert row["partition"] == "pilot"
    assert row["known_mask"] == [True, True, True]
    assert record["source_observation_hashes"] == [
        sha256_hex(observation.to_canonical_json())
    ]
    assert (row["title_tokens"], row["abstract_tokens"], row["code_link"]) == (
        1,
        1,
        False,
    )
    assert row["first_available_weekday"] == instant(T0).weekday()
    # Every label and the feature record the row cites are committed and
    # readable by their own content hash.
    for label_hash in row["label_hashes"]:
        with store.open_verified(label_hash) as handle:
            assert AutomaticLabel.from_json(handle.read()).paper_family_id == family_id
    with store.open_verified(row["feature_hash"]) as handle:
        feature = CombinedFeatureRecord.from_json(handle.read())
    assert feature.paper_family_id == family_id
    assert feature.original_source_hash == paper.original_source_hash
    with store.open_verified(feature.combined_vector.payload_hash) as handle:
        combined = np.frombuffer(handle.read(), dtype="<f4")
    assert np.isclose(np.linalg.norm(combined), 1.0, atol=1e-6)


def test_cli_refuses_to_run_without_a_population_rule(tmp_path: Path) -> None:
    base = [
        "run",
        "--state",
        str(tmp_path / "state"),
        "--dsn",
        "postgresql://unused/db",
        "--representation-hash",
        sha256_hex(b"representation"),
    ]
    with pytest.raises(SystemExit):
        release.main([*base, "--population-rule", "   "])
    with pytest.raises(SystemExit):
        release.main(base)


# --- the card fields a row records (#278) ---------------------------------

# 2020-06-15 is a Monday, so the first-availability weekday is 0.
CARD: dict[str, Any] = {
    "abstract_tokens": 180,
    "title_tokens": 9,
    "first_available_weekday": 0,
    "code_link": True,
}


def _row(**card: Any) -> CorpusRow:
    return CorpusRow(
        str(uuid4()),
        str(uuid4()),
        T0,
        publication_week(T0),
        "A",
        0,
        "d" * 64,
        (None, None, None),
        (False, False, False),
        "pilot",
        (),
        3,
        ("cs.AI",),
        1,
        **card,
    )


def test_an_unrecorded_row_keeps_the_bytes_it_had_before_card_fields() -> None:
    row = _row()
    body = json.loads(row.to_canonical_json())
    assert not set(CARD) & set(body)
    assert CorpusRow.from_json(row.to_canonical_json()) == row
    record = CorpusRelease(
        1,
        (),
        _META.producer_version,
        _META.config_hash,
        AS_OF,
        "acquisition_pilot",
        "1" * 64,
        "2" * 64,
        20260920,
        T0,
        AS_OF,
        100,
        "3" * 64,
        (row,),
        99,
        "4" * 64,
        "5" * 64,
        (),
        None,
    )
    # The release serializes each row exactly as the row does.
    assert json.loads(record.to_canonical_json())["rows"] == [body]
    assert CorpusRelease.from_json(record.to_canonical_json()) == record


def test_recorded_card_fields_round_trip() -> None:
    row = _row(**CARD)
    body = json.loads(row.to_canonical_json())
    assert {name: body[name] for name in CARD} == CARD
    assert CorpusRow.from_json(row.to_canonical_json()) == row


def test_card_fields_are_all_present_or_all_omitted_and_never_all_null() -> None:
    body = json.loads(_row(**CARD).to_canonical_json())
    partial = {key: value for key, value in body.items() if key != "code_link"}
    with pytest.raises(ContractValidationError, match="fields"):
        CorpusRow.from_json(canonical_json(partial))
    nulls = {**body, **{name: None for name in CARD}}
    with pytest.raises(ContractValidationError, match="omitted, never null"):
        CorpusRow.from_json(canonical_json(nulls))


def test_card_field_values_are_checked_against_the_row() -> None:
    with pytest.raises(ContractValidationError, match="differs from t0"):
        _row(**{**CARD, "first_available_weekday": 3})
    with pytest.raises(ContractValidationError, match="weekday is invalid"):
        _row(**{**CARD, "first_available_weekday": 7})
    with pytest.raises(ContractValidationError, match="boolean"):
        _row(**{**CARD, "code_link": 1})
    with pytest.raises(ValueError):
        _row(**{**CARD, "title_tokens": -1})
    # A weekday needs a known first-public time.
    with pytest.raises(ContractValidationError, match="differs from t0"):
        replace(_row(**CARD), t0=None, publication_week=None)
