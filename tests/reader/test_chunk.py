from collections.abc import Sequence
from uuid import uuid4

import pytest

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.passages import (
    ExtractedBlock,
    ExtractionRecord,
    SourceLocator,
)
from research_agent.reader.chunk import chunk_passages

_VERSION_ID = str(uuid4())
_EXTRACTION_HASH = "f" * 64


class _WhitespaceTokenizer:
    """A test tokenizer: one content token per whitespace-delimited word."""

    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        offsets: list[tuple[int, int]] = []
        index = 0
        length = len(text)
        while index < length:
            while index < length and text[index].isspace():
                index += 1
            if index >= length:
                break
            start = index
            while index < length and not text[index].isspace():
                index += 1
            offsets.append((start, index))
        return offsets


def _locator() -> SourceLocator:
    return SourceLocator("a" * 64, "latex", None, None, None, None)


def _build(sections: list[tuple[str, int]]) -> tuple[ExtractionRecord, str]:
    """Build one included block per (section_title, word_count) pair."""

    parts: list[str] = []
    blocks: list[ExtractedBlock] = []
    offset = 0
    for section_order, (title, word_count) in enumerate(sections):
        words = [f"tok{section_order}-{i}" for i in range(word_count)]
        text = " ".join(words)
        if parts:
            parts.append("\n\n")
            offset += 2
        start = offset
        parts.append(text)
        offset += len(text)
        blocks.append(
            ExtractedBlock(
                block_id=f"b{section_order}",
                section_path=(title,),
                section_order=section_order,
                block_order=len(blocks),
                kind="body",
                char_start=start,
                char_end_exclusive=offset,
                included_in_passages=True,
                omission_reason=None,
                locator=_locator(),
            )
        )
    canonical_text = "".join(parts)
    record = ExtractionRecord(
        paper_version_id=_VERSION_ID,
        source_hash="a" * 64,
        extractor_manifest_hash="b" * 64,
        text_hash=sha256_hex(canonical_text.encode("utf-8")),
        text_codepoints=len(canonical_text),
        blocks=tuple(blocks),
        coverage="complete",
        coverage_reasons=(),
        included_block_count=len(blocks),
        omitted_block_count=0,
        created_at="2026-01-01T00:00:00.000000Z",
    )
    return record, canonical_text


def _chunk(record: ExtractionRecord, text: str):
    return chunk_passages(record, text, _EXTRACTION_HASH, _WhitespaceTokenizer())


def passage_text(passage, text: str) -> str:
    return text[passage.char_start : passage.char_end_exclusive]


def test_short_section_forms_exactly_one_passage() -> None:
    record, text = _build([("Introduction", 100)])
    passages = _chunk(record, text)
    assert len(passages) == 1
    passage = passages[0]
    assert passage.section_token_start == 0
    assert passage.section_token_end_exclusive == 100
    assert passage.overlap_adjusted_weight == pytest.approx(100.0)
    assert passage_text(passage, text)


def test_long_section_slides_at_the_fixed_window_overlap_and_stride() -> None:
    record, text = _build([("Body", 800)])
    passages = _chunk(record, text)
    ranges = [
        (passage.section_token_start, passage.section_token_end_exclusive)
        for passage in passages
    ]
    assert ranges == [(0, 384), (320, 704), (640, 800)]
    for start, end in ranges:
        assert end - start <= 384
    # Consecutive starts advance by the fixed 320-token stride.
    assert ranges[1][0] - ranges[0][0] == 320
    assert ranges[2][0] - ranges[1][0] == 320
    # Weight distributes exactly one unit per content token, overlap included.
    total_weight = sum(passage.overlap_adjusted_weight for passage in passages)
    assert total_weight == pytest.approx(800.0)
    for passage in passages:
        span = passage_text(passage, text)
        assert span
        assert text[passage.char_start : passage.char_end_exclusive] == span


def test_passages_never_cross_a_section_boundary() -> None:
    record, text = _build([("Introduction", 200), ("Appendix", 200)])
    passages = _chunk(record, text)
    assert len(passages) == 2
    by_section = {passage.section_order: passage for passage in passages}
    assert by_section[0].section_path == ("Introduction",)
    assert by_section[1].section_path == ("Appendix",)
    assert by_section[0].block_ids == ("b0",)
    assert by_section[1].block_ids == ("b1",)
    intro_block = record.blocks[0]
    appendix_block = record.blocks[1]
    assert by_section[0].char_end_exclusive <= intro_block.char_end_exclusive
    assert by_section[1].char_start >= appendix_block.char_start


def test_a_section_with_no_included_blocks_yields_no_passages() -> None:
    record, text = _build([("Introduction", 50)])
    excluded_block = ExtractedBlock(
        block_id="bx",
        section_path=("Bibliography",),
        section_order=1,
        block_order=1,
        kind="bibliography",
        included_in_passages=False,
        omission_reason="bibliography",
        char_start=len(text),
        char_end_exclusive=len(text) + 5,
        locator=_locator(),
    )
    padded_text = text + "extra"
    record = ExtractionRecord(
        paper_version_id=record.paper_version_id,
        source_hash=record.source_hash,
        extractor_manifest_hash=record.extractor_manifest_hash,
        text_hash=sha256_hex(padded_text.encode("utf-8")),
        text_codepoints=len(padded_text),
        blocks=(*record.blocks, excluded_block),
        coverage="complete",
        coverage_reasons=(),
        included_block_count=1,
        omitted_block_count=1,
        created_at=record.created_at,
    )
    passages = _chunk(record, padded_text)
    assert len(passages) == 1
    assert passages[0].section_order == 0


def test_chunk_passages_rejects_text_that_does_not_match_the_extraction() -> None:
    record, text = _build([("Introduction", 10)])
    with pytest.raises(ContractValidationError):
        _chunk(record, text + " extra")
    with pytest.raises(ContractValidationError):
        _chunk(record, "x" * len(text))
