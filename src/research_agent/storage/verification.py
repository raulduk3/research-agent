"""Verification of exact immutable artifact productions and their dependencies."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_positive_int,
    validate_utc_instant,
)
from research_agent.storage.artifacts import ArtifactManifest
from research_agent.storage.errors import IntegrityFailure, UnavailableInput


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    raw_hash: str
    config_hash: str
    input_hashes: tuple[str, ...]
    kind: str


@dataclass(frozen=True, slots=True)
class PublicationCutoff:
    """Internal frozen storage watermark; never a producer's body timestamp."""

    published_at: str
    committed_ledger_sequence: int

    def __post_init__(self) -> None:
        validate_utc_instant(self.published_at)
        validate_positive_int(self.committed_ledger_sequence)

    @classmethod
    def capture(cls, connection: Connection[tuple[object, ...]]) -> "PublicationCutoff":
        # The ledger writer holds this row until commit. Locking ensures its
        # visible head cannot change during the owner's freeze transaction.
        row = connection.execute(
            "SELECT sequence, clock_timestamp() FROM ledger_head WHERE singleton FOR SHARE"
        ).fetchone()
        if row is None or cast(int, row[0]) < 1:
            raise UnavailableInput("no committed publication watermark is available")
        return cls(
            cast(datetime, row[1])
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            cast(int, row[0]),
        )


class ArtifactVerifier:
    """Resolve only producing-manifest identities and verify their complete DAG.

    Metadata is checked on every call. The exact bytes of a produced artifact
    are re-read and re-hashed once per verifier lifetime while the file's
    size, modification time and inode stay what they were when it was hashed;
    a changed or missing file is re-verified and fails closed. Artifacts are
    immutable, and a checkpoint that re-verifies a deep DAG (a selection over
    hundreds of listing pages) would otherwise re-hash gigabytes each time.
    Reads of an artifact's bytes for use still verify them (ArtifactStore.read).
    """

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store
        self._bytes_verified: dict[str, tuple[int, int, int]] = {}

    def _file_identity(self, artifact_hash: str) -> tuple[int, int, int] | None:
        try:
            stat = os.stat(self._store.path_for(artifact_hash))
        except OSError:
            return None
        return (stat.st_size, stat.st_mtime_ns, stat.st_ino)

    def _verified_length(self, artifact_hash: str) -> int:
        identity = self._file_identity(artifact_hash)
        cached = self._bytes_verified.get(artifact_hash)
        if cached is not None and identity == cached:
            return cached[0]
        with self._store.open_verified(artifact_hash) as stream:
            stream.seek(0, 2)
            length = stream.tell()
        identity = self._file_identity(artifact_hash)
        if identity is not None and identity[0] == length:
            self._bytes_verified[artifact_hash] = identity
        return length

    def verify(
        self,
        connection: Connection[tuple[object, ...]],
        identity: str,
        *,
        cutoff: PublicationCutoff | None = None,
    ) -> VerifiedArtifact:
        verified: dict[str, VerifiedArtifact] = {}
        visiting: set[str] = set()

        def visit(manifest_hash: str) -> VerifiedArtifact:
            if manifest_hash in verified:
                return verified[manifest_hash]
            if manifest_hash in visiting:
                raise IntegrityFailure("artifact production dependencies are cyclic")
            visiting.add(manifest_hash)
            row = connection.execute(
                """
                SELECT encode(p.artifact_hash,'hex'), encode(p.config_hash,'hex'),
                       encode(p.retention_policy_hash,'hex'), p.created_at,
                       encode(p.producer_image_digest,'hex'),
                       encode(p.producer_source_commit,'hex'),
                       p.producer_contract_version,
                       m.byte_length, a.byte_length, a.kind,
                       mt.artifact_hash IS NOT NULL, at.artifact_hash IS NOT NULL,
                       mr.published_at, mr.committed_ledger_sequence,
                       ar.published_at, ar.committed_ledger_sequence
                FROM artifact_productions p
                JOIN artifacts m ON m.hash=p.manifest_hash
                JOIN artifact_publication_receipts mr ON mr.artifact_hash=m.hash
                JOIN artifacts a ON a.hash=p.artifact_hash
                JOIN artifact_publication_receipts ar ON ar.artifact_hash=a.hash
                LEFT JOIN artifact_tombstones mt ON mt.artifact_hash=m.hash
                LEFT JOIN artifact_tombstones at ON at.artifact_hash=a.hash
                WHERE p.manifest_hash=decode(%s,'hex')
                """,
                (manifest_hash,),
            ).fetchone()
            if row is None or cast(bool, row[10]) or cast(bool, row[11]):
                raise UnavailableInput(
                    "artifact production is absent, unpublished or tombstoned"
                )
            if cutoff is not None:
                for time_index, sequence_index in ((12, 13), (14, 15)):
                    published_at = (
                        cast(datetime, row[time_index])
                        .astimezone(timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                    )
                    if (
                        published_at > cutoff.published_at
                        or cast(int, row[sequence_index])
                        > cutoff.committed_ledger_sequence
                    ):
                        raise UnavailableInput(
                            "artifact production is outside frozen publication cutoff"
                        )
            with self._store.open_verified(manifest_hash) as stream:
                manifest_bytes = stream.read()
            if len(manifest_bytes) != cast(int, row[7]):
                raise IntegrityFailure(
                    "production manifest length differs from metadata"
                )
            try:
                manifest = ArtifactManifest.from_json(manifest_bytes)
            except ContractValidationError as error:
                raise IntegrityFailure("production manifest is invalid") from error
            if manifest.to_canonical_json() != manifest_bytes:
                raise IntegrityFailure("production manifest is not canonical")
            edges = tuple(
                str(edge[0])
                for edge in connection.execute(
                    """
                    SELECT encode(input_hash,'hex')
                    FROM artifact_production_edges
                    WHERE manifest_hash=decode(%s,'hex') ORDER BY ordinal
                    """,
                    (manifest_hash,),
                ).fetchall()
            )
            database_values = (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                row[3],
                str(row[4]),
                str(row[5]),
                cast(int, row[6]),
            )
            if (
                manifest.artifact_hash != database_values[0]
                or manifest.config_hash != database_values[1]
                or manifest.retention_policy_hash != database_values[2]
                or manifest.created_at
                != cast(datetime, database_values[3])
                .astimezone(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                or manifest.producer_version.image_digest != database_values[4]
                or manifest.producer_version.source_commit != database_values[5]
                or manifest.producer_version.contract_version != database_values[6]
                or manifest.input_hashes != edges
            ):
                raise IntegrityFailure("production manifest disagrees with metadata")
            if self._verified_length(manifest.artifact_hash) != cast(int, row[8]):
                raise IntegrityFailure("artifact byte length differs from metadata")
            for dependency in manifest.input_hashes:
                visit(dependency)
            visiting.remove(manifest_hash)
            result = VerifiedArtifact(
                manifest.artifact_hash,
                manifest.config_hash,
                manifest.input_hashes,
                str(row[9]),
            )
            verified[manifest_hash] = result
            return result

        return visit(identity)
