"""Offline replay of already retained, permission-evidenced source bytes."""

from __future__ import annotations

import time
from dataclasses import dataclass

from research_agent.contracts import sha256_hex
from research_agent.contracts.learning import PaginationPage
from research_agent.contracts.papers import SourceAccess
from research_agent.storage.errors import IntegrityFailure, UnavailableInput


@dataclass(frozen=True, slots=True)
class ReplayMeasurement:
    payload: bytes
    byte_length: int
    elapsed_ns: int


def validate_pagination(pages: tuple[PaginationPage, ...], *, complete: bool) -> None:
    """Validate exact cursor continuity without turning partial capture into zero."""
    if not isinstance(complete, bool):
        raise IntegrityFailure("pagination completeness must be boolean")
    if not pages:
        raise UnavailableInput("pagination has no initial page")
    seen: set[str] = set()
    expected: str | None = None
    for index, page in enumerate(pages):
        if page.page_index != index or page.cursor_in != expected:
            raise IntegrityFailure("pagination page order or cursor chain is invalid")
        if page.capture_completed_at < page.capture_started_at:
            raise IntegrityFailure("pagination page completion precedes start")
        if page.status == "failed":
            if (
                page.failure
                not in {"timeout", "rejected", "transport", "invalid_payload"}
                or page.returned_count != 0
            ):
                raise IntegrityFailure("failed pagination page has accepted records")
            if complete:
                raise IntegrityFailure("failed pagination cannot be complete")
            if index != len(pages) - 1:
                raise IntegrityFailure("failed pagination page must be terminal")
            return
        if expected is None and index > 0:
            raise IntegrityFailure("pagination continues after terminal cursor")
        if (
            page.status != "completed"
            or page.failure is not None
            or page.response_hash is None
        ):
            raise IntegrityFailure("completed pagination page lacks response evidence")
        if page.cursor_out is not None:
            if page.cursor_out in seen:
                raise IntegrityFailure("pagination cursor repeats")
            seen.add(page.cursor_out)
        expected = page.cursor_out
    if complete != (expected is None):
        raise IntegrityFailure("pagination completeness disagrees with terminal cursor")


def replay_retained_source(access: SourceAccess, payload: bytes) -> ReplayMeasurement:
    """Verify and return exact retained bytes without any network fallback."""

    started = time.monotonic_ns()
    if access.failure is not None or access.retained_payload_hash is None:
        raise UnavailableInput("source capture has no successful retained payload")
    if access.license_expression is None:
        raise UnavailableInput("source capture lacks admitted license evidence")
    if sha256_hex(payload) != access.retained_payload_hash:
        raise IntegrityFailure("retained source bytes do not match capture identity")
    return ReplayMeasurement(payload, len(payload), time.monotonic_ns() - started)
