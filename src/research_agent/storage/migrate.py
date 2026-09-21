"""Explicit forward-only schema migration runner."""

from __future__ import annotations

from importlib.resources import files
from typing import cast

from psycopg import Connection

from research_agent.storage.database import Database

SCHEMA_VERSION = 4


def migrate(database: Database) -> None:
    """Install every forward migration in order."""

    migration_root = files("research_agent.storage.migrations")
    migrations = tuple(
        migration.read_text()
        for migration in sorted(migration_root.iterdir(), key=lambda item: item.name)
        if migration.name.endswith(".sql")
    )

    def apply(connection: Connection[tuple[object, ...]]) -> None:
        for migration in migrations:
            connection.execute(migration)

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
