"""The migration runner applies only unrecorded versions (#352)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.migrate import SCHEMA_VERSION, migrate, require_schema
from research_agent.storage.owners import OwnerRepository

pytestmark = pytest.mark.integration


def provision_owner(database: Database, artifact_root: Path) -> None:
    """Append a ledger record of a kind the early migrations' checks reject."""

    OwnerRepository(
        database,
        ArtifactStore(artifact_root),
        producer=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    ).execute(
        "provision",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "owner_id": str(UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")),
            "salt": "a" * 32,
            "credential_hash": "b" * 64,
        },
    )


def installed(dsn: str) -> dict[int, datetime]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        rows = connection.execute(
            "SELECT version, installed_at FROM storage_schema_versions"
        ).fetchall()
    return {version: installed_at for version, installed_at in rows}


def ledger(dsn: str) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        return connection.execute(
            "SELECT sequence, event_kind, record_hash FROM ledger_records ORDER BY sequence"
        ).fetchall()


def test_a_fresh_database_receives_every_version(unmigrated_postgres_dsn: str) -> None:
    database = Database(unmigrated_postgres_dsn)
    migrate(database)
    require_schema(database)
    assert set(installed(unmigrated_postgres_dsn)) == set(range(1, SCHEMA_VERSION + 1))


def test_a_current_populated_database_survives_a_second_migrate_unchanged(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    provision_owner(database, artifact_root)
    versions, records = installed(postgres_dsn), ledger(postgres_dsn)
    assert ("owner_provisioned",) in [(kind,) for _, kind, _ in records]

    migrate(database)

    assert installed(postgres_dsn) == versions
    assert ledger(postgres_dsn) == records
    require_schema(database)


def test_a_database_one_version_behind_receives_exactly_the_last_migration(
    postgres_dsn: str, artifact_root: Path
) -> None:
    database = Database(postgres_dsn)
    provision_owner(database, artifact_root)
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute("DROP TABLE run_ending_positions")
        connection.execute(
            "DELETE FROM storage_schema_versions WHERE version = %s", (SCHEMA_VERSION,)
        )
    earlier = installed(postgres_dsn)

    migrate(database)

    after = installed(postgres_dsn)
    assert set(after) == set(earlier) | {SCHEMA_VERSION}
    assert {v: after[v] for v in earlier} == earlier
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        row = connection.execute(
            "SELECT to_regclass('run_ending_positions') IS NOT NULL"
        ).fetchone()
    assert row == (True,)
    require_schema(database)
