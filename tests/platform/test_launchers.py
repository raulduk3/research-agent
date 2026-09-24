"""The operator's role launchers start from one checked configuration (#315).

Every launcher refuses a configuration for another role, a launch profile
other than the declared one and a missing or loosely scoped secret before it
opens anything. The model service and both web apps are started in-process
on real TLS and answer ``GET /health``; the owner and rating apps read the
test database through the production storage wiring. Role provisioning runs
against the test database's migrated schema.
"""

from __future__ import annotations

import json
import socket
import ssl
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import psycopg
import pytest
import uvicorn


from tests.storage.test_http import _tls_material, request  # noqa: E402
from tests.storage.test_roles import _drop_test_roles  # noqa: E402

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.learning import EMBEDDING_DIMENSION
from research_agent.models.embedding import FrozenEmbedder, ModelBackend, TokenEncoding
from research_agent.models.manifest import (
    ADOPTED_CHECKPOINT_DATE,
    DOCUMENT_PREFIX,
    DTYPE,
    MAX_MODEL_TOKENS,
    MODEL_ID,
    POOLING,
    QUERY_PREFIX,
    REVISION,
    RepresentationManifest,
)
from research_agent.models.service import ModelService
from research_agent.platform.profile import LaunchProfile
from research_agent.platform.services.config import (
    LaunchConfig,
    LaunchRefused,
    load_launch_config,
)
from research_agent.platform.services.ingest import serve_ingest
from research_agent.platform.services.models import build_model_server
from research_agent.platform.services.roles import provision_launch_roles
from research_agent.platform.services.web import (
    build_owner_app,
    build_rating_app,
    build_web_server,
)
from research_agent.platform.storage_service import build_storage_server
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.http import ServiceCapability
from research_agent.storage.owners import OwnerRepository
from research_agent.web.auth import hash_credential
from research_agent.web.digest import fixture_store_payload

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
SETTINGS: dict[str, Any] = {
    "producer": PRODUCER,
    "config_hash": "c" * 64,
    "retention_policy_hash": "d" * 64,
}
OWNER_SCOPES = ["owner:admit", "owner:read", "owner:retire", "owner:seed"]
RATING_SCOPES = ["digests:read", "raters:read", "ratings:record"]
BATCH_ID = "f" * 64

PROFILE: dict[str, Any] = {
    "profile_version": "launch-v2",
    "runtime": {"python_version": "3.12.12", "uv_version": "0.8.22"},
    "storage": {
        "postgres_version": "17.11",
        "backup_endpoint_bound": False,
        "anchor_endpoint_bound": False,
    },
    "model": {
        "agent_model_id": "glm-5.3-flash",
        "agent_provider": "zai",
        "embedding_model_revision": REVISION,
        "agent_qualification_passed": False,
    },
    "source": {"licensed_source_ids": ["arxiv"]},
    "budget": {
        "paid_execution_enabled": False,
        "daily_cap_usd": "8.00",
        "monthly_cap_usd": "200.00",
        "funded": False,
    },
    "evaluation": {"replay_integrity_verified": False},
    "privacy": {"retention_years": 2},
    "recovery": {"backup_verified": False},
    "disabled_capabilities": {"capability_ids": []},
    "run": {
        "model_calls": 6,
        "tool_calls": 12,
        "deep_reads": 3,
        "images": 6,
        "context_tokens": 32768,
        "generation_tokens": 4096,
        "max_tokens_per_run": 64000,
        "ask_calls": 4,
        "wall_time_seconds": 300,
        "retries": 1,
        "timeout_seconds": 120,
        "spend_micros": 10000,
        "allowed_tools": [
            "ask",
            "deep_read",
            "graph",
            "neighbors",
            "query_cards",
            "submit",
        ],
    },
    "host": {
        "guest_vcpus": 4,
        "guest_memory_gib": 8,
        "public_hostname": "",
        "front_end_origin": "",
    },
}


