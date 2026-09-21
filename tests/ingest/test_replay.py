from dataclasses import replace

import pytest

from research_agent.contracts import ProducerVersion, sha256_hex
from research_agent.contracts.papers import SourceAccess
from research_agent.ingest.replay import (
    PaginationPage,
    replay_retained_source,
    validate_pagination,
)
from research_agent.storage.errors import IntegrityFailure, UnavailableInput


def access(payload: bytes) -> SourceAccess:
    return SourceAccess(
        1,
        (),
        ProducerVersion("e" * 64, "f" * 40, 1),
        "1" * 64,
        "2026-01-01T00:00:02.000000Z",
        "arxiv",
        "https://export.arxiv.org/api/query",
        "a" * 64,
        "arxiv-v1",
        "2026-01-01T00:00:00.000000Z",
        "2026-01-01T00:00:01.000000Z",
        200,
        sha256_hex(payload),
        "c" * 64,
        "arXiv-1.0",
        "d" * 64,
        None,
    )


def test_replay_measures_and_preserves_exact_retained_bytes() -> None:
    payload = b"preserved source bytes\n"
    replay = replay_retained_source(access(payload), payload)
    assert replay.payload == payload
    assert replay.byte_length == len(payload)
    assert replay.elapsed_ns >= 0


def test_replay_refuses_corruption_and_missing_license_without_fallback() -> None:
    payload = b"preserved source bytes\n"
    with pytest.raises(IntegrityFailure):
        replay_retained_source(access(payload), payload + b"changed")
    with pytest.raises(UnavailableInput):
        replay_retained_source(
            replace(access(payload), license_expression=None), payload
        )


def test_offline_pagination_distinguishes_complete_and_partial_capture() -> None:
    page = PaginationPage(
        0,
        "a" * 64,
        "b" * 64,
        None,
        "next",
        100,
        "2026-01-01T00:00:00.000000Z",
        "2026-01-01T00:00:01.000000Z",
        "completed",
        None,
    )
    validate_pagination((page,), complete=False)
    with pytest.raises(IntegrityFailure):
        validate_pagination((page,), complete=True)
    failed = PaginationPage(
        1,
        "c" * 64,
        None,
        "next",
        None,
        0,
        "2026-01-01T00:00:01.000000Z",
        "2026-01-01T00:00:02.000000Z",
        "failed",
        "timeout",
    )
    validate_pagination((page, failed), complete=False)


def test_offline_pagination_rejects_pages_after_terminal_cursor() -> None:
    terminal = PaginationPage(
        0,
        "a" * 64,
        "b" * 64,
        None,
        None,
        1,
        "2026-01-01T00:00:00.000000Z",
        "2026-01-01T00:00:01.000000Z",
        "completed",
        None,
    )
    trailing = PaginationPage(
        1,
        "c" * 64,
        "d" * 64,
        None,
        None,
        1,
        "2026-01-01T00:00:01.000000Z",
        "2026-01-01T00:00:02.000000Z",
        "completed",
        None,
    )
    with pytest.raises(IntegrityFailure, match="terminal cursor"):
        validate_pagination((terminal, trailing), complete=True)
    with pytest.raises(IntegrityFailure, match="completeness"):
        validate_pagination((terminal,), complete=False)
