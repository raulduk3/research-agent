"""Strict wire contracts for storage-owned frozen snapshot records."""

from __future__ import annotations

from typing import Any

from .canonical import canonical_json, sha256_hex
from .primitives import ContractValidationError, validate_sha256, validate_uuid4


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _index_identity_hashes(value: object) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 10:
        raise ContractValidationError(
            "index_identity_hashes must be a JSON array with 1 to 10 items"
        )
    hashes = [validate_sha256(item) for item in value]
    if len(set(hashes)) != len(hashes):
        raise ContractValidationError("index_identity_hashes must be distinct")
    return hashes


def _optional_sha256(value: object) -> str | None:
    return None if value is None else validate_sha256(value)


def _snapshot_item(value: object) -> dict[str, Any]:
    item = _closed(
        value,
        {
            "paper_family_id",
            "paper_version_id",
            "card_hash",
            "overview_hash",
            "passage_index_hash",
            "graph_hash",
        },
        "SnapshotItem",
    )
    return {
        "paper_family_id": validate_uuid4(item["paper_family_id"]),
        "paper_version_id": validate_uuid4(item["paper_version_id"]),
        "card_hash": validate_sha256(item["card_hash"]),
        "overview_hash": _optional_sha256(item["overview_hash"]),
        "passage_index_hash": _optional_sha256(item["passage_index_hash"]),
        "graph_hash": _optional_sha256(item["graph_hash"]),
    }


def _snapshot_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 1000:
        raise ContractValidationError(
            "items must be a JSON array with 1 to 1000 entries"
        )
    items = [_snapshot_item(item) for item in value]
    version_ids = [item["paper_version_id"] for item in items]
    if len(set(version_ids)) != len(version_ids):
        raise ContractValidationError("items must not repeat a paper_version_id")
    return items


def validate_snapshot_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a snapshot-record operation."""

    if operation == "seal":
        value = _closed(
            payload, {"paper_manifest_hash", "index_identity_hashes"}, "seal payload"
        )
        return {
            "paper_manifest_hash": validate_sha256(value["paper_manifest_hash"]),
            "index_identity_hashes": _index_identity_hashes(
                value["index_identity_hashes"]
            ),
        }
    if operation == "pin_items":
        value = _closed(
            payload, {"snapshot_hash", "sheet_hash", "items"}, "pin_items payload"
        )
        return {
            "snapshot_hash": validate_sha256(value["snapshot_hash"]),
            "sheet_hash": validate_sha256(value["sheet_hash"]),
            "items": _snapshot_items(value["items"]),
        }
    raise ContractValidationError("unknown snapshot operation")


def snapshot_identity(
    paper_manifest_hash: str, index_identity_hashes: list[str]
) -> str:
    """Return the content-addressed identity of a frozen snapshot.

    Recomputing this from the same pinned inputs always reproduces the same
    hash, independent of when or by whom the snapshot was sealed (AG-10, EN-10).
    """

    return sha256_hex(
        canonical_json(
            {
                "schema_version": 1,
                "paper_manifest_hash": paper_manifest_hash,
                "index_identity_hashes": index_identity_hashes,
            }
        )
    )
