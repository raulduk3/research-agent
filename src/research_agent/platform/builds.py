"""Reproducible build and run identities (SDD-PL-06).

`BuildManifest` fixes what a releasable image must carry: a source tree
hash, pinned tool versions, the uv lock hash, a pinned base-image digest
rather than a floating human tag, ordered package hashes, the selected
model/runtime identities, the content hash of every evidence document
the image ships because the ingest runtime hashes it into its identity, and
the architecture the engine built for. `verify_lock_integrity` is the check that an
altered lock file is detected against the manifest's recorded hash before a
release proceeds. `build_run_stamp` inspects the images a set of actually
started containers report, never the build configuration alone, matching
PL-06's "run stamps inspect actual selected containers" rule; a container
whose observed labels do not carry this exact manifest hash fails the stamp.

`ImageRecord` is what `bin/build-image` writes to `deploy/images.json`: the
digest the engine reported for one build, the commit it was built from and
the manifest whose hash the image carries as a label. Reading it back
recomputes the manifest hash, so a hand-edited input cannot keep a stale one.
`main` is that command: it refuses a dirty tree, derives the manifest from
the committed tree, builds the `Dockerfile` for the engine's own
architecture with the manifest labels, refuses an image of any other
architecture and records the digest the engine reports. The representation
platform a batch was embedded on is recorded per batch, not here.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
)
from research_agent.platform.version import get_version

# Human image tags that never pin a specific build; PL-06 requires a
# releasable image to be selected by digest, never one of these.
FLOATING_TAGS: frozenset[str] = frozenset(
    {"latest", "main", "master", "stable", "edge"}
)

MANIFEST_HASH_LABEL: str = "org.research-agent.manifest_hash"
PRODUCT_VERSION_LABEL: str = "org.research-agent.version"

_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "source_tree_hash",
        "python_version",
        "tool_versions",
        "uv_lock_hash",
        "base_image_digest",
        "base_image_tag",
        "package_hashes",
        "model_runtime_identities",
        "product_version",
        "evidence_documents",
        "architecture",
    }
)
_RECORD_KEYS: frozenset[str] = frozenset(
    {"image_digest", "source_commit", "manifest_hash", "manifest"}
)
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_BASE_IMAGE = re.compile(
    r"^FROM\s+(?P<platform>--platform=\S+\s+)?[^\s:@]+:(?P<tag>[^\s@]+)@sha256:(?P<digest>[0-9a-f]{64})\s*$",
    re.MULTILINE,
)
# Packages whose locked versions identify the model runtime inside the image.
_RUNTIME_PACKAGES: tuple[str, ...] = ("torch", "transformers")
IMAGE_NAME: str = "research-agent"
IMAGES_RECORD: str = "deploy/images.json"
# The repository documents the runtime reads through `_ROOT / "docs"` and
# hashes into a day's or bulk job's identity; the `Dockerfile` copies this
# directory and `.dockerignore` admits it.
EVIDENCE_DOCUMENTS: str = "docs/evidence/source-pilot"
# Engine architectures an image may be built for; the base is pinned to its
# multi-architecture index so it resolves natively on either (#347).
ARCHITECTURES: frozenset[str] = frozenset({"amd64", "arm64"})


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
    evidence_documents: Mapping[str, str]
    architecture: str

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
        if not self.evidence_documents:
            raise ContractValidationError("evidence_documents must be nonempty")
        for path, value in self.evidence_documents.items():
            validate_non_empty_string(path)
            validate_sha256(value)
        if self.architecture not in ARCHITECTURES:
            raise ContractValidationError(
                f"architecture must be one of {sorted(ARCHITECTURES)}"
            )

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
            "evidence_documents": dict(self.evidence_documents),
            "architecture": self.architecture,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> BuildManifest:
        if set(value) != _MANIFEST_KEYS:
            raise ContractValidationError(
                "build manifest keys are not the declared set"
            )
        return cls(
            source_tree_hash=_text(value, "source_tree_hash"),
            python_version=_text(value, "python_version"),
            tool_versions=_text_mapping(value, "tool_versions"),
            uv_lock_hash=_text(value, "uv_lock_hash"),
            base_image_digest=_text(value, "base_image_digest"),
            base_image_tag=_text(value, "base_image_tag"),
            package_hashes=tuple(_text_list(value, "package_hashes")),
            model_runtime_identities=_text_mapping(value, "model_runtime_identities"),
            product_version=_text(value, "product_version"),
            evidence_documents=_text_mapping(value, "evidence_documents"),
            architecture=_text(value, "architecture"),
        )

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
class ImageRecord:
    """One built image: its engine-reported digest, source commit and manifest."""

    image_digest: str
    source_commit: str
    manifest: BuildManifest

    def __post_init__(self) -> None:
        validate_sha256(self.image_digest)
        if not _COMMIT.fullmatch(self.source_commit):
            raise ContractValidationError("source_commit must be a full commit id")

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "image_digest": self.image_digest,
                    "source_commit": self.source_commit,
                    "manifest_hash": self.manifest.manifest_hash(),
                    "manifest": self.manifest.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @classmethod
    def from_json(cls, text: str) -> ImageRecord:
        value = json.loads(text)
        if not isinstance(value, dict) or set(value) != _RECORD_KEYS:
            raise ContractValidationError("image record keys are not the declared set")
        manifest_value = value["manifest"]
        if not isinstance(manifest_value, dict):
            raise ContractValidationError("image record manifest must be an object")
        record = cls(
            image_digest=_text(value, "image_digest"),
            source_commit=_text(value, "source_commit"),
            manifest=BuildManifest.from_dict(manifest_value),
        )
        if _text(value, "manifest_hash") != record.manifest.manifest_hash():
            raise ContractValidationError(
                "recorded manifest hash does not match the recorded manifest"
            )
        return record


def _text(value: Mapping[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise ContractValidationError(f"{key} must be text")
    return item


def _text_list(value: Mapping[str, object], key: str) -> list[str]:
    item = value[key]
    if not isinstance(item, list) or not all(isinstance(part, str) for part in item):
        raise ContractValidationError(f"{key} must be a list of text")
    return item


def _text_mapping(value: Mapping[str, object], key: str) -> dict[str, str]:
    item = value[key]
    if not isinstance(item, dict) or not all(
        isinstance(name, str) and isinstance(part, str) for name, part in item.items()
    ):
        raise ContractValidationError(f"{key} must map text to text")
    return item


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


class BuildRefused(RuntimeError):
    """Raised when an image must not be built from the current tree."""


def _run(root: Path, *command: str) -> str:
    return subprocess.run(
        command, cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def check_built_architecture(manifest: BuildManifest, reported: str) -> None:
    """Refuse a built image whose architecture is not the one its manifest records."""

    if reported != manifest.architecture:
        raise BuildRefused(
            f"the engine built a {reported} image, not the {manifest.architecture} "
            "image its manifest records"
        )


def manifest_from_tree(
    root: Path, *, engine_version: str, architecture: str
) -> tuple[str, BuildManifest]:
    """The commit at HEAD and the manifest its committed build inputs declare."""

    commit = _run(root, "git", "rev-parse", "HEAD")
    listing = _run(root, "git", "ls-tree", "-r", "--full-tree", "HEAD")
    base = _BASE_IMAGE.search((root / "Dockerfile").read_text())
    if base is None:
        raise BuildRefused("the Dockerfile base image is not pinned by digest")
    if base["platform"]:
        raise BuildRefused(
            "the Dockerfile forces a platform; the base index resolves to the engine's"
        )
    lock_bytes = (root / "uv.lock").read_bytes()
    packages = sorted(
        tomllib.loads(lock_bytes.decode("utf-8"))["package"],
        # The project itself is locked without a version (it is dynamic).
        key=lambda package: (package["name"], package.get("version", "")),
    )
    versions = {package["name"]: package.get("version") for package in packages}
    project = tomllib.loads((root / "pyproject.toml").read_text())
    documents = _run(
        root, "git", "ls-tree", "-r", "--name-only", "HEAD", "--", EVIDENCE_DOCUMENTS
    ).splitlines()
    manifest = BuildManifest(
        source_tree_hash=sha256_hex(listing.encode("utf-8")),
        python_version=project["project"]["requires-python"].removeprefix("=="),
        tool_versions={
            "uv": project["tool"]["uv"]["required-version"].removeprefix("=="),
            "docker": engine_version,
        },
        uv_lock_hash=sha256_hex(lock_bytes),
        base_image_digest=base["digest"],
        base_image_tag=base["tag"],
        package_hashes=tuple(
            sha256_hex(canonical_json(package)) for package in packages
        ),
        model_runtime_identities={name: versions[name] for name in _RUNTIME_PACKAGES},
        product_version=get_version(root),
        evidence_documents={
            path: sha256_hex((root / path).read_bytes()) for path in sorted(documents)
        },
        architecture=architecture,
    )
    return commit, manifest


def build_image(root: Path) -> ImageRecord:
    """Build the Dockerfile from a clean tree and record the engine's digest."""

    if _run(root, "git", "status", "--porcelain", "--untracked-files=normal"):
        raise BuildRefused("the working tree has uncommitted changes")
    engine, architecture = _run(
        root, "docker", "version", "--format", "{{.Server.Version}} {{.Server.Arch}}"
    ).split()
    commit, manifest = manifest_from_tree(
        root, engine_version=engine, architecture=architecture
    )
    tag = re.sub(r"[^A-Za-z0-9_.-]", "-", manifest.product_version)[:128]
    labels = [
        argument
        for name, value in manifest.oci_labels().items()
        for argument in ("--label", f"{name}={value}")
    ]
    with tempfile.TemporaryDirectory() as scratch:
        iidfile = Path(scratch) / "image-id"
        subprocess.run(
            (
                "docker",
                "build",
                *labels,
                "--iidfile",
                str(iidfile),
                "--tag",
                f"{IMAGE_NAME}:{tag}",
                ".",
            ),
            cwd=root,
            check=True,
        )
        image_id = iidfile.read_text().strip()
    check_built_architecture(
        manifest,
        _run(
            root,
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Architecture}}",
            image_id,
        ),
    )
    record = ImageRecord(
        image_digest=image_id.removeprefix("sha256:"),
        source_commit=commit,
        manifest=manifest,
    )
    (root / IMAGES_RECORD).write_text(record.to_json())
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the application image and record its digest."
    )
    parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    try:
        record = build_image(root)
    except BuildRefused as error:
        print(f"Build refused: {error}.", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1
    print(f"Recorded {IMAGES_RECORD} for {record.source_commit}.")
    print(f"RESEARCH_AGENT_IMAGE_DIGEST={record.image_digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
