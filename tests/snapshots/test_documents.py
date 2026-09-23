from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.snapshots.documents import SnapshotDocuments
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
FAMILY_A = "123e4567-e89b-42d3-a456-426614174001"
VERSION_A = "123e4567-e89b-42d3-a456-426614174002"
FAMILY_B = "123e4567-e89b-42d3-a456-426614174003"
VERSION_B = "123e4567-e89b-42d3-a456-426614174004"


def _identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


class _Harness:
    def __init__(self, database: Database, artifact_root: Path) -> None:
        self.database = database
        self.store = ArtifactStore(artifact_root)
        self.artifacts = ArtifactRepository(database, self.store)
        self.snapshots = SnapshotRepository(
            database,
            self.store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        )
        self.sheets = SheetRepository(
            database,
            self.store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        )
        self.documents = SnapshotDocuments(database, self.artifacts)

    def artifact(self, payload: bytes) -> str:
        digest = sha256_hex(payload)
        publication = self.artifacts.publish(
            [payload],
            expected_hash=digest,
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

    def seal_snapshot(self) -> str:
        paper_manifest = self.artifact(b'{"papers":["p1","p2"]}')
        response = self.snapshots.execute(
            "seal",
            identity=_identity(),
            payload={
                "paper_manifest_hash": paper_manifest,
                "index_identity_hashes": ["e" * 64],
            },
        )
        return str(self._data(response)["snapshot_hash"])

    def seal_sheet(self) -> str:
        response = self.sheets.execute(
            "seal", identity=_identity(), payload={"questions": [QUESTION]}
        )
        return str(self._data(response)["sheet_hash"])

    def pin_items(
        self, snapshot_hash: str, sheet_hash: str, items: list[dict[str, Any]]
    ) -> None:
        self.snapshots.execute(
            "pin_items",
            identity=_identity(),
            payload={
                "snapshot_hash": snapshot_hash,
                "sheet_hash": sheet_hash,
                "items": items,
            },
        )


@pytest.fixture
def harness(postgres_dsn: str, artifact_root: Path) -> _Harness:
    return _Harness(Database(postgres_dsn), artifact_root)


def _item(
    *,
    family: str,
    version: str,
    card_hash: str,
    overview_hash: str | None = None,
    passage_index_hash: str | None = None,
    graph_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "paper_family_id": family,
        "paper_version_id": version,
        "card_hash": card_hash,
        "overview_hash": overview_hash,
        "passage_index_hash": passage_index_hash,
        "graph_hash": graph_hash,
    }


def test_cards_resolves_pinned_cards_in_requested_order(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    card_b = harness.artifact(b'{"title":"paper b"}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [
            _item(family=FAMILY_A, version=VERSION_A, card_hash=card_a),
            _item(family=FAMILY_B, version=VERSION_B, card_hash=card_b),
        ],
    )
    cards = harness.documents.cards(snapshot_hash, (VERSION_B, VERSION_A))
    assert cards[0]["title"] == "paper b"
    assert cards[1]["title"] == "paper a"


def test_cards_rejects_a_paper_version_absent_from_the_snapshot(
    harness: _Harness,
) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [_item(family=FAMILY_A, version=VERSION_A, card_hash=card_a)],
    )
    with pytest.raises(UnavailableInput):
        harness.documents.cards(snapshot_hash, (VERSION_B,))


def test_graph_reads_the_pinned_graph_artifact(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    graph_a = harness.artifact(b'{"incoming":["x"]}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [
            _item(
                family=FAMILY_A, version=VERSION_A, card_hash=card_a, graph_hash=graph_a
            )
        ],
    )
    assert harness.documents.graph(snapshot_hash, VERSION_A) == {"incoming": ["x"]}


def test_graph_is_unavailable_when_not_pinned(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [_item(family=FAMILY_A, version=VERSION_A, card_hash=card_a)],
    )
    with pytest.raises(UnavailableInput):
        harness.documents.graph(snapshot_hash, VERSION_A)


def test_passage_index_reads_the_pinned_passage_artifact(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    index_a = harness.artifact(b'{"passages":[]}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [
            _item(
                family=FAMILY_A,
                version=VERSION_A,
                card_hash=card_a,
                passage_index_hash=index_a,
            )
        ],
    )
    assert harness.documents.passage_index(snapshot_hash, VERSION_A) == {"passages": []}


def test_questions_returns_every_question_on_the_pinned_sheet(
    harness: _Harness,
) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [_item(family=FAMILY_A, version=VERSION_A, card_hash=card_a)],
    )
    questions = harness.documents.questions(snapshot_hash)
    assert len(questions) == 1
    assert questions[0]["question_id"] == QUESTION["question_id"]
    assert questions[0]["horizon"] == QUESTION["horizon"]


