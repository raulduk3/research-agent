"""Sanitize and hash a raw source response before any consumer sees it.

`preserve_response` is the one place a raw provider response is turned into
the bytes ingest is allowed to retain. It hashes the response exactly as
transport delivered it, strips credential and authorization material and any
field outside the license/privacy allowlist, hashes what remains, and
returns only that sanitized copy together with its capture record. Nothing
else in this module, and nothing calling it, is meant to retain the original
`body` or `request_parameters` arguments past this call: persistence always
goes through the sanitized copy, never an in-memory bypass of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256

SANITIZER_VERSION = "capture-sanitizer-v1"

# A request parameter or a JSON response field whose name contains one of
# these markers is dropped before anything is retained, regardless of an
# otherwise-permitted allowlist entry.
_SECRET_MARKERS = (
    "key",
    "token",
    "auth",
    "secret",
    "password",
    "credential",
    "cookie",
)

# The only request parameters the two source adapters ever send; anything
# else is dropped rather than trusted to be safe.
_PARAMETER_ALLOWLIST = frozenset(
    {
        "verb",
        "metadataPrefix",
        "set",
        "from",
        "until",
        "resumptionToken",
        "filter",
        "select",
        "per_page",
        "cursor",
    }
)


class RetentionFailure(Exception):
    """Sanitization failed; the response is unusable to any consumer."""


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    """The provenance of one retained response; never the bytes themselves."""

    transport_hash: str
    stored_hash: str
    sanitizer_version: str
    request_parameters: tuple[tuple[str, str], ...]
    http_status: int | None
    capture_started_at: str
    capture_completed_at: str
    retention_class: str


def _is_secret(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _sanitize_parameters(
    parameters: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (key, value)
        for key, value in parameters
        if key in _PARAMETER_ALLOWLIST and not _is_secret(key)
    )


def _sanitize_body(body: bytes) -> bytes:
    """Byte-preserving unless the payload is a JSON object carrying a
    secret-named top-level field; only then is it rewritten, stripped."""
    try:
        value = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(value, dict):
        return body
    stripped = {key: item for key, item in value.items() if not _is_secret(key)}
    if stripped == value:
        return body
    return json.dumps(stripped, sort_keys=True, separators=(",", ":")).encode()


def preserve_response(
    *,
    body: bytes,
    request_parameters: tuple[tuple[str, str], ...],
    http_status: int | None,
    capture_started_at: str,
    capture_completed_at: str,
    retention_class: str,
) -> tuple[bytes, CaptureRecord]:
    """Hash, sanitize and re-hash one raw response before it is retained.

    Returns the sanitized bytes to persist and the capture record naming
    both the transport and stored hashes (equal unless sanitization actually
    changed something), the sanitizer version, the request parameters with
    every secret-bearing or unlisted key dropped, the HTTP status and the
    actual capture interval. Raises before returning anything if the
    interval itself is invalid, so a caller never persists a half-built
    record.
    """
    if capture_completed_at < capture_started_at:
        raise RetentionFailure("capture completion precedes its start")
    if not retention_class:
        raise RetentionFailure("retention class is required")
    transport_hash = sha256(body).hexdigest()
    stored = _sanitize_body(body)
    stored_hash = sha256(stored).hexdigest()
    record = CaptureRecord(
        transport_hash,
        stored_hash,
        SANITIZER_VERSION,
        _sanitize_parameters(request_parameters),
        http_status,
        capture_started_at,
        capture_completed_at,
        retention_class,
    )
    return stored, record