class Layout:
    """A role's configuration file, launch profile and secret files under tmp."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.secrets_root = root / "mounts"
        self.profile_file = root / "profile.json"
        self.write_profile(PROFILE)

    def write_profile(self, profile: dict[str, Any]) -> str:
        raw = json.dumps(profile).encode()
        self.profile_file.write_bytes(raw)
        return LaunchProfile.from_json(raw).compute_hash()

    def secret(self, name: str, content: bytes | str) -> str:
        mount = f"/run/secrets/{name}"
        path = self.secrets_root / mount.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode()
        path.write_bytes(content)
        path.chmod(0o600)
        return mount

    def config(self, role: str, secrets: dict[str, str], **values: Any) -> Path:
        path = self.root / f"{role}.json"
        path.write_text(
            json.dumps(
                {
                    "role": role,
                    "profile_file": str(self.profile_file),
                    "profile_hash": LaunchProfile.from_json(
                        self.profile_file.read_bytes()
                    ).compute_hash(),
                    "secrets": secrets,
                    **values,
                }
            )
        )
        return path

    def load(self, path: Path, role: str) -> LaunchConfig:
        return load_launch_config(path, role, secrets_root=self.secrets_root)


@pytest.fixture
def tls(tmp_path: Path) -> tuple[Path, tuple[Any, ...]]:
    directory = tmp_path / "tls"
    directory.mkdir()
    return directory, _tls_material(directory)


def _tls_secrets(layout: Layout, directory: Path, *, client_ca: bool) -> dict[str, str]:
    secrets = {
        "tls_certificate": layout.secret(
            "tls_certificate", (directory / "server.pem").read_bytes()
        ),
        "tls_private_key": layout.secret(
            "tls_private_key", (directory / "server.key").read_bytes()
        ),
    }
    if client_ca:
        secrets["tls_client_ca"] = layout.secret(
            "tls_client_ca", (directory / "ca.pem").read_bytes()
        )
    return secrets


def _storage_secrets(layout: Layout, directory: Path) -> dict[str, str]:
    return {
        "storage_ca": layout.secret("storage_ca", (directory / "ca.pem").read_bytes()),
        "storage_client_certificate": layout.secret(
            "storage_client_certificate", (directory / "client.pem").read_bytes()
        ),
        "storage_client_private_key": layout.secret(
            "storage_client_private_key", (directory / "client.key").read_bytes()
        ),
    }


# --- configuration refusals ---------------------------------------------------


def _models_config(layout: Layout, directory: Path, **values: Any) -> Path:
    return layout.config(
        "models",
        _tls_secrets(layout, directory, client_ca=True),
        **{"host": "127.0.0.1", "port": 0, "client_fingerprints": [], **values},
    )


def test_a_configuration_for_another_role_is_refused(
    tmp_path: Path, tls: tuple[Path, tuple[Any, ...]]
) -> None:
    layout = Layout(tmp_path)
    path = _models_config(layout, tls[0])
    with pytest.raises(LaunchRefused, match="not declared for role 'owner'"):
        layout.load(path, "owner")


def test_a_profile_other_than_the_declared_one_is_refused(
    tmp_path: Path, tls: tuple[Path, tuple[Any, ...]]
) -> None:
    layout = Layout(tmp_path)
    path = _models_config(layout, tls[0])
    layout.write_profile({**PROFILE, "budget": {**PROFILE["budget"], "funded": True}})
    with pytest.raises(LaunchRefused, match="does not match profile_hash"):
        layout.load(path, "models")


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        ("undeclared", "undeclared secrets: tls_client_ca"),
        ("absent", "secret_reference=tls_client_ca"),
        ("empty", "secret_reference=tls_client_ca"),
        ("readable", "secret_reference=tls_client_ca"),
    ],
)
def test_a_missing_or_loose_secret_is_refused_by_name_only(
    damage: str, reason: str, tmp_path: Path, tls: tuple[Path, tuple[Any, ...]]
) -> None:
    layout = Layout(tmp_path)
    path = _models_config(layout, tls[0])
    config = json.loads(path.read_text())
    secret = layout.secrets_root / "run/secrets/tls_client_ca"
    if damage == "undeclared":
        del config["secrets"]["tls_client_ca"]
    elif damage == "absent":
        secret.unlink()
    elif damage == "empty":
        secret.write_bytes(b"")
    else:
        secret.chmod(0o644)
    path.write_text(json.dumps(config))
    with pytest.raises(LaunchRefused) as refused:
        layout.load(path, "models")
    assert str(refused.value) == reason
    assert "BEGIN CERTIFICATE" not in str(refused.value)


def test_the_entry_point_refuses_a_mismatched_configuration(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    path = layout.config("ingest", {"database_dsn": "/run/secrets/ingest_dsn"})
    result = subprocess.run(
        [sys.executable, "-m", "research_agent", "serve-owner", "--config", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 1
    assert "Launch refused: configuration is not declared for role 'owner'" in (
        result.stderr
    )
    missing = subprocess.run(
        [sys.executable, "-m", "research_agent", "serve-rating"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert missing.returncode == 2
    assert "--config is required" in missing.stderr


# --- serve-models ---------------------------------------------------------------


@contextmanager
def _threaded(server: Any) -> Iterator[None]:
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_serve_models_answers_health_to_an_admitted_caller(
    tmp_path: Path,
    tls: tuple[Path, tuple[Any, ...]],
    manifest: RepresentationManifest,
    fake_embedder_backend: ModelBackend,
) -> None:
    directory, (_server, client, fingerprint, *_rest) = tls
    layout = Layout(tmp_path)
    config = layout.load(
        _models_config(layout, directory, client_fingerprints=[fingerprint]),
        "models",
    )
    with ModelService(FrozenEmbedder(manifest, fake_embedder_backend)) as service:
        server = build_model_server(config, service)
        with _threaded(server):
            address = server.server_address[:2]
            response, body = request(
                (str(address[0]), int(address[1])), client, "GET", "/health"
            )
    assert response.status == 200
    assert json.loads(body)["data"]["revision"] == REVISION


def test_serve_models_refuses_an_embedder_the_profile_does_not_pin(
    tmp_path: Path,
    tls: tuple[Path, tuple[Any, ...]],
    manifest: RepresentationManifest,
    fake_embedder_backend: ModelBackend,
) -> None:
    layout = Layout(tmp_path)
    layout.write_profile(
        {**PROFILE, "model": {**PROFILE["model"], "embedding_model_revision": "0" * 40}}
    )
    config = layout.load(_models_config(layout, tls[0]), "models")
    with ModelService(FrozenEmbedder(manifest, fake_embedder_backend)) as service:
        with pytest.raises(LaunchRefused, match="pinned revision"):
            build_model_server(config, service)


class _UnusedBackend:
    """Health reads only the manifest; nothing here is ever embedded."""

    def encode(self, texts: Sequence[str]) -> Sequence[TokenEncoding]:
        raise AssertionError("the health route must not embed")


@pytest.fixture
def fake_embedder_backend() -> ModelBackend:
    return _UnusedBackend()


@pytest.fixture
def manifest() -> RepresentationManifest:
    return RepresentationManifest(
        model_id=MODEL_ID,
        revision=REVISION,
        checkpoint_date=ADOPTED_CHECKPOINT_DATE,
        dtype=DTYPE,
        device="cpu",
        deterministic_algorithms=True,
        dimension=EMBEDDING_DIMENSION,
        pooling=POOLING,
        document_prefix=DOCUMENT_PREFIX,
        query_prefix=QUERY_PREFIX,
        max_model_tokens=MAX_MODEL_TOKENS,
        tokenizer_hash="a" * 64,
        weight_hash="b" * 64,
        qualified=False,
    )


# --- serve-owner and serve-rating ---------------------------------------------


@contextmanager
def _storage(
    dsn: str, artifact_root: Path, server_context: ssl.SSLContext, capability: Any
) -> Iterator[tuple[str, int]]:
    server = build_storage_server(
        ("127.0.0.1", 0),
        capability,
        tls_context=server_context,
        database=Database(dsn),
        artifact_store=ArtifactStore(artifact_root),
        **SETTINGS,
    )
    with _threaded(server):
        host, port = server.server_address[:2]
        yield str(host), int(port)


def _capability(fingerprint: str, role: str, scopes: list[str]) -> Any:
    return {
        fingerprint: ServiceCapability(
            uuid4(),
            role,
            frozenset(scopes),
            frozenset(),
            PRODUCER,
            SETTINGS["config_hash"],
            SETTINGS["retention_policy_hash"],
        )
    }


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def _uvicorn(server: uvicorn.Server) -> Iterator[None]:
    thread = threading.Thread(target=server.run)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(0.05)
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=20)


def _web_health(directory: Path, port: int) -> httpx.Response:
    context = ssl.create_default_context(cafile=str(directory / "ca.pem"))
    return httpx.get(f"https://127.0.0.1:{port}/health", verify=context, timeout=10)


def _storage_values(address: tuple[str, int], scopes: list[str]) -> dict[str, Any]:
    return {
        "host": address[0],
        "port": address[1],
        "server_name": "localhost",
        "scopes": scopes,
        "timeout_seconds": 10,
    }


@pytest.mark.integration
def test_serve_owner_starts_over_https_and_reports_ready(
    postgres_dsn: str,
    artifact_root: Path,
    tmp_path: Path,
    tls: tuple[Path, tuple[Any, ...]],
) -> None:
    directory, (server_context, _client, fingerprint, *_rest) = tls
    salt, credential_hash = hash_credential("owner-credential-for-tests")
    OwnerRepository(
        Database(postgres_dsn), ArtifactStore(artifact_root), **SETTINGS
    ).execute(
        "provision",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "owner_id": str(uuid4()),
            "salt": salt,
            "credential_hash": credential_hash,
        },
    )
    layout = Layout(tmp_path)
    port = _free_port()
    with _storage(
        postgres_dsn,
        artifact_root,
        server_context,
        _capability(fingerprint, "owner", OWNER_SCOPES),
    ) as address:
        path = layout.config(
            "owner",
            {
                "database_dsn": layout.secret("database_dsn", postgres_dsn),
                **_tls_secrets(layout, directory, client_ca=False),
                **_storage_secrets(layout, directory),
            },
            host="127.0.0.1",
            port=port,
            artifact_root=str(artifact_root),
            producer={
                "image_digest": "a" * 64,
                "source_commit": "b" * 40,
                "contract_version": 1,
            },
            config_hash=SETTINGS["config_hash"],
            retention_policy_hash=SETTINGS["retention_policy_hash"],
            storage=_storage_values(address, OWNER_SCOPES),
        )
        config = layout.load(path, "owner")
        with _uvicorn(build_web_server(config, build_owner_app(config))):
            health = _web_health(directory, port)
            login = httpx.get(
                f"https://127.0.0.1:{port}/api/v1/health",
                verify=ssl.create_default_context(cafile=str(directory / "ca.pem")),
            )
    assert (health.status_code, health.json()) == (200, {"state": "ready"})
    # The monitor report stays behind an owner session.
    assert login.status_code == 401


@pytest.mark.integration
def test_serve_rating_serves_the_configured_digest_and_refuses_an_unstored_one(
    postgres_dsn: str,
    artifact_root: Path,
    tmp_path: Path,
    tls: tuple[Path, tuple[Any, ...]],
) -> None:
    directory, (server_context, _client, fingerprint, *_rest) = tls
    DigestRepository(
        Database(postgres_dsn), ArtifactStore(artifact_root), **SETTINGS
    ).execute(
        "store",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload=fixture_store_payload(batch_id=BATCH_ID, island="cs"),
    )
    layout = Layout(tmp_path)
    port = _free_port()
    with _storage(
        postgres_dsn,
        artifact_root,
        server_context,
        _capability(fingerprint, "rating_app", RATING_SCOPES),
    ) as address:
        secrets = {
            **_tls_secrets(layout, directory, client_ca=False),
            **_storage_secrets(layout, directory),
        }
        values: dict[str, Any] = {
            "host": "127.0.0.1",
            "port": port,
            "storage": _storage_values(address, RATING_SCOPES),
        }
        unstored = layout.load(
            layout.config(
                "rating",
                secrets,
                digest={"island": "cs", "batch_id": "0" * 64},
                **values,
            ),
            "rating",
        )
        with pytest.raises(LaunchRefused, match="digest is unreadable"):
            build_rating_app(unstored)
        config = layout.load(
            layout.config(
                "rating",
                secrets,
                digest={"island": "cs", "batch_id": BATCH_ID},
                **values,
            ),
            "rating",
        )
        with _uvicorn(build_web_server(config, build_rating_app(config))):
            health = _web_health(directory, port)
    assert (health.status_code, health.json()) == (200, {"state": "ready"})


# --- serve-ingest ---------------------------------------------------------------


def _ingest_config(layout: Layout) -> Path:
    return layout.config(
        "ingest",
        {"database_dsn": layout.secret("ingest_dsn", "dbname=ingest-test\n")},
        state_dir=str(layout.root / "daily"),
        agent_model_manifest="1" * 64,
        images={"storage": "2" * 64, "models": "3" * 64},
        index_identities=["4" * 64],
        since="2026-09-20",
    )


def test_serve_ingest_runs_the_day_pass_with_the_checked_profile_and_secret(
    tmp_path: Path,
) -> None:
    layout = Layout(tmp_path)
    passes: list[list[str]] = []

    def day_pass(argv: list[str]) -> int:
        passes.append(argv)
        return 0

    serve_ingest(
        _ingest_config(layout),
        once=True,
        day_pass=day_pass,
        now=lambda: datetime(2026, 9, 23, 6, tzinfo=timezone.utc),
        secrets_root=layout.secrets_root,
    )
    assert passes == [
        [
            "--state", str(tmp_path / "daily"),
            "--dsn", "dbname=ingest-test",
            "--profile", str(layout.profile_file),
            "--agent-model-manifest", "1" * 64,
            "--day", "2026-09-23",
            "--device", "cpu",
            "--image", f"models={'3' * 64}",
            "--image", f"storage={'2' * 64}",
            "--index-identity", "4" * 64,
            "--since", "2026-09-20",
        ]
    ]  # fmt: skip


def test_serve_ingest_waits_for_the_next_utc_day_and_stops_on_a_failed_pass(
    tmp_path: Path,
) -> None:
    layout = Layout(tmp_path)
    clock = iter(
        [
            datetime(2026, 9, 23, 22, tzinfo=timezone.utc),
            datetime(2026, 9, 23, 23, tzinfo=timezone.utc),
            datetime(2026, 9, 24, 0, 0, 1, tzinfo=timezone.utc),
        ]
    )
    days: list[str] = []
    slept: list[float] = []

    def day_pass(argv: list[str]) -> int:
        days.append(argv[argv.index("--day") + 1])
        return 0 if len(days) == 1 else 3

    with pytest.raises(RuntimeError, match="status 3"):
        serve_ingest(
            _ingest_config(layout),
            day_pass=day_pass,
            now=lambda: next(clock),
            sleep=slept.append,
            secrets_root=layout.secrets_root,
        )
    assert days == ["2026-09-23", "2026-09-24"]
    assert slept == [3600.0]


def test_serve_ingest_refuses_before_any_pass_on_a_profile_mismatch(
    tmp_path: Path,
) -> None:
    layout = Layout(tmp_path)
    path = _ingest_config(layout)
    layout.write_profile({**PROFILE, "privacy": {"retention_years": 3}})
    called: list[list[str]] = []

    def day_pass(argv: list[str]) -> int:
        called.append(argv)
        return 0

    with pytest.raises(LaunchRefused, match="profile_hash"):
        serve_ingest(
            path, once=True, day_pass=day_pass, secrets_root=layout.secrets_root
        )
    assert called == []


# --- provision-launch-roles -----------------------------------------------------


def _roles_config(layout: Layout, dsn: str, schema: str, suffix: str) -> Path:
    return layout.config(
        "roles",
        {"database_dsn": layout.secret("roles_dsn", dsn)},
        schema=schema,
        application_role=f"launch_app_{suffix}",
        migrator_role=f"launch_migrator_{suffix}",
    )


def _schema(dsn: str) -> str:
    with psycopg.connect(dsn) as connection:
        row = connection.execute("SELECT current_schema()").fetchone()
    assert row is not None
    return str(row[0])


@pytest.mark.integration
def test_provision_launch_roles_grants_the_runtime_role_its_tables(
    postgres_dsn: str, tmp_path: Path
) -> None:
    layout = Layout(tmp_path)
    schema = _schema(postgres_dsn)
    path = _roles_config(layout, postgres_dsn, schema, uuid4().hex)
    roles = provision_launch_roles(path, secrets_root=layout.secrets_root)
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        try:
            granted = connection.execute(
                "SELECT has_table_privilege(%s, %s, 'SELECT'),"
                " has_table_privilege(%s, %s, 'TRUNCATE')",
                (
                    roles.application,
                    f"{schema}.jobs",
                    roles.application,
                    f"{schema}.jobs",
                ),
            ).fetchone()
        finally:
            _drop_test_roles(connection, roles, schema)
    assert granted == (True, False)


@pytest.mark.integration
def test_provision_launch_roles_refuses_another_postgres_version(
    postgres_dsn: str, tmp_path: Path
) -> None:
    layout = Layout(tmp_path)
    layout.write_profile(
        {**PROFILE, "storage": {**PROFILE["storage"], "postgres_version": "16.4"}}
    )
    suffix = uuid4().hex
    path = _roles_config(layout, postgres_dsn, _schema(postgres_dsn), suffix)
    with pytest.raises(LaunchRefused, match="PostgreSQL version"):
        provision_launch_roles(path, secrets_root=layout.secrets_root)
    with psycopg.connect(postgres_dsn) as connection:
        created = connection.execute(
            "SELECT count(*) FROM pg_roles WHERE rolname = %s",
            (f"launch_app_{suffix}",),
        ).fetchone()
    assert created == (0,)
