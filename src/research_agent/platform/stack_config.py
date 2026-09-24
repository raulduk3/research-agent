"""Write the compose stack's configuration, secrets and certificates (#342).

`generate` turns a checked launch profile and the built image's record into
the three directories `deploy/compose.yaml` mounts and its environment file:

    OUT/certs    bin/issue-certs output, issued once
    OUT/secrets  PostgreSQL credentials, generated once and reused, and one
                 DSN file per consumer, derived from them on every run
    OUT/config   profile.json, one <service>.json per application role and
                 roles.json for provision-launch-roles, rewritten on every run
    OUT/sql      schema.sql, applied before migrate, and logins.sql, applied
                 once provision-launch-roles has created the group roles
    OUT/compose.env
    OUT/native   with --models-native: run/secrets/, the model service's
                 secret mounts as links into OUT/certs, for a host process

With ``models_native`` the model service runs on the host rather than in a
container (#350): compose.env leaves the ``models-container`` profile off
and maps ``models`` to the host gateway in its clients, and
``config/models.native.json`` names the host paths of the profile and of
the secrets root ``serve-models`` reads its mounts under.

Every DSN selects the storage schema through its ``search_path`` and every
config that names a schema names the same one, so ``migrate`` creates its
tables where the storage service and ``provision-launch-roles`` look for them.

The compose PostgreSQL superuser serves only provisioning: ``postgres_dsn``.
Storage, ingest and the owner app connect as a runtime login in the
application group, and ``migrate`` and ``check-schema`` as a migration login
in the migrator group, through ``migrator_dsn``.

Secret values are written to owner-only files and never returned or printed.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from psycopg.conninfo import make_conninfo

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.platform.builds import ImageRecord
from research_agent.platform.profile import LaunchProfile
from research_agent.platform.services.config import ROLE_SECRETS

ROOT = Path(__file__).resolve().parents[3]
STORAGE_PORT = 8443
LISTENER_PORT = 8443
CONTRACT_VERSION = 1
ARTIFACT_ROOT = "/var/lib/research-agent/artifacts"
PROFILE_MOUNT = "/run/config/profile.json"
DATABASE = "research_agent"
#: The launch profile's storage section carries no schema, so every generated
#: set uses this one.
SCHEMA = "research_agent"
#: Every generated role name starts with this prefix.
ROLE_PREFIX = "research_agent"
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,40}")
PROVIDER_KEYS = ("ZAI_API_KEY", "JEV_API_KEY")
#: The compose profile that starts the model service as a container.
MODELS_PROFILE = "models-container"
#: The model service's secret mounts and the certs/ files compose binds them to.
MODELS_SECRET_FILES = {
    "models_tls_certificate": "models-server.pem",
    "models_tls_private_key": "models-server.key",
    "models_tls_client_ca": "ca.pem",
    "models_client_certificate": "models-client.pem",
    "models_client_private_key": "models-client.key",
    "models_ca": "ca.pem",
}

_JOBS = ("jobs:claim", "jobs:renew", "jobs:checkpoint", "jobs:complete")
_ARTIFACTS = ("artifacts:publish", "artifacts:read")


@dataclass(frozen=True, slots=True)
class Service:
    """One application service: its launcher role, storage identity and mounts."""

    launcher_role: str
    capability_role: str
    scopes: tuple[str, ...]
    job_kinds: tuple[str, ...] = ()
    database: bool = False
    listener: bool = False


#: Each compose application service, keyed by its service name. Scopes are
#: the storage routes the role's code calls, as `storage/http.py` admits them.
SERVICES: dict[str, Service] = {
    "ingest": Service(
        "ingest",
        "ingest",
        (*_JOBS, *_ARTIFACTS, "paper_requests:read", "paper_requests:transition"),
        ("capture", "assess"),
        database=True,
    ),
    "reader": Service(
        "reader", "reader", (*_JOBS, *_ARTIFACTS, "assessments:read"), ("extract",)
    ),
    "models": Service(
        "models",
        "models",
        (*_JOBS, *_ARTIFACTS),
        ("embed", "fit", "calibrate", "predict"),
        listener=True,
    ),
    "tools": Service(
        "tools",
        "tools",
        (
            *_ARTIFACTS,
            "snapshots:read",
            "runs:specification",
            "runs:submit",
            "paper_requests:record",
            "trace:request",
            "trace:terminal",
        ),
        listener=True,
    ),
    "scorer": Service("scorer", "scorer", (*_JOBS, "artifacts:publish"), ("score",)),
    "orchestrator": Service(
        "orchestrator",
        "orchestrator",
        (
            *_ARTIFACTS,
            "runs:create",
            "runs:append_event",
            "runs:submit",
            "runs:void",
            "runs:worker",
            "snapshots:seal",
            "snapshots:read",
            "sheets:seal",
            "submissions:submit",
            "digests:store",
            "settlements:record",
            "resources:record",
        ),
    ),
    "app": Service(
        "rating",
        "rating_app",
        (
            "digests:read",
            "sheets:seal",
            "submissions:submit",
            "ratings:record",
            "raters:read",
        ),
        listener=True,
    ),
    "owner": Service(
        "owner",
        "owner",
        ("owner:admit", "owner:seed", "owner:retire", "owner:read"),
        database=True,
        listener=True,
    ),
}

#: The services that call the model service; its listener admits these alone.
MODEL_CLIENTS = ("ingest", "reader", "tools", "scorer", "orchestrator")


class StackConfigRefused(ValueError):
    """An input does not admit writing the stack's configuration."""


@dataclass
class Report:
    """What one run wrote; names only, never a secret value."""

    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def secret_mounts(service: str) -> dict[str, str]:
    """The secret names *service*'s launcher reads, mapped to their mount paths."""

    spec = SERVICES[service]
    names: dict[str, str] = {}
    if spec.database:
        names["database_dsn"] = f"{service}_database_dsn"
    if spec.listener:
        names["tls_certificate"] = f"{service}_tls_certificate"
        names["tls_private_key"] = f"{service}_tls_private_key"
        if service in ("models", "tools"):
            names["tls_client_ca"] = f"{service}_tls_client_ca"
    names["storage_ca"] = f"{service}_ca"
    names["storage_client_certificate"] = f"{service}_client_certificate"
    names["storage_client_private_key"] = f"{service}_client_private_key"
    return {name: f"/run/secrets/{mount}" for name, mount in names.items()}


def principal_id(capability_role: str) -> str:
    """A stable version-4 UUID per storage role, so reissued certificates keep it."""

    digest = sha256_hex(f"research-agent-principal:{capability_role}".encode())
    return str(uuid.UUID(bytes=bytes.fromhex(digest)[:16], version=4))


def role_names(prefix: str = ROLE_PREFIX) -> dict[str, str]:
    """The two group roles provision-launch-roles creates and their two logins."""

    return {
        "application": f"{prefix}_application",
        "migrator": f"{prefix}_migrator",
        "runtime": f"{prefix}_runtime",
        "migration": f"{prefix}_migration",
    }


def config_hash(values: Mapping[str, Any]) -> str:
    """The hash of a role file over everything but its own ``config_hash``."""

    return sha256_hex(
        canonical_json(
            {key: value for key, value in values.items() if key != "config_hash"}
        )
    )


def retention_policy_hash(profile: LaunchProfile) -> str:
    return sha256_hex(canonical_json(profile.privacy.to_dict()))


def generate(
    profile_path: Path,
    output: Path,
    *,
    images_path: Path,
    ingress_digest: str,
    values: Mapping[str, Mapping[str, Any]] | None = None,
    environment: Mapping[str, str] | None = None,
    profile_mount: str = PROFILE_MOUNT,
    schema: str = SCHEMA,
    role_prefix: str = ROLE_PREFIX,
    models_native: bool = False,
) -> Report:
    """Write the whole stack set into *output*; a rerun keeps certs and secrets.

    *values* adds operator-held launcher values per service (the rating
    digest, the ingest day pass's manifest and index identities).
    *profile_mount* is where the launchers read the profile; tests point it
    at the written copy. *schema* is the storage schema every DSN selects
    and every config names, and *role_prefix* starts every role name; tests
    point both at disposable ones. *models_native* writes the model
    service's host launcher files and leaves its container off.
    """

    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise StackConfigRefused("the output directory is inside the repository")
    for label, name in (("schema", schema), ("role prefix", role_prefix)):
        if not _IDENTIFIER.fullmatch(name):
            raise StackConfigRefused(f"the {label} is not a plain lowercase identifier")
    try:
        profile_bytes = profile_path.read_bytes()
        profile = LaunchProfile.from_json(profile_bytes)
    except (OSError, ValueError) as error:
        raise StackConfigRefused(
            f"the launch profile fails check-profile: {error}"
        ) from error
    if not profile.host.public_hostname:
        raise StackConfigRefused("the launch profile has no host.public_hostname")
    try:
        image = ImageRecord.from_json(images_path.read_text())
    except (OSError, ValueError) as error:
        raise StackConfigRefused(f"no usable image record at {images_path}") from error
    if len(ingress_digest) != 64 or any(
        c not in "0123456789abcdef" for c in ingress_digest
    ):
        raise StackConfigRefused("the ingress digest must be a sha256 hex digest")

    report = Report()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    certs = output / "certs"
    _issue_certs(certs, report)
    fingerprints: dict[str, str] = json.loads((certs / "fingerprints.json").read_text())
    missing = sorted(set(SERVICES) - set(fingerprints))
    if missing:
        raise StackConfigRefused(
            "the issued certificates lack clients: " + ", ".join(missing)
        )
    roles = role_names(role_prefix)
    _write_secrets(output / "secrets", schema, roles, report)
    _write_sql(output, schema, roles, report)
    _provider_keys(output / "secrets", environment or {}, report)

    producer = {
        "image_digest": image.image_digest,
        "source_commit": image.source_commit,
        "contract_version": CONTRACT_VERSION,
    }
    retention = retention_policy_hash(profile)
    config = output / "config"
    config.mkdir(mode=0o700, exist_ok=True)
    _write(config / "profile.json", profile_bytes, report, output)
    profile_hash = profile.compute_hash()
    extra = values or {}
    hashes: dict[str, str] = {}
    for service, spec in SERVICES.items():
        document = _role_values(service, spec, profile, fingerprints)
        document.update(
            role=spec.launcher_role,
            profile_file=profile_mount,
            profile_hash=profile_hash,
            producer=producer,
            retention_policy_hash=retention,
            secrets=secret_mounts(service),
            storage={
                "host": "storage",
                "port": STORAGE_PORT,
                "server_name": "storage",
                "scopes": list(spec.scopes),
            },
        )
        document.update(extra.get(service, {}))
        document["config_hash"] = hashes[service] = config_hash(document)
        _write(config / f"{service}.json", _json(document), report, output)
        for key in _missing_launcher_values(service, document):
            report.notes.append(
                f"{service}.json has no {key}; its launcher refuses until one is set"
            )
        if service == "models" and models_native:
            _write_models_native(output, document, report)

    storage: dict[str, Any] = {
        "database_dsn_file": "/run/secrets/storage_dsn",
        "artifact_root": ARTIFACT_ROOT,
        "schema": schema,
        "host": "0.0.0.0",
        "port": STORAGE_PORT,
        "tls": {
            "certificate_file": "/run/secrets/storage_tls_certificate",
            "private_key_file": "/run/secrets/storage_tls_private_key",
            "client_ca_file": "/run/secrets/storage_tls_client_ca",
        },
        "producer": producer,
        "retention_policy_hash": retention,
        "capabilities": {
            fingerprints[service]: {
                "principal_id": principal_id(spec.capability_role),
                "role": spec.capability_role,
                "scopes": sorted(spec.scopes),
                "job_kinds": sorted(spec.job_kinds),
                "producer_version": producer,
                "config_hash": hashes[service],
                "retention_policy_hash": retention,
            }
            for service, spec in SERVICES.items()
        },
    }
    storage.update(extra.get("storage", {}))
    storage["config_hash"] = config_hash(storage)
    _write(config / "storage.json", _json(storage), report, output)

    provisioning: dict[str, Any] = {
        "role": "roles",
        "application_role": roles["application"],
        "migrator_role": roles["migrator"],
        "schema": schema,
        "profile_file": profile_mount,
        "profile_hash": profile_hash,
        "producer": producer,
        "secrets": {"database_dsn": "/run/secrets/postgres_dsn"},
    }
    provisioning["config_hash"] = config_hash(provisioning)
    _write(config / "roles.json", _json(provisioning), report, output)

    env = {
        "RESEARCH_AGENT_IMAGE_DIGEST": image.image_digest,
        "RESEARCH_AGENT_INGRESS_DIGEST": ingress_digest,
        "RESEARCH_AGENT_PUBLIC_HOSTNAME": profile.host.public_hostname,
        "RESEARCH_AGENT_CONFIG": str(config),
        "RESEARCH_AGENT_SECRETS": str(output / "secrets"),
        "RESEARCH_AGENT_CERTS": str(certs),
        "RESEARCH_AGENT_MODELS_HOST_ALIAS": (
            "models" if models_native else "host.docker.internal"
        ),
    }
    if not models_native:
        env["COMPOSE_PROFILES"] = MODELS_PROFILE
    text = "".join(f"{key}={value}\n" for key, value in env.items())
    _write(output / "compose.env", text.encode(), report, output)
    return report


