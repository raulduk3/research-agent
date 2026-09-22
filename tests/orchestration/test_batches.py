from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.orchestration.batches import (
    PaperIdentity,
    build_daily_batch,
    partition_shards,
)

BATCH_ID = "a" * 64
CONFIGURATION_A = "123e4567-e89b-42d3-a456-426614174000"
CONFIGURATION_B = "223e4567-e89b-42d3-a456-426614174000"


def _papers(count: int) -> list[PaperIdentity]:
    return [
        PaperIdentity(
            canonical_id=f"paper-{index:03d}",
            first_public_at=f"2027-01-{(index % 28) + 1:02d}T00:00:00.000000Z",
        )
        for index in range(count)
    ]


def test_partition_shards_orders_by_first_public_at_then_canonical_id() -> None:
    papers = [
        PaperIdentity("paper-b", "2027-01-01T00:00:00.000000Z"),
        PaperIdentity("paper-a", "2027-01-01T00:00:00.000000Z"),
        PaperIdentity("paper-c", "2026-12-31T00:00:00.000000Z"),
    ]
    shards = partition_shards(papers, max_shard_size=20)
    assert len(shards) == 1
    assert shards[0].paper_ids == ("paper-c", "paper-a", "paper-b")


def test_partition_shards_splits_into_disjoint_chunks_of_the_max_size() -> None:
    papers = _papers(45)
    shards = partition_shards(papers, max_shard_size=20)
    assert [len(shard.paper_ids) for shard in shards] == [20, 20, 5]
    seen: set[str] = set()
    for shard in shards:
        seen.update(shard.paper_ids)
    assert seen == {paper.canonical_id for paper in papers}


def test_partition_shards_rejects_an_empty_paper_list() -> None:
    with pytest.raises(ContractValidationError):
        partition_shards([])


def test_partition_shards_rejects_duplicate_canonical_ids() -> None:
    papers = [
        PaperIdentity("paper-a", "2027-01-01T00:00:00.000000Z"),
        PaperIdentity("paper-a", "2027-01-02T00:00:00.000000Z"),
    ]
    with pytest.raises(ContractValidationError):
        partition_shards(papers)


def test_build_daily_batch_gives_every_configuration_every_shard() -> None:
    papers = _papers(25)
    batch = build_daily_batch(BATCH_ID, papers, [CONFIGURATION_A, CONFIGURATION_B])

    assert len(batch.shards) == 2
    assert len(batch.slots) == 4
    seen = {(slot.shard_id, slot.configuration_id) for slot in batch.slots}
    assert seen == {
        (shard.shard_id, configuration)
        for shard in batch.shards
        for configuration in (CONFIGURATION_A, CONFIGURATION_B)
    }
    assert all(slot.batch_id == BATCH_ID and slot.attempt == 0 for slot in batch.slots)


def test_build_daily_batch_rejects_duplicate_configuration_ids() -> None:
    with pytest.raises(ContractValidationError):
        build_daily_batch(BATCH_ID, _papers(1), [CONFIGURATION_A, CONFIGURATION_A])


def test_build_daily_batch_rejects_no_configurations() -> None:
    with pytest.raises(ContractValidationError):
        build_daily_batch(BATCH_ID, _papers(1), [])


def test_build_daily_batch_rejects_a_non_sha256_batch_id() -> None:
    with pytest.raises(ContractValidationError):
        build_daily_batch("not-a-hash", _papers(1), [CONFIGURATION_A])
