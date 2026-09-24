"""Atomic prediction-head bundle activation (SDD PL-14).

TDD-1.1.21: activation switches the pointer by one transactional append;
a handle already held before a promotion keeps resolving its own manifest
after a new one activates, and every response names exactly one bundle.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.learning import PRIMARY_CATEGORY_IDS, TargetDefinition
from research_agent.learning.features import Standardization
from research_agent.models.registry import (
    ActivationResult,
    BundleManifest,
    BundleTargetEntry,
    CategoryCalibrator,
    PublishedHead,
    RegistryError,
    ServingHandle,
    activate_bundle,
    publish_head,
)
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database

TARGET_REGISTRY_HASH = sha256(b"registry-fixture").hexdigest()
REPRESENTATION_HASH = sha256(b"representation-fixture").hexdigest()

Definitions = tuple[TargetDefinition, TargetDefinition, TargetDefinition]
Entries = tuple[BundleTargetEntry, BundleTargetEntry, BundleTargetEntry]


def _repository(dsn: str, tmp_path: Path) -> ArtifactRepository:
    return ArtifactRepository(Database(dsn), ArtifactStore(tmp_path / "artifacts"))


def _definition_hash(definition: TargetDefinition) -> str:
    return sha256(definition.to_canonical_json()).hexdigest()


def _head(
    definition: TargetDefinition,
    standardization: Standardization,
    weights: tuple[float, ...],
) -> PublishedHead:
    return PublishedHead(
        target_id=definition.target_id,
        target_definition_hash=_definition_hash(definition),
        weights=weights,
        intercept=0.1,
        standardization=standardization,
        calibrations=tuple(
            CategoryCalibrator(category, "qualified", None, 1.0, 0.0)
            for category in PRIMARY_CATEGORY_IDS
        ),
        representation_hash=REPRESENTATION_HASH,
        target_registry_hash=TARGET_REGISTRY_HASH,
        development_brier=0.2,
    )


def _unavailable(definition: TargetDefinition) -> BundleTargetEntry:
    return BundleTargetEntry(
        definition.target_id,
        _definition_hash(definition),
        "unavailable",
        None,
        "never_fit",
    )


def _qualified(definition: TargetDefinition, artifact_hash: str) -> BundleTargetEntry:
    return BundleTargetEntry(
        definition.target_id,
        _definition_hash(definition),
        "qualified",
        artifact_hash,
        None,
    )


def _manifest(
    definitions: Definitions,
    entries: Entries,
    producer_version: ProducerVersion,
    *,
    created_at: str = "2026-01-05T00:00:00.000000Z",
) -> BundleManifest:
    assert tuple(e.target_id for e in entries) == tuple(
        d.target_id for d in definitions
    )
    return BundleManifest(
        TARGET_REGISTRY_HASH, REPRESENTATION_HASH, entries, producer_version, created_at
    )


def _all_unavailable(definitions: Definitions) -> Entries:
    return (
        _unavailable(definitions[0]),
        _unavailable(definitions[1]),
        _unavailable(definitions[2]),
    )


@pytest.mark.integration
def test_activation_publishes_and_swaps_the_pointer_atomically(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    bundle_target_definitions: Definitions,
    standardization: Standardization,
    head_weights: tuple[float, ...],
) -> None:
    repository = _repository(postgres_dsn, tmp_path)
    first_target = bundle_target_definitions[0]
    head_hash = publish_head(
        repository,
        _head(first_target, standardization, head_weights),
        producer_version=producer_version,
    )
    entries: Entries = (
        _qualified(first_target, head_hash),
        _unavailable(bundle_target_definitions[1]),
        _unavailable(bundle_target_definitions[2]),
    )
    manifest = _manifest(bundle_target_definitions, entries, producer_version)

    result = activate_bundle(Database(postgres_dsn), repository, manifest)
    assert isinstance(result, ActivationResult)
    assert result.bundle_hash == sha256(manifest.to_canonical_json()).hexdigest()

    handle = ServingHandle.load(Database(postgres_dsn), repository)
    assert handle.bundle_hash == result.bundle_hash
    assert handle.generation == result.generation
    assert handle.manifest.entry_for(first_target.target_id).artifact_hash == head_hash


@pytest.mark.integration
def test_activating_the_active_manifest_again_appends_nothing(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    bundle_target_definitions: Definitions,
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path)
    manifest = _manifest(
        bundle_target_definitions,
        _all_unavailable(bundle_target_definitions),
        producer_version,
    )
    first = activate_bundle(database, repository, manifest)
    again = activate_bundle(database, repository, manifest)

    assert not first.already_active
    assert again == ActivationResult(first.bundle_hash, first.generation, True)
    count = database.transaction(
        lambda connection: connection.execute(
            "SELECT count(*) FROM ledger_records WHERE event_kind = 'bundle_activated'"
        ).fetchone()
    )
    assert count == (1,)


@pytest.mark.integration
def test_a_handle_held_before_a_new_activation_keeps_its_own_manifest(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    bundle_target_definitions: Definitions,
    standardization: Standardization,
    head_weights: tuple[float, ...],
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path)
    old_manifest = _manifest(
        bundle_target_definitions,
        _all_unavailable(bundle_target_definitions),
        producer_version,
    )
    activate_bundle(database, repository, old_manifest)
    held = ServingHandle.load(database, repository)

    first_target = bundle_target_definitions[0]
    head_hash = publish_head(
        repository,
        _head(first_target, standardization, head_weights),
        producer_version=producer_version,
    )
    new_entries: Entries = (
        _qualified(first_target, head_hash),
        _unavailable(bundle_target_definitions[1]),
        _unavailable(bundle_target_definitions[2]),
    )
    new_manifest = _manifest(
        bundle_target_definitions,
        new_entries,
        producer_version,
        created_at="2026-01-12T00:00:00.000000Z",
    )
    activate_bundle(database, repository, new_manifest)

    assert held.bundle_hash == sha256(old_manifest.to_canonical_json()).hexdigest()
    assert held.manifest.entry_for(first_target.target_id).status == "unavailable"

    fresh = ServingHandle.load(database, repository)
    assert fresh.bundle_hash == sha256(new_manifest.to_canonical_json()).hexdigest()
    assert fresh.generation > held.generation
    assert fresh.manifest.entry_for(first_target.target_id).artifact_hash == head_hash


@pytest.mark.integration
def test_serving_handle_load_fails_when_no_bundle_was_ever_activated(
    postgres_dsn: str, tmp_path: Path
) -> None:
    with pytest.raises(RegistryError):
        ServingHandle.load(Database(postgres_dsn), _repository(postgres_dsn, tmp_path))


@pytest.mark.integration
def test_activation_refuses_a_qualified_entry_whose_head_is_unreadable(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    bundle_target_definitions: Definitions,
) -> None:
    repository = _repository(postgres_dsn, tmp_path)
    first_target = bundle_target_definitions[0]
    phantom_hash = sha256(b"never-published").hexdigest()
    entries: Entries = (
        _qualified(first_target, phantom_hash),
        _unavailable(bundle_target_definitions[1]),
        _unavailable(bundle_target_definitions[2]),
    )
    manifest = _manifest(bundle_target_definitions, entries, producer_version)
    with pytest.raises(Exception):  # noqa: B017
        activate_bundle(Database(postgres_dsn), repository, manifest)
