from hashlib import sha256

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.builds import (
    MANIFEST_HASH_LABEL,
    BuildManifest,
    ObservedImage,
    build_run_stamp,
    verify_lock_integrity,
)

SOURCE_TREE_HASH = "a" * 64
LOCK_BYTES = b"uv.lock contents"
BASE_IMAGE_DIGEST = "b" * 64
PACKAGE_HASH = "c" * 64


def _manifest(**overrides: object) -> BuildManifest:
    values: dict[str, object] = {
        "source_tree_hash": SOURCE_TREE_HASH,
        "python_version": "3.12.12",
        "tool_versions": {
            "uv": "0.8.22",
            "ruff": "0.13.0",
            "mypy": "1.18.1",
            "pytest": "8.4.2",
        },
        "uv_lock_hash": sha256(LOCK_BYTES).hexdigest(),
        "base_image_digest": BASE_IMAGE_DIGEST,
        "base_image_tag": "v0.1.0",
        "package_hashes": (PACKAGE_HASH,),
        "model_runtime_identities": {"agent_model": "glm-5.3-flash"},
        "product_version": "0.1.0",
        "evidence_documents": {"docs/evidence/source-pilot/access-rules.md": "d" * 64},
        "architecture": "amd64",
    }
    values.update(overrides)
    return BuildManifest(**values)  # type: ignore[arg-type]


def test_build_manifest_rejects_a_floating_base_image_tag() -> None:
    with pytest.raises(ContractValidationError):
        _manifest(base_image_tag="latest")


def test_build_manifest_rejects_empty_package_hashes() -> None:
    with pytest.raises(ContractValidationError):
        _manifest(package_hashes=())


def test_oci_labels_carry_the_product_version_and_manifest_hash() -> None:
    manifest = _manifest()
    labels = manifest.oci_labels()
    assert labels[MANIFEST_HASH_LABEL] == manifest.manifest_hash()


def test_verify_lock_integrity_passes_for_the_exact_recorded_bytes() -> None:
    manifest = _manifest()
    assert verify_lock_integrity(manifest, LOCK_BYTES)


def test_verify_lock_integrity_rejects_an_altered_lock_file() -> None:
    manifest = _manifest()
    assert not verify_lock_integrity(manifest, LOCK_BYTES + b" tampered")


def test_build_run_stamp_carries_observed_digests_and_labels() -> None:
    manifest = _manifest()
    observed = (
        ObservedImage(
            role="storage",
            image_digest=BASE_IMAGE_DIGEST,
            labels={MANIFEST_HASH_LABEL: manifest.manifest_hash()},
        ),
    )
    stamp = build_run_stamp(manifest, observed)
    assert stamp.observed_images == observed
    assert stamp.manifest_hash == manifest.manifest_hash()


def test_build_run_stamp_rejects_a_container_whose_label_does_not_match() -> None:
    manifest = _manifest()
    observed = (
        ObservedImage(role="storage", image_digest=BASE_IMAGE_DIGEST, labels={}),
    )
    with pytest.raises(ContractValidationError):
        build_run_stamp(manifest, observed)
