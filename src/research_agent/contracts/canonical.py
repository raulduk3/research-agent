"""Canonical JSON encoding for immutable contract payloads."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping


class CanonicalJsonError(ValueError):
    """Raised when a value cannot be represented by the contract JSON format."""


JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def _normalize(value: object) -> JsonValue:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError("JSON numbers must be finite")
        return value
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise CanonicalJsonError(
                "JSON strings must not contain surrogate code points"
            )
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJsonError("JSON object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise CanonicalJsonError("duplicate object key after NFC normalization")
            normalized[normalized_key] = _normalize(item)
        return normalized
    raise CanonicalJsonError(
        f"value has no JSON representation: {type(value).__name__}"
    )


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        normalized_key = unicodedata.normalize("NFC", key)
        if normalized_key in result:
            raise CanonicalJsonError("duplicate object key after NFC normalization")
        result[normalized_key] = _normalize(value)
    return result


def canonical_loads(raw: bytes) -> JsonValue:
    """Decode UTF-8 JSON while rejecting duplicate keys and nonfinite values."""

    if not isinstance(raw, bytes):
        raise CanonicalJsonError("JSON input must be bytes")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                CanonicalJsonError(f"nonfinite JSON number: {value}")
            ),
        )
        return _normalize(value)
    except CanonicalJsonError:
        raise
    except UnicodeDecodeError as error:
        raise CanonicalJsonError("JSON input must be valid UTF-8") from error
    except (json.JSONDecodeError, ValueError) as error:
        raise CanonicalJsonError("malformed JSON") from error


def canonical_json(value: object) -> bytes:
    """Return the single UTF-8, NFC, compact serialization for *value*."""

    normalized = _normalize(value)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CanonicalJsonError("value cannot be canonically serialized") from error


def sha256_hex(raw: bytes) -> str:
    """Return the lowercase SHA-256 identity of exact bytes."""

    if not isinstance(raw, bytes):
        raise TypeError("SHA-256 input must be bytes")
    return hashlib.sha256(raw).hexdigest()
