"""Strict source identity primitives for preserved acquisition records."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from .canonical import canonical_json, canonical_loads
from .primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
    RecordMeta,
    ProducerVersion,
)

_OPENALEX = re.compile(r"W[1-9][0-9]*\Z")
_ARXIV = re.compile(r"(?:[0-9]{4}\.[0-9]{4,5}|[a-z-]+/[0-9]{7})v[1-9][0-9]*\Z")
T = TypeVar("T")


def _text(value: object, name: str, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\x00" in value
        or unicodedata.normalize("NFC", value) != value
    ):
        raise ContractValidationError(f"{name} is invalid")
    return value


def _closed(raw: bytes, fields: set[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} fields do not match schema")
    return cast(dict[str, Any], value)


def _construct(cls: type[T], values: dict[str, Any], name: str) -> T:
    try:
        return cls(**values)
    except ContractValidationError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise ContractValidationError(f"{name} field types are invalid") from error


def normalize_identifier(scheme: str, value: str) -> str:
    """Return the contract's exact canonical external identifier."""

    _text(value, "identifier")
    if scheme == "doi":
        normalized = value.strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if normalized.lower().startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        normalized = normalized.lower()
        if not normalized.startswith("10.") or "/" not in normalized:
            raise ContractValidationError("DOI is invalid")
        return normalized
    if scheme == "arxiv":
        if _ARXIV.fullmatch(value) is None:
            raise ContractValidationError(
                "arXiv identifier must name an explicit version"
            )
        return value
    if scheme == "openalex":
        if _OPENALEX.fullmatch(value) is None:
            raise ContractValidationError("OpenAlex work identifier is invalid")
        return value
    raise ContractValidationError("identifier scheme is not admitted")


@dataclass(frozen=True, slots=True)
class ExternalIdentifier:
    scheme: str
    value: str

    def __post_init__(self) -> None:
        if normalize_identifier(self.scheme, self.value) != self.value:
            raise ContractValidationError("identifier is not canonical")

    def to_canonical_json(self) -> bytes:
        return canonical_json({"scheme": self.scheme, "value": self.value})

    @classmethod
    def from_json(cls, raw: bytes) -> "ExternalIdentifier":
        value = canonical_loads(raw)
        if not isinstance(value, dict) or set(value) != {"scheme", "value"}:
            raise ContractValidationError(
                "ExternalIdentifier fields do not match schema"
            )
        return cls(_text(value["scheme"], "scheme"), _text(value["value"], "value"))


@dataclass(frozen=True, slots=True)
class SourceInterval:
    start: str
    end_exclusive: str

    def __post_init__(self) -> None:
        start = validate_utc_instant(self.start)
        end = validate_utc_instant(self.end_exclusive)
        if start >= end:
            raise ContractValidationError("source interval must be nonempty")

    def to_canonical_json(self) -> bytes:
        return canonical_json(
            {"start": self.start, "end_exclusive": self.end_exclusive}
        )

    @classmethod
    def from_json(cls, raw: bytes) -> "SourceInterval":
        value = canonical_loads(raw)
        if not isinstance(value, dict) or set(value) != {"start", "end_exclusive"}:
            raise ContractValidationError("SourceInterval fields do not match schema")
        return cls(
            _text(value["start"], "start"),
            _text(value["end_exclusive"], "end_exclusive"),
        )


@dataclass(frozen=True, slots=True)
class SourceAccess(RecordMeta):
    source: str
    requested_url: str
    request_parameters_hash: str
    adapter_version: str
    capture_started_at: str
    capture_completed_at: str
    http_status: int | None
    retained_payload_hash: str | None
    retention_policy_hash: str
    license_expression: str | None
    permission_evidence_hash: str
    failure: str | None

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        if self.source not in {"arxiv", "openalex", "original_publisher"}:
            raise ContractValidationError("source is not admitted")
        _text(self.requested_url, "requested_url")
        _text(self.adapter_version, "adapter_version")
        validate_sha256(self.request_parameters_hash)
        validate_sha256(self.retention_policy_hash)
        validate_sha256(self.permission_evidence_hash)
        if self.retained_payload_hash is not None:
            validate_sha256(self.retained_payload_hash)
        start = validate_utc_instant(self.capture_started_at)
        completed = validate_utc_instant(self.capture_completed_at)
        if completed < start:
            raise ContractValidationError("capture completion precedes its start")
        if self.http_status is not None and (
            isinstance(self.http_status, bool)
            or not isinstance(self.http_status, int)
            or not 100 <= self.http_status <= 599
        ):
            raise ContractValidationError("HTTP status is invalid")
        failures = {"timeout", "rejected", "not_found", "transport", "invalid_payload"}
        if self.failure is not None and self.failure not in failures:
            raise ContractValidationError("source failure is not admitted")
        if self.failure is None and self.retained_payload_hash is None:
            raise ContractValidationError(
                "successful capture requires retained payload"
            )
        if self.license_expression is not None:
            _text(self.license_expression, "license_expression")

    def to_canonical_json(self) -> bytes:
        value = self.to_dict()
        value.update({name: getattr(self, name) for name in self.__slots__})
        return canonical_json(value)

    @classmethod
    def from_json(cls, raw: bytes) -> "SourceAccess":
        values = _closed(
            raw, set(cls.__slots__) | set(RecordMeta.__slots__), "SourceAccess"
        )
        producer = values["producer_version"]
        if not isinstance(producer, dict):
            raise ContractValidationError("producer_version must be an object")
        values["producer_version"] = ProducerVersion.from_json(canonical_json(producer))
        if not isinstance(values["input_hashes"], list):
            raise ContractValidationError("input_hashes must be an array")
        values["input_hashes"] = tuple(values["input_hashes"])
        return _construct(cls, values, "SourceAccess")


