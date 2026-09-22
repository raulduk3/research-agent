from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.snapshots import (
    snapshot_identity,
    validate_snapshot_payload,
)

HASH = "a" * 64
INDEX_HASH = "b" * 64
OTHER_INDEX_HASH = "c" * 64
PAYLOAD = {
    "paper_manifest_hash": HASH,
    "index_identity_hashes": [INDEX_HASH],
}


def test_seal_accepts_the_normative_shape() -> None:
    assert validate_snapshot_payload("seal", PAYLOAD) == PAYLOAD


def test_seal_rejects_unknown_fields_empty_and_duplicate_indexes() -> None:
    with pytest.raises(ContractValidationError):
        validate_snapshot_payload("seal", {**PAYLOAD, "extra": True})
    with pytest.raises(ContractValidationError):
        validate_snapshot_payload("seal", {**PAYLOAD, "index_identity_hashes": []})
    with pytest.raises(ContractValidationError):
        validate_snapshot_payload(
            "seal", {**PAYLOAD, "index_identity_hashes": [INDEX_HASH, INDEX_HASH]}
        )


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(ContractValidationError):
        validate_snapshot_payload("delete", PAYLOAD)


def test_snapshot_identity_is_content_addressed_and_order_sensitive() -> None:
    first = snapshot_identity(HASH, [INDEX_HASH, OTHER_INDEX_HASH])
    again = snapshot_identity(HASH, [INDEX_HASH, OTHER_INDEX_HASH])
    reordered = snapshot_identity(HASH, [OTHER_INDEX_HASH, INDEX_HASH])
    altered = snapshot_identity(HASH, [INDEX_HASH])
    assert first == again
    assert first != reordered
    assert first != altered
