"""Stable serving handle until promotion (SDD PL-13).

TDD-2.1.42: the model service obtains a validated handle and holds it for
every admitted request; a later promotion never changes what is served
until the service loads a new handle, and a service that never saw a
promotion refuses to predict rather than adopting an unpromoted candidate.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

import pytest

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.learning import TargetDefinition
from research_agent.learning.features import Standardization
from research_agent.models.embedding import FrozenEmbedder
from research_agent.models.manifest import RepresentationManifest
from research_agent.models.predict import PredictError
from research_agent.models.registry import (
    BundleManifest,
    BundleTargetEntry,
    PublishedHead,
    ServingHandle,
    activate_bundle,
    publish_head,
)
from research_agent.models.service import ModelService, PredictionBundleUnavailableError
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database

Definitions = tuple[TargetDefinition, TargetDefinition, TargetDefinition]

TARGET_REGISTRY_HASH = sha256(b"stable-serving-registry").hexdigest()
REPRESENTATION_HASH = sha256(b"stable-serving-representation").hexdigest()
ORIGINAL_VERSION_ID = "00000000-0000-4000-8000-000000000000"


def _definition_hash(definition: TargetDefinition) -> str:
    return sha256(definition.to_canonical_json()).hexdigest()


def _unavailable(definition: TargetDefinition) -> BundleTargetEntry:
    return BundleTargetEntry(
        definition.target_id,
        _definition_hash(definition),
        "unavailable",
        None,
        "never_fit",
    )


def _all_unavailable(definitions: Definitions) -> tuple[BundleTargetEntry, ...]:
    return tuple(_unavailable(definition) for definition in definitions)


@pytest.mark.integration
def test_a_service_never_promoted_refuses_to_predict(
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
    bundle_target_definitions: Definitions,
    embedding_block: tuple[float, ...],
    metadata_block: tuple[float, ...],
) -> None:
    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    service = ModelService(embedder)
    try:
        with pytest.raises(PredictionBundleUnavailableError):
            service.predict_targets(
                bundle_target_definitions,
                original_version_id=ORIGINAL_VERSION_ID,
                requested_bundle_hash="a" * 64,
                representation_hash=REPRESENTATION_HASH,
                embedding_block=embedding_block,
                metadata_block=metadata_block,
                computed_at="2026-01-01T00:00:00.000000Z",
                available_at="2026-01-01T00:00:00.000000Z",
            )
    finally:
        service.close()


@pytest.mark.integration
def test_a_service_holds_its_loaded_handle_across_a_later_promotion(
    postgres_dsn: str,
    tmp_path: Path,
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., object],
    bundle_target_definitions: Definitions,
    producer_version: ProducerVersion,
    standardization: Standardization,
    head_weights: tuple[float, ...],
    embedding_block: tuple[float, ...],
    metadata_block: tuple[float, ...],
) -> None:
    database = Database(postgres_dsn)
    repository = ArtifactRepository(database, ArtifactStore(tmp_path / "artifacts"))
    first = BundleManifest(
        TARGET_REGISTRY_HASH,
        REPRESENTATION_HASH,
        _all_unavailable(bundle_target_definitions),
        producer_version,
        "2026-01-05T00:00:00.000000Z",
    )
    activate_bundle(database, repository, first)
    loaded = ServingHandle.load(database, repository)

    embedder = FrozenEmbedder(manifest, fake_backend_factory())  # type: ignore[arg-type]
    service = ModelService(embedder, serving_handle=loaded, heads={})
    try:
        target = bundle_target_definitions[0]
        head_hash = publish_head(
            repository,
            PublishedHead(
                target_id=target.target_id,
                target_definition_hash=_definition_hash(target),
                weights=head_weights,
                intercept=0.0,
                standardization=standardization,
                calibrator_a=1.0,
                calibrator_b=0.0,
                representation_hash=REPRESENTATION_HASH,
                target_registry_hash=TARGET_REGISTRY_HASH,
                development_brier=0.2,
            ),
            producer_version=producer_version,
        )
        second_entries = (
            BundleTargetEntry(
                target.target_id, _definition_hash(target), "qualified", head_hash, None
            ),
            _unavailable(bundle_target_definitions[1]),
            _unavailable(bundle_target_definitions[2]),
        )
        second = BundleManifest(
            TARGET_REGISTRY_HASH,
            REPRESENTATION_HASH,
            second_entries,
            producer_version,
            "2026-01-12T00:00:00.000000Z",
        )
        activate_bundle(database, repository, second)

        assert service.serving_handle is not None
        assert service.serving_handle.bundle_hash == loaded.bundle_hash
        assert (
            service.serving_handle.manifest.entry_for(target.target_id).status
            == "unavailable"
        )

        with pytest.raises(PredictError):
            service.predict_targets(
                bundle_target_definitions,
                original_version_id=ORIGINAL_VERSION_ID,
                requested_bundle_hash=sha256(second.to_canonical_json()).hexdigest(),
                representation_hash=REPRESENTATION_HASH,
                embedding_block=embedding_block,
                metadata_block=metadata_block,
                computed_at="2026-01-13T00:00:00.000000Z",
                available_at="2026-01-13T00:00:00.000000Z",
            )
    finally:
        service.close()