@dataclass(frozen=True, slots=True)
class PaperVersionRecord(RecordMeta):
    family_id: str
    version_id: str
    external_ids: tuple[ExternalIdentifier, ...]
    is_first_public_version: bool
    first_public_at: str | None
    first_public_interval: SourceInterval | None
    first_public_evidence_hashes: tuple[str, ...]
    source_access_hashes: tuple[str, ...]
    title: str
    abstract: str
    author_ids: tuple[str, ...]
    primary_source_subfield: str | None
    original_source_hash: str
    text_source_kind: str
    source_revision: str
    author_count: int
    categories: tuple[str, ...]
    version_count: int

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        validate_uuid4(self.family_id)
        validate_uuid4(self.version_id)
        validate_non_negative_int(self.author_count)
        validate_positive_int(self.version_count)
        if not isinstance(self.categories, tuple) or not self.categories:
            raise ContractValidationError(
                "categories must be a nonempty, ordered tuple with the primary first"
            )
        for category in self.categories:
            _text(category, "category", 64)
        if not isinstance(self.is_first_public_version, bool):
            raise ContractValidationError("first-public marker must be boolean")
        if not 1 <= len(self.external_ids) <= 64 or len(set(self.external_ids)) != len(
            self.external_ids
        ):
            raise ContractValidationError(
                "external_ids must contain 1 to 64 unique identities"
            )
        if not all(
            isinstance(value, ExternalIdentifier) for value in self.external_ids
        ):
            raise ContractValidationError("external_ids contain an invalid value")
        if (self.first_public_at is None) == (self.first_public_interval is None):
            raise ContractValidationError(
                "exactly one first-public time form is required"
            )
        if self.first_public_at is not None:
            validate_utc_instant(self.first_public_at)
        for values in (self.first_public_evidence_hashes, self.source_access_hashes):
            if not 1 <= len(values) <= 64 or len(set(values)) != len(values):
                raise ContractValidationError(
                    "evidence hashes must contain 1 to 64 unique values"
                )
            for value in values:
                validate_sha256(value)
        _text(self.title, "title", 10000)
        _text(self.abstract, "abstract", 1000000)
        if len(set(self.author_ids)) != len(self.author_ids):
            raise ContractValidationError("author_ids are duplicated")
        for author in self.author_ids:
            _text(author, "author_id")
        if self.primary_source_subfield is not None:
            _text(self.primary_source_subfield, "primary_source_subfield")
        validate_sha256(self.original_source_hash)
        if self.text_source_kind not in {"latex", "pdf", "metadata"}:
            raise ContractValidationError("text source kind is invalid")
        _text(self.source_revision, "source_revision")
        validate_utc_instant(self.created_at)

    def to_canonical_json(self) -> bytes:
        value = self.to_dict()
        value.update({name: getattr(self, name) for name in self.__slots__})
        value["external_ids"] = [
            {"scheme": item.scheme, "value": item.value} for item in self.external_ids
        ]
        value["first_public_interval"] = (
            None
            if self.first_public_interval is None
            else {
                "start": self.first_public_interval.start,
                "end_exclusive": self.first_public_interval.end_exclusive,
            }
        )
        return canonical_json(value)

    @classmethod
    def from_json(cls, raw: bytes) -> "PaperVersionRecord":
        values = _closed(
            raw, set(cls.__slots__) | set(RecordMeta.__slots__), "PaperVersionRecord"
        )
        producer = values["producer_version"]
        if not isinstance(producer, dict):
            raise ContractValidationError("producer_version must be an object")
        values["producer_version"] = ProducerVersion.from_json(canonical_json(producer))
        if not isinstance(values["input_hashes"], list):
            raise ContractValidationError("input_hashes must be an array")
        values["input_hashes"] = tuple(values["input_hashes"])
        identifiers = values["external_ids"]
        if not isinstance(identifiers, list):
            raise ContractValidationError("external_ids must be an array")
        values["external_ids"] = tuple(
            ExternalIdentifier.from_json(canonical_json(item)) for item in identifiers
        )
        interval = values["first_public_interval"]
        values["first_public_interval"] = (
            None
            if interval is None
            else SourceInterval.from_json(canonical_json(interval))
        )
        for field in (
            "first_public_evidence_hashes",
            "source_access_hashes",
            "author_ids",
            "categories",
        ):
            if not isinstance(values[field], list):
                raise ContractValidationError(f"{field} must be an array")
            values[field] = tuple(cast(list[object], values[field]))
        return _construct(cls, values, "PaperVersionRecord")


