"""Sanitize and hash a raw source response before it is retained."""

from __future__ import annotations

import json
from hashlib import sha256

import pytest

from research_agent.ingest.capture import RetentionFailure, preserve_response

_STARTED = "2026-01-01T00:00:00.000000Z"
_COMPLETED = "2026-01-01T00:00:01.000000Z"


def test_byte_preserving_input_stores_unchanged_with_matching_hashes() -> None:
    body = b'{"id":"2306.00001","title":"A paper"}'
    stored, record = preserve_response(
        body=body,
        request_parameters=(("verb", "ListRecords"), ("set", "cs:cs:AI")),
        http_status=200,
        capture_started_at=_STARTED,
        capture_completed_at=_COMPLETED,
        retention_class="private-research",
    )
    assert stored == body
    assert record.transport_hash == sha256(body).hexdigest()
    assert record.stored_hash == record.transport_hash


def test_secret_bearing_body_field_is_stripped_and_hashes_differ() -> None:
    body = json.dumps({"id": "2306.00001", "api_key": "shhh"}).encode()
    stored, record = preserve_response(
        body=body,
        request_parameters=(),
        http_status=200,
        capture_started_at=_STARTED,
        capture_completed_at=_COMPLETED,
        retention_class="private-research",
    )
    assert stored != body
    assert b"shhh" not in stored
    assert record.transport_hash == sha256(body).hexdigest()
    assert record.stored_hash == sha256(stored).hexdigest()
    assert record.transport_hash != record.stored_hash


def test_secret_bearing_request_parameters_are_dropped() -> None:
    _, record = preserve_response(
        body=b"{}",
        request_parameters=(("verb", "ListRecords"), ("api_key", "shhh")),
        http_status=200,
        capture_started_at=_STARTED,
        capture_completed_at=_COMPLETED,
        retention_class="private-research",
    )
    assert record.request_parameters == (("verb", "ListRecords"),)


def test_unlisted_request_parameter_is_dropped() -> None:
    _, record = preserve_response(
        body=b"{}",
        request_parameters=(("verb", "ListRecords"), ("mystery", "value")),
        http_status=200,
        capture_started_at=_STARTED,
        capture_completed_at=_COMPLETED,
        retention_class="private-research",
    )
    assert record.request_parameters == (("verb", "ListRecords"),)


def test_stored_bytes_round_trip_hash_exactly_detects_tampering() -> None:
    body = b"original bytes"
    stored, record = preserve_response(
        body=body,
        request_parameters=(),
        http_status=200,
        capture_started_at=_STARTED,
        capture_completed_at=_COMPLETED,
        retention_class="private-research",
    )
    assert sha256(stored).hexdigest() == record.stored_hash
    tampered = stored + b"x"
    assert sha256(tampered).hexdigest() != record.stored_hash


def test_capture_record_names_sanitizer_version_status_and_interval() -> None:
    _, record = preserve_response(
        body=b"{}",
        request_parameters=(),
        http_status=200,
        capture_started_at=_STARTED,
        capture_completed_at=_COMPLETED,
        retention_class="private-research",
    )
    assert record.sanitizer_version
    assert record.http_status == 200
    assert record.capture_started_at == _STARTED
    assert record.capture_completed_at == _COMPLETED
    assert record.retention_class == "private-research"


def test_inverted_capture_interval_fails_before_returning_anything() -> None:
    with pytest.raises(RetentionFailure):
        preserve_response(
            body=b"{}",
            request_parameters=(),
            http_status=200,
            capture_started_at=_COMPLETED,
            capture_completed_at=_STARTED,
            retention_class="private-research",
        )


def test_missing_retention_class_fails_before_returning_anything() -> None:
    with pytest.raises(RetentionFailure):
        preserve_response(
            body=b"{}",
            request_parameters=(),
            http_status=200,
            capture_started_at=_STARTED,
            capture_completed_at=_COMPLETED,
            retention_class="",
        )