def _role_values(
    service: str, spec: Service, profile: LaunchProfile, fingerprints: Mapping[str, str]
) -> dict[str, Any]:
    document: dict[str, Any] = {}
    if spec.listener:
        document.update(host="0.0.0.0", port=LISTENER_PORT)
    if service == "models":
        document["client_fingerprints"] = sorted(
            fingerprints[client] for client in MODEL_CLIENTS
        )
    elif service == "owner":
        document.update(
            artifact_root=ARTIFACT_ROOT,
            public_hostname=profile.host.public_hostname,
            front_end_origin=profile.host.front_end_origin,
        )
    elif service == "ingest":
        document.update(state_dir="/tmp/research-agent/ingest", images={})
    return document


def _write_models_native(
    output: Path, document: Mapping[str, Any], report: Report
) -> None:
    """Write ``models.native.json`` and link its secret mounts to ``certs/``.

    The launcher checks every secret under ``/run/secrets/``; on the host
    that directory is ``OUT/native/run/secrets``, which ``secrets_root``
    names. Links keep one copy of each private key.
    """

    root = output / "native"
    mounts = root / "run" / "secrets"
    mounts.mkdir(mode=0o700, parents=True, exist_ok=True)
    for mount in sorted(Path(path).name for path in secret_mounts("models").values()):
        link = mounts / mount
        target = output / "certs" / MODELS_SECRET_FILES[mount]
        label = str(link.relative_to(output))
        if link.is_symlink() and link.readlink() == target:
            report.unchanged.append(label)
            continue
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
        report.changed.append(label)
    native = dict(document)
    native["profile_file"] = str(output / "config" / "profile.json")
    native["secrets_root"] = str(root)
    native["config_hash"] = config_hash(native)
    _write(output / "config" / "models.native.json", _json(native), report, output)


def _missing_launcher_values(service: str, document: Mapping[str, Any]) -> list[str]:
    required = {
        "app": ("digest", "public_origin"),
        "ingest": ("agent_model_manifest", "index_identities"),
    }.get(service, ())
    return [key for key in required if key not in document]