@dataclass(frozen=True, slots=True)
class PaperObservation:
    source: ExternalIdentifier
    external_version: str
    identifiers: tuple[ExternalIdentifier, ...]
    source_artifact: str
    source_event_at: str | None
    source_event_interval: SourceInterval | None
    captured_at: str
    available_at: str
    transport_hash: str
    stored_payload_hash: str
    sanitization_policy_hash: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.source, ExternalIdentifier) or not all(
            isinstance(value, ExternalIdentifier) for value in self.identifiers
        ):
            raise ContractValidationError("paper identifiers are invalid")
        _text(self.external_version, "external_version", 64)
        if not 1 <= len(self.identifiers) <= 20 or len(set(self.identifiers)) != len(
            self.identifiers
        ):
            raise ContractValidationError(
                "identifiers must contain 1 to 20 unique values"
            )
        if (self.source_event_at is None) == (self.source_event_interval is None):
            raise ContractValidationError(
                "exactly one source event time form is required"
            )
        if self.source_event_at is not None:
            validate_utc_instant(self.source_event_at)
        if self.source_event_interval is not None and not isinstance(
            self.source_event_interval, SourceInterval
        ):
            raise ContractValidationError("source event interval is invalid")
        captured = validate_utc_instant(self.captured_at)
        available = validate_utc_instant(self.available_at)
        if available < captured:
            raise ContractValidationError("availability precedes capture")
        for value in (
            self.source_artifact,
            self.transport_hash,
            self.stored_payload_hash,
        ):
            validate_sha256(value)
        if self.stored_payload_hash != self.source_artifact:
            raise ContractValidationError("stored payload must equal source artifact")
        if (
            self.transport_hash != self.stored_payload_hash
            and self.sanitization_policy_hash is None
        ):
            raise ContractValidationError("sanitized transport requires policy")
        if self.sanitization_policy_hash is not None:
            validate_sha256(self.sanitization_policy_hash)

    def to_canonical_json(self) -> bytes:
        return canonical_json(
            {
                "source": {
                    "scheme": self.source.scheme,
                    "value": self.source.value,
                },
                "external_version": self.external_version,
                "identifiers": [
                    {"scheme": item.scheme, "value": item.value}
                    for item in self.identifiers
                ],
                "source_artifact": self.source_artifact,
                "source_event_at": self.source_event_at,
                "source_event_interval": (
                    None
                    if self.source_event_interval is None
                    else {
                        "start": self.source_event_interval.start,
                        "end_exclusive": self.source_event_interval.end_exclusive,
                    }
                ),
                "captured_at": self.captured_at,
                "available_at": self.available_at,
                "transport_hash": self.transport_hash,
                "stored_payload_hash": self.stored_payload_hash,
                "sanitization_policy_hash": self.sanitization_policy_hash,
            }
        )

    @classmethod
    def from_json(cls, raw: bytes) -> "PaperObservation":
        values = _closed(raw, set(cls.__slots__), "PaperObservation")
        values["source"] = ExternalIdentifier.from_json(
            canonical_json(values["source"])
        )
        identifiers = values["identifiers"]
        if not isinstance(identifiers, list):
            raise ContractValidationError("identifiers must be an array")
        values["identifiers"] = tuple(
            ExternalIdentifier.from_json(canonical_json(item)) for item in identifiers
        )
        interval = values["source_event_interval"]
        values["source_event_interval"] = (
            None
            if interval is None
            else SourceInterval.from_json(canonical_json(interval))
        )
        return _construct(cls, values, "PaperObservation")
