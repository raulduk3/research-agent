"""Chunk extracted text to the fixed passage policy (Appendix C: Retrieval protocol).

Splits within section boundaries into at most 384 content tokens with 64-token
overlap and a 320-token stride, never crossing a section, using the pinned
embedding tokenizer supplied by the caller.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple, Protocol

from ..contracts.canonical import sha256_hex
from ..contracts.primitives import ContractValidationError
from ..contracts.passages import (
    CHUNK_POLICY,
    CHUNK_STRIDE_TOKENS,
    CHUNK_WINDOW_TOKENS,
    ExtractedBlock,
    ExtractionRecord,
    PassageRecord,
    SourceLocator,
)

__all__ = ["SectionTokenizer", "chunk_passages"]


class SectionTokenizer(Protocol):
    """The pinned tokenizer's content-token offsets over one span of text."""

    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        """Return each token's (start, end_exclusive) codepoint span, in order."""


class _Token(NamedTuple):
    char_start: int
    char_end: int
    block_id: str


def _section_groups(
    blocks: tuple[ExtractedBlock, ...],
) -> list[tuple[int, tuple[str, ...], list[ExtractedBlock]]]:
    order: dict[int, tuple[str, ...]] = {}
    grouped: dict[int, list[ExtractedBlock]] = {}
    for block in blocks:
        order.setdefault(block.section_order, block.section_path)
        grouped.setdefault(block.section_order, []).append(block)
    groups: list[tuple[int, tuple[str, ...], list[ExtractedBlock]]] = []
    for section_order in sorted(grouped):
        groups.append(
            (
                section_order,
                order[section_order],
                grouped[section_order],
            ),
        )
    return groups


def _token_stream(
    included: list[ExtractedBlock],
    canonical_text: str,
    tokenizer: SectionTokenizer,
) -> list[_Token]:
    stream: list[_Token] = []
    for block in included:
        span_text = canonical_text[block.char_start : block.char_end_exclusive]
        for local_start, local_end in tokenizer.encode_offsets(span_text):
            stream.append(
                _Token(
                    block.char_start + local_start,
                    block.char_start + local_end,
                    block.block_id,
                )
            )
    return stream


def _window_ranges(total_tokens: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    last_end = 0
    start = 0
    while start < total_tokens:
        end = min(start + CHUNK_WINDOW_TOKENS, total_tokens)
        if not ranges or end > last_end:
            ranges.append((start, end))
            last_end = end
        if end == total_tokens:
            break
        start += CHUNK_STRIDE_TOKENS
    return ranges


def _weights(ranges: list[tuple[int, int]], total_tokens: int) -> list[float]:
    coverage = [0] * total_tokens
    for start, end in ranges:
        for index in range(start, end):
            coverage[index] += 1
    weights: list[float] = []
    for start, end in ranges:
        weights.append(sum(1.0 / coverage[index] for index in range(start, end)))
    return weights


def _validate_canonical_text(
    extraction: ExtractionRecord,
    canonical_text: str,
) -> None:
    if len(canonical_text) != extraction.text_codepoints:
        raise ContractValidationError(
            "canonical_text length does not match the extraction",
        )
    if sha256_hex(canonical_text.encode("utf-8")) != extraction.text_hash:
        raise ContractValidationError(
            "canonical_text does not match the extraction's hash",
        )


def chunk_passages(
    extraction: ExtractionRecord,
    canonical_text: str,
    extraction_hash: str,
    tokenizer: SectionTokenizer,
) -> tuple[PassageRecord, ...]:
    """Chunk one extraction's included text into ordered, source-linked passages."""

    _validate_canonical_text(extraction, canonical_text)

    passages: list[PassageRecord] = []
    for section_order, section_path, group in _section_groups(extraction.blocks):
        included = [block for block in group if block.included_in_passages]
        if not included:
            continue
        locators: dict[str, SourceLocator] = {
            block.block_id: block.locator for block in included
        }
        # A window never spans an omitted block. A passage is one contiguous
        # span of canonical text, so a window whose tokens sit on both sides of
        # an omitted bibliography would carry the whole bibliography between
        # them: text the extraction excluded, and far more than the window.
        # Each run of included blocks with nothing omitted between them is
        # windowed on its own; token indexes stay section-relative.
        passage_order = 0
        run_offset = 0
        for run in _contiguous_runs(group):
            stream = _token_stream(run, canonical_text, tokenizer)
            total_tokens = len(stream)
            if total_tokens == 0:
                continue
            ranges = _window_ranges(total_tokens)
            weights = _weights(ranges, total_tokens)
            for span, weight in zip(ranges, weights, strict=True):
                start, end = span
                tokens = stream[start:end]
                char_start = tokens[0].char_start
                char_end_exclusive = tokens[-1].char_end
                block_ids: list[str] = []
                for token in tokens:
                    if token.block_id not in block_ids:
                        block_ids.append(token.block_id)
                passage_text = canonical_text[char_start:char_end_exclusive]
                passages.append(
                    PassageRecord(
                        paper_version_id=extraction.paper_version_id,
                        extraction_hash=extraction_hash,
                        chunk_policy=CHUNK_POLICY,
                        section_order=section_order,
                        section_path=section_path,
                        passage_order=passage_order,
                        section_token_start=run_offset + start,
                        section_token_end_exclusive=run_offset + end,
                        char_start=char_start,
                        char_end_exclusive=char_end_exclusive,
                        block_ids=tuple(block_ids),
                        text_hash=sha256_hex(passage_text.encode("utf-8")),
                        source_locators=tuple(
                            locators[block_id] for block_id in block_ids
                        ),
                        overlap_adjusted_weight=weight,
                    )
                )
                passage_order += 1
            run_offset += total_tokens
    return tuple(passages)


def _contiguous_runs(group: list[ExtractedBlock]) -> list[list[ExtractedBlock]]:
    """Runs of included blocks, split wherever an omitted block sits between."""
    runs: list[list[ExtractedBlock]] = []
    current: list[ExtractedBlock] = []
    for block in group:
        if block.included_in_passages:
            current.append(block)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs
