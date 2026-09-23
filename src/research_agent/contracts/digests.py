"""Strict wire contracts for storage-owned digest persistence (#179)."""

from __future__ import annotations

import re
from typing import Any

from .primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_probability,
    validate_sha256,
    validate_uuid4,
)

DIGEST_ISLANDS = frozenset({"cs", "quant-ph", "q-bio"})
DIGEST_ORIGINS = frozenset({"population", "random_control", "service"})
ENTRY_LIMIT = 12
NOMINATION_LIMIT = 100

_SHUFFLE_SEED = re.compile(r"[0-9a-f]{16}\Z")


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _validate_shuffle_seed(value: object) -> str:
    if not isinstance(value, str) or _SHUFFLE_SEED.fullmatch(value) is None:
        raise ContractValidationError(
            "shuffle_seed must be 16 lowercase hexadecimal characters"
        )
    return value


def _entry(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError("DigestEntry must be a JSON object")
    entry = _closed(
        value,
        {
            "entry_id",
            "paper_hash",
            "origin",
            "display_position",
            "service_source",
            "candidate_pool_hash",
            "inclusion_probability",
        },
        "DigestEntry",
    )
    origin = entry["origin"]
    if origin not in DIGEST_ORIGINS:
        raise ContractValidationError("DigestEntry.origin is not an admitted value")
    service_source = entry["service_source"]
    if (service_source is not None) != (origin == "service"):
        raise ContractValidationError(
            "DigestEntry.service_source must be set only for a service entry"
        )
    candidate_pool_hash = entry["candidate_pool_hash"]
    if (candidate_pool_hash is not None) != (origin == "random_control"):
        raise ContractValidationError(
            "DigestEntry.candidate_pool_hash must be set only for a random_control entry"
        )
    inclusion_probability = entry["inclusion_probability"]
    if inclusion_probability is not None and origin != "random_control":
        raise ContractValidationError(
            "DigestEntry.inclusion_probability must be set only for a random_control entry"
        )
    return {
        "entry_id": validate_uuid4(entry["entry_id"]),
        "paper_hash": validate_sha256(entry["paper_hash"]),
        "origin": origin,
        "display_position": validate_non_negative_int(entry["display_position"]),
        "service_source": validate_non_empty_string(service_source)
        if service_source is not None
        else None,
        "candidate_pool_hash": validate_sha256(candidate_pool_hash)
        if candidate_pool_hash is not None
        else None,
        "inclusion_probability": validate_probability(inclusion_probability)
        if inclusion_probability is not None
        else None,
    }


def _entries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > ENTRY_LIMIT:
        raise ContractValidationError(
            f"entries must be a JSON array with at most {ENTRY_LIMIT} items"
        )
    entries = [_entry(item) for item in value]
    ids = [entry["entry_id"] for entry in entries]
    positions = [entry["display_position"] for entry in entries]
    papers = [entry["paper_hash"] for entry in entries]
    if len(set(ids)) != len(ids):
        raise ContractValidationError("entries must name distinct entry_id")
    if len(set(positions)) != len(positions):
        raise ContractValidationError("entries must name distinct display_position")
    if len(set(papers)) != len(papers):
        raise ContractValidationError("entries must name distinct paper_hash")
    return entries


def _nomination(value: object, entry_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError("DigestNomination must be a JSON object")
    nomination = _closed(
        value,
        {"entry_id", "configuration_id", "submission_id", "preference"},
        "DigestNomination",
    )
    entry_id = validate_uuid4(nomination["entry_id"])
    if entry_id not in entry_ids:
        raise ContractValidationError(
            "DigestNomination.entry_id is not one of this digest's entries"
        )
    preference = nomination["preference"]
    if (
        isinstance(preference, bool)
        or not isinstance(preference, int)
        or not 1 <= preference <= 7
    ):
        raise ContractValidationError("DigestNomination.preference must be from 1 to 7")
    return {
        "entry_id": entry_id,
        "configuration_id": validate_uuid4(nomination["configuration_id"]),
        "submission_id": validate_uuid4(nomination["submission_id"]),
        "preference": preference,
    }


def _nominations(value: object, entry_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > NOMINATION_LIMIT:
        raise ContractValidationError(
            f"nominations must be a JSON array with at most {NOMINATION_LIMIT} items"
        )
    nominations = [_nomination(item, entry_ids) for item in value]
    pairs = [(item["entry_id"], item["configuration_id"]) for item in nominations]
    if len(set(pairs)) != len(pairs):
        raise ContractValidationError(
            "nominations must name distinct entry_id and configuration_id pairs"
        )
    return nominations


def validate_digest_store_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a digest-store operation.

    The caller supplies an already-built digest (EN-40's ``DigestManifest``,
    resolved to real paper hashes) plus the nominating link storage has no
    other way to learn; this only checks shape, admitted values and internal
    cross references, never business rules that depend on other stored state.
    """

    if operation != "store":
        raise ContractValidationError("unknown digest operation")
    value = _closed(
        payload,
        {
            "digest_hash",
            "batch_id",
            "island",
            "source_watermark",
            "shuffle_seed",
            "entries",
            "nominations",
        },
        "store payload",
    )
    island = value["island"]
    if not isinstance(island, str) or island not in DIGEST_ISLANDS:
        raise ContractValidationError("island is not an admitted value")
    entries = _entries(value["entries"])
    entry_ids = {entry["entry_id"] for entry in entries}
    nominations = _nominations(value["nominations"], entry_ids)
    return {
        "digest_hash": validate_sha256(value["digest_hash"]),
        "batch_id": validate_sha256(value["batch_id"]),
        "island": island,
        "source_watermark": validate_non_negative_int(value["source_watermark"]),
        "shuffle_seed": _validate_shuffle_seed(value["shuffle_seed"]),
        "entries": entries,
        "nominations": nominations,
    }
