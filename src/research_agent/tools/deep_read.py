"""``deep_read``: a section, its continuation or rendered pages (MD-11).

Every read is of the one version the run's snapshot pins. A section or a
``next_span`` continuation is served from the paper's canonical text,
rebuilt from its pinned extraction and verified against the extraction's
text hash (``tools.text``), and paginated by ``reader.media``. A
``section_id`` names a top-level section as the card's section map lists it
(#270), so every block under that heading is read. Pages are
rasterized from the pinned source PDF by ``reader.media.render_pages`` and
answered as PNG bytes beside their hashes; a paper whose source is not a
PDF has no pages to render. Each call is one deep read and each page one
image of the run's budgets (AG-12). All content is marked untrusted.
"""

from __future__ import annotations

import base64
import dataclasses
from collections.abc import Mapping
from typing import Any

from ..contracts.primitives import ContractValidationError
from ..reader.chunk import SectionTokenizer
from ..reader.media import (
    DeepReadText,
    PageRenderer,
    RenderingUnavailable,
    render_next_span,
    render_pages,
    render_section_text,
)
from .answers import CallContext, ToolAnswer, ToolError
from .text import PinnedText, PinnedTexts, pdf_bytes

__all__ = ["DeepReadHandler"]


class DeepReadHandler:
    """Answer ``deep_read`` from the run's own pinned paper version."""

    def __init__(
        self,
        *,
        texts: PinnedTexts,
        tokenizer: SectionTokenizer,
        renderer: PageRenderer,
    ) -> None:
        self._texts = texts
        self._tokenizer = tokenizer
        self._renderer = renderer

    def __call__(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer:
        paper_id: str = arguments["paper_id"]
        if arguments["kind"] == "pages":
            return self._pages(paper_id, arguments["pages"], context)
        pinned = self._texts.text(context.snapshot_hash, paper_id)
        try:
            if arguments["kind"] == "section":
                span = self._section(pinned, arguments["section_id"])
            else:
                span = render_next_span(
                    blocks=pinned.extraction.blocks,
                    canonical_text=pinned.text,
                    next_span=arguments["next_span"],
                    paper_version_id=pinned.paper_version_id,
                    extraction_hash=pinned.extraction_hash,
                    tokenizer=self._tokenizer,
                )
        except ContractValidationError as error:
            raise ToolError("span_unavailable", str(error)) from error
        return ToolAnswer(
            {
                "kind": "text",
                "paper_id": paper_id,
                "untrusted": True,
                "text": span.text,
                "token_count": span.token_count,
                "source_locators": [locator.to_dict() for locator in span.locators],
                "next_span": span.next_span,
            },
            retrieved_ids=(pinned.extraction_hash,),
            deep_reads=1,
        )

    def _section(self, pinned: PinnedText, section_id: str) -> DeepReadText:
        """Every block under the top-level heading *section_id*, as one section."""

        blocks = tuple(
            dataclasses.replace(block, section_path=(section_id,))
            if block.section_path[:1] == (section_id,)
            else block
            for block in pinned.extraction.blocks
        )
        return render_section_text(
            blocks=blocks,
            canonical_text=pinned.text,
            section_path=(section_id,),
            paper_version_id=pinned.paper_version_id,
            extraction_hash=pinned.extraction_hash,
            tokenizer=self._tokenizer,
        )

    def _pages(
        self, paper_id: str, pages: tuple[int, ...], context: CallContext
    ) -> ToolAnswer:
        source = self._texts.source(context.snapshot_hash, paper_id)
        pdf = pdf_bytes(source.payload)
        if pdf is None:
            raise ToolError("pages_unavailable", "the paper's source is not a PDF")
        recording = _RecordingRenderer(self._renderer)
        try:
            pages_rendered = render_pages(
                pdf_bytes=pdf,
                pdf_hash=source.artifact_hash,
                page_numbers=pages,
                renderer=recording,
            )
        except RenderingUnavailable as error:
            raise ToolError("pages_unavailable", str(error)) from error
        rendered = [
            {
                "page_number": page_number,
                "media_type": "image/png",
                "media_hash": page.media_hash,
                "image_base64": base64.b64encode(recording.images[page_number]).decode(
                    "ascii"
                ),
                "source_locator": page.locator.to_dict(),
            }
            for page_number, page in zip(pages, pages_rendered, strict=True)
        ]
        return ToolAnswer(
            {
                "kind": "pages",
                "paper_id": paper_id,
                "untrusted": True,
                "pages": rendered,
            },
            retrieved_ids=(source.artifact_hash,),
            deep_reads=1,
            images=len(rendered),
        )


class _RecordingRenderer:
    """Keeps each page's bytes, so the answer carries exactly the image
    ``render_pages`` bounded and hashed."""

    def __init__(self, renderer: PageRenderer) -> None:
        self._renderer = renderer
        self.images: dict[int, bytes] = {}

    def render(self, pdf_bytes: bytes, page_number: int) -> bytes:
        image = self._renderer.render(pdf_bytes, page_number)
        self.images[page_number] = image
        return image
