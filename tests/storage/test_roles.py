"""Integration tests for storage database role separation."""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from research_agent.storage.roles import (
    StorageRoles,
    provision_storage_roles,
    validate_runtime_role,
)

pytestmark = pytest.mark.integration


def test_runtime_role_cannot_mutate_or_truncate_immutable_relations(
    postgres_dsn: str,
) -> None:
    roles = StorageRoles(
        application=f"storage_app_{uuid4().hex}",
        migrator=f"storage_migrator_{uuid4().hex}",
    )
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        schema = _current_schema(connection)
        try:
            with pytest.raises(RuntimeError, match="administrative privileges"):
                validate_runtime_role(connection, schema)
            provision_storage_roles(connection, roles, schema=schema, fresh=True)
            connection.execute(
                sql.SQL("GRANT {} TO CURRENT_USER").format(
                    sql.Identifier(roles.application)
                )
            )
            with connection.transaction():
                connection.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(
                        sql.Identifier(roles.application)
                    )
                )
                validate_runtime_role(connection, schema)
                # A table a migration adds without a runtime grant would pass
                # superuser tests and fail in a provisioned deployment.
                for (relation,) in connection.execute(
                    """SELECT relation.relname FROM pg_class relation
                       JOIN pg_namespace namespace
                         ON namespace.oid = relation.relnamespace
                       WHERE namespace.nspname = %s AND relation.relkind = 'r'""",
                    (schema,),
                ).fetchall():
                    assert _has(connection, str(relation), "select"), relation
                with pytest.raises(RuntimeError, match="search path"):
                    validate_runtime_role(connection, "wrong_schema")
                assert _has(connection, "ledger_records", "select")
                assert _has(connection, "ledger_records", "insert")
                assert _has(connection, "jobs", "update")
                assert not _has(connection, "storage_schema_versions", "insert")
                for table in (
                    "ledger_records",
                    "artifacts",
                    "job_checkpoints",
                    "job_outputs",
                    "snapshots",
                    "snapshot_indexes",
                    "snapshot_items",
                    "snapshot_sheets",
                    "sheets",
                    "sheet_questions",
                    "runs",
                    "run_events",
                    "run_terminal_states",
                    "run_trace_calls",
                    "run_trace_terminals",
                    "submissions",
                    "submission_evidence",
                    "ratings",
                    "rater_principals",
                ):
                    assert _has(connection, table, "select")
                    assert _has(connection, table, "insert")
                    assert not _has(connection, table, "update")
                    assert not _has(connection, table, "delete")
                    assert not _has(connection, table, "truncate")
                for statement in (
                    "UPDATE ledger_records SET event_kind = 'score_published'",
                    "DELETE FROM ledger_records",
                    "TRUNCATE ledger_records",
                    "UPDATE runs SET seed = 1",
                    "UPDATE run_terminal_states SET state = 'submitted'",
                    "UPDATE submissions SET status = 'void'",
                    "UPDATE run_trace_calls SET decision = 'refused'",
                    "DELETE FROM run_trace_terminals",
                ):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        with connection.transaction():
                            connection.execute(statement)
                for statement in (
                    "ALTER TABLE jobs ADD COLUMN denied integer",
                    "CREATE FUNCTION denied() RETURNS integer LANGUAGE sql AS 'SELECT 1'",
                ):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        with connection.transaction():
                            connection.execute(statement)
        finally:
            _drop_test_roles(connection, roles, schema)


def test_migrator_role_can_change_its_schema_but_runtime_role_is_hardened(
    postgres_dsn: str,
) -> None:
    roles = StorageRoles(
        application=f"storage_app_{uuid4().hex}",
        migrator=f"storage_migrator_{uuid4().hex}",
    )
    table = f"migration_probe_{uuid4().hex}"
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        schema = _current_schema(connection)
        try:
            provision_storage_roles(connection, roles, schema=schema, fresh=True)
            attributes = connection.execute(
                "SELECT rolcanlogin, rolsuper, rolcreaterole, rolinherit "
                "FROM pg_roles WHERE rolname = %s",
                (roles.application,),
            ).fetchone()
            assert attributes == (False, False, False, False)
            connection.execute(
                sql.SQL("GRANT {} TO CURRENT_USER").format(
                    sql.Identifier(roles.migrator)
                )
            )
            with connection.transaction():
                connection.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(roles.migrator))
                )
                connection.execute(
                    sql.SQL("CREATE TABLE {}.{} (id integer PRIMARY KEY)").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                )
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {}.jobs ADD COLUMN migrator_owned integer"
                    ).format(sql.Identifier(schema))
                )
                connection.execute(
                    sql.SQL("ALTER TABLE {}.jobs DROP COLUMN migrator_owned").format(
                        sql.Identifier(schema)
                    )
                )
                connection.execute(
                    sql.SQL("DROP TABLE {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                )
        finally:
            _drop_test_roles(connection, roles, schema)


def test_provisioning_rejects_existing_membership_and_public_table_access(
    postgres_dsn: str,
) -> None:
    membership_roles = StorageRoles(
        application=f"storage_app_{uuid4().hex}",
        migrator=f"storage_migrator_{uuid4().hex}",
    )
    public_roles = StorageRoles(
        application=f"storage_app_{uuid4().hex}",
        migrator=f"storage_migrator_{uuid4().hex}",
    )
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        schema = _current_schema(connection)
        try:
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(membership_roles.application))
            )
            connection.execute(
                sql.SQL("GRANT pg_read_all_data TO {}").format(
                    sql.Identifier(membership_roles.application)
                )
            )
            with pytest.raises(ValueError, match="inherited role membership"):
                provision_storage_roles(
                    connection, membership_roles, schema=schema, fresh=True
                )

            connection.execute(
                sql.SQL("GRANT SELECT ON TABLE {}.ledger_records TO PUBLIC").format(
                    sql.Identifier(schema)
                )
            )
            with pytest.raises(ValueError, match="grants privileges to PUBLIC"):
                provision_storage_roles(
                    connection, public_roles, schema=schema, fresh=True
                )
        finally:
            connection.execute(
                sql.SQL("REVOKE SELECT ON TABLE {}.ledger_records FROM PUBLIC").format(
                    sql.Identifier(schema)
                )
            )
            connection.execute(
                sql.SQL("REVOKE pg_read_all_data FROM {}").format(
                    sql.Identifier(membership_roles.application)
                )
            )
            _drop_test_roles(connection, membership_roles, schema)
            _drop_test_roles(connection, public_roles, schema)


