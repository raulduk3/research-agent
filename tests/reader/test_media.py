from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import pytest

from research_agent.contracts.passages import ExtractedBlock, SourceLocator
from research_agent.contracts.primitives import ContractValidationError
from research_agent.reader.media import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    MAX_TEXT_TOKENS,
    RenderingUnavailable,
    render_deep_read_media,
    render_next_span,
    render_pages,
    render_section_text,
)

VERSION_ID = str(uuid4())
EXTRACTION_HASH = "f" * 64
PDF_HASH = "a" * 64


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


def _locator(page: int | None = None) -> SourceLocator:
    if page is None:
        return SourceLocator(PDF_HASH, "latex", None, None, None, None)
    return SourceLocator(PDF_HASH, "pdf", page, None, None, None)


def _block(
    *, block_order: int, char_start: int, char_end: int, section_path: tuple[str, ...]
) -> ExtractedBlock:
    return ExtractedBlock(
        block_id=f"b{block_order:05d}",
        section_path=section_path,
        section_order=0,
        block_order=block_order,
        kind="body",
        char_start=char_start,
        char_end_exclusive=char_end,
        included_in_passages=True,
        omission_reason=None,
        locator=_locator(),
    )


def test_render_section_text_returns_the_sections_included_text() -> None:
    text = "one two three four five"
    blocks = (
        _block(block_order=0, char_start=0, char_end=len(text), section_path=("Body",)),
    )
    result = render_section_text(
        blocks=blocks,
        canonical_text=text,
        section_path=("Body",),
        paper_version_id=VERSION_ID,
        extraction_hash=EXTRACTION_HASH,
        tokenizer=_WhitespaceTokenizer(),
    )
    assert result.text == text
    assert result.token_count == 5
    assert result.next_span is None
    assert result.locators == (_locator(),)
    assert result.untrusted is True


def test_render_section_text_rejects_an_empty_or_excluded_section() -> None:
    blocks = (_block(block_order=0, char_start=0, char_end=5, section_path=("Body",)),)
    with pytest.raises(ContractValidationError):
        render_section_text(
            blocks=blocks,
            canonical_text="one t",
            section_path=("Missing",),
            paper_version_id=VERSION_ID,
            extraction_hash=EXTRACTION_HASH,
            tokenizer=_WhitespaceTokenizer(),
        )


def test_render_section_text_paginates_past_the_token_cap_and_next_span_continues() -> (
    None
):
    words = [f"word{i}" for i in range(MAX_TEXT_TOKENS + 50)]
    text = " ".join(words)
    blocks = (
        _block(block_order=0, char_start=0, char_end=len(text), section_path=("Body",)),
    )
    first = render_section_text(
        blocks=blocks,
        canonical_text=text,
        section_path=("Body",),
        paper_version_id=VERSION_ID,
        extraction_hash=EXTRACTION_HASH,
        tokenizer=_WhitespaceTokenizer(),
    )
    assert first.token_count == MAX_TEXT_TOKENS
    assert first.next_span is not None
    assert first.text == " ".join(words[:MAX_TEXT_TOKENS])

    second = render_next_span(
        blocks=blocks,
        canonical_text=text,
        next_span=first.next_span,
        paper_version_id=VERSION_ID,
        extraction_hash=EXTRACTION_HASH,
        tokenizer=_WhitespaceTokenizer(),
    )
    assert second.next_span is None
    assert first.text + second.text == text


def test_render_next_span_rejects_a_token_from_another_paper_version() -> None:
    words = [f"word{i}" for i in range(MAX_TEXT_TOKENS + 1)]
    text = " ".join(words)
    blocks = (
        _block(block_order=0, char_start=0, char_end=len(text), section_path=("Body",)),
    )
    result = render_section_text(
        blocks=blocks,
        canonical_text=text,
        section_path=("Body",),
        paper_version_id=VERSION_ID,
        extraction_hash=EXTRACTION_HASH,
        tokenizer=_WhitespaceTokenizer(),
    )
    assert result.next_span is not None
    with pytest.raises(ContractValidationError):
        render_next_span(
            blocks=blocks,
            canonical_text=text,
            next_span=result.next_span,
            paper_version_id=str(uuid4()),
            extraction_hash=EXTRACTION_HASH,
            tokenizer=_WhitespaceTokenizer(),
        )


