"""Resolve a frozen snapshot's pinned per-paper artifacts and questions (AG-10).

A snapshot pins each paper version's card, overview, passage-index and
graph hashes exactly once, when it is frozen
(``storage.snapshots.SnapshotRepository``'s ``pin_items`` operation writes
``snapshot_items``; the sheet issued with it is recorded in
``snapshot_sheets``). Each pinned hash is a production *manifest* hash,
the same identity :class:`~research_agent.storage.verification.ArtifactVerifier`
checked before it was pinned. ``SnapshotDocuments`` is the read side those
pins exist for: it resolves a snapshot id and paper ids to the pinned
manifests, resolves each manifest to its content hash, and streams that
content through the existing artifact read path
(``storage.artifacts.ArtifactRepository``). Nothing later than the
snapshot's freeze is ever reachable here, because only pinned hashes are
resolved -- never a fresh lookup by paper id alone.

The tool service names papers by family id, so the same owner also lists a
snapshot's members, resolves a family to the one version the snapshot pins,
and reads pinned overview vectors and passage indexes by their pinned hash
(#297). A hash is read only when this snapshot pins it in that role; knowing
a hash another snapshot pinned reaches nothing here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.contracts.canonical import CanonicalJsonError, canonical_loads
from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.artifacts import ArtifactManifest, ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput

__all__ = ["DocumentPins", "SnapshotDocuments"]


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _optional_hex(value: object) -> str | None:
    return None if value is None else bytes(cast(bytes, value)).hex()


_PIN_COLUMNS = """paper_family_id, paper_version_id, card_hash,
                  overview_hash, passage_index_hash, graph_hash"""


@dataclass(frozen=True, slots=True)
class DocumentPins:
    """One paper version's pinned artifact hashes within a frozen snapshot."""

    paper_family_id: str
    paper_version_id: str
    card_hash: str
    overview_hash: str | None
    passage_index_hash: str | None
    graph_hash: str | None


