"""Strict value validators shared by contract records."""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar
from urllib.parse import urlsplit

from .canonical import CanonicalJsonError, canonical_json, canonical_loads


class ContractValidationError(ValueError):
    """Raised when a wire value violates a closed contract."""


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_UTC_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_UTC_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_YEAR_MONTH = re.compile(r"\d{4}-\d{2}\Z")
_POSITIVE_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")
_INT64_MAX = 9_223_372_036_854_775_807


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{name} must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ContractValidationError(f"{name} must be valid UTF-8 text") from error
    return value


def validate_uuid4(value: object) -> str:
    value = _require_string(value, "UUIDv4")
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise ContractValidationError("must be a UUIDv4") from error
    if parsed.version != 4 or parsed.variant != uuid.RFC_4122 or str(parsed) != value:
        raise ContractValidationError("must be a lowercase canonical UUIDv4")
    return value


def validate_sha256(value: object) -> str:
    value = _require_string(value, "SHA-256")
    if _SHA256.fullmatch(value) is None:
        raise ContractValidationError("must be 64 lowercase hexadecimal characters")
    return value


def validate_utc_instant(value: object) -> str:
    value = _require_string(value, "UTC instant")
    if _UTC_INSTANT.fullmatch(value) is None:
        raise ContractValidationError("must be YYYY-MM-DDTHH:MM:SS.ffffffZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise ContractValidationError("must be a possible UTC instant") from error
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        raise ContractValidationError("must be a canonical UTC instant")
    return value


def validate_utc_date(value: object) -> str:
    value = _require_string(value, "UTC date")
    if _UTC_DATE.fullmatch(value) is None:
        raise ContractValidationError("must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ContractValidationError("must be a possible UTC date") from error
    if parsed.isoformat() != value:
        raise ContractValidationError("must be a canonical UTC date")
    return value


def validate_year_month(value: object) -> str:
    value = _require_string(value, "UTC billing month")
    if _YEAR_MONTH.fullmatch(value) is None:
        raise ContractValidationError("must be YYYY-MM")
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError as error:
        raise ContractValidationError("must be a possible UTC billing month") from error
    return value


def validate_non_negative_int(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _INT64_MAX
    ):
        raise ContractValidationError(
            "must be an integer from zero through signed int64 maximum"
        )
    return value


def validate_positive_int(value: object) -> int:
    value = validate_non_negative_int(value)
    if value == 0:
        raise ContractValidationError("must be a positive integer")
    return value


def validate_finite(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError("must be a JSON number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError("must be finite")
    return value


def validate_probability(value: object) -> int | float:
    value = validate_finite(value)
    if not 0 <= value <= 1:
        raise ContractValidationError("must be in [0, 1]")
    return value


def validate_positive_decimal(value: object) -> str:
    value = _require_string(value, "positive decimal")
    if _POSITIVE_DECIMAL.fullmatch(value) is None:
        raise ContractValidationError("must be an ASCII decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ContractValidationError("must be a decimal") from error
    if not parsed.is_finite() or parsed <= 0:
        raise ContractValidationError("must be strictly positive")
    return value


def validate_non_empty_string(value: object) -> str:
    value = _require_string(value, "text")
    if not value or "\x00" in value or unicodedata.normalize("NFC", value) != value:
        raise ContractValidationError("must be nonempty NFC text without NUL")
    return value


def validate_https_url(value: object) -> str:
    value = _require_string(value, "HTTPS URL")
    if not value or value != value.strip() or any(ord(char) <= 0x20 for char in value):
        raise ContractValidationError("must be an absolute HTTPS URI")
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise ContractValidationError("must be an absolute HTTPS URI") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "#" in value
    ):
        raise ContractValidationError(
            "must be an absolute HTTPS URI without userinfo or fragment"
        )
    try:
        _ = parsed.port
    except ValueError as error:
        raise ContractValidationError("must have a valid HTTPS port") from error
    return value


def _closed_object(raw: bytes, fields: frozenset[str], name: str) -> dict[str, Any]:
    try:
        value = canonical_loads(raw)
    except CanonicalJsonError as error:
        raise ContractValidationError(f"invalid {name} JSON") from error
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


@dataclass(frozen=True, slots=True)
class ProducerVersion:
    image_digest: str
    source_commit: str
    contract_version: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"image_digest", "source_commit", "contract_version"}
    )

    def __post_init__(self) -> None:
        validate_sha256(self.image_digest)
        if (
            not isinstance(self.source_commit, str)
            or _SOURCE_COMMIT.fullmatch(self.source_commit) is None
        ):
            raise ContractValidationError(
                "source_commit must be 40 lowercase hexadecimal characters"
            )
        if (
            not isinstance(self.contract_version, int)
            or isinstance(self.contract_version, bool)
            or self.contract_version != 1
        ):
            raise ContractValidationError("contract_version must be 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_digest": self.image_digest,
            "source_commit": self.source_commit,
            "contract_version": self.contract_version,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ProducerVersion":
        value = _closed_object(raw, cls._FIELDS, "ProducerVersion")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class RecordMeta:
    schema_version: int
    input_hashes: tuple[str, ...]
    producer_version: ProducerVersion
    config_hash: str
    created_at: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "input_hashes",
            "producer_version",
            "config_hash",
            "created_at",
        }
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != 1
        ):
            raise ContractValidationError("schema_version must be 1")
        if (
            not isinstance(self.input_hashes, tuple)
            or len(self.input_hashes) > 1_000_000
        ):
            raise ContractValidationError(
                "input_hashes must be an ordered list of at most 1000000 hashes"
            )
        for value in self.input_hashes:
            validate_sha256(value)
        if not isinstance(self.producer_version, ProducerVersion):
            raise ContractValidationError("producer_version must be a ProducerVersion")
        validate_sha256(self.config_hash)
        validate_utc_instant(self.created_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "input_hashes": list(self.input_hashes),
            "producer_version": self.producer_version.to_dict(),
            "config_hash": self.config_hash,
            "created_at": self.created_at,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "RecordMeta":
        value = _closed_object(raw, cls._FIELDS, "RecordMeta")
        hashes = value["input_hashes"]
        if not isinstance(hashes, list):
            raise ContractValidationError("input_hashes must be a JSON array")
        producer = value["producer_version"]
        if not isinstance(producer, dict):
            raise ContractValidationError("producer_version must be a JSON object")
        return cls(
            schema_version=value["schema_version"],
            input_hashes=tuple(hashes),
            producer_version=ProducerVersion.from_json(canonical_json(producer)),
            config_hash=value["config_hash"],
            created_at=value["created_at"],
        )


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    schema_version: int
    artifact_hash: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema_version", "artifact_hash"})

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != 1
        ):
            raise ContractValidationError("schema_version must be 1")
        validate_sha256(self.artifact_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_hash": self.artifact_hash,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ArtifactRef":
        return cls(**_closed_object(raw, cls._FIELDS, "ArtifactRef"))
