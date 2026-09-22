"""Extract an immutable paper version's text into ordered contract blocks.

Only non-executing source parsing and already-obtained PDF text-layer pages
are read here; nothing here runs TeX or an optical character recognition
model (SDD-MD-10). A page with no text layer is recorded unreadable rather
than invented.
"""

from __future__ import annotations

import re
import time
import tracemalloc
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

from ..contracts.canonical import sha256_hex
from ..contracts.passages import (
    ExtractedBlock,
    ExtractionRecord,
    ResourceDemand,
    SourceLocator,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")

_MARKER = re.compile(
    r"\\(?P<section>(?:sub){0,2}section)\*?\{(?P<title>[^{}]*)\}"
    r"|\\(?P<appendix>appendix)\b"
    r"|\\begin\{(?P<begin>abstract|thebibliography|table\*?|figure\*?)\}"
    r"|\\end\{(?P<end>abstract|thebibliography|table\*?|figure\*?)\}"
    r"|\\bibliography\{(?P<bib>[^{}]*)\}"
    r"|\\caption\{(?P<caption>[^{}]*)\}"
)
_SECTION_DEPTH = {"section": 1, "subsection": 2, "subsubsection": 3}
_TABLE_ENVS = {"table", "table*", "figure", "figure*"}


def normalize_text(source: str) -> str:
    """Return the canonical NFC text with LF-only line endings."""

    text = unicodedata.normalize("NFC", source)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _latex_locator(source_hash: str) -> SourceLocator:
    return SourceLocator(
        source_hash,
        "latex",
        None,
        None,
        None,
        None,
    )


def _pdf_locator(source_hash: str, page_number: int) -> SourceLocator:
    return SourceLocator(
        source_hash,
        "pdf",
        page_number,
        None,
        None,
        None,
    )


def measure(
    fn: Callable[_P, _R], *args: _P.args, **kwargs: _P.kwargs
) -> tuple[_R, ResourceDemand]:
    """Run *fn* once, recording its monotonic wall time and peak Python memory."""

    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
    finally:
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return result, ResourceDemand(elapsed, peak)


class _Builder:
    def __init__(self, text: str, source_hash: str) -> None:
        self._text = text
        self._source_hash = source_hash
        self._blocks: list[ExtractedBlock] = []
        self._section_orders: dict[tuple[str, ...], int] = {}
        self._path: tuple[str, ...] = ("Document",)
        self._appendix = False
        self._env: list[str] = []

    def _order(self, path: tuple[str, ...]) -> int:
        if path not in self._section_orders:
            self._section_orders[path] = len(self._section_orders)
        return self._section_orders[path]

    def _current_kind(self) -> tuple[str, tuple[str, ...], bool, str | None]:
        if self._env and self._env[-1] == "abstract":
            return "body", ("Abstract",), True, None
        if self._env and self._env[-1] == "bibliography":
            return "bibliography", self._path, False, "bibliography"
        if self._env and self._env[-1] == "table":
            return "table", self._path, True, None
        kind = "appendix" if self._appendix else "body"
        return kind, self._path, True, None

    def _emit(
        self,
        start: int,
        end: int,
        kind: str,
        path: tuple[str, ...],
        included: bool,
        reason: str | None,
        locator: SourceLocator,
    ) -> None:
        if end <= start:
            return
        self._blocks.append(
            ExtractedBlock(
                block_id=f"b{len(self._blocks):05d}",
                section_path=path,
                section_order=self._order(path),
                block_order=len(self._blocks),
                kind=kind,
                char_start=start,
                char_end_exclusive=end,
                included_in_passages=included,
                omission_reason=reason,
                locator=locator,
            )
        )

    def _emit_content(self, start: int, end: int, locator: SourceLocator) -> None:
        kind, path, included, reason = self._current_kind()
        self._emit(start, end, kind, path, included, reason, locator)

    def build(self) -> tuple[ExtractedBlock, ...]:
        cursor = 0
        for match in _MARKER.finditer(self._text):
            locator = _latex_locator(self._source_hash)
            self._emit_content(cursor, match.start(), locator)
            if match.group("section") is not None:
                depth = _SECTION_DEPTH[match.group("section")]
                title = match.group("title").strip()
                if title:
                    base = self._path[: depth - 1]
                    if len(base) < depth - 1:
                        base = base + ("Untitled",) * (depth - 1 - len(base))
                    self._path = (*base, title)
            elif match.group("appendix") is not None:
                self._appendix = True
            elif match.group("begin") is not None:
                name = match.group("begin")
                if name in _TABLE_ENVS:
                    self._env.append("table")
                elif name == "thebibliography":
                    self._env.append("bibliography")
                else:
                    self._env.append(name)
            elif match.group("end") is not None:
                if self._env:
                    self._env.pop()
            elif match.group("bib") is not None:
                self._emit(
                    match.start(),
                    match.end(),
                    "bibliography",
                    self._path,
                    False,
                    "bibliography",
                    locator,
                )
            elif match.group("caption") is not None:
                self._emit(
                    match.start("caption"),
                    match.end("caption"),
                    "caption",
                    self._path,
                    True,
                    None,
                    locator,
                )
            cursor = match.end()
        locator = _latex_locator(self._source_hash)
        self._emit_content(cursor, len(self._text), locator)
        return tuple(self._blocks)


def extract_latex(
    paper_version_id: str,
    source_hash: str,
    extractor_manifest_hash: str,
    latex_source: str,
    created_at: str,
) -> ExtractionRecord:
    """Extract ordered blocks from LaTeX source text using a non-executing parser."""

    text = normalize_text(latex_source)
    if not text.strip():
        return ExtractionRecord(
            paper_version_id=paper_version_id,
            source_hash=source_hash,
            extractor_manifest_hash=extractor_manifest_hash,
            text_hash=sha256_hex(text.encode("utf-8")),
            text_codepoints=len(text),
            blocks=(),
            coverage="unavailable",
            coverage_reasons=("empty_text",),
            included_block_count=0,
            omitted_block_count=0,
            created_at=created_at,
        )
    blocks = _Builder(text, source_hash).build()
    coverage = "complete"
    reasons: tuple[str, ...] = ()
    if not blocks:
        coverage = "unavailable"
        reasons = ("parse_failure",)
    included = sum(1 for block in blocks if block.included_in_passages)
    return ExtractionRecord(
        paper_version_id=paper_version_id,
        source_hash=source_hash,
        extractor_manifest_hash=extractor_manifest_hash,
        text_hash=sha256_hex(text.encode("utf-8")),
        text_codepoints=len(text),
        blocks=blocks,
        coverage=coverage,
        coverage_reasons=reasons,
        included_block_count=included,
        omitted_block_count=len(blocks) - included,
        created_at=created_at,
    )


@dataclass(frozen=True, slots=True)
class PdfPage:
    """One already-obtained page of a PDF's text layer.

    Rendering PDF bytes into pages is a separate, non-executing concern
    (SDD-MD-10); this module only structures pages it is given.
    """

    page_number: int
    text: str
    has_image: bool


def extract_pdf(
    paper_version_id: str,
    source_hash: str,
    extractor_manifest_hash: str,
    pages: Sequence[PdfPage],
    created_at: str,
) -> ExtractionRecord:
    """Structure an already-extracted PDF text layer; never invoke OCR."""

    if not pages:
        return ExtractionRecord(
            paper_version_id=paper_version_id,
            source_hash=source_hash,
            extractor_manifest_hash=extractor_manifest_hash,
            text_hash=sha256_hex(b""),
            text_codepoints=0,
            blocks=(),
            coverage="unavailable",
            coverage_reasons=("source_missing",),
            included_block_count=0,
            omitted_block_count=0,
            created_at=created_at,
        )
    ordered = sorted(pages, key=lambda page: page.page_number)
    expected_numbers = list(range(1, len(ordered) + 1))
    if [page.page_number for page in ordered] != expected_numbers:
        raise ValueError("PDF pages must be one-based and contiguous")

    parts: list[str] = []
    blocks: list[ExtractedBlock] = []
    offset = 0
    readable_pages = 0
    for page in ordered:
        normalized = normalize_text(page.text)
        locator = _pdf_locator(source_hash, page.page_number)
        if normalized.strip():
            readable_pages += 1
            if parts:
                parts.append("\n")
                offset += 1
            start = offset
            parts.append(normalized)
            offset += len(normalized)
            blocks.append(
                ExtractedBlock(
                    block_id=f"b{len(blocks):05d}",
                    section_path=("Body",),
                    section_order=0,
                    block_order=len(blocks),
                    kind="body",
                    char_start=start,
                    char_end_exclusive=offset,
                    included_in_passages=True,
                    omission_reason=None,
                    locator=locator,
                )
            )
        elif page.has_image:
            blocks.append(
                ExtractedBlock(
                    block_id=f"b{len(blocks):05d}",
                    section_path=("Body",),
                    section_order=0,
                    block_order=len(blocks),
                    kind="unreadable",
                    char_start=offset,
                    char_end_exclusive=offset,
                    included_in_passages=False,
                    omission_reason="unreadable",
                    locator=locator,
                )
            )

    text = "".join(parts)
    reasons: tuple[str, ...]
    if readable_pages == len(ordered):
        coverage, reasons = "complete", ()
    elif readable_pages == 0:
        coverage, reasons = "unavailable", ("empty_text",)
    else:
        coverage, reasons = "partial", ("unreadable_blocks",)
    included = sum(1 for block in blocks if block.included_in_passages)
    return ExtractionRecord(
        paper_version_id=paper_version_id,
        source_hash=source_hash,
        extractor_manifest_hash=extractor_manifest_hash,
        text_hash=sha256_hex(text.encode("utf-8")),
        text_codepoints=len(text),
        blocks=tuple(blocks),
        coverage=coverage,
        coverage_reasons=reasons,
        included_block_count=included,
        omitted_block_count=len(blocks) - included,
        created_at=created_at,
    )


def extract_unsupported(
    paper_version_id: str,
    source_hash: str,
    extractor_manifest_hash: str,
    created_at: str,
) -> ExtractionRecord:
    """Record unavailable coverage for a source with no supported text layer."""

    return ExtractionRecord(
        paper_version_id=paper_version_id,
        source_hash=source_hash,
        extractor_manifest_hash=extractor_manifest_hash,
        text_hash=sha256_hex(b""),
        text_codepoints=0,
        blocks=(),
        coverage="unavailable",
        coverage_reasons=("unsupported_source",),
        included_block_count=0,
        omitted_block_count=0,
        created_at=created_at,
    )
