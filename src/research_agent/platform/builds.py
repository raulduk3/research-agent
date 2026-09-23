"""Reproducible build and run identities (SDD-PL-06).

`BuildManifest` fixes what a releasable image must carry: a source tree
hash, pinned tool versions, the uv lock hash, a pinned base-image digest
rather than a floating human tag, ordered package hashes and the selected
model/runtime identities. `verify_lock_integrity` is the check that an
altered lock file is detected against the manifest's recorded hash before a
release proceeds. `build_run_stamp` inspects the images a set of actually
started containers report, never the build configuration alone, matching
PL-06's "run stamps inspect actual selected containers" rule; a container
whose observed labels do not carry this exact manifest hash fails the stamp.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
)

# Human image tags that never pin a specific build; PL-06 requires a
# releasable image to be selected by digest, never one of these.
FLOATING_TAGS: frozenset[str] = frozenset(
    {"latest", "main", "master", "stable", "edge"}
)

MANIFEST_HASH_LABEL: str = "org.research-agent.manifest_hash"
PRODUCT_VERSION_LABEL: str = "org.research-agent.version"


@dataclass(frozen=True, slots=True)
class BuildManifest:
    """The pinned inputs and identities one releasable image build carries."""

    source_tree_hash: str
    python_version: str
    tool_versions: Mapping[str, str]
    uv_lock_hash: str
    base_image_digest: str
    base_image_tag: str
    package_hashes: tuple[str, ...]
    model_runtime_identities: Mapping[str, str]
    product_version: str

    def __post_init__(self) -> None:
        validate_sha256(self.source_tree_hash)
        validate_non_empty_string(self.python_version)
        if not self.tool_versions:
            raise ContractValidationError("tool_versions must be nonempty")
        for value in self.tool_versions.values():
            validate_non_empty_string(value)
        validate_sha256(self.uv_lock_hash)
        validate_sha256(self.base_image_digest)
        validate_non_empty_string(self.base_image_tag)
        if self.base_image_tag in FLOATING_TAGS:
            raise ContractValidationError(
                "base_image_tag must not be a floating tag; select by digest"
            )
        if not self.package_hashes:
            raise ContractValidationError("package_hashes must be nonempty")
        for value in self.package_hashes:
            validate_sha256(value)
        if not self.model_runtime_identities:
            raise ContractValidationError("model_runtime_identities must be nonempty")
        for value in self.model_runtime_identities.values():
            validate_non_empty_string(value)
        validate_non_empty_string(self.product_version)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_tree_hash": self.source_tree_hash,
            "python_version": self.python_version,
            "tool_versions": dict(self.tool_versions),
            "uv_lock_hash": self.uv_lock_hash,
            "base_image_digest": self.base_image_digest,
            "base_image_tag": self.base_image_tag,
            "package_hashes": list(self.package_hashes),
            "model_runtime_identities": dict(self.model_runtime_identities),
            "product_version": self.product_version,
        }

    def manifest_hash(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))

    def oci_labels(self) -> dict[str, str]:
        return {
            PRODUCT_VERSION_LABEL: self.product_version,
            MANIFEST_HASH_LABEL: self.manifest_hash(),
        }


def verify_lock_integrity(manifest: BuildManifest, lock_file_bytes: bytes) -> bool:
    """Whether *lock_file_bytes* still hashes to the manifest's recorded lock hash."""

    return manifest.uv_lock_hash == sha256_hex(lock_file_bytes)


@dataclass(frozen=True, slots=True)
class ObservedImage:
    """The image digest and OCI labels one actually started container reports."""

    role: str
    image_digest: str
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        validate_non_empty_string(self.role)
        validate_sha256(self.image_digest)


@dataclass(frozen=True, slots=True)
class RunStamp:
    """The manifest identity a set of observed running containers actually carry."""

    manifest_hash: str
    observed_images: tuple[ObservedImage, ...]


def build_run_stamp(
    manifest: BuildManifest, observed: tuple[ObservedImage, ...]
) -> RunStamp:
    """Build a run stamp from actually observed containers, never build configuration alone."""

    expected_hash = manifest.manifest_hash()
    for image in observed:
        if image.labels.get(MANIFEST_HASH_LABEL) != expected_hash:
            raise ContractValidationError(
                f"observed image for role '{image.role}' does not carry this build's "
                "manifest hash label"
            )
    return RunStamp(manifest_hash=expected_hash, observed_images=observed)
