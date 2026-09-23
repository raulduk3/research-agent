from datetime import datetime, timezone

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.anchors import (
    AnchorClient,
    AnchorReceipt,
    AnchorRequest,
    AnchorTimeout,
    AnchorWatermark,
    exceeds_backlog,
    is_anchoring_due,
    record_receipt,
)

RECORD_HASH = "b" * 64


def _request(sequence: int) -> AnchorRequest:
    return AnchorRequest(
        sequence=sequence,
        record_hash=RECORD_HASH,
        profile_id="launch-v2",
        idempotency_key=f"key-{sequence}",
    )


def _receipt(sequence: int) -> AnchorReceipt:
    return AnchorReceipt(
        sequence=sequence,
        record_hash=RECORD_HASH,
        receiver_signature="signature",
        accepted_at="2026-09-22T00:00:00.000000Z",
    )


def test_anchor_client_returns_the_receiver_receipt() -> None:
    client = AnchorClient(transport=lambda request: _receipt(request.sequence))
    receipt = client.submit(_request(100))
    assert receipt == _receipt(100)


def test_anchor_client_timeout_does_not_raise_and_advances_nothing() -> None:
    def _timeout(request: AnchorRequest) -> AnchorReceipt:
        raise AnchorTimeout("receiver did not answer")

    client = AnchorClient(transport=_timeout)
    assert client.submit(_request(100)) is None


def test_record_receipt_rejects_a_decreasing_sequence() -> None:
    first = _receipt(200)
    with pytest.raises(ContractValidationError):
        record_receipt(first, _receipt(150))


def test_record_receipt_rejects_a_replacement_at_the_same_sequence() -> None:
    first = _receipt(200)
    with pytest.raises(ContractValidationError):
        record_receipt(first, _receipt(200))


def test_record_receipt_accepts_a_strictly_advancing_sequence() -> None:
    first = _receipt(200)
    second = record_receipt(first, _receipt(300))
    assert second.sequence == 300


def test_is_anchoring_due_after_100_new_records() -> None:
    watermark = AnchorWatermark(100, "2026-09-22T00:00:00.000000Z")
    now = datetime(2026, 9, 22, 0, 1, tzinfo=timezone.utc)
    assert is_anchoring_due(watermark, current_sequence=200, now=now)


def test_is_anchoring_due_after_15_minutes() -> None:
    watermark = AnchorWatermark(100, "2026-09-22T00:00:00.000000Z")
    now = datetime(2026, 9, 22, 0, 16, tzinfo=timezone.utc)
    assert is_anchoring_due(watermark, current_sequence=105, now=now)


def test_is_anchoring_not_due_below_both_bounds() -> None:
    watermark = AnchorWatermark(100, "2026-09-22T00:00:00.000000Z")
    now = datetime(2026, 9, 22, 0, 5, tzinfo=timezone.utc)
    assert not is_anchoring_due(watermark, current_sequence=105, now=now)


def test_exceeds_backlog_after_30_minutes() -> None:
    watermark = AnchorWatermark(100, "2026-09-22T00:00:00.000000Z")
    now = datetime(2026, 9, 22, 0, 31, tzinfo=timezone.utc)
    assert exceeds_backlog(watermark, now=now)


def test_exceeds_backlog_false_within_bound() -> None:
    watermark = AnchorWatermark(100, "2026-09-22T00:00:00.000000Z")
    now = datetime(2026, 9, 22, 0, 29, tzinfo=timezone.utc)
    assert not exceeds_backlog(watermark, now=now)
