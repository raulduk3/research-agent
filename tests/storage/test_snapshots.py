from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import (
    ProducerVersion,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.snapshots import snapshot_identity
from research_agent.snapshots.compose import seal_next_snapshot
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
QUESTION = {
    "question_id": "123e4567-e89b-42d3-a456-426614174000",
    "target_definition_hash": "a" * 64,
    "resolver_id": "citation-reach-v1",
    "resolver_version": 1,
    "horizon": "2027-09-01T00:00:00.000000Z",
}
PAPER_FAMILY_ID = "123e4567-e89b-42d3-a456-426614174001"
PAPER_VERSION_ID = "123e4567-e89b-42d3-a456-426614174002"


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class Storage:
    database: Database
    store: ArtifactStore
    artifacts: ArtifactRepository
    snapshots: SnapshotRepository
    sheets: SheetRepository

    def artifact(self, payload: bytes, inputs: tuple[str, ...] = ()) -> str:
        digest = sha256_hex(payload)
        publication = self.artifacts.publish(
            [payload],
            expected_hash=digest,
            byte_length=len(payload),
            maximum_length=1024 * 1024,
            media_type="application/json",
            kind="manifest",
            input_hashes=inputs,
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            command_id=uuid4(),
        )
        return publication.manifest_hash

    def seal(self, payload: object) -> dict[str, Any]:
        response = self.snapshots.execute("seal", identity=identity(), payload=payload)
        return dict(canonical_loads(response.body)["data"])

    def pin_items(self, payload: object) -> dict[str, Any]:
        response = self.snapshots.execute(
            "pin_items", identity=identity(), payload=payload
        )
        return dict(canonical_loads(response.body)["data"])

    def seal_sheet(self, questions: list[dict[str, Any]]) -> dict[str, Any]:
        response = self.sheets.execute(
            "seal", identity=identity(), payload={"questions": questions}
        )
        return dict(canonical_loads(response.body)["data"])


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> Storage:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    return Storage(
        database,
        store,
        ArtifactRepository(database, store),
        SnapshotRepository(
            database,
            store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
        SheetRepository(
            database,
            store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
    )


def test_seal_is_content_addressed_and_idempotent(storage: Storage) -> None:
    paper_manifest = storage.artifact(b'{"papers":["p1"]}')
    index_hash = "e" * 64
    payload = {
        "paper_manifest_hash": paper_manifest,
        "index_identity_hashes": [index_hash],
    }
    first = storage.seal(payload)
    assert first["snapshot_hash"] == snapshot_identity(paper_manifest, [index_hash])
    second = storage.seal(payload)
    assert second["snapshot_hash"] == first["snapshot_hash"]
    assert second["sealed_at"] == first["sealed_at"]
    with storage.database.connect() as connection:
        count = connection.execute("SELECT count(*) FROM snapshots").fetchone()
        assert count is not None and count[0] == 1


def test_seal_rejects_an_unpublished_paper_manifest(storage: Storage) -> None:
    with pytest.raises(UnavailableInput):
        storage.seal(
            {"paper_manifest_hash": "f" * 64, "index_identity_hashes": ["a" * 64]}
        )


def test_a_later_snapshot_does_not_alter_an_earlier_ones_pinned_manifest(
    storage: Storage,
) -> None:
    early_manifest = storage.artifact(b'{"papers":["p1"]}')
    early = storage.seal(
        {"paper_manifest_hash": early_manifest, "index_identity_hashes": ["a" * 64]}
    )
    later_manifest = storage.artifact(b'{"papers":["p1","p2"]}')
    storage.seal(
        {"paper_manifest_hash": later_manifest, "index_identity_hashes": ["a" * 64]}
    )
    with storage.database.connect() as connection:
        row = connection.execute(
            "SELECT encode(paper_manifest_hash,'hex') FROM snapshots WHERE hash=decode(%s,'hex')",
            (early["snapshot_hash"],),
        ).fetchone()
    assert row is not None and row[0] == early_manifest


def _sealed_snapshot_and_sheet(storage: Storage) -> tuple[str, str]:
    paper_manifest = storage.artifact(b'{"papers":["p1"]}')
    snapshot = storage.seal(
        {"paper_manifest_hash": paper_manifest, "index_identity_hashes": ["e" * 64]}
    )
    sheet = storage.seal_sheet([QUESTION])
    return snapshot["snapshot_hash"], sheet["sheet_hash"]


def test_pin_items_pins_a_paper_versions_artifact_hashes(storage: Storage) -> None:
    snapshot_hash, sheet_hash = _sealed_snapshot_and_sheet(storage)
    card_hash = storage.artifact(b'{"card":"p1v1"}')
    pinned = storage.pin_items(
        {
            "snapshot_hash": snapshot_hash,
            "sheet_hash": sheet_hash,
            "items": [
                {
                    "paper_family_id": PAPER_FAMILY_ID,
                    "paper_version_id": PAPER_VERSION_ID,
                    "card_hash": card_hash,
                    "overview_hash": None,
                    "passage_index_hash": None,
                    "graph_hash": None,
                }
            ],
        }
    )
    assert pinned["snapshot_hash"] == snapshot_hash
    assert pinned["pinned_count"] == 1
    with storage.database.connect() as connection:
        row = connection.execute(
            "SELECT encode(card_hash,'hex') FROM snapshot_items "
            "WHERE snapshot_hash=decode(%s,'hex') AND paper_version_id=%s",
            (snapshot_hash, PAPER_VERSION_ID),
        ).fetchone()
    assert row is not None and row[0] == card_hash


def test_pin_items_is_idempotent_for_the_same_paper_version(storage: Storage) -> None:
    snapshot_hash, sheet_hash = _sealed_snapshot_and_sheet(storage)
    card_hash = storage.artifact(b'{"card":"p1v1"}')
    payload = {
        "snapshot_hash": snapshot_hash,
        "sheet_hash": sheet_hash,
        "items": [
            {
                "paper_family_id": PAPER_FAMILY_ID,
                "paper_version_id": PAPER_VERSION_ID,
                "card_hash": card_hash,
                "overview_hash": None,
                "passage_index_hash": None,
                "graph_hash": None,
            }
        ],
    }
    storage.pin_items(payload)
    storage.pin_items(payload)
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM snapshot_items WHERE snapshot_hash=decode(%s,'hex')",
            (snapshot_hash,),
        ).fetchone()
    assert count is not None and count[0] == 1


def test_pin_items_rejects_an_unpublished_card_hash(storage: Storage) -> None:
    snapshot_hash, sheet_hash = _sealed_snapshot_and_sheet(storage)
    with pytest.raises(UnavailableInput):
        storage.pin_items(
            {
                "snapshot_hash": snapshot_hash,
                "sheet_hash": sheet_hash,
                "items": [
                    {
                        "paper_family_id": PAPER_FAMILY_ID,
                        "paper_version_id": PAPER_VERSION_ID,
                        "card_hash": "9" * 64,
                        "overview_hash": None,
                        "passage_index_hash": None,
                        "graph_hash": None,
                    }
                ],
            }
        )


def test_pin_items_rejects_an_unsealed_snapshot_or_sheet(storage: Storage) -> None:
    _, sheet_hash = _sealed_snapshot_and_sheet(storage)
    card_hash = storage.artifact(b'{"card":"p1v1"}')
    item = {
        "paper_family_id": PAPER_FAMILY_ID,
        "paper_version_id": PAPER_VERSION_ID,
        "card_hash": card_hash,
        "overview_hash": None,
        "passage_index_hash": None,
        "graph_hash": None,
    }
    with pytest.raises(UnavailableInput):
        storage.pin_items(
            {"snapshot_hash": "9" * 64, "sheet_hash": sheet_hash, "items": [item]}
        )
    snapshot_hash, _ = _sealed_snapshot_and_sheet(storage)
    with pytest.raises(UnavailableInput):
        storage.pin_items(
            {"snapshot_hash": snapshot_hash, "sheet_hash": "9" * 64, "items": [item]}
        )


def _card_item(storage: Storage, number: int) -> dict[str, Any]:
    return {
        "paper_family_id": str(uuid4()),
        "paper_version_id": str(uuid4()),
        "card_hash": storage.artifact(canonical_json({"card": number})),
        "overview_hash": None,
        "passage_index_hash": None,
        "graph_hash": None,
    }


def _publish(storage: Storage) -> Callable[[dict[str, Any]], str]:
    return lambda manifest: storage.artifact(canonical_json(manifest))


def test_the_days_snapshot_is_refused_before_any_sheet_exists(
    storage: Storage,
) -> None:
    with pytest.raises(ContractValidationError, match="after its day's sheets"):
        seal_next_snapshot(
            storage.snapshots,
            _publish(storage),
            principal_id=uuid4(),
            prior_items=(),
            acquired=[_card_item(storage, 1)],
            index_identity_hashes=("e" * 64,),
            sheet_hashes=(),
        )
    with storage.database.connect() as connection:
        count = connection.execute("SELECT count(*) FROM snapshots").fetchone()
    assert count == (0,)


def test_the_days_snapshot_pins_every_card_once_to_every_sheet(
    storage: Storage,
) -> None:
    later = {**QUESTION, "horizon": "2027-09-02T00:00:00.000000Z"}
    sheets = (
        storage.seal_sheet([QUESTION])["sheet_hash"],
        storage.seal_sheet([later])["sheet_hash"],
    )
    items = [_card_item(storage, number) for number in range(3)]
    snapshot_hash = seal_next_snapshot(
        storage.snapshots,
        _publish(storage),
        principal_id=uuid4(),
        prior_items=items[:1],
        acquired=items[1:],
        index_identity_hashes=("e" * 64,),
        sheet_hashes=sheets,
    )
    with storage.database.connect() as connection:
        pinned = connection.execute(
            """SELECT paper_version_id::text, encode(card_hash,'hex') FROM snapshot_items
               WHERE snapshot_hash=decode(%s,'hex')""",
            (snapshot_hash,),
        ).fetchall()
        bound = connection.execute(
            """SELECT encode(sheet_hash,'hex') FROM snapshot_sheets
               WHERE snapshot_hash=decode(%s,'hex')""",
            (snapshot_hash,),
        ).fetchall()
    assert sorted(pinned) == sorted(
        (item["paper_version_id"], item["card_hash"]) for item in items
    )
    assert sorted(row[0] for row in bound) == sorted(sheets)
