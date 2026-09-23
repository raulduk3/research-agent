import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.persistence import (
    PersistentStores,
    VolumeBinding,
    compare_snapshots,
    verify_readonly_roots,
    verify_volume_readiness,
)


def _stores() -> PersistentStores:
    return PersistentStores(
        (
            VolumeBinding("ledger-data", "/var/lib/postgresql/data", "postgres", False),
            VolumeBinding(
                "artifact-data", "/var/lib/research-agent/artifacts", "storage", False
            ),
        )
    )


def test_persistent_stores_rejects_a_duplicate_volume_name() -> None:
    with pytest.raises(ContractValidationError):
        PersistentStores(
            (
                VolumeBinding("data", "/a", "storage", False),
                VolumeBinding("data", "/b", "storage", False),
            )
        )


def test_verify_readonly_roots_flags_a_writable_non_owning_role() -> None:
    violations = verify_readonly_roots(
        roles={"storage": True, "ingest": False, "postgres": True},
        owning_roles=frozenset({"storage", "postgres"}),
    )
    assert violations == ("ingest",)


def test_verify_volume_readiness_flags_a_missing_mount() -> None:
    stores = _stores()
    violations = verify_volume_readiness(
        stores.bindings,
        exists=lambda path: False,
        is_writable=lambda path: True,
        free_bytes=lambda path: 10**12,
        min_free_bytes={},
    )
    assert len(violations) == 2


def test_verify_volume_readiness_flags_insufficient_free_space() -> None:
    stores = _stores()
    violations = verify_volume_readiness(
        stores.bindings,
        exists=lambda path: True,
        is_writable=lambda path: True,
        free_bytes=lambda path: 1,
        min_free_bytes={"artifact-data": 10**9},
    )
    assert violations == ("artifact-data: free space below required minimum",)


def test_verify_volume_readiness_passes_a_healthy_deployment() -> None:
    stores = _stores()
    violations = verify_volume_readiness(
        stores.bindings,
        exists=lambda path: True,
        is_writable=lambda path: True,
        free_bytes=lambda path: 10**12,
        min_free_bytes={"artifact-data": 10**9},
    )
    assert violations == ()


def test_compare_snapshots_is_empty_when_bytes_are_unchanged_after_replacement() -> (
    None
):
    before = {"ledger": b"chain-bytes", "artifacts/a": b"blob"}
    after = {"ledger": b"chain-bytes", "artifacts/a": b"blob"}
    assert compare_snapshots(before, after) == ()


def test_compare_snapshots_flags_a_changed_or_missing_key() -> None:
    before = {"ledger": b"chain-bytes", "artifacts/a": b"blob"}
    after = {"ledger": b"tampered", "artifacts/b": b"blob"}
    mismatches = compare_snapshots(before, after)
    assert "ledger" in mismatches
    assert "artifacts/a" in mismatches
    assert "artifacts/b" in mismatches
