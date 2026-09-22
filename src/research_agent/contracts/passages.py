"""Extraction and passage records for the reader's chunking contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar, cast

from .canonical import canonical_json, canonical_loads
from .primitives import (
    ContractValidationError,
    validate_finite,
    validate_non_negative_int,
    validate_non_empty_string,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

T = TypeVar("T")

_LOCATOR_KINDS = frozenset(
    {
        "latex",
        "pdf",
        "metadata",
    }
)
_BLOCK_KINDS = frozenset(
    {
        "body",
        "appendix",
        "caption",
        "table",
        "bibliography",
        "page_furniture",
        "unreadable",
    }
)
_EXCLUDED_KINDS = frozenset(
    {
        "bibliography",
        "page_furniture",
    }
)
_OMISSION_REASONS = frozenset(
    {
        "bibliography",
        "page_furniture",
        "unreadable",
        "parse_failure",
    }
)
_COVERAGE_STATES = frozenset(
    {
        "complete",
        "partial",
        "unavailable",
    }
)
_COVERAGE_REASONS = frozenset(
    {
        "source_missing",
        "parse_failure",
        "unreadable_blocks",
        "unsupported_source",
        "empty_text",
    }
)
CHUNK_POLICY = "passages-384-64-v1"
CHUNK_WINDOW_TOKENS = 384
CHUNK_OVERLAP_TOKENS = 64
CHUNK_STRIDE_TOKENS = CHUNK_WINDOW_TOKENS - CHUNK_OVERLAP_TOKENS


def _closed(raw: bytes, fields: set[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(
            f"{name} fields do not match schema",
        )
    return cast(dict[str, Any], value)


def _construct(cls: type[T], values: dict[str, Any], name: str) -> T:
    try:
        return cls(**values)
    except ContractValidationError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise ContractValidationError(
            f"{name} field types are invalid",
        ) from error


@dataclass(frozen=True, slots=True)
class SourceLocator:
    source_hash: str
    kind: str
    page_number: int | None
    source_member: str | None
    source_line_start: int | None
    source_line_end_inclusive: int | None

    def __post_init__(self) -> None:
        validate_sha256(self.source_hash)
        if self.kind not in _LOCATOR_KINDS:
            raise ContractValidationError(
                "locator kind is not admitted",
            )
        if self.page_number is not None:
            validate_positive_int(self.page_number)
        if self.source_member is not None:
            validate_non_empty_string(self.source_member)
        has_start = self.source_line_start is not None
        has_end = self.source_line_end_inclusive is not None
        if has_start != has_end:
            raise ContractValidationError(
                "a line range requires both ends",
            )
        if self.source_line_start is not None:
            validate_positive_int(self.source_line_start)
            assert self.source_line_end_inclusive is not None
            validate_positive_int(self.source_line_end_inclusive)
            if self.source_line_end_inclusive < self.source_line_start:
                raise ContractValidationError(
                    "line range must not end before it starts",
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_hash": self.source_hash,
            "kind": self.kind,
            "page_number": self.page_number,
            "source_member": self.source_member,
            "source_line_start": self.source_line_start,
            "source_line_end_inclusive": self.source_line_end_inclusive,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "SourceLocator":
        values = _closed(raw, set(cls.__slots__), "SourceLocator")
        return _construct(cls, values, "SourceLocator")


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    block_id: str
    section_path: tuple[str, ...]
    section_order: int
    block_order: int
    kind: str
    char_start: int
    char_end_exclusive: int
    included_in_passages: bool
    omission_reason: str | None
    locator: SourceLocator

    def __post_init__(self) -> None:
        validate_non_empty_string(self.block_id)
        if not all(isinstance(part, str) and part for part in self.section_path):
            raise ContractValidationError(
                "section_path must be nonempty strings",
            )
        validate_non_negative_int(self.section_order)
        validate_non_negative_int(self.block_order)
        if self.kind not in _BLOCK_KINDS:
            raise ContractValidationError(
                "block kind is not admitted",
            )
        validate_non_negative_int(self.char_start)
        validate_non_negative_int(self.char_end_exclusive)
        if self.char_end_exclusive < self.char_start:
            raise ContractValidationError(
                "block span must not end before it starts",
            )
        if not isinstance(self.included_in_passages, bool):
            raise ContractValidationError(
                "included_in_passages must be boolean",
            )
        if self.included_in_passages:
            self._check_included()
        else:
            self._check_omitted()
        if not isinstance(self.locator, SourceLocator):
            raise ContractValidationError(
                "locator must be a SourceLocator",
            )

    def _check_included(self) -> None:
        if self.omission_reason is not None:
            raise ContractValidationError(
                "an included block carries no reason",
            )
        if self.char_end_exclusive <= self.char_start:
            raise ContractValidationError(
                "an included block must be nonempty",
            )

    def _check_omitted(self) -> None:
        if self.omission_reason not in _OMISSION_REASONS:
            raise ContractValidationError(
                "an omitted block requires a reason",
            )
        if self.kind in _EXCLUDED_KINDS and self.omission_reason != self.kind:
            raise ContractValidationError(
                "bibliography and furniture name themselves as the reason",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "section_path": list(self.section_path),
            "section_order": self.section_order,
            "block_order": self.block_order,
            "kind": self.kind,
            "char_start": self.char_start,
            "char_end_exclusive": self.char_end_exclusive,
            "included_in_passages": self.included_in_passages,
            "omission_reason": self.omission_reason,
            "locator": self.locator.to_dict(),
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ExtractedBlock":
        values = _closed(raw, set(cls.__slots__), "ExtractedBlock")
        path = values["section_path"]
        if not isinstance(path, list):
            raise ContractValidationError(
                "section_path must be an array",
            )
        values["section_path"] = tuple(path)
        locator = values["locator"]
        if not isinstance(locator, dict):
            raise ContractValidationError(
                "locator must be an object",
            )
        values["locator"] = SourceLocator.from_json(canonical_json(locator))
        return _construct(cls, values, "ExtractedBlock")


@dataclass(frozen=True, slots=True)
class ExtractionRecord:
    paper_version_id: str
    source_hash: str
    extractor_manifest_hash: str
    text_hash: str
    text_codepoints: int
    blocks: tuple[ExtractedBlock, ...]
    coverage: str
    coverage_reasons: tuple[str, ...]
    included_block_count: int
    omitted_block_count: int
    created_at: str

    def __post_init__(self) -> None:
        validate_uuid4(self.paper_version_id)
        validate_sha256(self.source_hash)
        validate_sha256(self.extractor_manifest_hash)
        validate_sha256(self.text_hash)
        validate_non_negative_int(self.text_codepoints)
        if not all(isinstance(block, ExtractedBlock) for block in self.blocks):
            raise ContractValidationError(
                "blocks must be ExtractedBlock values",
            )
        self._check_coverage()
        self._check_counts()
        self._check_ordering()
        validate_utc_instant(self.created_at)

    def _check_coverage(self) -> None:
        if self.coverage not in _COVERAGE_STATES:
            raise ContractValidationError(
                "coverage is not admitted",
            )
        if len(set(self.coverage_reasons)) != len(self.coverage_reasons):
            raise ContractValidationError(
                "coverage_reasons must not repeat",
            )
        for reason in self.coverage_reasons:
            if reason not in _COVERAGE_REASONS:
                raise ContractValidationError(
                    "coverage reason is not admitted",
                )
        if self.coverage == "complete" and self.coverage_reasons:
            raise ContractValidationError(
                "complete coverage carries no reasons",
            )
        if self.coverage != "complete" and not self.coverage_reasons:
            raise ContractValidationError(
                "incomplete coverage names a reason",
            )

    def _check_counts(self) -> None:
        included = sum(1 for block in self.blocks if block.included_in_passages)
        if included != self.included_block_count:
            raise ContractValidationError(
                "included_block_count does not match blocks",
            )
        if len(self.blocks) - included != self.omitted_block_count:
            raise ContractValidationError(
                "omitted_block_count does not match blocks",
            )

    def _check_ordering(self) -> None:
        previous_end = 0
        for index, block in enumerate(self.blocks):
            if block.block_order != index:
                raise ContractValidationError(
                    "blocks must be ordered without gaps",
                )
            if block.char_start < previous_end:
                raise ContractValidationError(
                    "blocks must not overlap",
                )
            if block.char_end_exclusive > self.text_codepoints:
                raise ContractValidationError(
                    "a block span exceeds the extracted text",
                )
            previous_end = block.char_end_exclusive
        ids = {block.block_id for block in self.blocks}
        if len(ids) != len(self.blocks):
            raise ContractValidationError(
                "block_id must be unique",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_version_id": self.paper_version_id,
            "source_hash": self.source_hash,
            "extractor_manifest_hash": self.extractor_manifest_hash,
            "text_hash": self.text_hash,
            "text_codepoints": self.text_codepoints,
            "blocks": [block.to_dict() for block in self.blocks],
            "coverage": self.coverage,
            "coverage_reasons": list(self.coverage_reasons),
            "included_block_count": self.included_block_count,
            "omitted_block_count": self.omitted_block_count,
            "created_at": self.created_at,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ExtractionRecord":
        values = _closed(raw, set(cls.__slots__), "ExtractionRecord")
        blocks = values["blocks"]
        if not isinstance(blocks, list):
            raise ContractValidationError(
                "blocks must be an array",
            )
        values["blocks"] = tuple(
            ExtractedBlock.from_json(canonical_json(block)) for block in blocks
        )
        reasons = values["coverage_reasons"]
        if not isinstance(reasons, list):
            raise ContractValidationError(
                "coverage_reasons must be an array",
            )
        values["coverage_reasons"] = tuple(reasons)
        return _construct(cls, values, "ExtractionRecord")


@dataclass(frozen=True, slots=True)
class PassageRecord:
    paper_version_id: str
    extraction_hash: str
    chunk_policy: str
    section_order: int
    section_path: tuple[str, ...]
    passage_order: int
    section_token_start: int
    section_token_end_exclusive: int
    char_start: int
    char_end_exclusive: int
    block_ids: tuple[str, ...]
    text_hash: str
    source_locators: tuple[SourceLocator, ...]
    overlap_adjusted_weight: float

    def __post_init__(self) -> None:
        validate_uuid4(self.paper_version_id)
        validate_sha256(self.extraction_hash)
        if self.chunk_policy != CHUNK_POLICY:
            raise ContractValidationError(
                "chunk_policy must be the pinned policy",
            )
        validate_non_negative_int(self.section_order)
        if not all(isinstance(part, str) and part for part in self.section_path):
            raise ContractValidationError(
                "section_path must be nonempty strings",
            )
        validate_non_negative_int(self.passage_order)
        self._check_token_span()
        self._check_char_span()
        self._check_block_ids()
        validate_sha256(self.text_hash)
        if not all(isinstance(item, SourceLocator) for item in self.source_locators):
            raise ContractValidationError(
                "source_locators must be SourceLocator values",
            )
        weight = validate_finite(self.overlap_adjusted_weight)
        if weight <= 0:
            raise ContractValidationError(
                "overlap_adjusted_weight must be positive",
            )

    def _check_token_span(self) -> None:
        validate_non_negative_int(self.section_token_start)
        validate_positive_int(self.section_token_end_exclusive)
        span = self.section_token_end_exclusive - self.section_token_start
        if not 1 <= span <= CHUNK_WINDOW_TOKENS:
            raise ContractValidationError(
                f"a passage spans 1 to {CHUNK_WINDOW_TOKENS} tokens",
            )

    def _check_char_span(self) -> None:
        validate_non_negative_int(self.char_start)
        validate_positive_int(self.char_end_exclusive)
        if self.char_end_exclusive <= self.char_start:
            raise ContractValidationError(
                "a passage must be a nonempty character span",
            )

    def _check_block_ids(self) -> None:
        if not 1 <= len(self.block_ids) <= CHUNK_WINDOW_TOKENS:
            raise ContractValidationError(
                f"block_ids must contain 1 to {CHUNK_WINDOW_TOKENS} values",
            )
        for block_id in self.block_ids:
            validate_non_empty_string(block_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_version_id": self.paper_version_id,
            "extraction_hash": self.extraction_hash,
            "chunk_policy": self.chunk_policy,
            "section_order": self.section_order,
            "section_path": list(self.section_path),
            "passage_order": self.passage_order,
            "section_token_start": self.section_token_start,
            "section_token_end_exclusive": self.section_token_end_exclusive,
            "char_start": self.char_start,
            "char_end_exclusive": self.char_end_exclusive,
            "block_ids": list(self.block_ids),
            "text_hash": self.text_hash,
            "source_locators": [item.to_dict() for item in self.source_locators],
            "overlap_adjusted_weight": self.overlap_adjusted_weight,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "PassageRecord":
        values = _closed(raw, set(cls.__slots__), "PassageRecord")
        for field in ("section_path", "block_ids"):
            value = values[field]
            if not isinstance(value, list):
                raise ContractValidationError(
                    f"{field} must be an array",
                )
            values[field] = tuple(value)
        locators = values["source_locators"]
        if not isinstance(locators, list):
            raise ContractValidationError(
                "source_locators must be an array",
            )
        values["source_locators"] = tuple(
            SourceLocator.from_json(canonical_json(item)) for item in locators
        )
        return _construct(cls, values, "PassageRecord")


@dataclass(frozen=True, slots=True)
class ResourceDemand:
    """Wall time and peak memory an extraction or chunking call actually used."""

    wall_seconds: float
    peak_memory_bytes: int

    def __post_init__(self) -> None:
        seconds = validate_finite(self.wall_seconds)
        if seconds < 0:
            raise ContractValidationError(
                "wall_seconds must not be negative",
            )
        validate_non_negative_int(self.peak_memory_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_seconds": self.wall_seconds,
            "peak_memory_bytes": self.peak_memory_bytes,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ResourceDemand":
        values = _closed(raw, set(cls.__slots__), "ResourceDemand")
        return _construct(cls, values, "ResourceDemand")