def _current_schema(connection: psycopg.Connection[tuple[object, ...]]) -> str:
    row = connection.execute("SELECT current_schema()").fetchone()
    assert row is not None
    return str(row[0])


def _has(
    connection: psycopg.Connection[tuple[object, ...]], table: str, privilege: str
) -> bool:
    row = connection.execute(
        "SELECT has_table_privilege(current_user, %s, %s)", (table, privilege)
    ).fetchone()
    assert row is not None
    return bool(row[0])


def _drop_test_roles(
    connection: psycopg.Connection[tuple[object, ...]], roles: StorageRoles, schema: str
) -> None:
    namespace = sql.Identifier(schema)
    table_rows = connection.execute(
        """
        SELECT relation.relname
        FROM pg_class relation
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s AND relation.relkind = 'r'
        """,
        (schema,),
    ).fetchall()
    for row in table_rows:
        connection.execute(
            sql.SQL("ALTER TABLE {}.{} OWNER TO CURRENT_USER").format(
                namespace, sql.Identifier(str(row[0]))
            )
        )
    connection.execute(
        sql.SQL("ALTER SCHEMA {} OWNER TO CURRENT_USER").format(namespace)
    )
    functions = connection.execute(
        """SELECT p.proname FROM pg_proc p
           JOIN pg_namespace n ON n.oid=p.pronamespace
           JOIN pg_roles r ON r.oid=p.proowner
           WHERE n.nspname=%s AND r.rolname=%s AND p.pronargs=0""",
        (schema, roles.migrator),
    ).fetchall()
    for row in functions:
        connection.execute(
            sql.SQL("ALTER FUNCTION {}.{}() OWNER TO CURRENT_USER").format(
                namespace, sql.Identifier(str(row[0]))
            )
        )
    for role_name in (roles.application, roles.migrator):
        exists = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,)
        ).fetchone()
        if exists is None:
            continue
        role = sql.Identifier(role_name)
        connection.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} FROM {}").format(
                namespace, role
            )
        )
        connection.execute(
            sql.SQL(
                "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} FROM {}"
            ).format(namespace, role)
        )
        connection.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON SCHEMA {} FROM {}").format(
                namespace, role
            )
        )
        connection.execute(sql.SQL("REVOKE {} FROM CURRENT_USER").format(role))
        connection.execute(sql.SQL("DROP ROLE {}").format(role))


def test_real_migration_runner_uses_migrator_identity(postgres_dsn: str) -> None:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from research_agent.storage.database import Database
    from research_agent.storage.migrate import migrate, require_schema

    roles = StorageRoles(
        f"storage_app_{uuid4().hex}", f"storage_migrator_{uuid4().hex}"
    )
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        schema = _current_schema(connection)
        try:
            provision_storage_roles(connection, roles, schema=schema, fresh=True)
            connection.execute(
                sql.SQL("GRANT {}, {} TO CURRENT_USER").format(
                    sql.Identifier(roles.application), sql.Identifier(roles.migrator)
                )
            )
            options = conninfo_to_dict(postgres_dsn).get("options", "")
            migrator = Database(
                make_conninfo(
                    postgres_dsn, options=options + f" -crole={roles.migrator}"
                )
            )
            runtime = Database(
                make_conninfo(
                    postgres_dsn, options=options + f" -crole={roles.application}"
                )
            )
            migrate(migrator)
            require_schema(runtime)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                migrate(runtime)
        finally:
            _drop_test_roles(connection, roles, schema)
