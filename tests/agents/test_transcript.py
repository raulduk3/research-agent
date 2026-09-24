from __future__ import annotations

import pytest

from research_agent.agents.transcript import (
    ImageDelivery,
    RecordingFailed,
    record_exchange,
    record_images,
)
from research_agent.contracts.canonical import canonical_json, sha256_hex

from tests.agents.support import InMemoryRunEventSink


def test_record_exchange_appends_by_hash_and_in_order() -> None:
    sink = InMemoryRunEventSink()
    payload = b'{"role":"system"}'
    record = record_exchange(
        sink, run_id="run-1", attempt=1, ordinal=0, kind="request", payload=payload
    )
    assert record.ordinal == 0
    assert record.kind == "request"
    assert record.payload_hash == sha256_hex(payload)
    assert sink.events == [
        {
            "run_id": "run-1",
            "attempt": 1,
            "ordinal": 0,
            "kind": "request",
            "payload": payload,
        }
    ]


def test_record_exchange_rejects_an_unknown_kind() -> None:
    sink = InMemoryRunEventSink()
    with pytest.raises(ValueError):
        record_exchange(
            sink, run_id="run-1", attempt=1, ordinal=0, kind="status", payload=b"{}"
        )
    assert sink.events == []


def test_record_exchange_propagates_recording_failure() -> None:
    sink = InMemoryRunEventSink(fail_after=0)
    with pytest.raises(RecordingFailed):
        record_exchange(
            sink, run_id="run-1", attempt=1, ordinal=0, kind="request", payload=b"{}"
        )


class _FailingImageSink:
    def commit(self, *, run_id: str, tool_call_id: str, payload: bytes) -> None:
        raise RecordingFailed("simulated failure")


class _RecordingImageSink:
    def __init__(self) -> None:
        self.committed: list[bytes] = []

    def commit(self, *, run_id: str, tool_call_id: str, payload: bytes) -> None:
        self.committed.append(payload)


def _delivery(figure_id: str) -> ImageDelivery:
    return ImageDelivery(
        tool_call_id="call-1",
        paper_id="paper-a",
        figure_id=figure_id,
        rendered_artifact_hash="a" * 64,
    )


def test_record_images_commits_the_ordered_manifest() -> None:
    sink = _RecordingImageSink()
    deliveries = [_delivery("figure-1"), _delivery("figure-2")]
    manifest_hash = record_images(
        sink, run_id="run-1", tool_call_id="call-1", deliveries=deliveries
    )
    expected_payload = canonical_json([delivery.to_dict() for delivery in deliveries])
    assert sink.committed == [expected_payload]
    assert manifest_hash == sha256_hex(expected_payload)


def test_record_images_requires_at_least_one_delivery() -> None:
    with pytest.raises(ValueError):
        record_images(
            _RecordingImageSink(), run_id="run-1", tool_call_id="call-1", deliveries=[]
        )


def test_record_images_propagates_recording_failure() -> None:
    with pytest.raises(RecordingFailed):
        record_images(
            _FailingImageSink(),
            run_id="run-1",
            tool_call_id="call-1",
            deliveries=[_delivery("figure-1")],
        )
