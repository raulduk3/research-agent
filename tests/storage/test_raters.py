"""Operator-only provisioning and storage-backed resolution of raters (PL-22)."""

from __future__ import annotations

import threading
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ContractValidationError, ProducerVersion
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import (
    StorageClient,
    StorageClientError,
)
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.raters import RaterRepository, validate_rater_payload
from test_http import Jobs, _tls_material

pytestmark = pytest.mark.integration

CS_RATER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
QUANT_PH_RATER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def repository(database: Database, store: ArtifactStore) -> RaterRepository:
    return RaterRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )


def identity() -> CommandIdentity:
    return CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4())


def payload(
    rater_id: UUID,
    island: str,
    *,
    salt: str = "a" * 32,
    credential_hash: str = "b" * 64,
) -> dict[str, str]:
    return {
        "rater_id": str(rater_id),
        "island": island,
        "salt": salt,
        "credential_hash": credential_hash,
    }


def test_provision_payload_refuses_an_unadmitted_island() -> None:
    with pytest.raises(ContractValidationError, match="island"):
        validate_rater_payload("provision", payload(CS_RATER_ID, "q_bio"))


def test_provisioning_refuses_a_second_rater_on_an_occupied_island(
    postgres_dsn: str, artifact_root: Path
) -> None:
    raters = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    raters.execute("provision", identity=identity(), payload=payload(CS_RATER_ID, "cs"))
    with pytest.raises(StateConflict):
        raters.execute("provision", identity=identity(), payload=payload(uuid4(), "cs"))


def test_provisioning_refuses_a_repeated_rater_id(
    postgres_dsn: str, artifact_root: Path
) -> None:
    raters = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    raters.execute("provision", identity=identity(), payload=payload(CS_RATER_ID, "cs"))
    with pytest.raises(StateConflict):
        raters.execute(
            "provision", identity=identity(), payload=payload(CS_RATER_ID, "quant_ph")
        )


def test_exactly_two_islands_admit_exactly_two_provisioned_principals(
    postgres_dsn: str, artifact_root: Path
) -> None:
    raters = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    raters.execute("provision", identity=identity(), payload=payload(CS_RATER_ID, "cs"))
    raters.execute(
        "provision", identity=identity(), payload=payload(QUANT_PH_RATER_ID, "quant_ph")
    )
    principals = raters.list_principals()
    assert {row["island"] for row in principals} == {"cs", "quant_ph"}
    assert {row["rater_id"] for row in principals} == {
        str(CS_RATER_ID),
        str(QUANT_PH_RATER_ID),
    }


def test_provisioning_records_no_credential_material_in_its_ledger_artifact(
    postgres_dsn: str, artifact_root: Path
) -> None:
    store = ArtifactStore(artifact_root)
    raters = repository(Database(postgres_dsn), store)
    salt, credential_hash = "c" * 32, "d" * 64
    raters.execute(
        "provision",
        identity=identity(),
        payload=payload(CS_RATER_ID, "cs", salt=salt, credential_hash=credential_hash),
    )
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        row = connection.execute(
            """SELECT encode(payload_hash,'hex') FROM ledger_records
               WHERE event_kind='rater_provisioned' ORDER BY sequence DESC LIMIT 1"""
        ).fetchone()
    assert row is not None
    body = store.path_for(row[0]).read_text()
    assert salt not in body
    assert credential_hash not in body


def test_operator_provisions_rating_app_reads_and_neither_role_may_cross(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    raters = repository(database, ArtifactStore(artifact_root))
    (
        server_context,
        _client_context,
        fingerprint,
        _wrong_context,
        wrong_fingerprint,
        _no_certificate_context,
    ) = _tls_material(tmp_path)
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {
            fingerprint: ServiceCapability(
                uuid4(), "operator", frozenset({"raters:provision"})
            ),
            wrong_fingerprint: ServiceCapability(
                uuid4(),
                "rating_app",
                frozenset({"raters:read", "raters:provision"}),
            ),
        },
        tls_context=server_context,
        authorization=StorageAuthorization(database),
        raters=raters,
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        host, port = httpd.server_address[:2]

        def storage_client(cert: str, scopes: frozenset[str]) -> StorageClient:
            return StorageClient(
                connect_host=str(host),
                port=int(port),
                server_hostname="localhost",
                ca_file=tmp_path / "ca.pem",
                client_cert_file=tmp_path / f"{cert}.pem",
                client_key_file=tmp_path / f"{cert}.key",
                scopes=scopes,
                timeout_seconds=5,
            )

        operator = storage_client("client", frozenset({"raters:provision"}))
        rating_app = storage_client(
            "wrong", frozenset({"raters:read", "raters:provision"})
        )

        operator.provision_rater(
            rater_id=CS_RATER_ID,
            island="cs",
            salt="a" * 32,
            credential_hash="b" * 64,
            command_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )

        # The rating app's certificate carries the raters:provision scope too,
        # but its role is not operator, so the server still refuses the write.
        with pytest.raises(StorageClientError, match="capability does not permit"):
            rating_app.provision_rater(
                rater_id=QUANT_PH_RATER_ID,
                island="quant_ph",
                salt="c" * 32,
                credential_hash="d" * 64,
                command_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            )

        principals = rating_app.list_raters()
        assert len(principals) == 1
        assert principals[0].island == "cs"

        with pytest.raises(PermissionError):
            operator.list_raters()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
