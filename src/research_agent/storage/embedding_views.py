"""The stored embedding view of each paper family (#298).

A publish path stores each view it builds as an artifact with provenance
(``models.embedding_view``) and records its manifest hash here against the
paper version. ``current`` answers the owner's read: the family's most
recently recorded view, read back from the artifact it points at. Rows are
immutable, so every view a family ever had stays addressable.
"""

from __future__ import annotations

from typing import Any, cast

from psycopg import Connection

from research_agent.contracts.canonical import CanonicalJsonError, canonical_loads
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
    validate_uuid4,
)
from research_agent.storage.artifacts import ArtifactManifest, ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput

__all__ = ["EmbeddingViewRepository"]


class EmbeddingViewRepository:
    """Records and reads the view manifest each paper version was given."""

    def __init__(self, database: Database, artifacts: ArtifactRepository) -> None:
        self._database = database
        self._artifacts = artifacts

    def record(self, view_hash: str) -> None:
        """Point the view's paper version at the published view ``view_hash``.

        The family and version are read from the stored view itself, so a
        row can never name a paper its view is not about. Recording the same
        view twice records it once.
        """

        validate_sha256(view_hash)
        view = self._read(view_hash)
        family_id = validate_uuid4(str(view.get("paper_id")))
        version_id = validate_uuid4(str(view.get("paper_version_id")))

        def insert(connection: Connection[tuple[object, ...]]) -> None:
            connection.execute(
                """INSERT INTO embedding_views(
                       paper_family_id, paper_version_id, view_hash, recorded_at)
                   VALUES(%s, %s, decode(%s,'hex'), clock_timestamp())
                   ON CONFLICT DO NOTHING""",
                (family_id, version_id, view_hash),
            )

        self._database.transaction(insert)

    def current(self, paper_family_id: str) -> dict[str, Any] | None:
        """The family's most recently recorded view, or None when it has none."""

        validate_uuid4(paper_family_id)
        row = self._database.transaction(
            lambda connection: connection.execute(
                """SELECT encode(view_hash,'hex') FROM embedding_views
                   WHERE paper_family_id=%s
                   ORDER BY recorded_at DESC, view_hash DESC LIMIT 1""",
                (paper_family_id,),
            ).fetchone()
        )
        return None if row is None else self._read(cast(str, row[0]))

    def _read(self, view_hash: str) -> dict[str, Any]:
        _, manifest_stream = self._artifacts.read(view_hash)
        with manifest_stream:
            manifest_bytes = manifest_stream.read()
        try:
            manifest = ArtifactManifest.from_json(manifest_bytes)
        except ContractValidationError as error:
            raise UnavailableInput("view hash is not an artifact manifest") from error
        _, stream = self._artifacts.read(manifest.artifact_hash)
        with stream:
            raw = stream.read()
        try:
            value = canonical_loads(raw)
        except CanonicalJsonError as error:
            raise UnavailableInput("stored view is not valid JSON") from error
        if not isinstance(value, dict):
            raise UnavailableInput("stored view is not a JSON object")
        return value
