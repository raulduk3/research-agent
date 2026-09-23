from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.contracts.learning import TARGET_IDS
from research_agent.orchestration.stamps import build_run_stamp
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


def _identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


def _card(bundle_ids: dict[str, str | None]) -> bytes:
    head_predictions = [
        {"target_id": target_id, "model_bundle_id": bundle_ids.get(target_id)}
        for target_id in TARGET_IDS
    ]
    return json.dumps({"head_predictions": head_predictions}).encode()


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

    def seal_snapshot(self, paper_manifest_payload: bytes) -> str:
        paper_manifest = self.artifact(paper_manifest_payload)
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

    def pin_card(self, snapshot_hash: str, sheet_hash: str, card_hash: str) -> None:
        self.snapshots.execute(
            "pin_items",
            identity=_identity(),
            payload={
                "snapshot_hash": snapshot_hash,
                "sheet_hash": sheet_hash,
                "items": [
                    {
                        "paper_family_id": FAMILY_A,
                        "paper_version_id": VERSION_A,
                        "card_hash": card_hash,
                        "overview_hash": None,
                        "passage_index_hash": None,
                        "graph_hash": None,
                    }
                ],
            },
        )


@pytest.fixture
def harness(postgres_dsn: str, artifact_root: Path) -> _Harness:
    return _Harness(Database(postgres_dsn), artifact_root)


GENOME_HASH = "7" * 64
AGENT_MODEL_MANIFEST = "8" * 64
SERVICE_IMAGE_VERSIONS = {"reader": "9" * 64}


def _fixed_fields() -> dict[str, Any]:
    return {
        "genome_hash": GENOME_HASH,
        "seed": 1,
        "agent_model_manifest": AGENT_MODEL_MANIFEST,
        "service_image_versions": SERVICE_IMAGE_VERSIONS,
    }


def test_run_stamp_names_the_snapshots_paper_manifest(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot(b'{"papers":["p1"]}')
    stamp = build_run_stamp(
        harness.documents,
        **_fixed_fields(),
        snapshot_hash=snapshot_hash,
        paper_version_ids=(),
    )
    assert stamp.snapshot_hash == snapshot_hash
    assert stamp.paper_card_manifest == harness.documents.paper_manifest_hash(
        snapshot_hash
    )


def test_run_stamp_carries_the_callers_fixed_identity_fields(
    harness: _Harness,
) -> None:
    snapshot_hash = harness.seal_snapshot(b'{"papers":["p1"]}')
    stamp = build_run_stamp(
        harness.documents,
        **_fixed_fields(),
        snapshot_hash=snapshot_hash,
        paper_version_ids=(),
    )
    assert stamp.genome_hash == GENOME_HASH
    assert stamp.seed == 1
    assert stamp.agent_model_manifest == AGENT_MODEL_MANIFEST
    assert stamp.service_image_versions == SERVICE_IMAGE_VERSIONS


def test_run_stamp_collects_bundle_ids_from_pinned_cards(harness: _Harness) -> None:
    snapshot_hash = harness.seal_snapshot(b'{"papers":["p1"]}')
    sheet_hash = harness.seal_sheet()
    bundle_a = "1" * 64
    card_hash = harness.artifact(
        _card({TARGET_IDS[0]: bundle_a, TARGET_IDS[1]: None, TARGET_IDS[2]: None})
    )
    harness.pin_card(snapshot_hash, sheet_hash, card_hash)

    stamp = build_run_stamp(
        harness.documents,
        **_fixed_fields(),
        snapshot_hash=snapshot_hash,
        paper_version_ids=(VERSION_A,),
    )
    assert stamp.prediction_head_bundles[TARGET_IDS[0]] == (bundle_a,)
    assert stamp.prediction_head_bundles[TARGET_IDS[1]] == ()
    assert stamp.prediction_head_bundles[TARGET_IDS[2]] == ()


def test_run_stamp_retains_yesterdays_bundle_after_a_later_promotion(
    harness: _Harness,
) -> None:
    yesterday_snapshot = harness.seal_snapshot(b'{"papers":["p1"]}')
    sheet_hash = harness.seal_sheet()
    yesterday_bundle = "2" * 64
    yesterday_card = harness.artifact(
        _card(
            {TARGET_IDS[0]: yesterday_bundle, TARGET_IDS[1]: None, TARGET_IDS[2]: None}
        )
    )
    harness.pin_card(yesterday_snapshot, sheet_hash, yesterday_card)

    # A later snapshot pins a card built under a newly promoted bundle; the
    # older, already-sealed snapshot's stamp must not see it.
    today_snapshot = harness.seal_snapshot(b'{"papers":["p1","p2"]}')
    today_bundle = "3" * 64
    today_card = harness.artifact(
        _card({TARGET_IDS[0]: today_bundle, TARGET_IDS[1]: None, TARGET_IDS[2]: None})
    )
    harness.pin_card(today_snapshot, sheet_hash, today_card)

    stamp = build_run_stamp(
        harness.documents,
        **_fixed_fields(),
        snapshot_hash=yesterday_snapshot,
        paper_version_ids=(VERSION_A,),
    )
    assert stamp.prediction_head_bundles[TARGET_IDS[0]] == (yesterday_bundle,)


def test_run_stamp_rejects_an_unresolved_snapshot(harness: _Harness) -> None:
    with pytest.raises(UnavailableInput):
        build_run_stamp(
            harness.documents,
            **_fixed_fields(),
            snapshot_hash="f" * 64,
            paper_version_ids=(),
        )
