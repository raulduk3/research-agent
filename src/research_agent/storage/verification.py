"""Verification of exact immutable artifact productions and their dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.artifacts import ArtifactManifest
from research_agent.storage.errors import IntegrityFailure, UnavailableInput


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    raw_hash: str
    config_hash: str
    input_hashes: tuple[str, ...]
    kind: str


class ArtifactVerifier:
    """Resolve only producing-manifest identities and verify their complete DAG."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def verify(
        self,
        connection: Connection[tuple[object, ...]],
        identity: str,
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
                       mt.artifact_hash IS NOT NULL, at.artifact_hash IS NOT NULL
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
            with self._store.open_verified(manifest.artifact_hash) as stream:
                stream.seek(0, 2)
                if stream.tell() != cast(int, row[8]):
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
