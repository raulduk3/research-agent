import hashlib
import json
import os
import re
import shutil
import ssl
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
import yaml
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from research_agent.platform.builds import BuildManifest, ImageRecord
from research_agent.platform.compose import inventory_from_definition
from research_agent.platform.services.config import LaunchRefused, load_launch_config
from research_agent.platform.services.models import (
    secrets_root as models_secrets_root,
)
from research_agent.platform.stack_config import (
    MODELS_PROFILE,
    SCHEMA,
    SERVICES,
    StackConfigRefused,
    commands,
    config_hash,
    generate,
    role_names,
)
from research_agent.platform.storage_service import _capabilities
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate, require_schema
from research_agent.storage.roles import (
    StorageRoles,
    provision_storage_roles,
    validate_runtime_role,
)

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "compose.yaml"
INGRESS = "c" * 64
LAUNCHERS = {"ingest": "ingest", "models": "models", "app": "rating", "owner": "owner"}
DSNS = (
    "postgres_dsn",
    "storage_dsn",
    "ingest_database_dsn",
    "owner_database_dsn",
    "migrator_dsn",
)
_VARIABLE = re.compile(r"(?<!\$)\$\{([A-Z_]+)(?::\?[^}]*)?\}")


def _manifest() -> BuildManifest:
    return BuildManifest(
        source_tree_hash="a" * 64,
        python_version="3.12.12",
        tool_versions={"uv": "0.8.22", "docker": "29.8.1"},
        uv_lock_hash="b" * 64,
        base_image_digest="c" * 64,
        base_image_tag="3.12.12-slim-bookworm",
        package_hashes=("d" * 64, "e" * 64),
        model_runtime_identities={"torch": "2.14.0", "transformers": "5.17.0"},
        product_version="0.1.1-main.3+0123abcd",
        evidence_documents={"docs/evidence/source-pilot/access-rules.md": "0" * 64},
    )


def _inputs(directory: Path) -> tuple[Path, Path]:
    profile = json.loads(
        (ROOT / "docs/implementation/launch-profile.example.json").read_text()
    )
    profile["host"]["public_hostname"] = "owner.example.test"
    profile_path = directory / "profile.json"
    profile_path.write_text(json.dumps(profile))
    images = directory / "images.json"
    images.write_text(
        ImageRecord(
            image_digest="f" * 64, source_commit="1" * 40, manifest=_manifest()
        ).to_json()
    )
    return profile_path, images


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    inputs = tmp_path_factory.mktemp("inputs")
    profile, images = _inputs(inputs)
    output = tmp_path_factory.mktemp("stack") / "out"
    generate(
        profile,
        output,
        images_path=images,
        ingress_digest=INGRESS,
        profile_mount=str(output / "config" / "profile.json"),
    )
    return output, profile, images


