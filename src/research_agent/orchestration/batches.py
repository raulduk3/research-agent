"""Daily batch and shard construction: partition papers, build every run slot."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.orchestration.slots import Slot, build_slot

MAX_SHARD_PAPERS = 20


@dataclass(frozen=True, slots=True)
class PaperIdentity:
    """One eligible paper's ordering key and canonical id for sharding."""

    canonical_id: str
    first_public_at: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.canonical_id)
        validate_utc_instant(self.first_public_at)


@dataclass(frozen=True, slots=True)
class Shard:
    """One disjoint partition of a sealed sheet's eligible papers."""

    shard_id: str
    paper_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DailyBatch:
    """One day's sealed sheet, partitioned into shards, with every slot.

    Appendix A: Launch profile fixes this shape: disjoint shards of at most
    twenty papers ordered by first-public time then canonical id, with
    every configuration in the population running every shard against the
    same sealed sheet and frozen snapshot.
    """

    batch_id: str
    shards: tuple[Shard, ...]
    slots: tuple[Slot, ...]


def partition_shards(
    papers: Sequence[PaperIdentity], *, max_shard_size: int = MAX_SHARD_PAPERS
) -> tuple[Shard, ...]:
    """Sort eligible papers and split them into disjoint shards.

    Sharding changes engineering task size only; paper inclusion, sampling
    weight and forecast deadlines are unaffected by shard boundaries
    (Appendix A: Launch profile).
    """

    if not papers:
        raise ContractValidationError("partition_shards requires at least one paper")
    if max_shard_size < 1:
        raise ContractValidationError("max_shard_size must be a positive integer")
    ordered = sorted(
        papers, key=lambda paper: (paper.first_public_at, paper.canonical_id)
    )
    canonical_ids = [paper.canonical_id for paper in ordered]
    if len(set(canonical_ids)) != len(canonical_ids):
        raise ContractValidationError("papers must have distinct canonical_id")
    shards = []
    for index in range(0, len(ordered), max_shard_size):
        chunk = ordered[index : index + max_shard_size]
        shard_id = f"{index // max_shard_size:04d}"
        shards.append(Shard(shard_id, tuple(paper.canonical_id for paper in chunk)))
    return tuple(shards)


def build_daily_batch(
    batch_id: str,
    papers: Sequence[PaperIdentity],
    configuration_ids: Sequence[str],
    *,
    max_shard_size: int = MAX_SHARD_PAPERS,
) -> DailyBatch:
    """Partition a sealed sheet's papers and build every configuration's slot.

    ``batch_id`` is the sealed sheet's content hash (EN-10). Every
    configuration in ``configuration_ids`` receives one slot per shard, at
    attempt zero, so every configuration runs the same shards against the
    same sheet and snapshot (Appendix A: Launch profile).
    """

    validate_sha256(batch_id)
    if not configuration_ids:
        raise ContractValidationError(
            "build_daily_batch requires at least one configuration"
        )
    if len(set(configuration_ids)) != len(configuration_ids):
        raise ContractValidationError("configuration_ids must be distinct")
    for configuration_id in configuration_ids:
        validate_uuid4(configuration_id)
    shards = partition_shards(papers, max_shard_size=max_shard_size)
    slots = tuple(
        build_slot(batch_id, shard.shard_id, configuration_id, attempt=0)
        for shard in shards
        for configuration_id in configuration_ids
    )
    return DailyBatch(batch_id, shards, slots)
