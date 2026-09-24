"""Configuration-backed launcher for the authenticated storage HTTP handler."""

from __future__ import annotations

import json
import ssl
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.platform.anchoring import (
    AnchorSettings,
    bind_anchor,
    start_anchoring,
)
from research_agent.snapshots.documents import SnapshotDocuments
from research_agent.storage.actions import OwnerActions
from research_agent.storage.anchors import AnchorBinding, AnchorBindingRepository
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.assessments import (
    AskRepository,
    AssessmentPointerRepository,
)
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.embedding_views import EmbeddingViewRepository
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.jobs import JobRepository
from research_agent.storage.migrate import require_schema
from research_agent.storage.preference import PreferenceRepository
from research_agent.storage.queries import InspectorQueries
from research_agent.storage.raters import RaterRepository
from research_agent.storage.ratings import RatingRepository
from research_agent.storage.requests import PaperRequestRepository
from research_agent.storage.resources import ResourceRepository
from research_agent.storage.roles import validate_runtime_role
from research_agent.storage.runs import RunRepository
from research_agent.storage.settlements import SettlementRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository
from research_agent.storage.submissions import SubmissionRepository
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
    producer_version = ProducerVersion(
        _text(producer, "image_digest"),
        _text(producer, "source_commit"),
        _integer(producer, "contract_version"),
    )
    # The anchoring schedule runs only once bind-anchor has recorded a receiver.
    anchor = (
        AnchorSettings.from_config(_mapping(config, "anchor"))
        if "anchor" in config
        else None
    )
    server = build_storage_server(
        (_text(config, "host"), _integer(config, "port")),
        _capabilities(_mapping(config, "capabilities")),
        tls_context=context,
        database=database,
        artifact_store=ArtifactStore(Path(_text(config, "artifact_root"))),
        producer=producer_version,
        config_hash=_text(config, "config_hash"),
        retention_policy_hash=_text(config, "retention_policy_hash"),
    )
    anchoring = None
    try:
        if anchor is not None:
            anchoring = start_anchoring(AnchorBindingRepository(database), anchor)
        server.serve_forever()
    finally:
        if anchoring is not None:
            stop, thread = anchoring
            stop.set()
            thread.join()
        server.server_close()


def bind_storage_anchor(config_path: Path, receiver_url: str) -> AnchorBinding:
    """Verify one round trip to *receiver_url* and record it as storage's receiver.

    Reads the same configuration `serve_storage` does; its ``anchor`` section
    names the receiver's CA and the storage credential by file reference.
    """
    config = _read_config(config_path)
    dsn = Path(_text(config, "database_dsn_file")).read_text().strip()
    if not dsn:
        raise ValueError("database_dsn_file is empty")
    settings = AnchorSettings.from_config(_mapping(config, "anchor"))
    database = Database(dsn)
    require_schema(database)
    return bind_anchor(
        AnchorBindingRepository(database),
        receiver_url,
        settings.transport(receiver_url),
        profile_id=settings.profile_id,
    )


def build_storage_server(
    address: tuple[str, int],
    capabilities: dict[str, ServiceCapability],
    *,
    tls_context: ssl.SSLContext,
    database: Database,
    artifact_store: ArtifactStore,
    producer: ProducerVersion,
    config_hash: str,
    retention_policy_hash: str,
) -> ThreadingHTTPServer:
    """Construct every owner the storage server can serve, so no route of a
    built owner answers as if it did not exist."""

    settings: dict[str, Any] = {
        "producer": producer,
        "config_hash": config_hash,
        "retention_policy_hash": retention_policy_hash,
    }
    artifacts = ArtifactRepository(database, artifact_store)
    return create_storage_server(
        address,
        JobRepository(database, artifact_store, **settings),
        capabilities,
        tls_context=tls_context,
        authorization=StorageAuthorization(database),
        artifacts=artifacts,
        documents=SnapshotDocuments(database, artifacts),
        queries=InspectorQueries(database, artifact_store),
        runs=RunRepository(database, artifact_store, **settings),
        snapshots=SnapshotRepository(database, artifact_store, **settings),
        sheets=SheetRepository(database, artifact_store, **settings),
        submissions=SubmissionRepository(database, artifact_store, **settings),
        ratings=RatingRepository(database, artifact_store, **settings),
        raters=RaterRepository(database, artifact_store, **settings),
        digests=DigestRepository(database, artifact_store, **settings),
        owners=OwnerActions(database, artifact_store, **settings),
        assessments=AssessmentPointerRepository(database),
        paper_requests=PaperRequestRepository(database, artifact_store, **settings),
        preference=PreferenceRepository(database, artifact_store, **settings),
        settlements=SettlementRepository(database, artifact_store, **settings),
        trace=TraceRepository(database, artifact_store, **settings),
        resources=ResourceRepository(database, artifact_store, **settings),
        embedding_views=EmbeddingViewRepository(database, artifacts),
        asks=AskRepository(database, artifact_store, **settings),
    )


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