def test_render_next_span_rejects_a_malformed_token() -> None:
    with pytest.raises(ContractValidationError):
        render_next_span(
            blocks=(),
            canonical_text="one two",
            next_span="not-a-real-token",
            paper_version_id=VERSION_ID,
            extraction_hash=EXTRACTION_HASH,
            tokenizer=_WhitespaceTokenizer(),
        )


class _FakeRenderer:
    def __init__(self, payload: bytes = b"\x89PNG-fake-bytes") -> None:
        self.payload = payload
        self.calls: list[int] = []

    def render(self, pdf_bytes: bytes, page_number: int) -> bytes:
        self.calls.append(page_number)
        return self.payload


def test_render_pages_returns_locators_and_media_hashes_in_order() -> None:
    renderer = _FakeRenderer()
    pages = render_pages(
        pdf_bytes=b"%PDF-fake",
        pdf_hash=PDF_HASH,
        page_numbers=(1, 2),
        renderer=renderer,
    )
    assert renderer.calls == [1, 2]
    assert [page.locator.page_number for page in pages] == [1, 2]
    assert all(page.untrusted for page in pages)
    assert all(page.locator.kind == "pdf" for page in pages)


def test_render_pages_rejects_more_than_the_image_cap() -> None:
    with pytest.raises(ContractValidationError):
        render_pages(
            pdf_bytes=b"%PDF-fake",
            pdf_hash=PDF_HASH,
            page_numbers=tuple(range(1, MAX_IMAGES + 2)),
            renderer=_FakeRenderer(),
        )


def test_render_pages_rejects_a_rendering_that_exceeds_the_byte_bound() -> None:
    renderer = _FakeRenderer(payload=b"x" * (MAX_IMAGE_BYTES + 1))
    with pytest.raises(RenderingUnavailable):
        render_pages(
            pdf_bytes=b"%PDF-fake",
            pdf_hash=PDF_HASH,
            page_numbers=(1,),
            renderer=renderer,
        )


class _FailingRenderer:
    def render(self, pdf_bytes: bytes, page_number: int) -> bytes:
        raise RenderingUnavailable("page could not be rendered")


def test_render_pages_propagates_an_unavailable_page() -> None:
    with pytest.raises(RenderingUnavailable):
        render_pages(
            pdf_bytes=b"%PDF-fake",
            pdf_hash=PDF_HASH,
            page_numbers=(1,),
            renderer=_FailingRenderer(),
        )


def test_render_deep_read_media_dispatches_each_admitted_kind() -> None:
    text = "one two three"
    blocks = (
        _block(block_order=0, char_start=0, char_end=len(text), section_path=("Body",)),
    )
    section_result = render_deep_read_media(
        kind="section",
        section_path=("Body",),
        pages=None,
        next_span=None,
        blocks=blocks,
        canonical_text=text,
        paper_version_id=VERSION_ID,
        extraction_hash=EXTRACTION_HASH,
        tokenizer=_WhitespaceTokenizer(),
        pdf_bytes=None,
        pdf_hash=None,
        renderer=_FakeRenderer(),
    )
    assert section_result.text == text

    pages_result = render_deep_read_media(
        kind="pages",
        section_path=None,
        pages=(1,),
        next_span=None,
        blocks=(),
        canonical_text="",
        paper_version_id=VERSION_ID,
        extraction_hash=EXTRACTION_HASH,
        tokenizer=_WhitespaceTokenizer(),
        pdf_bytes=b"%PDF-fake",
        pdf_hash=PDF_HASH,
        renderer=_FakeRenderer(),
    )
    assert pages_result[0].locator.page_number == 1


def test_render_deep_read_media_rejects_a_kind_missing_its_own_field() -> None:
    with pytest.raises(ContractValidationError):
        render_deep_read_media(
            kind="section",
            section_path=None,
            pages=None,
            next_span=None,
            blocks=(),
            canonical_text="",
            paper_version_id=VERSION_ID,
            extraction_hash=EXTRACTION_HASH,
            tokenizer=_WhitespaceTokenizer(),
            pdf_bytes=None,
            pdf_hash=None,
            renderer=_FakeRenderer(),
        )
    with pytest.raises(ContractValidationError):
        render_deep_read_media(
            kind="browse",
            section_path=None,
            pages=None,
            next_span=None,
            blocks=(),
            canonical_text="",
            paper_version_id=VERSION_ID,
            extraction_hash=EXTRACTION_HASH,
            tokenizer=_WhitespaceTokenizer(),
            pdf_bytes=None,
            pdf_hash=None,
            renderer=_FakeRenderer(),
        )
