from dataclasses import replace

import pytest

from research_agent.contracts import ProducerVersion, RecordMeta, sha256_hex
from research_agent.outcomes.targets import definitions, TARGET_ORDER


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
