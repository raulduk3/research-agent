from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research_agent.artifacts import ArtifactStore, BlobState
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


# --- a mirror on a second device makes a dropped block a repair, not a loss --


def _commit(store: ArtifactStore, payload: bytes) -> str:
    identity = hashlib.sha256(payload).hexdigest()
    store.commit(
        [payload],
        expected_hash=identity,
        expected_length=len(payload),
        maximum_length=100,
    )
    return identity


def test_commit_installs_the_same_bytes_in_the_mirror(
    artifact_root: Path, tmp_path: Path
) -> None:
    mirror = tmp_path / "mirror"
    store = ArtifactStore(artifact_root, mirror)
    payload = b"kept twice"
    identity = _commit(store, payload)

    copy = mirror / identity[:2] / identity
    assert copy.read_bytes() == payload
    assert store.path_for(identity).read_bytes() == payload
    assert [s.primary + "/" + s.mirror for s in store.verify([identity])] == ["ok/ok"]


def test_a_damaged_primary_is_read_from_the_mirror_and_rewritten(
    artifact_root: Path, tmp_path: Path
) -> None:
    """The prohibited alternative is the read failing on the primary alone,
    which is how a dropped block on the corpus volume stopped a build."""
    store = ArtifactStore(artifact_root, tmp_path / "mirror")
    payload = b"x" * 40
    identity = _commit(store, payload)
    primary = store.path_for(identity)
    primary.write_bytes(b"\x00" * 16 + payload[16:])
    assert [s.primary for s in store.verify([identity])] == ["damaged"]

    with store.open_verified(identity) as source:
        assert source.read() == payload
    assert primary.read_bytes() == payload
    assert [s.primary + "/" + s.mirror for s in store.verify([identity])] == ["ok/ok"]


def test_a_missing_primary_is_restored_from_the_mirror(
    artifact_root: Path, tmp_path: Path
) -> None:
    store = ArtifactStore(artifact_root, tmp_path / "mirror")
    payload = b"gone from one device"
    identity = _commit(store, payload)
    store.path_for(identity).unlink()

    with store.open_verified(identity) as source:
        assert source.read() == payload
    assert store.path_for(identity).read_bytes() == payload


def test_heal_refreshes_a_damaged_or_missing_mirror_from_a_good_primary(
    artifact_root: Path, tmp_path: Path
) -> None:
    mirror = tmp_path / "mirror"
    store = ArtifactStore(artifact_root, mirror)
    damaged = _commit(store, b"mirror damaged")
    missing = _commit(store, b"mirror missing")
    (mirror / damaged[:2] / damaged).write_bytes(b"garbage")
    (mirror / missing[:2] / missing).unlink()

    before = list(store.heal([damaged, missing]))
    assert [s.mirror for s in before] == ["damaged", "missing"]
    assert [s.primary + "/" + s.mirror for s in store.verify([damaged, missing])] == [
        "ok/ok",
        "ok/ok",
    ]


def test_both_copies_damaged_still_fails_closed(
    artifact_root: Path, tmp_path: Path
) -> None:
    mirror = tmp_path / "mirror"
    store = ArtifactStore(artifact_root, mirror)
    identity = _commit(store, b"twice damaged")
    store.path_for(identity).write_bytes(b"bad")
    (mirror / identity[:2] / identity).write_bytes(b"worse")

    with pytest.raises(IntegrityFailure):
        store.open_verified(identity)
    assert [s.primary + "/" + s.mirror for s in store.heal([identity])] == [
        "damaged/damaged"
    ]
    assert store.path_for(identity).read_bytes() == b"bad"


def test_verify_without_a_mirror_reports_none(artifact_root: Path) -> None:
    store = ArtifactStore(artifact_root)
    identity = _commit(store, b"single copy")
    assert list(store.verify([identity])) == [BlobState(identity, "ok", "none")]


def test_the_mirror_must_be_a_different_root(artifact_root: Path) -> None:
    with pytest.raises(ValueError):
        ArtifactStore(artifact_root, artifact_root)
