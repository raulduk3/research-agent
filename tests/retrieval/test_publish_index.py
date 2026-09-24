"""publish_index's atomic per-paper-version publication (RD-28, Appendix C),
and a published namespace's index identity (#355)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import ContractValidationError
from research_agent.retrieval.passages import (
    NAMESPACE_MANIFEST,
    IndexEntry,
    PublishedPassage,
    namespace_identity,
    publish_index,
    publish_namespace_manifest,
)

_PLATFORM = {"device": "cpu", "device_name": "Test CPU"}


def _entry(**overrides: object) -> IndexEntry:
    values: dict[str, object] = {
        "paper_version_id": "11111111-1111-4111-8111-111111111111",
        "extraction_hash": "c" * 64,
        "chunk_policy": "passages-384-64-v1",
        "coverage": "complete",
        "coverage_reasons": (),
        "overview_vector": (0.1, 0.2, 0.3),
        "passages": (PublishedPassage(0, "e" * 64, (0.4, 0.5)),),
        "platform": _PLATFORM,
        "equivalence": None,
    }
    values.update(overrides)
    return IndexEntry(**values)  # type: ignore[arg-type]


def test_publish_index_writes_one_file_per_paper_version(tmp_path: Path) -> None:
    entry = _entry()
    result = publish_index(tmp_path, entry)

    assert result.reused is False
    assert result.path == tmp_path / f"{entry.paper_version_id}.json"
    assert result.path.exists()
    assert not list(tmp_path.glob(".tmp-*"))


def test_publish_index_reuses_an_unchanged_entry(tmp_path: Path) -> None:
    entry = _entry()
    first = publish_index(tmp_path, entry)
    written_bytes = first.path.read_bytes()

    second = publish_index(tmp_path, entry)

    assert second.reused is True
    assert second.entry_hash == first.entry_hash
    assert first.path.read_bytes() == written_bytes


def test_a_different_equivalence_report_reuses_the_published_entry(
    tmp_path: Path,
) -> None:
    """The prohibited alternative: a second import of the same vectors,
    sampled differently, refused as a replacement (#361)."""
    report = {"sample_count": 100, "min_cosine": 1.0}
    first = publish_index(tmp_path, _entry(equivalence=report))
    written_bytes = first.path.read_bytes()

    second = publish_index(
        tmp_path, _entry(equivalence={"sample_count": 1, "min_cosine": 1.0})
    )

    assert second.reused is True
    assert second.entry_hash == first.entry_hash
    assert first.path.read_bytes() == written_bytes
    with pytest.raises(ContractValidationError):
        publish_index(
            tmp_path, _entry(equivalence=report, overview_vector=(0.9, 0.9, 0.9))
        )


def test_publish_index_refuses_to_silently_replace_a_published_entry(
    tmp_path: Path,
) -> None:
    entry = _entry()
    publish_index(tmp_path, entry)
    changed = dataclasses.replace(entry, overview_vector=(0.9, 0.9, 0.9))

    with pytest.raises(ContractValidationError):
        publish_index(tmp_path, changed)


def test_publish_index_preserves_other_paper_versions_membership(
    tmp_path: Path,
) -> None:
    first = _entry()
    second = _entry(paper_version_id="22222222-2222-4222-8222-222222222222")

    publish_index(tmp_path, first)
    publish_index(tmp_path, second)

    assert (tmp_path / f"{first.paper_version_id}.json").exists()
    assert (tmp_path / f"{second.paper_version_id}.json").exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_policy": "passages-512-0-v1"},
        {"overview_vector": ()},
        {
            "passages": (
                PublishedPassage(0, "e" * 64, (0.1,)),
                PublishedPassage(0, "f" * 64, (0.2,)),
            )
        },
        {"platform": {}},
        {"index_kind": "study"},
    ],
)
def test_index_entry_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        _entry(**overrides)


# A representation manifest's record less ``qualified``, as import writes it.
REPRESENTATION: dict[str, object] = {
    "model_id": "nomic-ai/modernbert-embed-base",
    "revision": "d556a88e332558790b210f7bdbe87da2fa94a8d8",
    "checkpoint_date": "2026-09-21",
    "dtype": "float32",
    "device": "mps",
    "deterministic_algorithms": True,
    "dimension": 768,
    "pooling": "attention_masked_mean",
    "document_prefix": "search_document: ",
    "query_prefix": "search_query: ",
    "max_model_tokens": 8192,
    "tokenizer_hash": "a" * 64,
    "weight_hash": "b" * 64,
}
POLICY = "passages-384-64-v1"


def _published(namespace: Path, representation: dict[str, object], policy: str) -> str:
    identity = publish_namespace_manifest(namespace, representation, policy)
    publish_index(namespace, _entry())
    return identity


def test_namespace_identity_is_stable_across_a_republish(tmp_path: Path) -> None:
    first = _published(tmp_path / "a", REPRESENTATION, POLICY)
    again = _published(tmp_path / "a", REPRESENTATION, POLICY)
    elsewhere = _published(tmp_path / "b", REPRESENTATION, POLICY)

    assert first == again == elsewhere == namespace_identity(tmp_path / "a")
    # The manifest is not a paper version to namespace readers.
    assert [path.name for path in (tmp_path / "a").glob("*.json")] == [
        f"{_entry().paper_version_id}.json"
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("device", "cuda"),
        ("revision", "0" * 40),
        ("dtype", "float16"),
        ("pooling", "cls"),
        ("weight_hash", "f" * 64),
    ],
)
def test_namespace_identity_differs_with_its_manifest(
    tmp_path: Path, field: str, value: object
) -> None:
    base = _published(tmp_path / "a", REPRESENTATION, POLICY)
    changed = dict(REPRESENTATION)
    changed[field] = value

    assert publish_namespace_manifest(tmp_path / "b", changed, POLICY) != base
    # Another representation is never recorded over a published one.
    with pytest.raises(ContractValidationError, match="cannot be replaced"):
        publish_namespace_manifest(tmp_path / "a", changed, POLICY)
    assert namespace_identity(tmp_path / "a") == base


def test_namespace_identity_differs_with_its_chunk_policy(tmp_path: Path) -> None:
    base = publish_namespace_manifest(tmp_path / "a", REPRESENTATION, POLICY)
    other = publish_namespace_manifest(
        tmp_path / "b", REPRESENTATION, "passages-512-0-v1"
    )

    assert other != base


def test_a_namespace_without_a_complete_manifest_has_no_identity(
    tmp_path: Path,
) -> None:
    publish_index(tmp_path, _entry())
    with pytest.raises(ContractValidationError, match="no namespace manifest"):
        namespace_identity(tmp_path)

    incomplete = dict(REPRESENTATION)
    del incomplete["tokenizer_hash"]
    manifest = tmp_path / NAMESPACE_MANIFEST
    manifest.write_bytes(
        canonical_json({"chunk_policy": POLICY, "representation": incomplete})
    )
    with pytest.raises(ContractValidationError, match="representation fields"):
        namespace_identity(tmp_path)

    manifest.write_bytes(canonical_json({"representation": REPRESENTATION}))
    with pytest.raises(ContractValidationError, match="exactly chunk_policy"):
        namespace_identity(tmp_path)

    # Qualification is not part of the representation a namespace records.
    qualified = dict(REPRESENTATION)
    qualified["qualified"] = True
    with pytest.raises(ContractValidationError, match="representation fields"):
        publish_namespace_manifest(tmp_path / "q", qualified, POLICY)
