"""Explicit forward-only schema migration runner."""

from __future__ import annotations

from importlib.resources import files
from typing import cast

from psycopg import Connection

from research_agent.storage.database import Database

SCHEMA_VERSION = 1


def migrate(database: Database) -> None:
    """Install the version-one schema with a migrator connection."""

    sql = (
        files("research_agent.storage.migrations")
        .joinpath("0001_foundation.sql")
        .read_text()
    )

    def apply(connection: Connection[tuple[object, ...]]) -> None:
        connection.execute(sql)

    database.transaction(apply)


def require_schema(database: Database) -> None:
    """Refuse startup when the durable schema is absent or unsupported."""

    def read(connection: Connection[tuple[object, ...]]) -> int | None:
        row = connection.execute(
            "SELECT max(version) FROM storage_schema_versions"
        ).fetchone()
        return None if row is None else cast(int, row[0])

    version = database.transaction(read)
    if version != SCHEMA_VERSION:
        raise RuntimeError(f"unsupported storage schema version: {version!r}")
