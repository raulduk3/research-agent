"""bin/import-embeddings' platform equivalence gate and publication (Appendix A)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.passages import (
    ExtractedBlock,
    ExtractionRecord,
    SourceLocator,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    ProducerVersion,
)
from research_agent.ingest.pilot import (
    Identity,
    ParallelGate,
    PilotWorker,
    RateGate,
    Sources,
    derived_uuid,
)
from research_agent.ingest.pilot_local import local_storage, worker_principal
from research_agent.ingest.requests import LocalEmbeddingViews
from research_agent.learning.text_export import release_identities
from research_agent.models.batch import (
    PaperText,
    PlatformIdentity,
    paper_batch_path,
    read_paper_batch,
    run_batch,
    write_paper_batch,
)
from research_agent.models.embedding import FrozenEmbedder
from research_agent.models.equivalence import (
    EquivalenceRefusedError,
    EquivalenceReport,
    check_equivalence,
    compute_equivalence,
    cosine_similarity,
    import_batch,
)
from research_agent.models.manifest import RepresentationManifest
from research_agent.storage.embedding_views import EmbeddingViewRepository


class _WhitespaceTokenizer:
    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        offsets: list[tuple[int, int]] = []
        index = 0
        length = len(text)
        while index < length:
            while index < length and text[index].isspace():
                index += 1
            if index >= length:
                break
            start = index
            while index < length and not text[index].isspace():
                index += 1
            offsets.append((start, index))
        return offsets


def _platform() -> PlatformIdentity:
    return PlatformIdentity(
        device="cuda",
        device_name="Test GPU",
        driver_version="1.2.3",
        library_versions={"torch": "2.14.0", "transformers": "5.17.0"},
    )


def _paper_text(paper_version_id: str, words: int = 20) -> PaperText:
    text = " ".join(f"tok{i}" for i in range(words))
    block = ExtractedBlock(
        block_id="b0",
        section_path=("Introduction",),
        section_order=0,
        block_order=0,
        kind="body",
        char_start=0,
        char_end_exclusive=len(text),
        included_in_passages=True,
        omission_reason=None,
        locator=SourceLocator("a" * 64, "latex", None, None, None, None),
    )
    extraction = ExtractionRecord(
        paper_version_id=paper_version_id,
        source_hash="a" * 64,
        extractor_manifest_hash="b" * 64,
        text_hash=sha256_hex(text.encode("utf-8")),
        text_codepoints=len(text),
        blocks=(block,),
        coverage="complete",
        coverage_reasons=(),
        included_block_count=1,
        omitted_block_count=0,
        created_at="2026-01-01T00:00:00.000000Z",
    )
    return PaperText(
        paper_version_id=paper_version_id,
        title="A Test Paper",
        abstract="An abstract about testing.",
        extraction_hash="c" * 64,
        canonical_text=text,
        extraction=extraction,
    )


def _write_paper_text(text_dir: Path, paper_text: PaperText) -> None:
    (text_dir / f"{paper_text.paper_version_id}.json").write_bytes(
        paper_text.to_canonical_json()
    )


def test_cosine_similarity_of_identical_and_opposite_vectors() -> None:
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine_similarity((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(-1.0)
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)


def test_compute_equivalence_over_identical_vectors_is_perfect_agreement() -> None:
    vectors = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    report = compute_equivalence(vectors, vectors)
    assert report.min_cosine == pytest.approx(1.0)
    assert report.mean_cosine == pytest.approx(1.0)
    assert report.max_absolute_difference == pytest.approx(0.0)


def test_check_equivalence_passes_when_above_threshold() -> None:
    vectors = [(1.0, 0.0), (0.0, 1.0)]
    report = check_equivalence(vectors, vectors, min_cosine=0.9999)
    assert isinstance(report, EquivalenceReport)


def test_check_equivalence_refuses_a_planted_divergent_vector() -> None:
    host_vectors = [(1.0, 0.0), (0.0, 1.0)]
    batch_vectors = [(1.0, 0.0), (0.0, -1.0)]  # one paper's batch vector is divergent

    with pytest.raises(EquivalenceRefusedError):
        check_equivalence(host_vectors, batch_vectors, min_cosine=0.9999)


@pytest.mark.parametrize(
    "overrides",
    [
        {"sample_count": 0},
        {"min_cosine": 1.5},
        {"max_absolute_difference": -0.1},
    ],
)
def test_equivalence_report_rejects_invalid_values(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "sample_count": 1,
        "min_cosine": 1.0,
        "mean_cosine": 1.0,
        "max_absolute_difference": 0.0,
    }
    values.update(overrides)
    with pytest.raises(ContractValidationError):
        EquivalenceReport(**values)  # type: ignore[arg-type]


def test_import_batch_publishes_and_records_platform_and_agreement(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    batch_embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    host_embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    batch_dir = tmp_path / "batch"
    namespace_dir = tmp_path / "namespace"
    text_dir.mkdir()

    paper_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    for paper_id in paper_ids:
        _write_paper_text(text_dir, _paper_text(paper_id))
    run_batch(text_dir, batch_dir, batch_embedder, _WhitespaceTokenizer(), _platform())

    result = import_batch(
        batch_dir, namespace_dir, text_dir, host_embedder, _WhitespaceTokenizer(), 1
    )

    assert result.equivalence is not None
    assert result.equivalence.min_cosine == pytest.approx(1.0)
    assert {item.paper_version_id for item in result.published} == set(paper_ids)
    for paper_id in paper_ids:
        assert (namespace_dir / f"{paper_id}.json").exists()


def test_a_second_import_with_another_sample_reuses_every_entry(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    """The prohibited alternative: a rerun whose equivalence report differs
    refused at its first entry although the vectors are unchanged (#361)."""
    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    batch_dir = tmp_path / "batch"
    namespace_dir = tmp_path / "namespace"
    text_dir.mkdir()
    for paper_id in (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ):
        _write_paper_text(text_dir, _paper_text(paper_id))
    run_batch(text_dir, batch_dir, embedder, _WhitespaceTokenizer(), _platform())

    first = import_batch(
        batch_dir, namespace_dir, text_dir, embedder, _WhitespaceTokenizer(), 2
    )
    again = import_batch(
        batch_dir, namespace_dir, text_dir, embedder, _WhitespaceTokenizer(), 1
    )

    assert first.equivalence is not None and first.equivalence.sample_count == 2
    assert again.equivalence is not None and again.equivalence.sample_count == 1
    assert len(again.published) == 2
    assert all(item.reused for item in again.published)
    assert [item.entry_hash for item in again.published] == [
        item.entry_hash for item in first.published
    ]


class _NoViews:
    def identities(self) -> dict[str, Any]:
        raise AssertionError("a refused views-only import reads no identity")

    def store(self, view: object, neighbors: object) -> str:
        raise AssertionError("a refused views-only import stores nothing")


def test_a_views_only_import_refuses_a_batch_not_fully_published(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    batch_dir = tmp_path / "batch"
    namespace_dir = tmp_path / "namespace"
    text_dir.mkdir()
    _write_paper_text(text_dir, _paper_text("11111111-1111-4111-8111-111111111111"))
    run_batch(text_dir, batch_dir, embedder, _WhitespaceTokenizer(), _platform())
    import_batch(
        batch_dir, namespace_dir, text_dir, embedder, _WhitespaceTokenizer(), 1
    )
    _write_paper_text(text_dir, _paper_text("22222222-2222-4222-8222-222222222222"))
    run_batch(text_dir, batch_dir, embedder, _WhitespaceTokenizer(), _platform())

    with pytest.raises(ContractValidationError, match="not published"):
        import_batch(
            batch_dir,
            namespace_dir,
            text_dir,
            embedder,
            _WhitespaceTokenizer(),
            0,
            views=cast(Any, _NoViews()),
            views_only=True,
        )


def test_import_batch_refuses_a_divergent_batch_and_publishes_nothing(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    batch_embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    host_embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    batch_dir = tmp_path / "batch"
    namespace_dir = tmp_path / "namespace"
    text_dir.mkdir()

    paper_id = "11111111-1111-4111-8111-111111111111"
    _write_paper_text(text_dir, _paper_text(paper_id))
    run_batch(text_dir, batch_dir, batch_embedder, _WhitespaceTokenizer(), _platform())

    divergent = read_paper_batch(paper_batch_path(batch_dir, paper_id))
    divergent = dataclasses.replace(
        divergent, overview_vector=tuple(-v for v in divergent.overview_vector)
    )
    write_paper_batch(batch_dir, divergent)
    # The divergent content is part of the batch, not a post-hoc tamper: a
    # fresh manifest recomputed over it records its own (matching) hash, so
    # only the equivalence gate below can refuse it.
    run_batch(text_dir, batch_dir, batch_embedder, _WhitespaceTokenizer(), _platform())

    with pytest.raises(EquivalenceRefusedError):
        import_batch(
            batch_dir, namespace_dir, text_dir, host_embedder, _WhitespaceTokenizer(), 1
        )

    assert not namespace_dir.exists()


def test_cosine_of_identical_vectors_never_exceeds_one() -> None:
    """The prohibited alternative is refusing the best-agreeing batch: two
    identical unit vectors divided to 1.0000001 on a real import and the
    report's bound rejected it as a cosine above one."""
    import random

    from research_agent.models.equivalence import _bounded_cosine, cosine_similarity

    rng = random.Random(7)
    for _ in range(20):
        raw = [rng.uniform(-1.0, 1.0) for _ in range(768)]
        norm = sum(x * x for x in raw) ** 0.5
        unit = [x / norm for x in raw]
        assert cosine_similarity(unit, unit) <= 1.0
    assert _bounded_cosine(1.0 + 5e-7) == 1.0
    assert _bounded_cosine(-1.0 - 5e-7) == -1.0
    assert _bounded_cosine(0.5) == 0.5
    assert _bounded_cosine(1.01) == 1.01, "past rounding is not absorbed"


RELEASE_FAMILIES = ("2305.01937", "2305.01938")


def _selected(family_id: str) -> dict[str, Any]:
    return {
        "family_id": family_id,
        "first_public_at": f"2023-05-0{RELEASE_FAMILIES.index(family_id) + 3}"
        "T00:00:00.000000Z",
        "categories": ["cs.LG"],
        "license_url": None,
        "doi": None,
        "title": f"Release paper {family_id}",
        "abstract": "An abstract.",
        "author_count": 1,
        "version_count": 1,
    }


def _unreachable(*_: object, **__: object) -> Any:
    raise AssertionError("only the selection stage runs here")


@pytest.mark.integration
def test_a_release_import_stores_a_view_for_every_version_and_a_rerun_stores_none(
    postgres_dsn: str,
    artifact_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    """The prohibited alternatives: a backfill that publishes vectors with no
    view because the text directory names no family, and a rerun over the
    same batch that records every view again."""
    monkeypatch.setattr(
        PilotWorker,
        "_select",
        lambda self, lease: {
            "stage": "select",
            "selected": [_selected(family) for family in RELEASE_FAMILIES],
        },
    )
    batch_embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    host_embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    batch_dir = tmp_path / "batch"
    namespace_dir = tmp_path / "namespace"
    text_dir.mkdir()
    versions = {
        str(derived_uuid("gate-paper-version", family)): str(
            derived_uuid("gate-paper-family", family)
        )
        for family in RELEASE_FAMILIES
    }
    for version in versions:
        _write_paper_text(text_dir, _paper_text(version))
    run_batch(text_dir, batch_dir, batch_embedder, _WhitespaceTokenizer(), _platform())
    tls = tmp_path / "tls"
    identity = Identity(
        ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
    )

    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tls,
        identity=identity,
    ) as storage:
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=identity,
            sources=Sources(
                listing=_unreachable,
                document=_unreachable,
                openalex_match=_unreachable,
                openalex_cites=_unreachable,
                arxiv_gate=RateGate(0.001),
                openalex_gate=RateGate(0.001),
                pdf_bucket=_unreachable,
                bucket_gate=ParallelGate(1),
            ),
        )
        storage.enqueue({"stage": "select"})
        assert worker.run().jobs_completed == 1
        repository = EmbeddingViewRepository(storage.database, storage.artifacts)

        def run() -> Any:
            return import_batch(
                batch_dir,
                namespace_dir,
                text_dir,
                host_embedder,
                _WhitespaceTokenizer(),
                1,
                views=LocalEmbeddingViews(storage, release_identities(storage)),
                current_view=repository.current,
            )

        def recorded() -> int:
            row = storage.database.transaction(
                lambda connection: connection.execute(
                    "SELECT count(*) FROM embedding_views"
                ).fetchone()
            )
            assert row is not None
            return cast(int, row[0])

        first = run()
        assert len(first.views) == len(versions)
        assert first.views_current == 0
        for version, family in versions.items():
            view = repository.current(family)
            assert view is not None
            assert view["paper_version_id"] == version
            assert [n["paper_id"] for n in view["neighbors"]] == [
                other for other in versions.values() if other != family
            ]
        assert recorded() == len(versions)

        again = run()
        assert all(item.reused for item in again.published)
        assert again.views == ()
        assert again.views_current == len(versions)
        assert recorded() == len(versions)


@pytest.mark.integration
def test_a_views_only_import_stores_each_view_of_a_published_batch_once(
    postgres_dsn: str,
    artifact_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    """The prohibited alternative: a namespace published without views that
    no later run can give views, because every entry is already there (#361)."""
    monkeypatch.setattr(
        PilotWorker,
        "_select",
        lambda self, lease: {
            "stage": "select",
            "selected": [_selected(family) for family in RELEASE_FAMILIES],
        },
    )
    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    batch_dir = tmp_path / "batch"
    namespace_dir = tmp_path / "namespace"
    text_dir.mkdir()
    for family in RELEASE_FAMILIES:
        _write_paper_text(
            text_dir, _paper_text(str(derived_uuid("gate-paper-version", family)))
        )
    run_batch(text_dir, batch_dir, embedder, _WhitespaceTokenizer(), _platform())
    import_batch(
        batch_dir, namespace_dir, text_dir, embedder, _WhitespaceTokenizer(), 2
    )
    tls = tmp_path / "tls"
    identity = Identity(
        ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
    )

    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tls,
        identity=identity,
    ) as storage:
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=identity,
            sources=Sources(
                listing=_unreachable,
                document=_unreachable,
                openalex_match=_unreachable,
                openalex_cites=_unreachable,
                arxiv_gate=RateGate(0.001),
                openalex_gate=RateGate(0.001),
                pdf_bucket=_unreachable,
                bucket_gate=ParallelGate(1),
            ),
        )
        storage.enqueue({"stage": "select"})
        assert worker.run().jobs_completed == 1
        repository = EmbeddingViewRepository(storage.database, storage.artifacts)

        def views_only() -> Any:
            return import_batch(
                batch_dir,
                namespace_dir,
                text_dir,
                embedder,
                _WhitespaceTokenizer(),
                0,
                views=LocalEmbeddingViews(storage, release_identities(storage)),
                current_view=repository.current,
                views_only=True,
            )

        first = views_only()
        assert first.equivalence is None and first.published == ()
        assert len(first.views) == len(RELEASE_FAMILIES)
        again = views_only()
        assert again.views == ()
        assert again.views_current == len(RELEASE_FAMILIES)
        row = storage.database.transaction(
            lambda connection: connection.execute(
                "SELECT count(*) FROM embedding_views"
            ).fetchone()
        )
        assert row is not None and row[0] == len(RELEASE_FAMILIES)
