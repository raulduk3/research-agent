"""Bound deep_read's text and rendered-page media to MD-11's limits.

deep_read answers one of three request shapes (Appendix A: Launch
profile): a section id, one or two page numbers, or an immutable
``next_span`` continuation of a previous section response. A section (or
its continuation) renders as text, paginated to at most
:data:`MAX_TEXT_TOKENS` agent-model tokens with an explicit
:data:`DeepReadText.next_span` locator when more remains -- source figures
and tables already reach that text because
:mod:`research_agent.reader.extract` keeps their blocks in extraction
order. Page numbers instead rasterize the source PDF at 150dpi bounded to
1600px through an injected, restricted-subprocess renderer; this module
never runs OCR and never invents pixels for a page it could not render.
Every response is explicitly untrusted content (IN-23): no image or span
here can widen a run's tools or budgets.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..contracts.canonical import canonical_json, canonical_loads, sha256_hex
from ..contracts.passages import ExtractedBlock, SourceLocator
from ..contracts.primitives import ContractValidationError, validate_sha256
from .chunk import SectionTokenizer

__all__ = [
    "MAX_TEXT_TOKENS",
    "MAX_IMAGES",
    "MAX_IMAGE_BYTES",
    "RENDER_DPI",
    "MAX_IMAGE_EDGE_PIXELS",
    "DeepReadText",
    "RenderedPage",
    "PageRenderer",
    "SubprocessPageRenderer",
    "RenderingUnavailable",
    "render_section_text",
    "render_next_span",
    "render_pages",
    "render_deep_read_media",
]

MAX_TEXT_TOKENS = 6000
MAX_IMAGES = 2
MAX_IMAGE_BYTES = 10 * 1024 * 1024
RENDER_DPI = 150
MAX_IMAGE_EDGE_PIXELS = 1600


class RenderingUnavailable(Exception):
    """A page could not be rendered; deep_read names what is missing (MD-11)."""


@dataclass(frozen=True, slots=True)
class DeepReadText:
    """One paginated, untrusted text span of a section (MD-11, IN-23)."""

    text: str
    locators: tuple[SourceLocator, ...]
    token_count: int
    next_span: str | None
    untrusted: bool = True

    def __post_init__(self) -> None:
        if not self.text:
            raise ContractValidationError("a deep_read text span must be nonempty")
        if not self.locators:
            raise ContractValidationError("a deep_read text span requires locators")
        if self.token_count <= 0 or self.token_count > MAX_TEXT_TOKENS:
            raise ContractValidationError(
                f"token_count must be from 1 to {MAX_TEXT_TOKENS}"
            )
        if not self.untrusted:
            raise ContractValidationError("deep_read text must be marked untrusted")


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """One page rendered as an image, marked untrusted (MD-11, IN-23)."""

    locator: SourceLocator
    media_hash: str
    byte_length: int
    untrusted: bool = True

    def __post_init__(self) -> None:
        if self.locator.kind != "pdf" or self.locator.page_number is None:
            raise ContractValidationError("a rendered page requires a PDF page locator")
        validate_sha256(self.media_hash)
        if not 0 < self.byte_length <= MAX_IMAGE_BYTES:
            raise ContractValidationError("rendered page byte length is invalid")
        if not self.untrusted:
            raise ContractValidationError("a rendered page must be marked untrusted")


class PageRenderer(Protocol):
    """Rasterize one PDF page to PNG bytes at 150dpi bounded to 1600px."""

    def render(self, pdf_bytes: bytes, page_number: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SubprocessPageRenderer:
    """Render through ``pdftoppm`` in a time- and output-bounded subprocess.

    The renderer performs no network I/O and reads only the PDF bytes it
    is given; ``timeout_seconds`` bounds wall time and
    :data:`MAX_IMAGE_BYTES` bounds output so a hostile or malformed PDF
    cannot hang or exhaust the caller.
    """

    executable: str = "pdftoppm"
    timeout_seconds: float = 20.0

    def render(self, pdf_bytes: bytes, page_number: int) -> bytes:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            source = directory / "source.pdf"
            source.write_bytes(pdf_bytes)
            output_prefix = directory / "page"
            try:
                completed = subprocess.run(
                    [
                        self.executable,
                        "-f",
                        str(page_number),
                        "-l",
                        str(page_number),
                        "-r",
                        str(RENDER_DPI),
                        "-png",
                        "-scale-to",
                        str(MAX_IMAGE_EDGE_PIXELS),
                        str(source),
                        str(output_prefix),
                    ],
                    capture_output=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise RenderingUnavailable(
                    f"page {page_number} could not be rendered"
                ) from error
            if completed.returncode != 0:
                raise RenderingUnavailable(f"page {page_number} could not be rendered")
            rendered = sorted(directory.glob("page*.png"))
            if not rendered:
                raise RenderingUnavailable(f"page {page_number} produced no image")
            return rendered[0].read_bytes()


def render_pages(
    *,
    pdf_bytes: bytes,
    pdf_hash: str,
    page_numbers: tuple[int, ...],
    renderer: PageRenderer,
) -> tuple[RenderedPage, ...]:
    """Render *page_numbers* to bounded images, marked untrusted (MD-11).

    Requested over-budget content is refused rather than silently
    truncated: at most :data:`MAX_IMAGES` pages may be requested.
    """

    validate_sha256(pdf_hash)
    if not 1 <= len(page_numbers) <= MAX_IMAGES:
        raise ContractValidationError(f"deep_read renders at most {MAX_IMAGES} pages")
    rendered_pages: list[RenderedPage] = []
    for page_number in page_numbers:
        data = renderer.render(pdf_bytes, page_number)
        if len(data) > MAX_IMAGE_BYTES:
            raise RenderingUnavailable(
                f"page {page_number} rendered over the {MAX_IMAGE_BYTES}-byte bound"
            )
        rendered_pages.append(
            RenderedPage(
                locator=SourceLocator(pdf_hash, "pdf", page_number, None, None, None),
                media_hash=sha256_hex(data),
                byte_length=len(data),
            )
        )
    return tuple(rendered_pages)


def _covering_locators(
    blocks: tuple[ExtractedBlock, ...], start: int, end: int
) -> tuple[SourceLocator, ...]:
    covering: list[SourceLocator] = []
    seen: set[SourceLocator] = set()
    for block in blocks:
        if block.char_start < end and start < block.char_end_exclusive:
            if block.locator not in seen:
                seen.add(block.locator)
                covering.append(block.locator)
    if not covering:
        raise ContractValidationError("span has no source locator to attach")
    return tuple(covering)


def _paginate(
    canonical_text: str,
    blocks: tuple[ExtractedBlock, ...],
    start_char: int,
    end_char: int,
    paper_version_id: str,
    extraction_hash: str,
    tokenizer: SectionTokenizer,
) -> DeepReadText:
    if end_char <= start_char:
        raise ContractValidationError("a deep_read span must be nonempty")
    span_text = canonical_text[start_char:end_char]
    tokens = tokenizer.encode_offsets(span_text)
    if not tokens:
        raise ContractValidationError("span has no content to render")
    if len(tokens) <= MAX_TEXT_TOKENS:
        return DeepReadText(
            text=span_text,
            locators=_covering_locators(blocks, start_char, end_char),
            token_count=len(tokens),
            next_span=None,
        )
    cut = tokens[MAX_TEXT_TOKENS - 1][1]
    included_text = span_text[:cut]
    next_start = start_char + cut
    return DeepReadText(
        text=included_text,
        locators=_covering_locators(blocks, start_char, next_start),
        token_count=MAX_TEXT_TOKENS,
        next_span=_encode_span(paper_version_id, extraction_hash, next_start, end_char),
    )


def render_section_text(
    *,
    blocks: tuple[ExtractedBlock, ...],
    canonical_text: str,
    section_path: tuple[str, ...],
    paper_version_id: str,
    extraction_hash: str,
    tokenizer: SectionTokenizer,
) -> DeepReadText:
    """Render one section's included text, paginated at ``MAX_TEXT_TOKENS`` (MD-11).

    Only blocks already marked included in passages (extract.py's
    bibliography/furniture/unreadable exclusions) are ever served; a
    section absent from that set, or with no included blocks, is
    refused rather than answered from omitted text.
    """

    included = sorted(
        (
            block
            for block in blocks
            if block.section_path == section_path and block.included_in_passages
        ),
        key=lambda block: block.block_order,
    )
    if not included:
        raise ContractValidationError("section is empty or excluded from passages")
    start_char = included[0].char_start
    end_char = included[-1].char_end_exclusive
    return _paginate(
        canonical_text,
        blocks,
        start_char,
        end_char,
        paper_version_id,
        extraction_hash,
        tokenizer,
    )


def render_next_span(
    *,
    blocks: tuple[ExtractedBlock, ...],
    canonical_text: str,
    next_span: str,
    paper_version_id: str,
    extraction_hash: str,
    tokenizer: SectionTokenizer,
) -> DeepReadText:
    """Continue a previous section response from its ``next_span`` locator (MD-11).

    The token must name exactly this snapshot's paper version and
    extraction identity; a token minted for another paper or an earlier
    extraction is refused rather than resolved against the wrong text.
    """

    start_char, end_char = _decode_span(next_span, paper_version_id, extraction_hash)
    return _paginate(
        canonical_text,
        blocks,
        start_char,
        end_char,
        paper_version_id,
        extraction_hash,
        tokenizer,
    )


def _encode_span(
    paper_version_id: str, extraction_hash: str, start: int, end: int
) -> str:
    body = canonical_json(
        {
            "paper_version_id": paper_version_id,
            "extraction_hash": extraction_hash,
            "start": start,
            "end": end,
        }
    )
    return body.hex()


def _decode_span(
    token: str, paper_version_id: str, extraction_hash: str
) -> tuple[int, int]:
    try:
        value = canonical_loads(bytes.fromhex(token))
    except (ValueError, TypeError) as error:
        raise ContractValidationError(
            "next_span is not a valid continuation"
        ) from error
    if not isinstance(value, dict) or set(value) != {
        "paper_version_id",
        "extraction_hash",
        "start",
        "end",
    }:
        raise ContractValidationError("next_span is not a valid continuation")
    if (
        value["paper_version_id"] != paper_version_id
        or value["extraction_hash"] != extraction_hash
    ):
        raise ContractValidationError(
            "next_span does not name this snapshot's paper version"
        )
    start, end = value["start"], value["end"]
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end <= start
    ):
        raise ContractValidationError("next_span span bounds are invalid")
    return start, end


def render_deep_read_media(
    *,
    kind: str,
    section_path: tuple[str, ...] | None,
    pages: tuple[int, ...] | None,
    next_span: str | None,
    blocks: tuple[ExtractedBlock, ...],
    canonical_text: str,
    paper_version_id: str,
    extraction_hash: str,
    tokenizer: SectionTokenizer,
    pdf_bytes: bytes | None,
    pdf_hash: str | None,
    renderer: PageRenderer,
) -> DeepReadText | tuple[RenderedPage, ...]:
    """Render one deep_read request: a section, its continuation, or pages (MD-11).

    ``kind`` matches exactly the three variants
    :class:`research_agent.contracts.tools.ToolRequest` admits for
    deep_read -- ``"section"``, ``"next_span"`` or ``"pages"`` -- and
    dispatches to the matching bounded renderer: paginated text for the
    first two, at most :data:`MAX_IMAGES` rendered page images for the
    last. This is the single entry point deep_read's handler calls; the
    per-shape functions above remain independently usable and tested.
    """

    if kind == "section":
        if section_path is None:
            raise ContractValidationError("a section request requires section_path")
        return render_section_text(
            blocks=blocks,
            canonical_text=canonical_text,
            section_path=section_path,
            paper_version_id=paper_version_id,
            extraction_hash=extraction_hash,
            tokenizer=tokenizer,
        )
    if kind == "next_span":
        if next_span is None:
            raise ContractValidationError("a next_span request requires next_span")
        return render_next_span(
            blocks=blocks,
            canonical_text=canonical_text,
            next_span=next_span,
            paper_version_id=paper_version_id,
            extraction_hash=extraction_hash,
            tokenizer=tokenizer,
        )
    if kind == "pages":
        if pages is None or pdf_bytes is None or pdf_hash is None:
            raise ContractValidationError(
                "a pages request requires pages, pdf_bytes and pdf_hash"
            )
        return render_pages(
            pdf_bytes=pdf_bytes,
            pdf_hash=pdf_hash,
            page_numbers=pages,
            renderer=renderer,
        )
    raise ContractValidationError("deep_read kind is not admitted")
