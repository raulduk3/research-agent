from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.storage.errors import IntegrityFailure


def test_commit_streams_exact_bytes_and_reuses_existing_blob(
    artifact_root: Path,
) -> None:
    payload = b"first\x00second"
    identity = hashlib.sha256(payload).hexdigest()
    store = ArtifactStore(artifact_root)

    first = store.commit(
        [payload[:4], payload[4:]],
        expected_hash=identity,
        expected_length=len(payload),
        maximum_length=100,
    )
    second = store.commit(
        [payload],
        expected_hash=identity,
        expected_length=len(payload),
        maximum_length=100,
    )

    assert first.created is True
    assert second.created is False
    assert first.path.read_bytes() == payload
    assert first.path == artifact_root / identity[:2] / identity


def test_corrupt_or_overlong_upload_never_becomes_visible(artifact_root: Path) -> None:
    payload = b"declared bytes"
    identity = hashlib.sha256(payload).hexdigest()
    store = ArtifactStore(artifact_root)

    with pytest.raises(IntegrityFailure):
        store.commit(
            [payload + b"!"],
            expected_hash=identity,
            expected_length=len(payload),
            maximum_length=100,
        )

    assert not store.path_for(identity).exists()
    assert list((artifact_root / identity[:2]).iterdir()) == []


def test_read_detects_bytes_changed_after_commit(artifact_root: Path) -> None:
    payload = b"immutable"
    identity = hashlib.sha256(payload).hexdigest()
    store = ArtifactStore(artifact_root)
    blob = store.commit(
        [payload],
        expected_hash=identity,
        expected_length=len(payload),
        maximum_length=100,
    )
    blob.path.write_bytes(b"tampered")

    with pytest.raises(IntegrityFailure):
        store.open_verified(identity)


def test_symlinked_shard_cannot_escape_artifact_root(
    artifact_root: Path, tmp_path: Path
) -> None:
    payload = b"escape"
    identity = hashlib.sha256(payload).hexdigest()
    outside = tmp_path / "outside"
    outside.mkdir()
    (artifact_root / identity[:2]).symlink_to(outside, target_is_directory=True)

    with pytest.raises(IntegrityFailure):
        ArtifactStore(artifact_root).commit(
            [payload],
            expected_hash=identity,
            expected_length=len(payload),
            maximum_length=100,
        )

    assert list(outside.iterdir()) == []
