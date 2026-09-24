import json

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.builds import BuildManifest, ImageRecord


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