def _environment(output: Path) -> dict[str, str]:
    lines = (output / "compose.env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def _compose(output: Path) -> dict[str, Any]:
    environment = _environment(output)
    text = _VARIABLE.sub(lambda match: environment[match.group(1)], COMPOSE.read_text())
    document = yaml.safe_load(text)
    assert isinstance(document, dict)
    return document


def _mounts(output: Path, root: Path) -> Path:
    """Copy every compose secret to where Docker mounts it, under *root*."""

    for name, secret in _compose(output)["secrets"].items():
        target = root / "run" / "secrets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(secret["file"], target)
        target.chmod(0o600)
    return root


def test_every_launcher_accepts_its_generated_configuration(
    stack: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    output, _, _ = stack
    root = _mounts(output, tmp_path)
    for service, role in LAUNCHERS.items():
        config = load_launch_config(
            output / "config" / f"{service}.json", role, secrets_root=root
        )
        assert config.producer().image_digest == "f" * 64
        if "storage_ca" in config.secrets:
            config.storage_client()
        if "tls_certificate" in config.secrets:
            config.server_tls(client_certificates="tls_client_ca" in config.secrets)


def test_compose_accepts_the_generated_environment_and_every_file_exists(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    document = _compose(output)
    inventory = inventory_from_definition(document["services"])
    assert inventory.for_role("storage") is not None
    for name, secret in document["secrets"].items():
        assert Path(secret["file"]).is_file(), name
    for service in document["services"].values():
        for volume in service.get("volumes", []):
            if (
                isinstance(volume, dict)
                and volume.get("type") == "bind"
                and "/run/config/" in volume["target"]
            ):
                assert Path(volume["source"]).is_file(), volume["source"]
    assert (
        _environment(output)["RESEARCH_AGENT_PUBLIC_HOSTNAME"] == "owner.example.test"
    )


def test_each_storage_capability_is_keyed_by_the_issued_certificate(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    storage = json.loads((output / "config" / "storage.json").read_text())
    capabilities = _capabilities(storage["capabilities"])
    for service, spec in SERVICES.items():
        der = ssl.PEM_cert_to_DER_cert(
            (output / "certs" / f"{service}-client.pem").read_text()
        )
        capability = capabilities[hashlib.sha256(der).hexdigest()]
        role_file = json.loads((output / "config" / f"{service}.json").read_text())
        assert capability.role == spec.capability_role
        assert capability.scopes == frozenset(spec.scopes)
        assert (
            capability.config_hash == role_file["config_hash"] == config_hash(role_file)
        )
        assert capability.retention_policy_hash == role_file["retention_policy_hash"]
    assert len(capabilities) == len(SERVICES)


def test_models_admits_the_model_clients_by_fingerprint(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    fingerprints = json.loads((output / "certs" / "fingerprints.json").read_text())
    models = json.loads((output / "config" / "models.json").read_text())
    assert set(models["client_fingerprints"]) <= set(fingerprints.values())
    assert fingerprints["owner"] not in models["client_fingerprints"]


def test_a_rerun_keeps_certificates_and_secrets_and_changes_nothing(
    stack: tuple[Path, Path, Path],
) -> None:
    output, profile, images = stack
    before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    report = generate(
        profile,
        output,
        images_path=images,
        ingress_digest=INGRESS,
        profile_mount=str(output / "config" / "profile.json"),
    )
    assert report.changed == []
    assert (
        "certs" in report.unchanged and "secrets/postgres_password" in report.unchanged
    )
    assert {
        path: path.read_bytes() for path in output.rglob("*") if path.is_file()
    } == before


def test_secrets_are_owner_only_and_never_reported(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    passwords = [
        (output / "secrets" / name).read_text().strip()
        for name in ("postgres_password", "runtime_password", "migration_password")
    ]
    for directory in ("secrets", "sql"):
        for path in (output / directory).iterdir():
            assert path.stat().st_mode & 0o077 == 0, path
    printed = "\n".join(commands(output))
    for password in passwords:
        assert password not in printed
        for path in (output / "config").iterdir():
            assert password not in path.read_text(), path
    assert passwords[1] in (output / "secrets" / "ingest_database_dsn").read_text()


def _dsn(output: Path, name: str) -> dict[str, Any]:
    return conninfo_to_dict((output / "secrets" / name).read_text().strip())


def test_every_dsn_and_config_names_the_same_schema(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    storage = json.loads((output / "config" / "storage.json").read_text())
    roles = json.loads((output / "config" / "roles.json").read_text())
    assert storage["schema"] == roles["schema"] == SCHEMA
    for name in DSNS:
        assert _dsn(output, name)["options"] == f"-csearch_path={SCHEMA}", name
    schema_sql = (output / "sql" / "schema.sql").read_text()
    assert schema_sql == (
        f"CREATE SCHEMA {SCHEMA} AUTHORIZATION research_agent;\n"
        f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC;\n"
    )


def test_only_provisioning_connects_as_the_superuser(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    names = role_names()
    assert _dsn(output, "postgres_dsn")["user"] == "research_agent"
    for name in ("storage_dsn", "ingest_database_dsn", "owner_database_dsn"):
        assert _dsn(output, name)["user"] == names["runtime"], name
    assert _dsn(output, "migrator_dsn")["user"] == names["migration"]
    logins = (output / "sql" / "logins.sql").read_text()
    assert f"GRANT {names['application']} TO {names['runtime']};" in logins
    assert f"GRANT {names['migrator']} TO {names['migration']};" in logins
    assert logins.count(" LOGIN INHERIT NOSUPERUSER ") == 2


def test_provision_launch_roles_accepts_the_generated_roles_file(
    stack: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    output, _, _ = stack
    target = tmp_path / "run" / "secrets" / "postgres_dsn"
    target.parent.mkdir(parents=True)
    shutil.copyfile(output / "secrets" / "postgres_dsn", target)
    target.chmod(0o600)
    config = load_launch_config(
        output / "config" / "roles.json", "roles", secrets_root=tmp_path
    )
    assert config.secret_text("database_dsn") == (
        (output / "secrets" / "postgres_dsn").read_text().strip()
    )
    assert config.text("application_role") == role_names()["application"]
    assert config.text("migrator_role") == role_names()["migrator"]
    assert config.values["config_hash"] == config_hash(config.values)


def test_printed_steps_run_schema_migrate_groups_logins_then_stack(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    lines = commands(output)
    order = [
        "up -d postgres",
        "sql/schema.sql",
        'secrets/postgres_dsn)" ',
        "provision-launch-roles",
        "sql/logins.sql",
        "check-schema",
    ]
    for line, expected in zip(lines, order, strict=False):
        assert expected in line, (expected, line)
    assert "migrate" in lines[2] and "migrator_dsn" in lines[5]
    assert lines[-1].endswith("up -d") and len(lines) == len(order) + 1


def test_the_default_stack_starts_the_model_container(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    environment = _environment(output)
    assert environment["COMPOSE_PROFILES"] == MODELS_PROFILE
    assert environment["RESEARCH_AGENT_MODELS_HOST_ALIAS"] != "models"
    assert not (output / "config" / "models.native.json").exists()
    assert not any("serve-models" in line for line in commands(output))


def test_a_native_model_service_loads_its_host_configuration(tmp_path: Path) -> None:
    profile, images = _inputs(tmp_path)
    output = tmp_path / "out"
    generate(
        profile, output, images_path=images, ingress_digest=INGRESS, models_native=True
    )
    environment = _environment(output)
    assert "COMPOSE_PROFILES" not in environment
    assert environment["RESEARCH_AGENT_MODELS_HOST_ALIAS"] == "models"
    assert "models" not in {
        name
        for name, service in _compose(output)["services"].items()
        if not service.get("profiles")
    }

    path = output / "config" / "models.native.json"
    root = models_secrets_root(path)
    assert root == output.resolve() / "native"
    config = load_launch_config(path, "models", secrets_root=root)
    assert config.profile_file == output.resolve() / "config" / "profile.json"
    config.server_tls(client_certificates=True)
    assert json.loads(path.read_text())["config_hash"] == config_hash(config.values)
    # The container configuration is untouched and names no host root.
    assert models_secrets_root(output / "config" / "models.json") is None

    lines = commands(output.resolve(), models_native=True)
    assert (
        f"serve-models --config {output.resolve()}/config/models.native.json"
        in (lines[-2])
    )
    rerun = generate(
        profile, output, images_path=images, ingress_digest=INGRESS, models_native=True
    )
    assert rerun.changed == []


def test_a_native_secrets_root_must_be_absolute(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"secrets_root": "native"}))
    with pytest.raises(LaunchRefused):
        models_secrets_root(path)


def _statements(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line]


def test_the_generated_bring_up_lands_in_the_schema_and_admits_the_logins(
    tmp_path: Path,
) -> None:
    admin = os.environ.get("RESEARCH_AGENT_TEST_DSN")
    if not admin:
        pytest.skip("Set RESEARCH_AGENT_TEST_DSN to run PostgreSQL integration tests")
    schema = "test_" + uuid4().hex[:16]
    names = role_names(schema)
    profile, images = _inputs(tmp_path)
    output = tmp_path / "out"
    # Other checks share this database, so the test reads only schemas it names.
    query = (
        "SELECT 1 FROM information_schema.tables"
        " WHERE table_schema = %s AND table_name = 'storage_schema_versions'"
    )
    with psycopg.connect(admin, autocommit=True) as connection:
        row = connection.execute("SELECT current_user").fetchone()
        assert row is not None
        # The test server's superuser stands in for the compose one.
        (output / "secrets").mkdir(mode=0o700, parents=True)
        (output / "secrets" / "postgres_user").write_text(f"{row[0]}\n")
        generate(
            profile,
            output,
            images_path=images,
            ingress_digest=INGRESS,
            schema=schema,
            role_prefix=schema,
        )
        roles = json.loads((output / "config" / "roles.json").read_text())

        def dsn(name: str) -> str:
            # The test server's address, with the generated login and search path.
            generated = _dsn(output, name)
            return make_conninfo(
                admin,
                user=generated["user"],
                password=generated["password"],
                options=generated["options"],
            )

        in_public = connection.execute(query, ("public",)).fetchone()
        assert connection.execute(query, (schema,)).fetchone() is None
        try:
            for statement in _statements(output / "sql" / "schema.sql"):
                connection.execute(statement)
            migrate(
                Database(
                    make_conninfo(
                        admin, options=_dsn(output, "postgres_dsn")["options"]
                    )
                )
            )
            # The migration lands in the named schema, not the default one.
            assert connection.execute(query, (schema,)).fetchone() is not None
            assert connection.execute(query, ("public",)).fetchone() == in_public
            versions = connection.execute(
                sql.SQL("SELECT count(*) FROM {}.storage_schema_versions").format(
                    sql.Identifier(schema)
                )
            ).fetchone()
            assert versions is not None and versions[0] > 0
            with psycopg.connect(admin) as provisioning, provisioning.transaction():
                provision_storage_roles(
                    provisioning,
                    StorageRoles(roles["application_role"], roles["migrator_role"]),
                    schema=roles["schema"],
                    fresh=True,
                )
            for statement in _statements(output / "sql" / "logins.sql"):
                connection.execute(statement)
            with psycopg.connect(dsn("storage_dsn")) as runtime:
                validate_runtime_role(runtime, schema)
            require_schema(Database(dsn("migrator_dsn")))
        finally:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
            for role in names.values():
                exists = connection.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
                ).fetchone()
                if exists:
                    connection.execute(
                        sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role))
                    )
                    connection.execute(
                        sql.SQL("DROP ROLE {}").format(sql.Identifier(role))
                    )


def test_provider_keys_no_launcher_declares_are_left_out(tmp_path: Path) -> None:
    profile, images = _inputs(tmp_path)
    output = tmp_path / "out"
    report = generate(
        profile,
        output,
        images_path=images,
        ingress_digest=INGRESS,
        environment={"ZAI_API_KEY": "not-a-real-key"},
    )
    assert not (output / "secrets" / "zai_api_key").exists()
    assert any(note.startswith("ZAI_API_KEY") for note in report.notes)
    assert all("not-a-real-key" not in note for note in report.notes)


def test_refuses_an_output_inside_the_repository(tmp_path: Path) -> None:
    profile, images = _inputs(tmp_path)
    with pytest.raises(StackConfigRefused, match="inside the repository"):
        generate(
            profile, ROOT / "stack-out", images_path=images, ingress_digest=INGRESS
        )
    assert not (ROOT / "stack-out").exists()


def test_refuses_a_missing_image_record(tmp_path: Path) -> None:
    profile, _ = _inputs(tmp_path)
    with pytest.raises(StackConfigRefused, match="image record"):
        generate(
            profile,
            tmp_path / "out",
            images_path=tmp_path / "none.json",
            ingress_digest=INGRESS,
        )
    assert not (tmp_path / "out").exists()


def test_refuses_a_profile_that_fails_check_profile(tmp_path: Path) -> None:
    profile, images = _inputs(tmp_path)
    value = json.loads(profile.read_text())
    value["unexpected"] = True
    profile.write_text(json.dumps(value))
    with pytest.raises(StackConfigRefused, match="check-profile"):
        generate(profile, tmp_path / "out", images_path=images, ingress_digest=INGRESS)
