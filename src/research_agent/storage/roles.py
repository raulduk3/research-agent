"""Least-privilege PostgreSQL roles for the durable storage schema."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection, sql


_TABLES = (
    "storage_schema_versions",
    "artifacts",
    "artifact_edges",
    "artifact_tombstones",
    "artifact_publication_receipts",
    "artifact_productions",
    "artifact_production_edges",
    "idempotency_records",
    "ledger_records",
    "ledger_head",
    "jobs",
    "job_attempts",
    "job_checkpoints",
    "job_outputs",
    "job_productions",
    "snapshots",
    "snapshot_indexes",
    "snapshot_items",
    "snapshot_sheets",
    "sheets",
    "sheet_questions",
    "runs",
    "run_events",
    "run_submissions",
    "run_forecasts",
    "run_forecast_evidence",
    "run_nominations",
    "submissions",
    "submission_evidence",
    "ratings",
    "rater_principals",
    "digests",
    "digest_entries",
    "digest_nominations",
    "resolutions",
    "operational_findings",
    "genomes",
    "genome_parts",
    "genome_archive",
    "owner_principals",
    "genome_owner_admissions",
    "genome_retirements",
    "preference_credits",
    "preference_credit_gaps",
)
_RUNTIME_INSERT_TABLES = tuple(
    table for table in _TABLES if table != "storage_schema_versions"
)
_RUNTIME_MUTABLE_TABLES = (
    "idempotency_records",
    "ledger_head",
    "jobs",
    "job_attempts",
)


@dataclass(frozen=True, slots=True)
class StorageRoles:
    """Names for the database roles that own migration and runtime access."""

    application: str
    migrator: str

    def __post_init__(self) -> None:
        if not self.application or not self.migrator:
            raise ValueError("storage role names must not be empty")
        if self.application == self.migrator:
            raise ValueError("application and migrator roles must differ")


def provision_storage_roles(
    connection: Connection[tuple[object, ...]],
    roles: StorageRoles,
    *,
    schema: str,
    fresh: bool,
) -> None:
    """Create hardened group roles and grant only foundation-schema access.

    ``fresh`` must be true only while adopting a newly created storage schema.
    The caller must be allowed to transfer its objects to the migrator role. Role
    and schema identifiers are always composed as identifiers, never interpolated
    into SQL. Login credentials and membership are deployment concerns and remain
    outside this schema-level provisioning step.
    """

    if not schema:
        raise ValueError("storage schema name must not be empty")
    if not fresh:
        raise ValueError("storage role provisioning only adopts a fresh schema")
    _ensure_hardened_role(connection, roles.application)
    _ensure_hardened_role(connection, roles.migrator)
    _reject_public_privileges(connection, schema)

    app = sql.Identifier(roles.application)
    migrator = sql.Identifier(roles.migrator)
    namespace = sql.Identifier(schema)
    all_tables = _qualified_tables(schema, _TABLES)
    insert_tables = _qualified_tables(schema, _RUNTIME_INSERT_TABLES)
    mutable_tables = _qualified_tables(schema, _RUNTIME_MUTABLE_TABLES)

    _transfer_ownership(connection, schema, roles.migrator)
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(namespace, app))
    connection.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(all_tables, app)
    )
    connection.execute(
        sql.SQL("GRANT INSERT ON TABLE {} TO {}").format(insert_tables, app)
    )
    connection.execute(
        sql.SQL("GRANT UPDATE ON TABLE {} TO {}").format(mutable_tables, app)
    )

    connection.execute(
        sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(namespace, migrator)
    )
    connection.execute(
        sql.SQL("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} TO {}").format(
            namespace, migrator
        )
    )
    connection.execute(
        sql.SQL("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
            namespace, migrator
        )
    )


def _ensure_hardened_role(
    connection: Connection[tuple[object, ...]], role_name: str
) -> None:
    row = connection.execute(
        """
        SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit,
               rolreplication, rolbypassrls
        FROM pg_roles WHERE rolname = %s
        """,
        (role_name,),
    ).fetchone()
    role = sql.Identifier(role_name)
    if row is None:
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(role)
        )
        return
    if tuple(bool(value) for value in row) != (False,) * 7:
        raise ValueError("existing storage role is not hardened")
    membership = connection.execute(
        """
        SELECT 1 FROM pg_auth_members membership
        JOIN pg_roles member ON member.oid = membership.member
        WHERE member.rolname = %s
        """,
        (role_name,),
    ).fetchone()
    if membership is not None:
        raise ValueError("existing storage role has inherited role membership")


def _reject_public_privileges(
    connection: Connection[tuple[object, ...]], schema: str
) -> None:
    schema_public = connection.execute(
        """
        SELECT 1 FROM pg_namespace
        WHERE nspname = %s
          AND (has_schema_privilege('public', oid, 'USAGE')
               OR has_schema_privilege('public', oid, 'CREATE'))
        """,
        (schema,),
    ).fetchone()
    if schema_public is not None:
        raise ValueError("storage schema grants privileges to PUBLIC")
    table_public = connection.execute(
        """
        SELECT 1
        FROM pg_class relation
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s AND relation.relkind = 'r'
          AND has_table_privilege(
              'public', relation.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE'
          )
        """,
        (schema,),
    ).fetchone()
    if table_public is not None:
        raise ValueError("storage table grants privileges to PUBLIC")


def _transfer_ownership(
    connection: Connection[tuple[object, ...]], schema: str, migrator: str
) -> None:
    namespace = sql.Identifier(schema)
    owner = sql.Identifier(migrator)
    connection.execute(sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(namespace, owner))
    for table in _TABLES:
        connection.execute(
            sql.SQL("ALTER TABLE {}.{} OWNER TO {}").format(
                namespace, sql.Identifier(table), owner
            )
        )
    for function in (
        "reject_immutable_change",
        "protect_completed_idempotency",
        "require_completed_idempotency",
    ):
        connection.execute(
            sql.SQL("ALTER FUNCTION {}.{}() OWNER TO {}").format(
                namespace, sql.Identifier(function), owner
            )
        )


def _qualified_tables(schema: str, tables: tuple[str, ...]) -> sql.Composed:
    return sql.SQL(", ").join(sql.Identifier(schema, table) for table in tables)


def validate_runtime_role(
    connection: Connection[tuple[object, ...]], schema: str
) -> None:
    """Refuse a storage connection that can bypass immutable-data policy."""
    namespace = connection.execute("SELECT current_schema()").fetchone()
    if namespace is None or namespace[0] != schema:
        raise RuntimeError("storage schema does not match connection search path")
    row = connection.execute(
        "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname=current_user"
    ).fetchone()
    if row is None or any(bool(value) for value in row):
        raise RuntimeError("storage database role has administrative privileges")
    row = connection.execute(
        "SELECT has_schema_privilege(current_user, %s, 'CREATE')", (schema,)
    ).fetchone()
    if row is not None and bool(row[0]):
        raise RuntimeError("storage database role can create schema objects")
    for table in (
        "ledger_records",
        "artifacts",
        "artifact_edges",
        "artifact_tombstones",
        "artifact_publication_receipts",
        "artifact_productions",
        "artifact_production_edges",
        "job_checkpoints",
        "job_outputs",
        "job_productions",
    ):
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            row = connection.execute(
                "SELECT has_table_privilege(current_user, %s, %s)",
                (f"{schema}.{table}", privilege),
            ).fetchone()
            if row is not None and bool(row[0]):
                raise RuntimeError("storage database role can mutate immutable data")
    row = connection.execute(
        "SELECT has_table_privilege(current_user, %s, 'INSERT')",
        (f"{schema}.storage_schema_versions",),
    ).fetchone()
    if row is not None and bool(row[0]):
        raise RuntimeError("storage database role can forge schema versions")
