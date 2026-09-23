from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.snapshots.documents import DocumentPins, SnapshotDocuments
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
FAMILY = "123e4567-e89b-42d3-a456-426614174001"
ORIGINAL_VERSION = "123e4567-e89b-42d3-a456-426614174002"
REVISED_VERSION = "123e4567-e89b-42d3-a456-426614174003"


def _identity() -> CommandIdentity:
    return CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4())


class _Harness:
    def __init__(self, database: Database, artifact_root: Path) -> None:
        store = ArtifactStore(artifact_root)
        self.artifacts = ArtifactRepository(database, store)
        settings: dict[str, Any] = {
            "producer": PRODUCER,
            "config_hash": "c" * 64,
            "retention_policy_hash": "d" * 64,
        }
        self.snapshots = SnapshotRepository(database, store, **settings)
        self.sheets = SheetRepository(database, store, **settings)
        self.documents = SnapshotDocuments(database, self.artifacts)

    def artifact(self, payload: bytes) -> str:
        publication = self.artifacts.publish(
            [payload],
            expected_hash=sha256_hex(payload),
            byte_length=len(payload),
            maximum_length=1024 * 1024,
            media_type="application/json",
            kind="manifest",
            input_hashes=(),
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            command_id=uuid4(),
        )
        return publication.manifest_hash

    def _data(self, response: Any) -> dict[str, Any]:
        return dict(canonical_loads(response.body)["data"])

    def freeze(self, label: str, items: list[dict[str, Any]]) -> str:
        """Seal a snapshot over *label*'s paper manifest and pin *items* to it."""

        paper_manifest = self.artifact(f'{{"papers":["{label}"]}}'.encode())
        snapshot = self.snapshots.execute(
            "seal",
            identity=_identity(),
            payload={
                "paper_manifest_hash": paper_manifest,
                "index_identity_hashes": ["e" * 64],
            },
        )
        snapshot_hash = str(self._data(snapshot)["snapshot_hash"])
        sheet = self.sheets.execute(
            "seal", identity=_identity(), payload={"questions": [QUESTION]}
        )
        self.snapshots.execute(
            "pin_items",
            identity=_identity(),
            payload={
                "snapshot_hash": snapshot_hash,
                "sheet_hash": str(self._data(sheet)["sheet_hash"]),
                "items": items,
            },
        )
        return snapshot_hash


@pytest.fixture
def harness(postgres_dsn: str, artifact_root: Path) -> _Harness:
    return _Harness(Database(postgres_dsn), artifact_root)


def _item(version: UUID | str, card_hash: str, **hashes: str) -> dict[str, Any]:
    return {
        "paper_family_id": FAMILY,
        "paper_version_id": str(version),
        "card_hash": card_hash,
        "overview_hash": hashes.get("overview_hash"),
        "passage_index_hash": hashes.get("passage_index_hash"),
        "graph_hash": hashes.get("graph_hash"),
    }


def test_a_readable_revision_is_read_without_a_pinned_original(
    harness: _Harness,
) -> None:
    revised_card = harness.artifact(b'{"title":"revised text"}')
    revised_index = harness.artifact(b'{"passages":["revised"]}')
    snapshot_hash = harness.freeze(
        "revision-only",
        [_item(REVISED_VERSION, revised_card, passage_index_hash=revised_index)],
    )

    pins = harness.documents.pins(snapshot_hash, (ORIGINAL_VERSION, REVISED_VERSION))

    assert set(pins) == {REVISED_VERSION}
    assert pins[REVISED_VERSION] == DocumentPins(
        paper_family_id=FAMILY,
        paper_version_id=REVISED_VERSION,
        card_hash=revised_card,
        overview_hash=None,
        passage_index_hash=revised_index,
        graph_hash=None,
    )
    assert harness.documents.cards(snapshot_hash, (REVISED_VERSION,)) == (
        {"title": "revised text"},
    )
    assert harness.documents.passage_index(snapshot_hash, REVISED_VERSION) == {
        "passages": ["revised"]
    }
    with pytest.raises(UnavailableInput):
        harness.documents.cards(snapshot_hash, (ORIGINAL_VERSION,))
    with pytest.raises(UnavailableInput):
        harness.documents.graph(snapshot_hash, REVISED_VERSION)


def test_a_later_revision_cannot_alter_an_earlier_snapshot(
    harness: _Harness,
) -> None:
    original_card = harness.artifact(b'{"title":"original","results":"none"}')
    original_graph = harness.artifact(b'{"incoming":[]}')
    earlier = harness.freeze(
        "before-revision",
        [_item(ORIGINAL_VERSION, original_card, graph_hash=original_graph)],
    )
    before = harness.documents.pins(earlier, (ORIGINAL_VERSION, REVISED_VERSION))

    revised_card = harness.artifact(b'{"title":"original","results":"new results"}')
    later = harness.freeze(
        "after-revision",
        [
            _item(ORIGINAL_VERSION, original_card, graph_hash=original_graph),
            _item(REVISED_VERSION, revised_card),
        ],
    )

    assert (
        harness.documents.pins(earlier, (ORIGINAL_VERSION, REVISED_VERSION)) == before
    )
    assert set(before) == {ORIGINAL_VERSION}
    assert harness.documents.cards(earlier, (ORIGINAL_VERSION,)) == (
        {"title": "original", "results": "none"},
    )
    assert harness.documents.graph(earlier, ORIGINAL_VERSION) == {"incoming": []}
    with pytest.raises(UnavailableInput):
        harness.documents.cards(earlier, (REVISED_VERSION,))

    assert harness.documents.cards(later, (REVISED_VERSION, ORIGINAL_VERSION)) == (
        {"title": "original", "results": "new results"},
        {"title": "original", "results": "none"},
    )
    assert (
        harness.documents.pins(later, (ORIGINAL_VERSION,))[ORIGINAL_VERSION].card_hash
        == original_card
    )
