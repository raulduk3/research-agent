"""The weekly stage: refresh, evaluate and activate, in order (SDD FT-16).

TDD-1.1.24: a fit crash and a broken chain are different paths -- a
candidate with no eligible head still runs scoring and reporting and
activates a fully-unavailable bundle with one disposition record; a real
promoted candidate is served afterward.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID

import numpy as np
import pytest

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import (
    EMBEDDING_FEATURE_DIMENSION,
    TargetDefinition,
)
from research_agent.learning.fit import DIMENSION, MaterializedPartition
from research_agent.learning.heads import (
    ThreeHeadCalibration,
    calibrate_three_heads,
    fit_three_heads,
)
from research_agent.models.registry import ServingHandle
from research_agent.orchestration.weekly import WeeklyDisposition, run_week
from research_agent.outcomes.targets import definitions as target_definitions
from research_agent.outcomes.targets import registry as target_registry
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database

IDENTITY = ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)
_META = RecordMeta(
    1,
    (),
    ProducerVersion("a" * 64, "b" * 40, 1),
    "c" * 64,
    "2026-01-01T00:00:00.000000Z",
)


def _three_definitions() -> tuple[TargetDefinition, TargetDefinition, TargetDefinition]:
    found = target_definitions(_META)
    return (found[0], found[1], found[2])


def _ids(name: str, count: int) -> tuple[str, ...]:
    return tuple(
        str(UUID(bytes=sha256(f"{name}-{index}".encode()).digest()[:16], version=4))
        for index in range(count)
    )


def _bindings() -> tuple[str, str, str, str, str, tuple[str, str, str]]:
    hashes = cast(
        "tuple[str, str, str]",
        tuple(
            sha256(row.to_canonical_json()).hexdigest()
            for row in target_definitions(_META)
        ),
    )
    return (*IDENTITY, hashes)


def _partition(name: str, count: int, seed: int) -> MaterializedPartition:
    rng = np.random.default_rng(seed)
    x = np.zeros((count, DIMENSION), dtype=np.float32)
    x[:, :2] = rng.normal(size=(count, 2)).astype(np.float32)
    labels = np.zeros((count, 3), dtype=np.uint8)
    labels[:, 0] = (np.arange(count) % 2).astype(np.uint8)
    x[:, 0] += labels[:, 0].astype(np.int8) * 2 - 1
    embedding = x[:, :EMBEDDING_FEATURE_DIMENSION]
    norms = np.linalg.norm(embedding.astype(np.float64), axis=1)
    x[:, :EMBEDDING_FEATURE_DIMENSION] = embedding / norms[:, None].astype(np.float32)
    labels[:, 1] = labels[:, 0]
    labels[:, 2] = labels[:, 0]
    return MaterializedPartition(
        x, labels, np.ones_like(labels), _ids(name, count), name, *_bindings()
    )


def _empty_partition(name: str) -> MaterializedPartition:
    """The cheapest valid partition: never read when every head is unavailable."""
    x = np.zeros((1, DIMENSION), dtype=np.float32)
    x[0, 0] = 1.0
    labels = np.zeros((1, 3), dtype=np.uint8)
    mask = np.zeros((1, 3), dtype=np.uint8)
    return MaterializedPartition(x, labels, mask, _ids(name, 1), name, *_bindings())


def _repository(dsn: str, tmp_path: Path) -> ArtifactRepository:
    return ArtifactRepository(Database(dsn), ArtifactStore(tmp_path / "artifacts"))


@pytest.mark.integration
def test_a_candidate_with_no_eligible_head_still_activates_and_reports_once(
    postgres_dsn: str, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path)
    registry_hash, representation_hash = IDENTITY[2], IDENTITY[3]
    fit = _empty_partition("fit")
    development = _empty_partition("development")
    calibration_partition = _empty_partition("calibration")
    fitted = fit_three_heads(target_registry(_META), fit, development)
    calibration = calibrate_three_heads(fitted, calibration_partition)
    assert isinstance(calibration, ThreeHeadCalibration)

    disposition = run_week(
        database,
        repository,
        weekly_id="week-2026-w01",
        freeze_watermark="2026-01-05T00:00:00.000000Z",
        calibration=calibration,
        fit=fit,
        development=development,
        definitions=_three_definitions(),
        incumbent_handle=None,
        incumbent_evaluations=(None, None, None),
        matches=(),
        baselines={item.target_id: 0.3 for item in _three_definitions()},
        producer_version=_META.producer_version,
        target_registry_hash=registry_hash,
        representation_hash=representation_hash,
    )

    assert isinstance(disposition, WeeklyDisposition)
    assert all(not item.promoted for item in disposition.decisions)
    handle = ServingHandle.load(database, repository)
    assert handle.bundle_hash == disposition.bundle_hash
    assert all(entry.status == "unavailable" for entry in handle.manifest.entries)


@pytest.mark.integration
def test_a_real_promoted_candidate_is_activated_and_served(
    postgres_dsn: str, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path)
    registry_hash, representation_hash = IDENTITY[2], IDENTITY[3]
    fit = _partition("fit", 220, 1)
    development = _partition("development", 60, 2)
    calibration_partition = _partition("calibration", 60, 3)
    fitted = fit_three_heads(target_registry(_META), fit, development)
    calibration = calibrate_three_heads(fitted, calibration_partition)

    disposition = run_week(
        database,
        repository,
        weekly_id="week-2026-w02",
        freeze_watermark="2026-01-12T00:00:00.000000Z",
        calibration=calibration,
        fit=fit,
        development=development,
        definitions=_three_definitions(),
        incumbent_handle=None,
        incumbent_evaluations=(None, None, None),
        matches=(),
        baselines={item.target_id: 0.5 for item in _three_definitions()},
        producer_version=_META.producer_version,
        target_registry_hash=registry_hash,
        representation_hash=representation_hash,
    )

    assert all(item.promoted for item in disposition.decisions)
    handle = ServingHandle.load(database, repository)
    assert handle.bundle_hash == disposition.bundle_hash
    assert all(entry.status == "qualified" for entry in handle.manifest.entries)
    for entry in handle.manifest.entries:
        assert entry.artifact_hash is not None
        repository.read(entry.artifact_hash)[1].close()


def test_run_week_refuses_definitions_out_of_registry_order() -> None:
    with pytest.raises(Exception):  # noqa: B017
        definitions = _three_definitions()
        run_week(
            Database("dbname=unused"),
            cast(ArtifactRepository, object()),
            weekly_id="week",
            freeze_watermark="2026-01-01T00:00:00.000000Z",
            calibration=cast(ThreeHeadCalibration, object()),
            fit=cast(MaterializedPartition, object()),
            development=cast(MaterializedPartition, object()),
            definitions=(definitions[1], definitions[0], definitions[2]),
            incumbent_handle=None,
            incumbent_evaluations=(None, None, None),
            matches=(),
            baselines={item.target_id: 0.3 for item in definitions},
            producer_version=_META.producer_version,
            target_registry_hash=IDENTITY[2],
            representation_hash=IDENTITY[3],
        )