class SnapshotDocuments:
    """Resolve snapshot-pinned hashes and stream their artifacts (AG-10)."""

    def __init__(self, database: Database, artifacts: ArtifactRepository) -> None:
        self._database = database
        self._artifacts = artifacts

    def paper_manifest_hash(self, snapshot_hash: str) -> str:
        """Resolve a sealed snapshot's own frozen paper manifest hash."""

        def read(connection: Connection[tuple[object, ...]]) -> str | None:
            row = connection.execute(
                """SELECT encode(paper_manifest_hash, 'hex') FROM snapshots
                   WHERE hash = decode(%s, 'hex')""",
                (snapshot_hash,),
            ).fetchone()
            return None if row is None else str(row[0])

        resolved = self._database.transaction(read)
        if resolved is None:
            raise UnavailableInput("snapshot is not sealed")
        return resolved

    def pins(
        self, snapshot_hash: str, paper_version_ids: tuple[str, ...]
    ) -> dict[str, DocumentPins]:
        """Resolve every pinned paper version among *paper_version_ids*.

        A requested id absent from this snapshot's pins is simply absent
        from the returned mapping -- never fabricated -- so callers can
        distinguish "not pinned" from a transport failure.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> dict[str, DocumentPins]:
            rows = connection.execute(
                f"""SELECT {_PIN_COLUMNS} FROM snapshot_items
                    WHERE snapshot_hash = decode(%s, 'hex')
                      AND paper_version_id = ANY(%s)""",
                (snapshot_hash, list(paper_version_ids)),
            ).fetchall()
            return {str(row[1]): _pin(row) for row in rows}

        return self._database.transaction(read)

    def members(
        self,
        snapshot_hash: str,
        *,
        after: tuple[str, str] | None = None,
        limit: int | None = None,
    ) -> tuple[DocumentPins, ...]:
        """The paper versions this snapshot pins, by family then version id.

        *after* is the ``(family, version)`` pair a previous page ended on;
        *limit* bounds the page.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[DocumentPins, ...]:
            rows = connection.execute(
                f"""SELECT {_PIN_COLUMNS} FROM snapshot_items
                    WHERE snapshot_hash = decode(%s, 'hex')
                      AND (%s::uuid IS NULL
                           OR (paper_family_id, paper_version_id) > (%s::uuid, %s::uuid))
                    ORDER BY paper_family_id, paper_version_id
                    LIMIT %s""",
                (
                    snapshot_hash,
                    None if after is None else after[0],
                    None if after is None else after[0],
                    None if after is None else after[1],
                    limit,
                ),
            ).fetchall()
            return tuple(_pin(row) for row in rows)

        return self._database.transaction(read)

    def family_pin(self, snapshot_hash: str, paper_family_id: str) -> DocumentPins:
        """The one version of *paper_family_id* this snapshot pins.

        A family the snapshot does not hold is unavailable. So is a family
        pinned under more than one version: choosing one of them here would
        be a guess, and the caller can still name a version from ``members``.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[DocumentPins, ...]:
            rows = connection.execute(
                f"""SELECT {_PIN_COLUMNS} FROM snapshot_items
                    WHERE snapshot_hash = decode(%s, 'hex')
                      AND paper_family_id = %s
                    ORDER BY paper_version_id LIMIT 2""",
                (snapshot_hash, paper_family_id),
            ).fetchall()
            return tuple(_pin(row) for row in rows)

        pins = self._database.transaction(read)
        if not pins:
            raise UnavailableInput("paper family is not pinned in this snapshot")
        if len(pins) > 1:
            raise UnavailableInput(
                "paper family is pinned under more than one version in this snapshot"
            )
        return pins[0]

    def overviews(
        self, snapshot_hash: str, overview_hashes: tuple[str, ...]
    ) -> tuple[dict[str, Any], ...]:
        """Read each pinned overview vector by its pinned hash, in requested order."""

        pinned = self._pinned_hashes(snapshot_hash, "overview_hash", overview_hashes)
        if set(overview_hashes) - pinned:
            raise UnavailableInput("overview hash is not pinned in this snapshot")
        return tuple(self._read_json(item) for item in overview_hashes)

    def passage_index_by_hash(
        self, snapshot_hash: str, passage_index_hash: str
    ) -> dict[str, Any]:
        """Read a pinned passage index by its pinned hash."""

        pinned = self._pinned_hashes(
            snapshot_hash, "passage_index_hash", (passage_index_hash,)
        )
        if passage_index_hash not in pinned:
            raise UnavailableInput("passage index hash is not pinned in this snapshot")
        return self._read_json(passage_index_hash)

    def _pinned_hashes(
        self, snapshot_hash: str, column: str, hashes: tuple[str, ...]
    ) -> set[str]:
        """Which of *hashes* this snapshot pins in *column*."""

        if column not in {"overview_hash", "passage_index_hash"}:
            raise ValueError("column is not a pinned hash column")

        def read(connection: Connection[tuple[object, ...]]) -> set[str]:
            rows = connection.execute(
                f"""SELECT DISTINCT {column} FROM snapshot_items
                    WHERE snapshot_hash = decode(%s, 'hex')
                      AND {column} = ANY(%s)""",
                (snapshot_hash, [bytes.fromhex(item) for item in hashes]),
            ).fetchall()
            return {bytes(cast(bytes, row[0])).hex() for row in rows}

        return self._database.transaction(read)

    def cards(
        self, snapshot_hash: str, paper_version_ids: tuple[str, ...]
    ) -> tuple[dict[str, Any], ...]:
        """Read each requested paper version's pinned card, in requested order."""

        resolved = self.pins(snapshot_hash, paper_version_ids)
        cards: list[dict[str, Any]] = []
        for paper_version_id in paper_version_ids:
            pin = resolved.get(paper_version_id)
            if pin is None:
                raise UnavailableInput("paper version is not pinned in this snapshot")
            cards.append(self._read_json(pin.card_hash))
        return tuple(cards)

    def graph(self, snapshot_hash: str, paper_version_id: str) -> dict[str, Any]:
        """Read the requested paper version's pinned graph data."""

        pin = self.pins(snapshot_hash, (paper_version_id,)).get(paper_version_id)
        if pin is None or pin.graph_hash is None:
            raise UnavailableInput("paper version has no pinned graph in this snapshot")
        return self._read_json(pin.graph_hash)

    def passage_index(
        self, snapshot_hash: str, paper_version_id: str
    ) -> dict[str, Any]:
        """Read the requested paper version's pinned passage index."""

        pin = self.pins(snapshot_hash, (paper_version_id,)).get(paper_version_id)
        if pin is None or pin.passage_index_hash is None:
            raise UnavailableInput(
                "paper version has no pinned passage index in this snapshot"
            )
        return self._read_json(pin.passage_index_hash)

    def sheet_hashes(self, snapshot_hash: str) -> tuple[str, ...]:
        """The hashes of every sheet issued with this snapshot, sealed order."""

        def read(connection: Connection[tuple[object, ...]]) -> tuple[str, ...]:
            rows = connection.execute(
                """SELECT sheet_hash FROM snapshot_sheets
                   WHERE snapshot_hash = decode(%s, 'hex')
                   ORDER BY sheet_hash""",
                (snapshot_hash,),
            ).fetchall()
            return tuple(bytes(cast(bytes, row[0])).hex() for row in rows)

        return self._database.transaction(read)

    def questions(self, snapshot_hash: str) -> tuple[dict[str, Any], ...]:
        """Every question on a sheet issued with this snapshot, sealed order."""

        sheet_hashes = self.sheet_hashes(snapshot_hash)
        if not sheet_hashes:
            return ()

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[dict[str, Any], ...]:
            rows = connection.execute(
                """SELECT question_id, target_definition_hash, resolver_id,
                          resolver_version, horizon
                   FROM sheet_questions
                   WHERE sheet_hash = ANY(%s)
                   ORDER BY sheet_hash, ordinal""",
                ([bytes.fromhex(item) for item in sheet_hashes],),
            ).fetchall()
            return tuple(
                {
                    "question_id": str(row[0]),
                    "target_definition_hash": bytes(cast(bytes, row[1])).hex(),
                    "resolver_id": str(row[2]),
                    "resolver_version": cast(int, row[3]),
                    "horizon": _utc(cast(datetime, row[4])),
                }
                for row in rows
            )

        return self._database.transaction(read)

    def _read_json(self, manifest_hash: str) -> dict[str, Any]:
        _manifest_metadata, manifest_stream = self._artifacts.read(manifest_hash)
        with manifest_stream:
            manifest_bytes = manifest_stream.read()
        try:
            manifest = ArtifactManifest.from_json(manifest_bytes)
        except ContractValidationError as error:
            raise UnavailableInput(
                "pinned hash is not a valid artifact manifest"
            ) from error
        _content_metadata, stream = self._artifacts.read(manifest.artifact_hash)
        with stream:
            raw = stream.read()
        try:
            value = canonical_loads(raw)
        except CanonicalJsonError as error:
            raise UnavailableInput("pinned artifact is not valid JSON") from error
        if not isinstance(value, dict):
            raise UnavailableInput("pinned artifact is not a JSON object")
        return value


def _pin(row: tuple[object, ...]) -> DocumentPins:
    return DocumentPins(
        paper_family_id=str(row[0]),
        paper_version_id=str(row[1]),
        card_hash=bytes(cast(bytes, row[2])).hex(),
        overview_hash=_optional_hex(row[3]),
        passage_index_hash=_optional_hex(row[4]),
        graph_hash=_optional_hex(row[5]),
    )
