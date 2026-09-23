"""Whole extracted-text assessment input (RD-17, TDD-4.1.55).

The state text is the saved paper version's body, appendix, caption and
table text in document order, with the extraction's coverage. Nothing else
from the paper record enters it: no title or abstract metadata, popularity,
discovery ranking, forecast, other-paper context or summary. The text is
checked against the 128 KiB launch cap and the verified provider token
limit, counting the rubric's own questions as overhead, before any request;
an empty or over-limit text becomes an unavailable input and is never
truncated, chunked or summarized to fit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from research_agent.contracts.assessments import (
    MAX_STATE_TEXT_BYTES,
    JevAssessmentInput,
    JevProviderIdentity,
)
from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.papers import PaperVersionRecord
from research_agent.contracts.passages import ExtractionRecord
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_positive_int,
)

from .rubric import Rubric

__all__ = [
    "ASSESSED_BLOCK_KINDS",
    "RequestTokenCounter",
    "ProviderInputLimit",
    "AssessmentInput",
    "build_assessment_input",
]

#: Block kinds an assessment reads; bibliography, page furniture and
#: unreadable blocks are not paper content for the rubric.
ASSESSED_BLOCK_KINDS = frozenset({"body", "appendix", "caption", "table"})
_BLOCK_SEPARATOR = "\n\n"


class RequestTokenCounter(Protocol):
    """The verified provider token count for a piece of request text."""

    def count(self, text: str) -> int: ...


@dataclass(frozen=True, slots=True)
class ProviderInputLimit:
    """The verified provider input limit, in tokens, for one whole request."""

    max_input_tokens: int

    def __post_init__(self) -> None:
        validate_positive_int(self.max_input_tokens)


@dataclass(frozen=True, slots=True)
class AssessmentInput:
    """The input record, the exact state text, and why it cannot be sent, if so."""

    record: JevAssessmentInput
    state_text: str
    unavailable_reason: str | None

    @property
    def sendable(self) -> bool:
        return self.unavailable_reason is None


def _state_text(extraction: ExtractionRecord, canonical_text: str) -> str:
    return _BLOCK_SEPARATOR.join(
        canonical_text[block.char_start : block.char_end_exclusive]
        for block in extraction.blocks
        if block.included_in_passages and block.kind in ASSESSED_BLOCK_KINDS
    )


def build_assessment_input(
    paper: PaperVersionRecord,
    extraction: ExtractionRecord,
    canonical_text: str,
    rubric: Rubric,
    provider: JevProviderIdentity,
    *,
    limit: ProviderInputLimit,
    counter: RequestTokenCounter,
    smoke_report_hash: str | None,
) -> AssessmentInput:
    """Build the one request input for `paper`'s saved extraction.

    `canonical_text` must be the extraction's own text (its length and hash
    are checked). The result is sendable only when the selected text is
    nonempty, at most 131072 UTF-8 bytes, and its tokens plus the rubric's
    question tokens fit `limit`; otherwise it carries `missing_input` or
    `input_too_large` and the caller makes no provider call.
    """

    if extraction.paper_version_id != paper.version_id:
        raise ContractValidationError("extraction belongs to another paper version")
    if len(canonical_text) != extraction.text_codepoints or (
        sha256_hex(canonical_text.encode("utf-8")) != extraction.text_hash
    ):
        raise ContractValidationError("canonical_text does not match the extraction")

    state_text = _state_text(extraction, canonical_text)
    encoded = state_text.encode("utf-8")
    empty = not state_text.strip()
    reasons = extraction.coverage_reasons
    if empty and "empty_text" not in reasons:
        reasons = (*reasons, "empty_text")
    record = JevAssessmentInput(
        paper_version_id=paper.version_id,
        extraction_hash=sha256_hex(extraction.to_canonical_json()),
        supplied_text_hash=sha256_hex(encoded),
        supplied_text_bytes=len(encoded),
        coverage="unavailable" if empty else extraction.coverage,
        coverage_reasons=reasons,
        rubric_hash=rubric.rubric_hash,
        provider_configuration_hash=provider.configuration_hash,
        smoke_report_hash=smoke_report_hash,
    )
    if empty:
        return AssessmentInput(record, "", "missing_input")
    if len(encoded) > MAX_STATE_TEXT_BYTES:
        return AssessmentInput(record, state_text, "input_too_large")
    overhead = counter.count(canonical_json(rubric.choice_questions()).decode("utf-8"))
    if counter.count(state_text) + overhead > limit.max_input_tokens:
        return AssessmentInput(record, state_text, "input_too_large")
    return AssessmentInput(record, state_text, None)
