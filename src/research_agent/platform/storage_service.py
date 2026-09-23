"""Configuration-backed launcher for the authenticated storage HTTP handler."""

from __future__ import annotations

import json
import ssl
from pathlib import Path
from typing import Any
from uuid import UUID

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.snapshots.documents import SnapshotDocuments
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.database import Database
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.jobs import JobRepository
from research_agent.storage.migrate import require_schema
from research_agent.storage.roles import validate_runtime_role
from research_agent.storage.trace import TraceRepository


def serve_storage(config_path: Path) -> None:
    """Start storage from references to runtime files, never embedded secrets."""
    config = _read_config(config_path)
    dsn = Path(_text(config, "database_dsn_file")).read_text().strip()
    if not dsn:
        raise ValueError("database_dsn_file is empty")
    tls = _mapping(config, "tls")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        _text(tls, "certificate_file"), _text(tls, "private_key_file")
    )
    context.load_verify_locations(_text(tls, "client_ca_file"))
    context.verify_mode = ssl.CERT_REQUIRED
    producer = _mapping(config, "producer")
    database = Database(dsn)
    require_schema(database)
    database.transaction(
        lambda connection: validate_runtime_role(connection, _text(config, "schema"))
    )
    artifact_store = ArtifactStore(Path(_text(config, "artifact_root")))
    producer_version = ProducerVersion(
        _text(producer, "image_digest"),
        _text(producer, "source_commit"),
        _integer(producer, "contract_version"),
    )
    config_hash = _text(config, "config_hash")
    retention_policy_hash = _text(config, "retention_policy_hash")
    jobs = JobRepository(
        database,
        artifact_store,
        producer=producer_version,
        config_hash=config_hash,
        retention_policy_hash=retention_policy_hash,
    )
    artifacts = ArtifactRepository(database, artifact_store)
    trace = TraceRepository(
        database,
        artifact_store,
        producer=producer_version,
        config_hash=config_hash,
        retention_policy_hash=retention_policy_hash,
    )
    server = create_storage_server(
        (_text(config, "host"), _integer(config, "port")),
        jobs,
        _capabilities(
            _mapping(config, "capabilities"),
        ),
        tls_context=context,
        authorization=StorageAuthorization(database),
        artifacts=artifacts,
        documents=SnapshotDocuments(database, artifacts),
        trace=trace,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("storage configuration is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("storage configuration must be an object")
    return value


def _capabilities(
    value: dict[str, Any],
) -> dict[str, ServiceCapability]:
    result: dict[str, ServiceCapability] = {}
    principals: set[UUID] = set()
    for fingerprint, raw in value.items():
        if not isinstance(raw, dict):
            raise ValueError("capability must be an object")
        principal = UUID(_text(raw, "principal_id"))
        if principal in principals:
            raise ValueError("capability principal_id must be unique")
        principals.add(principal)
        producer = _mapping(raw, "producer_version")
        result[fingerprint] = ServiceCapability(
            principal,
            _text(raw, "role"),
            frozenset(_strings(raw, "scopes")),
            frozenset(_strings(raw, "job_kinds")),
            ProducerVersion(
                _text(producer, "image_digest"),
                _text(producer, "source_commit"),
                _integer(producer, "contract_version"),
            ),
            _text(raw, "config_hash"),
            _text(raw, "retention_policy_hash"),
        )
    return result


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ValueError(f"{key} must be an object")
    return result


def _text(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{key} must be a nonempty string")
    return result


def _integer(value: dict[str, Any], key: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ValueError(f"{key} must be an integer")
    return result


def _strings(value: dict[str, Any], key: str) -> list[str]:
    result = value.get(key)
    if not isinstance(result, list) or not all(
        isinstance(item, str) for item in result
    ):
        raise ValueError(f"{key} must be a string list")
    return result
