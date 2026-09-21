from __future__ import annotations

import pytest

from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate, require_schema

pytestmark = pytest.mark.integration


def test_migration_is_repeatable_and_schema_is_supported(
    unmigrated_postgres_dsn: str,
) -> None:
    database = Database(unmigrated_postgres_dsn)
    migrate(database)
    migrate(database)
    require_schema(database)
