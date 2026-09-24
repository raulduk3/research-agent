"""Explicit forward-only schema migration runner."""

from __future__ import annotations

from importlib.resources import files
from typing import cast

from psycopg import Connection

from research_agent.storage.database import Database

SCHEMA_VERSION = 27


def migrate(database: Database) -> None:
    """Install, in order and in one transaction, every forward migration whose
    version is not yet recorded.

    A migration's version is its file name's numeric prefix; files sharing a
    prefix are one version. Applied migrations are never re-run: re-adding a
    constraint validates existing rows, so a rerun of an early migration fails
    on data a later one admits (#352).
    """

    migration_root = files("research_agent.storage.migrations")
    migrations = tuple(
        (int(migration.name.split("_", 1)[0]), migration.read_text())
        for migration in sorted(migration_root.iterdir(), key=lambda item: item.name)
        if migration.name.endswith(".sql")
    )

    def apply(connection: Connection[tuple[object, ...]]) -> None:
        applied = recorded_versions(connection)
        for version, migration in migrations:
            if version in applied:
                continue
            connection.execute(migration)
            connection.execute(
                "INSERT INTO storage_schema_versions(version) VALUES (%s)"
                " ON CONFLICT DO NOTHING",
                (version,),
            )

    database.transaction(apply)


def recorded_versions(connection: Connection[tuple[object, ...]]) -> frozenset[int]:
    """Versions recorded as installed; none before the foundation migration."""

    row = connection.execute(
        "SELECT to_regclass('storage_schema_versions') IS NOT NULL"
    ).fetchone()
    if row is None or not row[0]:
        return frozenset()
    return frozenset(
        cast(int, version)
        for (version,) in connection.execute(
            "SELECT version FROM storage_schema_versions"
        ).fetchall()
    )


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
