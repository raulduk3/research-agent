from dataclasses import replace

import pytest

from research_agent.contracts import ProducerVersion, RecordMeta, sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.outcomes.targets import (
    TARGET_ORDER,
    definitions,
    registry,
    validate_extension,
)

META = RecordMeta(
    1,
    (),
    ProducerVersion("a" * 64, "b" * 40, 1),
    "c" * 64,
    "2026-01-01T00:00:00.000000Z",
)


def test_registry_fixed_order_and_threshold_identity() -> None:
    meta = RecordMeta(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        "2026-01-01T00:00:00.000000Z",
    )
    first, second = definitions(meta), definitions(meta)
    assert tuple(target.target_id for target in first) == TARGET_ORDER
    assert tuple(target.threshold for target in first) == (5, 1, 2)
    assert [sha256_hex(item.to_canonical_json()) for item in first] == [
        sha256_hex(item.to_canonical_json()) for item in second
    ]
    assert len({sha256_hex(item.to_canonical_json()) for item in first}) == 3
    for target in first:
        with pytest.raises(ValueError):
            replace(target, threshold=target.threshold + 1)
        with pytest.raises(ValueError):
            replace(target, source="unadmitted")


def test_validate_extension_accepts_an_admitted_target_with_a_manifest() -> None:
    validate_extension(
        registry(META),
        previous_order=TARGET_ORDER,
        requested_target_id=TARGET_ORDER[0],
        qualification_manifest_hash="a" * 64,
    )
    validate_extension(
        registry(META),
        previous_order=TARGET_ORDER[:1],
        requested_target_id=TARGET_ORDER[0],
        qualification_manifest_hash="a" * 64,
    )


def test_validate_extension_rejects_an_unknown_target() -> None:
    with pytest.raises(ContractValidationError, match="accepted definition"):
        validate_extension(
            registry(META),
            previous_order=TARGET_ORDER,
            requested_target_id="citation_reach_2yr",
            qualification_manifest_hash="a" * 64,
        )


def test_validate_extension_requires_a_qualification_manifest() -> None:
    with pytest.raises(ContractValidationError, match="qualification manifest"):
        validate_extension(
            registry(META),
            previous_order=TARGET_ORDER,
            requested_target_id=TARGET_ORDER[0],
            qualification_manifest_hash=None,
        )


def test_validate_extension_rejects_a_changed_prior_snapshot_order() -> None:
    reordered = (TARGET_ORDER[1], TARGET_ORDER[0])
    with pytest.raises(ContractValidationError, match="prior snapshot"):
        validate_extension(
            registry(META),
            previous_order=reordered,
            requested_target_id=TARGET_ORDER[0],
            qualification_manifest_hash="a" * 64,
        )


def test_failed_extension_leaves_the_registry_usable() -> None:
    before = registry(META)
    with pytest.raises(ContractValidationError):
        validate_extension(
            before,
            previous_order=TARGET_ORDER,
            requested_target_id="unknown_target",
            qualification_manifest_hash=None,
        )
    after = registry(META)
    assert sha256_hex(before.to_canonical_json()) == sha256_hex(
        after.to_canonical_json()
    )
