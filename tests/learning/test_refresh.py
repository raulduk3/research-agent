from __future__ import annotations

from hashlib import sha256
from typing import cast
from uuid import UUID

import numpy as np
import pytest

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import EMBEDDING_FEATURE_DIMENSION, TARGET_IDS
from research_agent.learning.fit import DIMENSION, MaterializedPartition
from research_agent.learning.refresh import (
    LabelObservation,
    RefreshError,
    TargetRefreshOutcome,
    build_refresh,
    freeze_watermark,
)
from research_agent.outcomes.targets import registry

IDENTITY = ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)
FREEZE_AT = "2026-09-20T00:00:00.000000Z"
BEFORE_FREEZE = "2026-09-01T00:00:00.000000Z"
AFTER_FREEZE = "2026-09-21T00:00:00.000000Z"
CONFIG_HASH = "f" * 64


def _meta() -> RecordMeta:
    return RecordMeta(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        "2026-01-01T00:00:00.000000Z",
    )


def _bindings() -> tuple[str, str, str, str, str, tuple[str, str, str]]:
    hashes = cast(
        tuple[str, str, str],
        tuple(
            sha256(row.to_canonical_json()).hexdigest()
            for row in registry(_meta()).definitions
        ),
    )
    return (*IDENTITY, hashes)


def _ids(name: str, count: int) -> tuple[str, ...]:
    return tuple(
        str(UUID(bytes=sha256(f"{name}-{index}".encode()).digest()[:16], version=4))
        for index in range(count)
    )


def _partition(name: str, count: int, seed: int) -> MaterializedPartition:
    rng = np.random.default_rng(seed)
    x = np.zeros((count, DIMENSION), dtype=np.float32)
    x[:, :3] = rng.normal(size=(count, 3)).astype(np.float32)
    labels = np.zeros((count, 3), dtype=np.uint8)
    for index in range(3):
        labels[:, index] = ((np.arange(count) + index) % 2).astype(np.uint8)
        x[:, index] += labels[:, index].astype(np.int8) * 2 - 1
    embedding = x[:, :EMBEDDING_FEATURE_DIMENSION]
    norms = np.linalg.norm(embedding.astype(np.float64), axis=1)
    x[:, :EMBEDDING_FEATURE_DIMENSION] = embedding / norms[:, None].astype(np.float32)
    return MaterializedPartition(
        x, labels, np.ones_like(labels), _ids(name, count), name, *_bindings()
    )


def _partitions() -> tuple[
    MaterializedPartition, MaterializedPartition, MaterializedPartition
]:
    return (
        _partition("fit", 220, 1),
        _partition("development", 60, 2),
        _partition("calibration", 60, 3),
    )


def _observations(
    partitions: tuple[MaterializedPartition, ...], available_at: str = BEFORE_FREEZE
) -> tuple[LabelObservation, ...]:
    observations = []
    for partition in partitions:
        for family_id in partition.family_ids:
            for target_id in TARGET_IDS:
                observations.append(
                    LabelObservation(family_id, target_id, "v1", available_at)
                )
    return tuple(observations)


def test_freeze_watermark_rejects_an_observation_after_the_freeze() -> None:
    late = LabelObservation(_ids("x", 1)[0], TARGET_IDS[0], "v1", AFTER_FREEZE)
    with pytest.raises(RefreshError, match="after the freeze"):
        freeze_watermark(FREEZE_AT, (late,))


def test_build_refresh_rejects_a_materialized_row_with_no_covering_observation() -> (
    None
):
    fit, development, calibration = _partitions()
    watermark = freeze_watermark(FREEZE_AT, ())
    with pytest.raises(RefreshError, match="no covering mature observation"):
        build_refresh(
            registry(_meta()), watermark, fit, development, calibration, CONFIG_HASH
        )


def test_build_refresh_completes_all_three_targets_from_mature_labels() -> None:
    partitions = _partitions()
    watermark = freeze_watermark(FREEZE_AT, _observations(partitions))
    result = build_refresh(registry(_meta()), watermark, *partitions, CONFIG_HASH)
    assert tuple(item.target_id for item in result.outcomes) == TARGET_IDS
    for outcome in result.outcomes:
        assert outcome.status == "completed"
        assert outcome.fit is not None
        assert outcome.calibrations
    assert result.watermark is watermark


def test_build_refresh_returns_unchanged_data_without_fitting_when_hash_matches() -> (
    None
):
    partitions = _partitions()
    watermark = freeze_watermark(FREEZE_AT, _observations(partitions))
    first = build_refresh(registry(_meta()), watermark, *partitions, CONFIG_HASH)
    second = build_refresh(
        registry(_meta()),
        watermark,
        *partitions,
        CONFIG_HASH,
        prior_dataset_hash=first.dataset_hash,
    )
    assert second.dataset_hash == first.dataset_hash
    for outcome in second.outcomes:
        assert outcome.status == "unchanged_data"
        assert outcome.fit is None
        assert outcome.reason is None


def test_build_refresh_classifies_insufficient_fit_classes() -> None:
    fit = _partition("fit", 10, 1)
    development = _partition("development", 60, 2)
    calibration = _partition("calibration", 60, 3)
    partitions = (fit, development, calibration)
    watermark = freeze_watermark(FREEZE_AT, _observations(partitions))
    result = build_refresh(registry(_meta()), watermark, *partitions, CONFIG_HASH)
    for outcome in result.outcomes:
        assert outcome.status == "insufficient_data"
        assert outcome.fit is None
        assert outcome.reason is not None


def test_target_refresh_outcome_rejects_inconsistent_fields() -> None:
    with pytest.raises(RefreshError, match="completed outcome"):
        TargetRefreshOutcome(TARGET_IDS[0], "completed", None, None, ())
    with pytest.raises(RefreshError, match="failed outcome requires"):
        TargetRefreshOutcome(TARGET_IDS[0], "failed", None, None, ())
