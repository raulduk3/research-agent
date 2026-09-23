"""Durable content-addressed blob storage."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Iterator
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


@dataclass(frozen=True, slots=True)
class BlobState:
    """What `verify` found for one identity: `ok`, `missing` or `damaged` for
    the primary copy and for the mirror, or `none` when no mirror is kept."""

    artifact_hash: str
    primary: str
    mirror: str


class ArtifactStore:
    """Write exact bytes under their SHA-256 without exposing caller paths.

    With a `mirror` root on a second device, every blob is also installed
    there. A primary whose bytes no longer match their identity is read from
    the mirror and rewritten in place, so a dropped block on one device
    costs nothing but a verified copy; `verify` and `heal` do the same for
    the whole store on demand.
    """

    def __init__(self, root: Path, mirror: Path | None = None) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._mirror: Path | None = None
        if mirror is not None:
            self._mirror = mirror.resolve()
            if self._mirror == self._root:
                raise ValueError("artifact mirror must not be the artifact root")
            self._mirror.mkdir(parents=True, exist_ok=True)

    @property
    def mirror(self) -> Path | None:
        return self._mirror

    def path_for(self, artifact_hash: str) -> Path:
        self._validate_hash(artifact_hash)
        return self._root / artifact_hash[:2] / artifact_hash

    def mirror_path_for(self, artifact_hash: str) -> Path | None:
        self._validate_hash(artifact_hash)
        if self._mirror is None:
            return None
        return self._mirror / artifact_hash[:2] / artifact_hash

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
            self._mirror_from(destination, expected_hash, expected_length)
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
            self._mirror_from(destination, expected_hash, expected_length)
            return BlobInfo(expected_hash, expected_length, destination, created)
        finally:
            temporary.unlink(missing_ok=True)

    def verify(self, hashes: Iterable[str]) -> Iterator[BlobState]:
        """Read-only: the state of the primary and mirror copies of each identity."""
        for artifact_hash in hashes:
            self._validate_hash(artifact_hash)
            primary = self._state(self.path_for(artifact_hash), artifact_hash)
            mirror_path = self.mirror_path_for(artifact_hash)
            mirror = (
                "none"
                if mirror_path is None
                else self._state(mirror_path, artifact_hash)
            )
            yield BlobState(artifact_hash, primary, mirror)

    def heal(self, hashes: Iterable[str]) -> Iterator[BlobState]:
        """Rewrite each damaged or missing copy from the other verified copy.

        Yields the state found before healing; a copy that is still not
        `ok` afterwards had no good source and stays as it was.
        """
        for state in self.verify(hashes):
            primary = self.path_for(state.artifact_hash)
            mirror_path = self.mirror_path_for(state.artifact_hash)
            if state.primary != "ok" and state.mirror == "ok" and mirror_path:
                self._install_copy(mirror_path, primary, state.artifact_hash)
            elif state.primary == "ok" and state.mirror in {"missing", "damaged"}:
                assert mirror_path is not None
                self._install_copy(primary, mirror_path, state.artifact_hash)
            yield state

    def _state(self, path: Path, artifact_hash: str) -> str:
        if not path.exists():
            return "missing"
        try:
            self._verify_file(path, artifact_hash, None)
        except IntegrityFailure:
            return "damaged"
        return "ok"

    def _mirror_from(self, source: Path, artifact_hash: str, length: int) -> None:
        """Install the verified primary's bytes in the mirror unless present."""
        mirror_path = self.mirror_path_for(artifact_hash)
        if mirror_path is None:
            return
        if mirror_path.exists():
            try:
                self._verify_file(mirror_path, artifact_hash, length)
                return
            except IntegrityFailure:
                pass
        self._install_copy(source, mirror_path, artifact_hash)

    def _install_copy(
        self, source: Path, destination: Path, artifact_hash: str
    ) -> None:
        """Copy verified bytes into place atomically, replacing any damaged file."""
        root = self._root if destination.is_relative_to(self._root) else self._mirror
        assert root is not None
        shard = destination.parent
        shard.mkdir(exist_ok=True)
        if shard.resolve() != shard or shard.parent != root:
            raise IntegrityFailure("artifact shard escapes the configured root")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".heal-", dir=shard)
        temporary = Path(temporary_name)
        try:
            with (
                self._open_file(source) as reader,
                os.fdopen(descriptor, "wb", closefd=True) as writer,
            ):
                shutil.copyfileobj(reader, writer, 1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            self._verify_file(temporary, artifact_hash, None)
            os.replace(temporary, destination)
            self._fsync_directory(shard)
        finally:
            temporary.unlink(missing_ok=True)

    def open_verified(self, artifact_hash: str) -> BinaryIO:
        """Return the same descriptor whose exact bytes were verified.

        A primary that is absent or no longer matches its identity is
        rewritten from a verified mirror copy first, when one is kept.
        """
        path = self.path_for(artifact_hash)
        try:
            return self._open_verified(path, artifact_hash)
        except IntegrityFailure:
            mirror_path = self.mirror_path_for(artifact_hash)
            if mirror_path is None or self._state(mirror_path, artifact_hash) != "ok":
                raise
            self._install_copy(mirror_path, path, artifact_hash)
            return self._open_verified(path, artifact_hash)

    def _open_verified(self, path: Path, artifact_hash: str) -> BinaryIO:
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
