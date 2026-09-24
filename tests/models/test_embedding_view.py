"""The embedding view a publish path builds for each paper version (#298)."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.passages import (
    ExtractedBlock,
    ExtractionRecord,
    SourceLocator,
)
from research_agent.contracts.primitives import ContractValidationError
from research_agent.models.batch import (
    PaperText,
    PlatformIdentity,
    paper_text_path,
    run_batch,
)
from research_agent.models.embedding import FrozenEmbedder
from research_agent.models.embedding_view import (
    COMPONENT_VERSION,
    NEIGHBOR_COUNT,
    NeighborCandidate,
    PaperIdentity,
    build_embedding_view,
    load_candidates,
)
from research_agent.models.equivalence import import_batch
from research_agent.models.manifest import RepresentationManifest
from research_agent.retrieval.passages import (
    IndexEntry,
    PublishedPassage,
    build_passages,
)


class _Words:
    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        offsets: list[tuple[int, int]] = []
        index = 0
        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            start = index
            while index < len(text) and not text[index].isspace():
                index += 1
            if index > start:
                offsets.append((start, index))
        return offsets


def _version(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-{n:012x}"


def _family(n: int) -> str:
    return f"{n:08x}-1111-4111-8111-{n:012x}"


def _text(n: int, words: int = 900) -> PaperText:
    # Each paper shares a vocabulary but mixes it its own way, so overviews
    # and passages differ without being unrelated.
    text = " ".join(f"w{(i * (n + 1)) % 97}" for i in range(words))
    version = _version(n)
    extraction = ExtractionRecord(
        paper_version_id=version,
        source_hash="a" * 64,
        extractor_manifest_hash="b" * 64,
        text_hash=sha256_hex(text.encode("utf-8")),
        text_codepoints=len(text),
        blocks=(
            ExtractedBlock(
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
            ),
        ),
        coverage="complete",
        coverage_reasons=(),
        included_block_count=1,
        omitted_block_count=0,
        created_at="2026-01-01T00:00:00.000000Z",
    )
    return PaperText(
        paper_version_id=version,
        title=f"Paper {n}",
        abstract=f"An abstract about paper {n}.",
        extraction_hash=sha256_hex(extraction.to_canonical_json()),
        canonical_text=text,
        extraction=extraction,
    )


def _identity(n: int, day: int | None) -> PaperIdentity:
    first = None if day is None else f"2026-01-{day:02d}T00:00:00.000000Z"
    return PaperIdentity(_family(n), f"Paper {n}", first)


class _Sink:
    def __init__(self, identities: Mapping[str, PaperIdentity]) -> None:
        self._identities = identities
        self.stored: list[tuple[dict[str, Any], tuple[str, ...]]] = []

    def identities(self) -> Mapping[str, PaperIdentity]:
        return self._identities

    def store(self, view: Mapping[str, Any], input_hashes: tuple[str, ...]) -> str:
        self.stored.append((dict(view), input_hashes))
        return sha256_hex(canonical_json(view))


@pytest.fixture
def imported(
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
) -> tuple[Path, Path, FrozenEmbedder, dict[str, PaperIdentity], _Sink]:
    """Twelve papers through a verified batch import with a view sink; the
    twelfth has no identity the sink can name."""

    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    text_dir, batch_dir, namespace = (
        tmp_path / "text",
        tmp_path / "batch",
        tmp_path / "index",
    )
    text_dir.mkdir()
    for n in range(1, 13):
        paper_text_path(text_dir, _version(n)).write_bytes(_text(n).to_canonical_json())
    run_batch(
        text_dir,
        batch_dir,
        embedder,
        _Words(),
        PlatformIdentity("cpu", "test", "0", {"torch": "0"}),
    )
    identities = {_version(n): _identity(n, n) for n in range(1, 12)}
    sink = _Sink(identities)
    result = import_batch(
        batch_dir, namespace, text_dir, embedder, _Words(), 1, views=sink
    )
    assert len(result.views) == 11
    return text_dir, namespace, embedder, identities, sink


def _entry(namespace: Path, n: int) -> IndexEntry:
    raw = json.loads((namespace / f"{_version(n)}.json").read_bytes())
    return IndexEntry(
        paper_version_id=raw["paper_version_id"],
        extraction_hash=raw["extraction_hash"],
        chunk_policy=raw["chunk_policy"],
        coverage=raw["coverage"],
        coverage_reasons=tuple(raw["coverage_reasons"]),
        overview_vector=tuple(raw["overview_vector"]),
        passages=tuple(
            PublishedPassage(p["passage_order"], p["text_hash"], tuple(p["vector"]))
            for p in raw["passages"]
        ),
        platform=raw["platform"],
        equivalence=raw["equivalence"],
    )


def test_the_import_stores_a_measured_view_for_every_named_paper(
    imported: tuple[Path, Path, FrozenEmbedder, dict[str, PaperIdentity], _Sink],
) -> None:
    _, namespace, embedder, _, sink = imported
    views = {view["paper_version_id"]: view for view, _ in sink.stored}
    # The unnamed twelfth paper was published but has no view.
    assert set(views) == {_version(n) for n in range(1, 12)}
    assert (namespace / f"{_version(12)}.json").exists()
    view = views[_version(6)]
    entry = _entry(namespace, 6)

    assert view["paper_id"] == _family(6)
    assert view["representation_hash"] == embedder.manifest.representation_hash
    assert view["dims"] == len(entry.overview_vector) == 768
    assert view["overview"]["vector"] == [round(x, 4) for x in entry.overview_vector]
    histogram = view["overview"]["histogram"]
    assert (histogram["bins"], sum(histogram["counts"])) == (48, 768)
    assert len(histogram["counts"]) == 48
    passages = view["passages"]
    assert len(passages) == len(entry.passages) > 1
    assert [p["order"] for p in passages] == list(range(len(passages)))
    assert all(len(p["bins"]) == 96 and len(p["pc"]) == 2 for p in passages)
    assert all(len(p["excerpt"]) <= 121 for p in passages)
    rows = view["similarity"]["rows"]
    assert [len(row) for row in rows] == [len(passages)] * len(passages)
    assert all(rows[i][i] == 1.0 for i in range(len(rows)))
    assert all(rows[i][j] == rows[j][i] for i in range(len(rows)) for j in range(i))
    assert view["projection"]["method"] == "pca"
    assert 0 < sum(view["projection"]["explained"]) <= 1.0
    # The batch path stores no index artifact, so the view names its inputs
    # by hash in its body alone.
    assert view["derived_from"]["passage_index_hash"] == sha256_hex(
        entry.to_canonical_json()
    )
    assert view["derived_from"]["component_version"] == COMPONENT_VERSION
    assert {inputs for _, inputs in sink.stored} == {()}


def test_neighbors_are_the_nearest_other_families_with_earlier_marked(
    imported: tuple[Path, Path, FrozenEmbedder, dict[str, PaperIdentity], _Sink],
) -> None:
    _, _, _, _, sink = imported
    view = next(v for v, _ in sink.stored if v["paper_version_id"] == _version(6))
    neighbors = view["neighbors"]
    assert len(neighbors) == NEIGHBOR_COUNT
    families = [n["paper_id"] for n in neighbors]
    # Never itself, never the unnamed paper, and later papers are listed too.
    assert _family(6) not in families and _family(12) not in families
    cosines = [n["cos"] for n in neighbors]
    assert cosines == sorted(cosines, reverse=True)
    for neighbor in neighbors:
        n = int(neighbor["paper_id"][:8], 16)
        assert neighbor["title"] == f"Paper {n}"
        assert neighbor["earlier"] is (n < 6)
    assert {n["earlier"] for n in neighbors} == {True, False}


def test_a_view_rebuilds_bit_for_bit_from_the_same_inputs(
    imported: tuple[Path, Path, FrozenEmbedder, dict[str, PaperIdentity], _Sink],
) -> None:
    text_dir, namespace, embedder, identities, sink = imported
    stored = next(v for v, _ in sink.stored if v["paper_version_id"] == _version(3))

    def build() -> bytes:
        return canonical_json(
            build_embedding_view(
                identity=identities[_version(3)],
                text=_text(3),
                entry=_entry(namespace, 3),
                tokenizer=_Words(),
                representation_hash=embedder.manifest.representation_hash,
                candidates=load_candidates(namespace, identities),
            )
        )

    assert build() == build() == canonical_json(stored)


def test_a_family_is_ranked_by_its_first_public_version_only() -> None:
    unit = tuple([1.0] + [0.0] * 767)
    near = tuple([0.9, 0.1] + [0.0] * 766)
    far = tuple([0.1, 0.9] + [0.0] * 766)
    paper = _identity(1, 10)
    later_version = PaperIdentity(_family(2), "Paper 2", "2026-01-05T00:00:00.000000Z")
    candidates = (
        NeighborCandidate(_version(20), later_version, near),
        NeighborCandidate(_version(21), _identity(2, 3), far),
        NeighborCandidate(_version(22), _identity(3, 20), near),
    )
    text = _text(1, words=20)
    (record,) = build_passages(
        text.extraction, text.canonical_text, text.extraction_hash, _Words()
    )
    entry = IndexEntry(
        paper_version_id=text.paper_version_id,
        extraction_hash=text.extraction_hash,
        chunk_policy="passages-384-64-v1",
        coverage="complete",
        coverage_reasons=(),
        overview_vector=unit,
        passages=(PublishedPassage(0, record.text_hash, far),),
        platform={"device": "cpu"},
        equivalence=None,
    )
    view = build_embedding_view(
        identity=paper,
        text=text,
        entry=entry,
        tokenizer=_Words(),
        representation_hash="e" * 64,
        candidates=candidates,
    )
    # Family 2's later, nearer version is not its original: it ranks by the
    # far vector its first public version has.
    assert [(n["paper_id"], n["cos"], n["earlier"]) for n in view["neighbors"]] == [
        (_family(3), 0.994, False),
        (_family(2), 0.11, True),
    ]
    assert view["passages"][0]["tokens"] == 20
    assert view["passages"][0]["excerpt"] == text.canonical_text


def test_passages_that_do_not_match_the_text_are_refused(
    imported: tuple[Path, Path, FrozenEmbedder, dict[str, PaperIdentity], _Sink],
) -> None:
    _, namespace, embedder, identities, _ = imported
    entry = _entry(namespace, 4)
    tampered = dataclasses.replace(
        entry,
        passages=(
            dataclasses.replace(entry.passages[0], text_hash="f" * 64),
            *entry.passages[1:],
        ),
    )
    for wrong_text, wrong_entry in ((_text(5), entry), (_text(4), tampered)):
        with pytest.raises(ContractValidationError):
            build_embedding_view(
                identity=identities[_version(4)],
                text=wrong_text,
                entry=wrong_entry,
                tokenizer=_Words(),
                representation_hash=embedder.manifest.representation_hash,
                candidates=(),
            )
