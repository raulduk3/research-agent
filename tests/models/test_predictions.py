"""Three named prediction-head outputs from one pinned bundle (SDD RD-08).

TDD-1.1.22: a request is refused before any head is evaluated when its
pinned bundle id or representation namespace disagrees with the resolved
serving handle; an unavailable head leaves the other qualified outputs
intact; the public projection never carries the raw logit.
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from research_agent.contracts.learning import TargetDefinition
from research_agent.models.predict import PredictError, predict_targets
from research_agent.models.registry import (
    BundleManifest,
    BundleTargetEntry,
    ServingHandle,
)
from research_agent.contracts import ProducerVersion

Definitions = tuple[TargetDefinition, TargetDefinition, TargetDefinition]

TARGET_REGISTRY_HASH = sha256(b"prediction-registry").hexdigest()
REPRESENTATION_HASH = sha256(b"prediction-representation").hexdigest()
ORIGINAL_VERSION_ID = "00000000-0000-4000-8000-000000000001"
COMPUTED_AT = "2026-02-01T00:00:00.000000Z"


def _definition_hash(definition: TargetDefinition) -> str:
    return sha256(definition.to_canonical_json()).hexdigest()


def _handle(
    definitions: Definitions,
    producer_version: ProducerVersion,
    *,
    representation_hash: str = REPRESENTATION_HASH,
) -> ServingHandle:
    entries = tuple(
        BundleTargetEntry(
            definition.target_id,
            _definition_hash(definition),
            "unavailable",
            None,
            "never_fit",
        )
        for definition in definitions
    )
    manifest = BundleManifest(
        TARGET_REGISTRY_HASH,
        representation_hash,
        entries,
        producer_version,
        "2026-01-20T00:00:00.000000Z",
    )
    return ServingHandle(1, sha256(manifest.to_canonical_json()).hexdigest(), manifest)


def test_a_mismatched_pinned_bundle_id_is_refused_before_any_head_runs(
    bundle_target_definitions: Definitions,
    producer_version: ProducerVersion,
    embedding_block: tuple[float, ...],
    metadata_block: tuple[float, ...],
) -> None:
    handle = _handle(bundle_target_definitions, producer_version)
    with pytest.raises(PredictError):
        predict_targets(
            handle,
            {},
            bundle_target_definitions,
            original_version_id=ORIGINAL_VERSION_ID,
            requested_bundle_hash="a" * 64,
            representation_hash=REPRESENTATION_HASH,
            embedding_block=embedding_block,
            metadata_block=metadata_block,
            computed_at=COMPUTED_AT,
            available_at=COMPUTED_AT,
        )


def test_a_mismatched_representation_namespace_is_refused(
    bundle_target_definitions: Definitions,
    producer_version: ProducerVersion,
    embedding_block: tuple[float, ...],
    metadata_block: tuple[float, ...],
) -> None:
    handle = _handle(bundle_target_definitions, producer_version)
    with pytest.raises(PredictError):
        predict_targets(
            handle,
            {},
            bundle_target_definitions,
            original_version_id=ORIGINAL_VERSION_ID,
            requested_bundle_hash=handle.bundle_hash,
            representation_hash=sha256(b"a-different-representation").hexdigest(),
            embedding_block=embedding_block,
            metadata_block=metadata_block,
            computed_at=COMPUTED_AT,
            available_at=COMPUTED_AT,
        )


def test_an_all_unavailable_bundle_returns_three_null_records_with_reasons(
    bundle_target_definitions: Definitions,
    producer_version: ProducerVersion,
    embedding_block: tuple[float, ...],
    metadata_block: tuple[float, ...],
) -> None:
    handle = _handle(bundle_target_definitions, producer_version)
    records = predict_targets(
        handle,
        {},
        bundle_target_definitions,
        original_version_id=ORIGINAL_VERSION_ID,
        requested_bundle_hash=handle.bundle_hash,
        representation_hash=REPRESENTATION_HASH,
        embedding_block=embedding_block,
        metadata_block=metadata_block,
        computed_at=COMPUTED_AT,
        available_at=COMPUTED_AT,
    )
    assert len(records) == 3
    for record in records:
        assert record.status == "unavailable"
        assert record.reason == "never_fit"
        assert record.probability is None
        assert record.raw_logit is None
        public = record.public()
        assert public.probability is None
        assert not hasattr(public, "raw_logit")


def test_a_qualified_head_is_evaluated_and_its_public_projection_hides_the_logit(
    bundle_target_definitions: Definitions,
    producer_version: ProducerVersion,
    standardization: object,
    head_weights: tuple[float, ...],
    embedding_block: tuple[float, ...],
    metadata_block: tuple[float, ...],
) -> None:
    from research_agent.models.registry import PublishedHead

    target = bundle_target_definitions[0]
    head = PublishedHead(
        target_id=target.target_id,
        target_definition_hash=_definition_hash(target),
        weights=head_weights,
        intercept=0.25,
        standardization=standardization,  # type: ignore[arg-type]
        calibrator_a=1.5,
        calibrator_b=-0.1,
        representation_hash=REPRESENTATION_HASH,
        target_registry_hash=TARGET_REGISTRY_HASH,
        development_brier=0.2,
    )
    artifact_hash = sha256(head.to_canonical_json()).hexdigest()
    entries = (
        BundleTargetEntry(
            target.target_id, _definition_hash(target), "qualified", artifact_hash, None
        ),
        BundleTargetEntry(
            bundle_target_definitions[1].target_id,
            _definition_hash(bundle_target_definitions[1]),
            "unavailable",
            None,
            "never_fit",
        ),
        BundleTargetEntry(
            bundle_target_definitions[2].target_id,
            _definition_hash(bundle_target_definitions[2]),
            "unavailable",
            None,
            "never_fit",
        ),
    )
    manifest = BundleManifest(
        TARGET_REGISTRY_HASH,
        REPRESENTATION_HASH,
        entries,
        producer_version,
        "2026-01-20T00:00:00.000000Z",
    )
    handle = ServingHandle(
        1, sha256(manifest.to_canonical_json()).hexdigest(), manifest
    )

    records = predict_targets(
        handle,
        {target.target_id: head},
        bundle_target_definitions,
        original_version_id=ORIGINAL_VERSION_ID,
        requested_bundle_hash=handle.bundle_hash,
        representation_hash=REPRESENTATION_HASH,
        embedding_block=embedding_block,
        metadata_block=metadata_block,
        computed_at=COMPUTED_AT,
        available_at=COMPUTED_AT,
    )
    qualified = next(
        record for record in records if record.target_id == target.target_id
    )
    assert qualified.status == "available"
    assert qualified.raw_logit is not None
    assert qualified.probability is not None
    assert 0.0 <= qualified.probability <= 1.0
    assert qualified.bundle_hash == handle.bundle_hash

    public = qualified.public()
    assert public.probability == qualified.probability
    assert not hasattr(public, "raw_logit")
    others = [record for record in records if record.target_id != target.target_id]
    assert all(record.status == "unavailable" for record in others)
