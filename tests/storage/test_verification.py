"""The verifier walks provenance without the interpreter's stack (#373)."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

from research_agent.contracts.primitives import ProducerVersion
from research_agent.storage.artifacts import ArtifactManifest
from research_agent.storage.errors import IntegrityFailure
from research_agent.storage.verification import ArtifactVerifier

_CREATED = "2026-09-24T00:00:00.000000Z"
_PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


class _Storage:
    """Productions held in memory, answering the verifier's two queries."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.blobs: dict[str, bytes] = {}
        self.manifests: dict[str, tuple[str, tuple[str, ...]]] = {}
        self.reads: list[str] = []

    def put(self, payload: bytes, inputs: tuple[str, ...]) -> str:
        artifact = sha256(payload).hexdigest()
        self.blobs[artifact] = payload
        manifest = ArtifactManifest(
            artifact, inputs, _PRODUCER, "c" * 64, "f" * 64, _CREATED
        ).to_canonical_json()
        manifest_hash = sha256(manifest).hexdigest()
        self.blobs[manifest_hash] = manifest
        self.manifests[manifest_hash] = (artifact, inputs)
        return manifest_hash

    # --- store ---------------------------------------------------------

    def path_for(self, artifact_hash: str) -> Path:
        return self.root / artifact_hash

    def open_verified(self, artifact_hash: str) -> io.BytesIO:
        return io.BytesIO(self.blobs[artifact_hash])

    # --- connection ------------------------------------------------------

    def execute(self, query: str, params: tuple[str]) -> "_Storage._Result":
        (manifest_hash,) = params
        artifact, inputs = self.manifests[manifest_hash]
        if "artifact_production_edges" in query:
            return self._Result([(edge,) for edge in inputs])
        self.reads.append(manifest_hash)
        created = datetime(2026, 9, 24, tzinfo=timezone.utc)
        return self._Result(
            [
                (
                    artifact,
                    "c" * 64,
                    "f" * 64,
                    created,
                    _PRODUCER.image_digest,
                    _PRODUCER.source_commit,
                    _PRODUCER.contract_version,
                    len(self.blobs[manifest_hash]),
                    len(self.blobs[artifact]),
                    "manifest",
                    False,
                    False,
                    created,
                    1,
                    created,
                    1,
                )
            ]
        )

    class _Result:
        def __init__(self, rows: list[tuple[Any, ...]]) -> None:
            self._rows = rows

        def fetchone(self) -> tuple[Any, ...] | None:
            return self._rows[0] if self._rows else None

        def fetchall(self) -> list[tuple[Any, ...]]:
            return self._rows


def _verify(storage: _Storage, identity: str) -> Any:
    return ArtifactVerifier(cast(Any, storage)).verify(cast(Any, storage), identity)


def test_a_chain_of_5000_manifests_verifies_without_recursion(tmp_path: Path) -> None:
    storage = _Storage(tmp_path)
    head = storage.put(b"root", ())
    for index in range(4999):
        head = storage.put(f"link {index}".encode(), (head,))
    verified = _verify(storage, head)
    assert verified.raw_hash == sha256(b"link 4998").hexdigest()
    assert len(storage.reads) == 5000


def test_a_shared_dependency_is_read_once(tmp_path: Path) -> None:
    storage = _Storage(tmp_path)
    shared = storage.put(b"shared", ())
    left = storage.put(b"left", (shared,))
    right = storage.put(b"right", (shared,))
    top = storage.put(b"top", (left, right, shared))
    assert _verify(storage, top).input_hashes == (left, right, shared)
    assert sorted(storage.reads) == sorted([top, left, right, shared])
    # Dependencies are verified in manifest order, depth first.
    assert storage.reads == [top, left, shared, right]


def test_a_cycle_fails_closed(tmp_path: Path) -> None:
    storage = _Storage(tmp_path)
    first = storage.put(b"first", ())
    second = storage.put(b"second", (first,))
    # Rewire the first production's edge to point back at the second.
    artifact, _ = storage.manifests[first]
    manifest = ArtifactManifest(
        artifact, (second,), _PRODUCER, "c" * 64, "f" * 64, _CREATED
    ).to_canonical_json()
    storage.blobs[first] = manifest
    storage.manifests[first] = (artifact, (second,))
    with pytest.raises(IntegrityFailure, match="cyclic"):
        _verify(storage, second)
