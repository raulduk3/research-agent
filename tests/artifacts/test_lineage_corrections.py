"""Correction dependency graph: invalidate without rewriting history (SDD FT-25).

TDD-1.1.20: a correction is appended, never edits its superseded content;
enumeration walks the existing dependency graph forward from it; a critical
correction that reaches the active bundle withdraws exactly the affected
target, atomically, while every other target's membership and every prior
byte carries over unchanged.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from research_agent.artifacts.lineage import (
    Correction,
    LineageError,
    apply_correction,
    dependents_of,
)
from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.learning import PRIMARY_CATEGORY_IDS, TargetDefinition
from research_agent.learning.features import Standardization
from research_agent.models.registry import (
    BundleManifest,
    BundleTargetEntry,
    CategoryCalibrator,
    PublishedHead,
    ServingHandle,
    activate_bundle,
    publish_head,
)
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database

Definitions = tuple[TargetDefinition, TargetDefinition, TargetDefinition]

TARGET_REGISTRY_HASH = sha256(b"lineage-registry").hexdigest()
REPRESENTATION_HASH = sha256(b"lineage-representation").hexdigest()
RETENTION_HASH = sha256(b"lineage-retention").hexdigest()
CALIBRATIONS = tuple(
    CategoryCalibrator(category, "qualified", None, 1.0, 0.0)
    for category in PRIMARY_CATEGORY_IDS
)


def _repository(dsn: str, tmp_path: Path) -> ArtifactRepository:
    return ArtifactRepository(Database(dsn), ArtifactStore(tmp_path / "artifacts"))


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


@pytest.mark.integration
def test_dependents_of_walks_the_production_graph_forward(
    postgres_dsn: str, tmp_path: Path, producer_version: ProducerVersion
) -> None:
    repository = _repository(postgres_dsn, tmp_path)
    source_payload = b'{"kind":"source"}'
    source_hash = sha256(source_payload).hexdigest()
    source = repository.publish(
        [source_payload],
        expected_hash=source_hash,
        byte_length=len(source_payload),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=producer_version,
        config_hash=RETENTION_HASH,
        retention_policy_hash=RETENTION_HASH,
        command_id=uuid4(),
    )
    derived_payload = b'{"kind":"derived"}'
    derived_hash = sha256(derived_payload).hexdigest()
    derived = repository.publish(
        [derived_payload],
        expected_hash=derived_hash,
        byte_length=len(derived_payload),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(source.artifact_hash,),
        producer_version=producer_version,
        config_hash=RETENTION_HASH,
        retention_policy_hash=RETENTION_HASH,
        command_id=uuid4(),
    )

    reached = dependents_of(Database(postgres_dsn), source.artifact_hash)
    assert derived.manifest_hash in reached
    assert source.artifact_hash not in reached


@pytest.mark.integration
def test_a_critical_correction_withdraws_only_its_reached_target(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    bundle_target_definitions: Definitions,
    standardization: Standardization,
    head_weights: tuple[float, ...],
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path)
    corrected_target, safe_target, third_target = bundle_target_definitions

    corrected_head_hash = publish_head(
        repository,
        PublishedHead(
            target_id=corrected_target.target_id,
            target_definition_hash=_definition_hash(corrected_target),
            weights=head_weights,
            intercept=0.0,
            standardization=standardization,
            calibrations=CALIBRATIONS,
            representation_hash=REPRESENTATION_HASH,
            target_registry_hash=TARGET_REGISTRY_HASH,
            development_brier=0.2,
        ),
        producer_version=producer_version,
    )
    safe_head_hash = publish_head(
        repository,
        PublishedHead(
            target_id=safe_target.target_id,
            target_definition_hash=_definition_hash(safe_target),
            weights=head_weights,
            intercept=0.0,
            standardization=standardization,
            calibrations=CALIBRATIONS,
            representation_hash=REPRESENTATION_HASH,
            target_registry_hash=TARGET_REGISTRY_HASH,
            development_brier=0.2,
        ),
        producer_version=producer_version,
    )
    entries = (
        BundleTargetEntry(
            corrected_target.target_id,
            _definition_hash(corrected_target),
            "qualified",
            corrected_head_hash,
            None,
        ),
        BundleTargetEntry(
            safe_target.target_id,
            _definition_hash(safe_target),
            "qualified",
            safe_head_hash,
            None,
        ),
        _unavailable(third_target),
    )
    manifest = BundleManifest(
        TARGET_REGISTRY_HASH,
        REPRESENTATION_HASH,
        entries,
        producer_version,
        "2026-02-01T00:00:00.000000Z",
    )
    activate_bundle(database, repository, manifest)
    handle = ServingHandle.load(database, repository)

    correction = Correction(
        "representation",
        corrected_head_hash,
        "corrupted checkpoint",
        "2026-02-10T00:00:00.000000Z",
    )
    impact = apply_correction(
        database,
        repository,
        correction,
        critical=True,
        current_handle=handle,
        producer_version=producer_version,
    )

    assert impact.withdrawn_bundle_hash is not None
    fresh = ServingHandle.load(database, repository)
    assert fresh.bundle_hash == impact.withdrawn_bundle_hash
    corrected_entry = fresh.manifest.entry_for(corrected_target.target_id)
    assert corrected_entry.status == "unavailable"
    assert corrected_entry.reason == "corrected_dependency"
    safe_entry = fresh.manifest.entry_for(safe_target.target_id)
    assert safe_entry.status == "qualified"
    assert safe_entry.artifact_hash == safe_head_hash

    # the withdrawn bundle is new; the prior bundle stays addressable, untouched.
    assert handle.bundle_hash != fresh.bundle_hash
    assert handle.manifest.entry_for(corrected_target.target_id).status == "qualified"


@pytest.mark.integration
def test_a_non_critical_correction_never_touches_serving(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    bundle_target_definitions: Definitions,
    standardization: Standardization,
    head_weights: tuple[float, ...],
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path)
    target = bundle_target_definitions[0]
    head_hash = publish_head(
        repository,
        PublishedHead(
            target_id=target.target_id,
            target_definition_hash=_definition_hash(target),
            weights=head_weights,
            intercept=0.0,
            standardization=standardization,
            calibrations=CALIBRATIONS,
            representation_hash=REPRESENTATION_HASH,
            target_registry_hash=TARGET_REGISTRY_HASH,
            development_brier=0.2,
        ),
        producer_version=producer_version,
    )
    entries = (
        BundleTargetEntry(
            target.target_id, _definition_hash(target), "qualified", head_hash, None
        ),
        _unavailable(bundle_target_definitions[1]),
        _unavailable(bundle_target_definitions[2]),
    )
    manifest = BundleManifest(
        TARGET_REGISTRY_HASH,
        REPRESENTATION_HASH,
        entries,
        producer_version,
        "2026-02-01T00:00:00.000000Z",
    )
    activate_bundle(database, repository, manifest)
    handle = ServingHandle.load(database, repository)

    correction = Correction(
        "label", head_hash, "audit note only", "2026-02-10T00:00:00.000000Z"
    )
    impact = apply_correction(
        database,
        repository,
        correction,
        critical=False,
        current_handle=handle,
        producer_version=producer_version,
    )
    assert impact.withdrawn_bundle_hash is None
    still = ServingHandle.load(database, repository)
    assert still.bundle_hash == handle.bundle_hash


def test_correction_rejects_an_unadmitted_kind() -> None:
    with pytest.raises(LineageError):
        Correction("weight", "a" * 64, "reason", "2026-01-01T00:00:00.000000Z")
