import json
import re
import shutil
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.ingest import bulk, daily, pilot_run
from research_agent.platform.builds import (
    EVIDENCE_DOCUMENTS,
    BuildManifest,
    ImageRecord,
    manifest_from_tree,
)

ROOT = Path(__file__).resolve().parents[2]
_GIT_USER = ("-c", "user.name=builder", "-c", "user.email=builder@example.test")


def _manifest() -> BuildManifest:
    return BuildManifest(
        source_tree_hash="a" * 64,
        python_version="3.12.12",
        tool_versions={"uv": "0.8.22", "docker": "29.8.1"},
        uv_lock_hash="b" * 64,
        base_image_digest="c" * 64,
        base_image_tag="3.12.12-slim-bookworm",
        package_hashes=("d" * 64, "e" * 64),
        model_runtime_identities={"torch": "2.14.0", "transformers": "5.17.0"},
        product_version="0.1.1-main.3+0123abcd",
        evidence_documents={"docs/evidence/source-pilot/access-rules.md": "0" * 64},
    )


def _record() -> ImageRecord:
    return ImageRecord(
        image_digest="f" * 64, source_commit="1" * 40, manifest=_manifest()
    )


def test_image_record_round_trips_through_its_json() -> None:
    record = _record()
    assert ImageRecord.from_json(record.to_json()) == record


def test_image_record_json_carries_the_label_manifest_hash() -> None:
    record = _record()
    value = json.loads(record.to_json())
    assert (
        value["manifest_hash"]
        == record.manifest.oci_labels()["org.research-agent.manifest_hash"]
    )


def test_image_record_refuses_a_manifest_edited_after_the_build() -> None:
    value = json.loads(_record().to_json())
    value["manifest"]["uv_lock_hash"] = "9" * 64
    with pytest.raises(ContractValidationError):
        ImageRecord.from_json(json.dumps(value))


def test_image_record_refuses_an_undeclared_field() -> None:
    value = json.loads(_record().to_json())
    value["tag"] = "latest"
    with pytest.raises(ContractValidationError):
        ImageRecord.from_json(json.dumps(value))


def test_image_record_refuses_an_abbreviated_commit() -> None:
    with pytest.raises(ContractValidationError):
        ImageRecord(
            image_digest="f" * 64, source_commit="1234abcd", manifest=_manifest()
        )


def test_a_manifest_without_evidence_documents_is_refused() -> None:
    value = json.loads(_record().to_json())
    del value["manifest"]["evidence_documents"]
    with pytest.raises(ContractValidationError):
        ImageRecord.from_json(json.dumps(value))
    with pytest.raises(ContractValidationError):
        replace(_manifest(), evidence_documents={})
    with pytest.raises(ContractValidationError):
        replace(_manifest(), evidence_documents={EVIDENCE_DOCUMENTS: "latest"})


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(("git", "-C", str(root), *_GIT_USER, *arguments), check=True)


def _committed_tree(root: Path) -> Path:
    for name in ("Dockerfile", "uv.lock", "pyproject.toml"):
        shutil.copy(ROOT / name, root / name)
    shutil.copytree(ROOT / EVIDENCE_DOCUMENTS, root / EVIDENCE_DOCUMENTS)
    _git(root, "init", "-q", "-b", "develop")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "tree")
    _git(root, "tag", "v0.1.0")
    return root


def test_manifest_lists_every_evidence_document_with_the_hash_ingest_reads(
    tmp_path: Path,
) -> None:
    root = _committed_tree(tmp_path)
    _, manifest = manifest_from_tree(root, engine_version="29.8.1")
    shipped = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / EVIDENCE_DOCUMENTS).rglob("*")
        if path.is_file()
    )
    assert sorted(manifest.evidence_documents) == shipped
    # Daily ingest hashes the same bytes into its identity as the manifest.
    access_rules = daily._ACCESS_RULES.relative_to(daily._ROOT).as_posix()
    assert (
        manifest.evidence_documents[access_rules]
        == sha256(daily._ACCESS_RULES.read_bytes()).hexdigest()
    )

    # Editing a document changes the recorded image identity.
    (root / access_rules).write_text("edited\n")
    _git(root, "commit", "-q", "-am", "edit")
    _, edited = manifest_from_tree(root, engine_version="29.8.1")
    assert edited.manifest_hash() != manifest.manifest_hash()


def test_the_image_ships_every_document_the_runtime_reads() -> None:
    read = (daily._ACCESS_RULES, pilot_run._ACCESS_RULES, bulk._EVIDENCE_PATH)
    for path in read:
        assert path.relative_to(ROOT).is_relative_to(EVIDENCE_DOCUMENTS)
    named = [
        line
        for path in (ROOT / "src").rglob("*.py")
        for line in re.findall(r'^_\w+ = _ROOT / "docs"', path.read_text(), re.M)
    ]
    assert len(named) == len(read)
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert f"COPY {EVIDENCE_DOCUMENTS} ./{EVIDENCE_DOCUMENTS}\n" in dockerfile
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    assert ignored.index(f"!{EVIDENCE_DOCUMENTS}/") > ignored.index("docs")