def _issue_certs(certs: Path, report: Report) -> None:
    if (certs / "fingerprints.json").exists():
        report.unchanged.append("certs")
        return
    result = subprocess.run(
        (str(ROOT / "bin" / "issue-certs"), str(certs)),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise StackConfigRefused(f"bin/issue-certs failed: {result.stderr.strip()}")
    report.changed.append("certs")


def _write_secrets(
    directory: Path, schema: str, roles: Mapping[str, str], report: Report
) -> None:
    directory.mkdir(mode=0o700, exist_ok=True)
    fixed = {"postgres_database": DATABASE, "postgres_user": DATABASE}
    for name, value in fixed.items():
        _secret(directory / name, value, report)
    for name in ("postgres_password", "runtime_password", "migration_password"):
        _secret(directory / name, secrets.token_urlsafe(32), report)
    database = _read_secret(directory, "postgres_database")

    def dsn(user: str, password: str) -> bytes:
        text = make_conninfo(
            f"postgresql://{user}:{password}@postgres:5432/{database}",
            options=f"-csearch_path={schema}",
        )
        return (text + "\n").encode()

    admin = dsn(
        _read_secret(directory, "postgres_user"),
        _read_secret(directory, "postgres_password"),
    )
    runtime = dsn(roles["runtime"], _read_secret(directory, "runtime_password"))
    migration = dsn(roles["migration"], _read_secret(directory, "migration_password"))
    derived = {
        "postgres_dsn": admin,
        "storage_dsn": runtime,
        "ingest_database_dsn": runtime,
        "owner_database_dsn": runtime,
        "migrator_dsn": migration,
    }
    for name, content in derived.items():
        _write(directory / name, content, report, directory.parent)


def _write_sql(
    output: Path, schema: str, roles: Mapping[str, str], report: Report
) -> None:
    """Write the two psql files around ``provision-launch-roles``.

    ``schema.sql`` creates the schema the migrations assume and withholds it
    from PUBLIC, which ``provision-launch-roles`` requires. ``logins.sql``
    creates the two login roles in the groups that command creates; it holds
    their passwords, so it is owner-only like a secret.
    """

    directory = output / "sql"
    directory.mkdir(mode=0o700, exist_ok=True)
    secret_dir = output / "secrets"
    owner = _read_secret(secret_dir, "postgres_user")
    if not _IDENTIFIER.fullmatch(owner):
        raise StackConfigRefused("secrets/postgres_user is not a plain identifier")
    schema_sql = (
        f"CREATE SCHEMA {schema} AUTHORIZATION {owner};\n"
        f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC;\n"
    )
    _write(directory / "schema.sql", schema_sql.encode(), report, output)
    lines = []
    for login, group in (("runtime", "application"), ("migration", "migrator")):
        password = _read_secret(secret_dir, f"{login}_password")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", password):
            raise StackConfigRefused(f"secrets/{login}_password is not URL-safe")
        lines += [
            f"CREATE ROLE {roles[login]} LOGIN INHERIT NOSUPERUSER NOCREATEDB "
            f"NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '{password}';",
            f"GRANT {roles[group]} TO {roles[login]};",
        ]
    _write(directory / "logins.sql", ("\n".join(lines) + "\n").encode(), report, output)


def _read_secret(directory: Path, name: str) -> str:
    return (directory / name).read_text().strip()


def _provider_keys(
    directory: Path, environment: Mapping[str, str], report: Report
) -> None:
    declared = set().union(*ROLE_SECRETS.values())
    for key in PROVIDER_KEYS:
        name = key.lower()
        if name not in declared:
            report.notes.append(
                f"{key}: no launcher declares a {name} secret; the run command "
                "reads it from its own environment"
            )
        elif environment.get(key):
            _secret(directory / name, environment[key], report)
        else:
            report.notes.append(f"{key} is unset; {name} was not written")


def _secret(path: Path, value: str, report: Report) -> None:
    label = f"secrets/{path.name}"
    if path.exists() and path.read_text().strip():
        report.unchanged.append(label)
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(value + "\n")
    path.chmod(0o600)
    report.changed.append(label)


def _write(path: Path, content: bytes, report: Report, output: Path) -> None:
    label = str(path.relative_to(output))
    if path.exists() and path.read_bytes() == content:
        report.unchanged.append(label)
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
    path.chmod(0o600)
    report.changed.append(label)


def _json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def commands(output: Path, *, models_native: bool = False) -> list[str]:
    """The operator lines that start the stack from what `generate` wrote.

    In order: the schema, the migration as the superuser (the migration
    login does not exist yet), the group roles, the logins, the schema check
    as the migration login, then the stack. The compose network alone
    reaches PostgreSQL, so each step runs in a container. With
    *models_native* the model service starts on the host before the stack.
    """

    compose = f"docker compose --env-file {output}/compose.env -f deploy/compose.yaml"
    psql = f"{compose} exec -T postgres psql -v ON_ERROR_STOP=1 -U {DATABASE} -d {DATABASE}"
    run = f"{compose} run --rm --no-deps"

    def with_dsn(secret: str, command: str) -> str:
        return (
            f'RESEARCH_AGENT_STORAGE_DSN="$(cat {output}/secrets/{secret})" '
            f"{run} -e RESEARCH_AGENT_STORAGE_DSN storage {command}"
        )

    return [
        f"{compose} up -d postgres",
        f"{psql} < {output}/sql/schema.sql",
        with_dsn("postgres_dsn", "migrate"),
        f"{run} -v {output}/config/roles.json:/run/config/roles.json:ro "
        f"-v {output}/config/profile.json:{PROFILE_MOUNT}:ro "
        f"-v {output}/secrets/postgres_dsn:/run/secrets/postgres_dsn:ro "
        "storage provision-launch-roles --config /run/config/roles.json",
        f"{psql} < {output}/sql/logins.sql",
        with_dsn("migrator_dsn", "check-schema"),
        *(
            [
                f"uv run --locked --project {ROOT} python -m research_agent "
                f"serve-models --config {output}/config/models.native.json &"
            ]
            if models_native
            else []
        ),
        f"{compose} up -d",
    ]


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--images", type=Path, default=ROOT / "deploy" / "images.json")
    parser.add_argument("--ingress-digest", required=True)
    parser.add_argument(
        "--values",
        type=Path,
        help="JSON object of per-service launcher values merged into each role file",
    )
    parser.add_argument(
        "--models-native",
        action="store_true",
        help="run the model service on the host, where no graphics device "
        "reaches a container",
    )
    args = parser.parse_args(argv)
    try:
        extra = json.loads(args.values.read_text()) if args.values else None
        report = generate(
            args.profile,
            args.output,
            images_path=args.images,
            ingress_digest=args.ingress_digest,
            values=extra,
            environment=os.environ,
            models_native=args.models_native,
        )
    except (StackConfigRefused, OSError, json.JSONDecodeError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    for label in report.changed:
        print(f"wrote {label}")
    for label in report.unchanged:
        print(f"kept {label}")
    for note in report.notes:
        print(f"note: {note}")
    for line in commands(args.output.resolve(), models_native=args.models_native):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
