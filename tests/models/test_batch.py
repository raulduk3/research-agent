"""bin/embed-batch's manifest, paper batch and resumable batch loop (Appendix A, C)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.passages import (
    ExtractedBlock,
    ExtractionRecord,
    SourceLocator,
)
from research_agent.contracts.primitives import ContractValidationError
from research_agent.models.batch import (
    BatchManifest,
    DEFAULT_MIN_COSINE_THRESHOLD,
    PaperBatch,
    PaperText,
    PassageVector,
    PlatformIdentity,
    embed_paper_batch,
    paper_batch_path,
    read_batch_manifest,
    read_paper_batch,
    run_batch,
    verify_batch_manifest,
    write_paper_batch,
)
from research_agent.models.embedding import FrozenEmbedder, overview_text
from research_agent.models.manifest import RepresentationManifest


class _WhitespaceTokenizer:
    """One content token per whitespace-delimited word (matches tests/retrieval)."""

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


def _platform(**overrides: object) -> PlatformIdentity:
    values: dict[str, object] = {
        "device": "cuda",
        "device_name": "Test GPU",
        "driver_version": "1.2.3",
        "library_versions": {"torch": "2.14.0", "transformers": "5.17.0"},
    }
    values.update(overrides)
    return PlatformIdentity(**values)  # type: ignore[arg-type]


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


def _batch_manifest_factory(
    manifest: RepresentationManifest,
) -> Callable[..., BatchManifest]:
    def factory(**overrides: object) -> BatchManifest:
        values: dict[str, object] = {
            "model_id": manifest.model_id,
            "revision": manifest.revision,
            "checkpoint_date": manifest.checkpoint_date,
            "dtype": manifest.dtype,
            "pooling": manifest.pooling,
            "document_prefix": manifest.document_prefix,
            "query_prefix": manifest.query_prefix,
            "chunk_policy": "passages-384-64-v1",
            "platform": _platform(),
            "created_at": "2026-01-01T00:00:00.000000Z",
            "min_cosine_threshold": DEFAULT_MIN_COSINE_THRESHOLD,
            "file_hashes": {"11111111-1111-4111-8111-111111111111": "a" * 64},
        }
        values.update(overrides)
        return BatchManifest(**values)  # type: ignore[arg-type]

    return factory


def test_platform_identity_round_trips_through_dict() -> None:
    platform = _platform()
    assert PlatformIdentity.from_dict(platform.to_dict()) == platform


@pytest.mark.parametrize(
    "overrides",
    [
        {"device": "tpu"},
        {"device_name": ""},
        {"driver_version": ""},
        {"library_versions": {}},
    ],
)
def test_platform_identity_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        _platform(**overrides)


def test_embed_paper_batch_reuses_build_passages_and_pooling(
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    paper_text = _paper_text("11111111-1111-4111-8111-111111111111", words=800)

    batch = embed_paper_batch(paper_text, _WhitespaceTokenizer(), embedder)

    assert batch.paper_version_id == paper_text.paper_version_id
    assert batch.coverage == "complete"
    assert len(batch.passages) > 1
    (expected_overview,) = embedder.embed_documents(
        [overview_text(paper_text.title, paper_text.abstract)]
    )
    assert batch.overview_vector == expected_overview
    orders = [passage.passage_order for passage in batch.passages]
    assert orders == sorted(orders)


def test_paper_batch_round_trips_through_json() -> None:
    batch = PaperBatch(
        paper_version_id="11111111-1111-4111-8111-111111111111",
        extraction_hash="c" * 64,
        chunk_policy="passages-384-64-v1",
        coverage="complete",
        coverage_reasons=(),
        overview_vector=(0.1, 0.2, 0.3),
        passages=(PassageVector(0, "e" * 64, (0.4, 0.5)),),
    )
    assert PaperBatch.from_json(batch.to_canonical_json()) == batch


def test_batch_manifest_round_trips_and_computes_a_stable_namespace_id(
    manifest: RepresentationManifest,
) -> None:
    factory = _batch_manifest_factory(manifest)
    first = factory()
    assert BatchManifest.from_json(first.to_canonical_json()) == first
    with pytest.raises(ContractValidationError):
        factory(file_hashes={})
    second = factory(
        created_at="2026-02-02T00:00:00.000000Z",
        file_hashes={"22222222-2222-4222-8222-222222222222": "b" * 64},
    )
    assert first.namespace_id == second.namespace_id


def test_batch_manifest_namespace_id_changes_with_platform(
    manifest: RepresentationManifest,
) -> None:
    factory = _batch_manifest_factory(manifest)
    cuda_batch = factory()
    cpu_batch = factory(platform=_platform(device="cpu", device_name="Test CPU"))
    assert cuda_batch.namespace_id != cpu_batch.namespace_id


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_id": "some-other/model"},
        {"revision": "0" * 40},
        {"dtype": "float16"},
        {"pooling": "last_token"},
        {"document_prefix": "passage: "},
        {"query_prefix": "query: "},
        {"chunk_policy": "passages-512-0-v1"},
        {"min_cosine_threshold": 1.5},
    ],
)
def test_batch_manifest_rejects_drift_from_the_pinned_identity(
    manifest: RepresentationManifest,
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ContractValidationError):
        _batch_manifest_factory(manifest)(**overrides)


def test_run_batch_embeds_writes_files_and_the_manifest(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    backend = fake_backend_factory()
    embedder = FrozenEmbedder(manifest, backend)  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    out_dir = tmp_path / "out"
    text_dir.mkdir()

    first_id = "11111111-1111-4111-8111-111111111111"
    second_id = "22222222-2222-4222-8222-222222222222"
    _write_paper_text(text_dir, _paper_text(first_id))
    _write_paper_text(text_dir, _paper_text(second_id))

    written_manifest = run_batch(
        text_dir, out_dir, embedder, _WhitespaceTokenizer(), _platform()
    )

    assert set(written_manifest.file_hashes) == {first_id, second_id}
    for paper_version_id in (first_id, second_id):
        path = paper_batch_path(out_dir, paper_version_id)
        assert path.exists()
        assert (
            sha256_hex(path.read_bytes())
            == written_manifest.file_hashes[paper_version_id]
        )
    assert read_batch_manifest(out_dir) == written_manifest
    calls_after_first_run = len(backend.received_texts)  # type: ignore[attr-defined]

    run_batch(text_dir, out_dir, embedder, _WhitespaceTokenizer(), _platform())
    assert len(backend.received_texts) == calls_after_first_run  # type: ignore[attr-defined]


def test_run_batch_resumes_without_recomputing_existing_papers(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    backend = fake_backend_factory()
    embedder = FrozenEmbedder(manifest, backend)  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    out_dir = tmp_path / "out"
    text_dir.mkdir()

    first_id = "11111111-1111-4111-8111-111111111111"
    _write_paper_text(text_dir, _paper_text(first_id))
    run_batch(text_dir, out_dir, embedder, _WhitespaceTokenizer(), _platform())
    first_bytes = paper_batch_path(out_dir, first_id).read_bytes()

    second_id = "22222222-2222-4222-8222-222222222222"
    _write_paper_text(text_dir, _paper_text(second_id))
    run_batch(text_dir, out_dir, embedder, _WhitespaceTokenizer(), _platform())

    assert paper_batch_path(out_dir, first_id).read_bytes() == first_bytes
    assert paper_batch_path(out_dir, second_id).exists()


def test_verify_batch_manifest_accepts_untouched_files(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    out_dir = tmp_path / "out"
    text_dir.mkdir()
    paper_id = "11111111-1111-4111-8111-111111111111"
    _write_paper_text(text_dir, _paper_text(paper_id))

    written = run_batch(
        text_dir, out_dir, embedder, _WhitespaceTokenizer(), _platform()
    )
    verify_batch_manifest(out_dir, written)


def test_verify_batch_manifest_refuses_a_modified_file(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    out_dir = tmp_path / "out"
    text_dir.mkdir()
    paper_id = "11111111-1111-4111-8111-111111111111"
    _write_paper_text(text_dir, _paper_text(paper_id))

    written = run_batch(
        text_dir, out_dir, embedder, _WhitespaceTokenizer(), _platform()
    )
    tampered = read_paper_batch(paper_batch_path(out_dir, paper_id))
    tampered = dataclasses.replace(
        tampered, overview_vector=tuple(v + 1.0 for v in tampered.overview_vector)
    )
    write_paper_batch(out_dir, tampered)

    with pytest.raises(ContractValidationError):
        verify_batch_manifest(out_dir, written)


def test_verify_batch_manifest_refuses_a_missing_file(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> None:
    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir = tmp_path / "text"
    out_dir = tmp_path / "out"
    text_dir.mkdir()
    paper_id = "11111111-1111-4111-8111-111111111111"
    _write_paper_text(text_dir, _paper_text(paper_id))

    written = run_batch(
        text_dir, out_dir, embedder, _WhitespaceTokenizer(), _platform()
    )
    paper_batch_path(out_dir, paper_id).unlink()

    with pytest.raises(ContractValidationError):
        verify_batch_manifest(out_dir, written)
