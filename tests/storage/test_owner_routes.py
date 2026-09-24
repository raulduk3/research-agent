"""The owner routes are served only to the ``owner`` role and its scopes (#234)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from tests.storage.test_http import Jobs, _tls_material

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ContractValidationError, ProducerVersion
from research_agent.storage.actions import OwnerActions
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import (
    OwnerActionResult,
    StorageClient,
    StorageClientError,
)
from research_agent.storage.database import Database
from research_agent.storage.http import ServiceCapability, create_storage_server

pytestmark = pytest.mark.integration

OWNER_SCOPES = frozenset({"owner:admit", "owner:seed", "owner:retire", "owner:read"})
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


@contextmanager
def owner_service(
    postgres_dsn: str,
    artifact_root: Path,
    tmp_path: Path,
    *,
    owner_role: str = "owner",
    owner_scopes: frozenset[str] = OWNER_SCOPES,
) -> Iterator[Callable[..., StorageClient]]:
    """A client factory: ``owner`` is the owner certificate, ``scorer`` a scorer's."""

    database = Database(postgres_dsn)
    actions = OwnerActions(
        database,
        ArtifactStore(artifact_root),
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
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
            fingerprint: ServiceCapability(uuid4(), owner_role, owner_scopes),
            wrong_fingerprint: ServiceCapability(uuid4(), "scorer", OWNER_SCOPES),
        },
        tls_context=server_context,
        authorization=StorageAuthorization(database),
        owners=actions,
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        host, port = httpd.server_address[:2]

        def client(
            certificate: str, scopes: frozenset[str] = OWNER_SCOPES
        ) -> StorageClient:
            return StorageClient(
                connect_host=str(host),
                port=int(port),
                server_hostname="localhost",
                ca_file=tmp_path / "ca.pem",
                client_cert_file=tmp_path / f"{certificate}.pem",
                client_key_file=tmp_path / f"{certificate}.key",
                scopes=scopes,
                timeout_seconds=5,
            )

        yield client
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def retire(client: StorageClient) -> OwnerActionResult:
    return client.retire_genome(
        owner_id=uuid4(), configuration_id=uuid4(), command_id=uuid4()
    )


def test_every_owner_route_is_refused_to_a_role_other_than_owner(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    with owner_service(postgres_dsn, artifact_root, tmp_path) as connect:
        scorer = connect("wrong")
        for refused in (
            lambda: retire(scorer),
            lambda: scorer.admit_edited_genome(
                owner_id=uuid4(),
                source_configuration_id=uuid4(),
                new_configuration_id=uuid4(),
                changes={"prompt": "x"},
                lineage_id="l",
                corpus_identifiers=(),
                completed_weekly_cycles=2,
                profile_hash=None,
                command_id=uuid4(),
            ),
            lambda: scorer.seed_variant(
                owner_id=uuid4(),
                new_configuration_id=uuid4(),
                island="cs",
                lineage_id="l",
                emphasis={},
                template_configuration_id=uuid4(),
                corpus_identifiers=(),
                profile_hash="a" * 64,
                budget_funded=True,
                command_id=uuid4(),
            ),
        ):
            with pytest.raises(StorageClientError) as write:
                refused()
            assert (write.value.status_code, write.value.code) == (403, "forbidden")
        for read in (
            scorer.retrospective,
            lambda: scorer.read_genome_view(uuid4()),
            lambda: scorer.admission_history(uuid4()),
            lambda: scorer.retirement_status(uuid4()),
        ):
            with pytest.raises(StorageClientError) as refused_read:
                read()
            assert refused_read.value.status_code == 404


def test_the_owner_role_is_refused_a_route_its_certificate_has_no_scope_for(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    with owner_service(
        postgres_dsn,
        artifact_root,
        tmp_path,
        owner_scopes=frozenset({"owner:read"}),
    ) as connect:
        owner = connect("client")
        with pytest.raises(StorageClientError) as write:
            retire(owner)
        assert (write.value.status_code, write.value.code) == (403, "forbidden")
        assert owner.retrospective() == ((), ())


def test_an_inspector_holding_owner_scopes_is_still_refused(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    with owner_service(
        postgres_dsn, artifact_root, tmp_path, owner_role="inspector"
    ) as connect:
        with pytest.raises(StorageClientError) as write:
            retire(connect("client"))
        assert (write.value.status_code, write.value.code) == (403, "forbidden")
        with pytest.raises(StorageClientError) as read:
            connect("client").retrospective()
        assert read.value.status_code == 404


def test_a_client_without_the_scope_never_sends_the_request(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    with owner_service(postgres_dsn, artifact_root, tmp_path) as connect:
        read_only = connect("client", frozenset({"owner:read"}))
        with pytest.raises(PermissionError):
            retire(read_only)


def test_the_owner_role_reaches_the_owner_repository_and_a_bad_form_is_invalid(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    with owner_service(postgres_dsn, artifact_root, tmp_path) as connect:
        owner = connect("client")
        refusal = retire(owner)
        assert (refusal.accepted, refusal.reason) == (False, "not_owner")
        with pytest.raises(ContractValidationError):
            owner.seed_variant(
                owner_id=uuid4(),
                new_configuration_id=uuid4(),
                island="astro",
                lineage_id="l",
                emphasis={},
                template_configuration_id=uuid4(),
                corpus_identifiers=(),
                profile_hash="a" * 64,
                budget_funded=True,
                command_id=uuid4(),
            )
        assert owner.read_genome_view(uuid4()) is None