def test_questions_is_empty_for_a_snapshot_with_no_pinned_sheet(
    harness: _Harness,
) -> None:
    snapshot_hash = harness.seal_snapshot()
    assert harness.documents.questions(snapshot_hash) == ()


# -- member reads for the tool service (#297) -----------------------------

VERSION_A2 = "123e4567-e89b-42d3-a456-426614174005"


def test_members_lists_every_pinned_version_by_family(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    card_b = harness.artifact(b'{"title":"paper b"}')
    overview_b = harness.artifact(b'{"vector":[1.0,0.0]}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [
            _item(
                family=FAMILY_B,
                version=VERSION_B,
                card_hash=card_b,
                overview_hash=overview_b,
            ),
            _item(family=FAMILY_A, version=VERSION_A, card_hash=card_a),
        ],
    )
    members = harness.documents.members(snapshot_hash)
    assert [(pin.paper_family_id, pin.paper_version_id) for pin in members] == [
        (FAMILY_A, VERSION_A),
        (FAMILY_B, VERSION_B),
    ]
    assert members[1].overview_hash == overview_b
    assert members[0].overview_hash is None
    assert harness.documents.members(harness.seal_snapshot()) == ()
    first_page = harness.documents.members(snapshot_hash, limit=1)
    assert first_page == members[:1]
    assert harness.documents.members(
        snapshot_hash, after=(FAMILY_A, VERSION_A), limit=1
    ) == (members[1],)
    assert harness.documents.members(snapshot_hash, after=(FAMILY_B, VERSION_B)) == ()


def test_family_pin_resolves_the_one_pinned_version(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [_item(family=FAMILY_A, version=VERSION_A, card_hash=card_a)],
    )
    pin = harness.documents.family_pin(snapshot_hash, FAMILY_A)
    assert pin.paper_version_id == VERSION_A
    with pytest.raises(UnavailableInput, match="not pinned"):
        harness.documents.family_pin(snapshot_hash, FAMILY_B)


def test_family_pin_refuses_to_choose_between_two_pinned_versions(
    harness: _Harness,
) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    card_a2 = harness.artifact(b'{"title":"paper a, revised"}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [
            _item(family=FAMILY_A, version=VERSION_A, card_hash=card_a),
            _item(family=FAMILY_A, version=VERSION_A2, card_hash=card_a2),
        ],
    )
    with pytest.raises(UnavailableInput, match="more than one version"):
        harness.documents.family_pin(snapshot_hash, FAMILY_A)


def test_overviews_read_only_hashes_this_snapshot_pins(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot()
    other_snapshot = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    card_b = harness.artifact(b'{"title":"paper b"}')
    overview_a = harness.artifact(b'{"vector":[1.0,0.0]}')
    overview_b = harness.artifact(b'{"vector":[0.0,1.0]}')
    index_a = harness.artifact(b'{"passages":[]}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [
            _item(
                family=FAMILY_A,
                version=VERSION_A,
                card_hash=card_a,
                overview_hash=overview_a,
                passage_index_hash=index_a,
            )
        ],
    )
    harness.pin_items(
        other_snapshot,
        sheet_hash,
        [
            _item(
                family=FAMILY_B,
                version=VERSION_B,
                card_hash=card_b,
                overview_hash=overview_b,
            )
        ],
    )
    assert harness.documents.overviews(snapshot_hash, (overview_a,)) == (
        {"vector": [1.0, 0.0]},
    )
    # A hash another snapshot pinned, or one pinned here in another role,
    # reaches nothing.
    with pytest.raises(UnavailableInput):
        harness.documents.overviews(snapshot_hash, (overview_a, overview_b))
    with pytest.raises(UnavailableInput):
        harness.documents.overviews(snapshot_hash, (index_a,))


def test_passage_index_by_hash_reads_only_a_pinned_index(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot()
    sheet_hash = harness.seal_sheet()
    card_a = harness.artifact(b'{"title":"paper a"}')
    overview_a = harness.artifact(b'{"vector":[1.0,0.0]}')
    index_a = harness.artifact(b'{"passages":[{"text_hash":"x"}]}')
    harness.pin_items(
        snapshot_hash,
        sheet_hash,
        [
            _item(
                family=FAMILY_A,
                version=VERSION_A,
                card_hash=card_a,
                overview_hash=overview_a,
                passage_index_hash=index_a,
            )
        ],
    )
    assert harness.documents.passage_index_by_hash(snapshot_hash, index_a) == {
        "passages": [{"text_hash": "x"}]
    }
    with pytest.raises(UnavailableInput):
        harness.documents.passage_index_by_hash(snapshot_hash, overview_a)
    with pytest.raises(UnavailableInput):
        harness.documents.passage_index_by_hash(harness.seal_snapshot(), index_a)
