"""Operator-provisioned owner principal, persisted through storage (#139)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ContractValidationError, ProducerVersion
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict
from research_agent.storage.owners import OwnerRepository, validate_owner_payload
from research_agent.web.auth import OwnerDirectory, hash_credential

pytestmark = pytest.mark.integration

OWNER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def repository(database: Database, store: ArtifactStore) -> OwnerRepository:
    return OwnerRepository(
        database,
        store,
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )


def identity() -> CommandIdentity:
    return CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4())


def payload(
    owner_id: UUID = OWNER_ID, *, salt: str = "a" * 32, credential_hash: str = "b" * 64
) -> dict[str, str]:
    return {
        "owner_id": str(owner_id),
        "salt": salt,
        "credential_hash": credential_hash,
    }


@pytest.mark.parametrize(
    "bad",
    [
        payload(salt="short"),
        payload(credential_hash="not-a-hash"),
        {**payload(), "island": "cs"},
    ],
    ids=["salt", "hash", "extra-field"],
)
def test_provision_payload_refuses_malformed_material(bad: dict[str, str]) -> None:
    with pytest.raises(ContractValidationError):
        validate_owner_payload("provision", bad)


def test_provision_refuses_an_unknown_operation() -> None:
    with pytest.raises(ContractValidationError, match="operation"):
        validate_owner_payload("revoke", payload())


def test_provisioning_refuses_a_repeated_owner_id(
    postgres_dsn: str, artifact_root: Path
) -> None:
    owners = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    owners.execute("provision", identity=identity(), payload=payload())
    with pytest.raises(StateConflict):
        owners.execute("provision", identity=identity(), payload=payload())


def test_a_provisioned_owner_is_listed_and_authenticates_by_credential(
    postgres_dsn: str, artifact_root: Path
) -> None:
    owners = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    salt, credential_hash = hash_credential("correct horse")
    owners.execute(
        "provision",
        identity=identity(),
        payload=payload(salt=salt, credential_hash=credential_hash),
    )
    assert [row["owner_id"] for row in owners.list_principals()] == [str(OWNER_ID)]

    directory = OwnerDirectory(owners)
    principal = directory.authenticate("correct horse")
    assert principal is not None and principal.owner_id == OWNER_ID
    assert directory.authenticate("wrong credential") is None


def test_provisioning_records_no_credential_material_in_its_ledger_artifact(
    postgres_dsn: str, artifact_root: Path
) -> None:
    store = ArtifactStore(artifact_root)
    owners = repository(Database(postgres_dsn), store)
    salt, credential_hash = "c" * 32, "d" * 64
    owners.execute(
        "provision",
        identity=identity(),
        payload=payload(salt=salt, credential_hash=credential_hash),
    )
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        row = connection.execute(
            """SELECT encode(payload_hash,'hex') FROM ledger_records
               WHERE event_kind='owner_provisioned' ORDER BY sequence DESC LIMIT 1"""
        ).fetchone()
    assert row is not None
    body = store.path_for(row[0]).read_text()
    assert salt not in body
    assert credential_hash not in body


def test_an_owner_principal_cannot_be_changed_or_removed(
    postgres_dsn: str, artifact_root: Path
) -> None:
    owners = repository(Database(postgres_dsn), ArtifactStore(artifact_root))
    owners.execute("provision", identity=identity(), payload=payload())
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        with pytest.raises(psycopg.Error, match="immutable"):
            connection.execute("UPDATE owner_principals SET salt = salt")
        with pytest.raises(psycopg.Error, match="immutable"):
            connection.execute("DELETE FROM owner_principals")
