"""Durable content-addressed blob storage."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import BinaryIO
from pathlib import Path

from research_agent.storage.errors import IntegrityFailure

_HASH = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class BlobInfo:
    artifact_hash: str
    byte_length: int
    path: Path
    created: bool


class ArtifactStore:
    """Write exact bytes under their SHA-256 without exposing caller paths."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def path_for(self, artifact_hash: str) -> Path:
        self._validate_hash(artifact_hash)
        return self._root / artifact_hash[:2] / artifact_hash

    def commit(
        self,
        chunks: Iterable[bytes],
        *,
        expected_hash: str,
        expected_length: int,
        maximum_length: int,
    ) -> BlobInfo:
        """Stream, checksum, fsync and atomically install one immutable blob."""

        self._validate_hash(expected_hash)
        if (
            expected_length < 0
            or maximum_length < 0
            or expected_length > maximum_length
        ):
            raise ValueError("artifact byte length exceeds its admitted bound")

        destination = self.path_for(expected_hash)
        shard = destination.parent
        shard_created = False
        try:
            shard.mkdir()
            shard_created = True
        except FileExistsError:
            pass
        if shard.resolve() != shard or shard.parent != self._root:
            raise IntegrityFailure("artifact shard escapes the configured root")
        if shard_created:
            self._fsync_directory(self._root)
        if destination.exists():
            self._verify_file(destination, expected_hash, expected_length)
            return BlobInfo(expected_hash, expected_length, destination, False)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".upload-", dir=destination.parent
        )
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        length = 0
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as output:
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise TypeError("artifact chunks must be bytes")
                    length += len(chunk)
                    if length > expected_length or length > maximum_length:
                        raise IntegrityFailure("artifact length exceeds declaration")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())

            if length != expected_length or digest.hexdigest() != expected_hash:
                raise IntegrityFailure("artifact bytes do not match declaration")

            try:
                os.link(temporary, destination)
                created = True
            except FileExistsError:
                self._verify_file(destination, expected_hash, expected_length)
                created = False
            temporary.unlink()
            self._fsync_directory(destination.parent)
            return BlobInfo(expected_hash, expected_length, destination, created)
        finally:
            temporary.unlink(missing_ok=True)

    def open_verified(self, artifact_hash: str) -> BinaryIO:
        """Return the same descriptor whose exact bytes were verified."""

        path = self.path_for(artifact_hash)
        source = self._open_file(path)
        try:
            self._verify_stream(source, artifact_hash, None)
            source.seek(0)
            return source
        except BaseException:
            source.close()
            raise

    @staticmethod
    def _validate_hash(artifact_hash: str) -> None:
        if _HASH.fullmatch(artifact_hash) is None:
            raise ValueError("artifact hash must be lowercase SHA-256 hex")

    @staticmethod
    def _verify_file(
        path: Path, expected_hash: str, expected_length: int | None
    ) -> None:
        source = ArtifactStore._open_file(path)
        try:
            ArtifactStore._verify_stream(source, expected_hash, expected_length)
        finally:
            source.close()

    @staticmethod
    def _open_file(path: Path) -> BinaryIO:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            return os.fdopen(os.open(path, flags), "rb", closefd=True)
        except (FileNotFoundError, OSError) as error:
            raise IntegrityFailure(
                "referenced artifact bytes are absent or unsafe"
            ) from error

    @staticmethod
    def _verify_stream(
        source: BinaryIO, expected_hash: str, expected_length: int | None
    ) -> None:
        digest = hashlib.sha256()
        length = 0
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            length += len(chunk)
            digest.update(chunk)
        if expected_length is not None and length != expected_length:
            raise IntegrityFailure("stored artifact length does not match metadata")
        if digest.hexdigest() != expected_hash:
            raise IntegrityFailure(
                "stored artifact checksum does not match its identity"
            )

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
