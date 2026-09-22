"""publish_index's atomic per-paper-version publication (RD-28, Appendix C)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.retrieval.passages import (
    IndexEntry,
    PublishedPassage,
    publish_index,
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
