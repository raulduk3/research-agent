"""``provision-launch-roles``: the launch database's runtime and migrator roles (#315).

The same owner the tests and the Linux boundary probe provision through,
``storage/roles.py#provision_storage_roles``, run once against the launch
database's freshly migrated schema from an administrative DSN held in a
secret file. Login credentials and role membership stay deployment concerns,
as that owner states.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from research_agent.platform.services.config import LaunchRefused, load_launch_config
from research_agent.storage.roles import StorageRoles, provision_storage_roles


def provision_launch_roles(
    config_path: Path, *, secrets_root: Path | None = None
) -> StorageRoles:
    """Provision the configured roles on the configured schema, in one transaction.

    Refuses a server whose PostgreSQL major version is not the launch
    profile's before changing anything.
    """

    config = load_launch_config(config_path, "roles", secrets_root=secrets_root)
    roles = StorageRoles(
        application=config.text("application_role"),
        migrator=config.text("migrator_role"),
    )
    schema = config.text("schema")
    expected_major = int(config.profile.storage.postgres_version.split(".")[0])
    with psycopg.connect(config.secret_text("database_dsn")) as connection:
        if connection.info.server_version // 10000 != expected_major:
            raise LaunchRefused("the database is not the profile's PostgreSQL version")
        with connection.transaction():
            provision_storage_roles(connection, roles, schema=schema, fresh=True)
    return roles
