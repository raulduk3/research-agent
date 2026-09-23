from uuid import uuid4

import pytest

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.passages import ExtractionRecord
from research_agent.reader.extract import (
    PdfPage,
    extract_latex,
    extract_pdf,
    extract_unsupported,
    latex_section_rules,
    measure,
    normalize_text,
    pdf_section_rules,
)

_VERSION_ID = str(uuid4())
_SOURCE_HASH = "a" * 64
_MANIFEST_HASH = "b" * 64
_CREATED_AT = "2026-01-01T00:00:00.000000Z"

_LATEX = r"""
\begin{abstract}
This paper studies chunking.
\end{abstract}
\section{Introduction}
Background text about the problem.
\subsection{Motivation}
More detail on why it matters.
\begin{table}
Row one. Row two.
\caption{A small results table.}
\end{table}
\appendix
\section{Proofs}
Supporting proofs go here.
\begin{thebibliography}{9}
\bibitem{a} Some Author, Some Title, 2020.
\end{thebibliography}
"""


def _extract(source: str) -> ExtractionRecord:
    return extract_latex(_VERSION_ID, _SOURCE_HASH, _MANIFEST_HASH, source, _CREATED_AT)


def _extract_pdf(pages: list[PdfPage]) -> ExtractionRecord:
    return extract_pdf(_VERSION_ID, _SOURCE_HASH, _MANIFEST_HASH, pages, _CREATED_AT)


def _blocks_text(record: ExtractionRecord, canonical: str) -> dict[str, str]:
    return {
        block.block_id: canonical[block.char_start : block.char_end_exclusive]
        for block in record.blocks
    }


def test_extract_latex_sections_captions_and_excludes_bibliography() -> None:
    record = _extract(_LATEX)
    assert record.coverage == "complete"
    assert record.coverage_reasons == ()
    canonical = normalize_text(_LATEX)
    assert record.text_hash == sha256_hex(canonical.encode("utf-8"))
    assert record.text_codepoints == len(canonical)

    texts = _blocks_text(record, canonical)
    kinds = {block.block_id: block.kind for block in record.blocks}
    paths = {block.block_id: block.section_path for block in record.blocks}
    included = {block.block_id: block.included_in_passages for block in record.blocks}

    assert any("This paper studies chunking." in text for text in texts.values())
    assert any(
        path == ("Abstract",) and "chunking" in texts[block_id]
        for block_id, path in paths.items()
    )
    assert any(
        path == ("Introduction",) and "Background text" in texts[block_id]
        for block_id, path in paths.items()
    )
    assert any(
        path == ("Introduction", "Motivation") and "why it matters" in texts[block_id]
        for block_id, path in paths.items()
    )
    assert any(
        kind == "caption" and "results table" in texts[block_id]
        for block_id, kind in kinds.items()
    )
    assert any(
        kind == "table" and "Row one" in texts[block_id]
        for block_id, kind in kinds.items()
    )
    assert any(kind == "appendix" for kind in kinds.values())

    bibliography_ids = [bid for bid, kind in kinds.items() if kind == "bibliography"]
    assert bibliography_ids
    for block_id in bibliography_ids:
        assert included[block_id] is False

    # Reconstructing every span from the stored canonical text must be exact.
    for block in record.blocks:
        span = canonical[block.char_start : block.char_end_exclusive]
        assert span == texts[block.block_id]

    included_count = sum(1 for value in included.values() if value)
    omitted_count = sum(1 for value in included.values() if not value)
    assert record.included_block_count == included_count
    assert record.omitted_block_count == omitted_count


def test_extract_latex_empty_source_is_unavailable_without_inventing_text() -> None:
    record = _extract("   \n\t  ")
    assert record.coverage == "unavailable"
    assert record.coverage_reasons == ("empty_text",)
    assert record.blocks == ()


def test_extract_latex_falls_back_to_one_body_block_without_headings() -> None:
    record = _extract("Just plain prose, no markup.")
    assert record.coverage == "complete"
    assert len(record.blocks) == 1
    assert record.blocks[0].kind == "body"
    assert record.blocks[0].included_in_passages is True


def test_extract_pdf_marks_an_image_only_page_unreadable_without_ocr() -> None:
    pages = [
        PdfPage(1, "Real extracted text from the text layer.", False),
        PdfPage(2, "", True),
        PdfPage(3, "More real text on the third page.", False),
    ]
    record = _extract_pdf(pages)
    assert record.coverage == "partial"
    assert record.coverage_reasons == ("unreadable_blocks",)

    unreadable = [block for block in record.blocks if block.kind == "unreadable"]
    assert len(unreadable) == 1
    block = unreadable[0]
    assert block.included_in_passages is False
    assert block.omission_reason == "unreadable"
    # No OCR ever runs: an image-only page contributes no characters at all.
    assert block.char_start == block.char_end_exclusive
    assert block.locator.page_number == 2

    for included_block in (b for b in record.blocks if b.included_in_passages):
        assert included_block.char_end_exclusive > included_block.char_start


def test_extract_pdf_scanned_document_is_unavailable() -> None:
    pages = [PdfPage(1, "", True), PdfPage(2, "", True)]
    record = _extract_pdf(pages)
    assert record.coverage == "unavailable"
    assert record.coverage_reasons == ("empty_text",)
    assert record.text_codepoints == 0
    assert all(not block.included_in_passages for block in record.blocks)


def test_extract_pdf_requires_contiguous_one_based_pages() -> None:
    with pytest.raises(ValueError):
        _extract_pdf([PdfPage(0, "text", False)])


def test_extract_pdf_with_no_pages_is_source_missing() -> None:
    record = _extract_pdf([])
    assert record.coverage == "unavailable"
    assert record.coverage_reasons == ("source_missing",)


def test_extract_unsupported_records_no_text_layer() -> None:
    record = extract_unsupported(_VERSION_ID, _SOURCE_HASH, _MANIFEST_HASH, _CREATED_AT)
    assert record.coverage == "unavailable"
    assert record.coverage_reasons == ("unsupported_source",)
    assert record.blocks == ()


def test_measure_reports_a_nonnegative_demand_record() -> None:
    result, demand = measure(lambda x: x * 2, 21)
    assert result == 42
    assert demand.wall_seconds >= 0
    assert demand.peak_memory_bytes >= 0


def _paths(record: ExtractionRecord) -> list[tuple[str, ...]]:
    seen: list[tuple[str, ...]] = []
    for block in record.blocks:
        if block.section_path not in seen:
            seen.append(block.section_path)
    return seen


_FILLER = "word " * 100


def test_extract_latex_recovers_titles_the_brace_free_pattern_missed() -> None:
    source = (
        "\\documentclass{revtex4}\n"
        "\\renewcommand\\section{\\@startsection{section}{1}{0pt}}\n"
        "\\begin{document}\n"
        "\\section{INTRODUCTION\\label{sec:intro}}\nIntro.\n"
        "% \\section{Commented out}\n"
        "\\section [Short]{Bounds on $\\mathcal{O}(n)$}\nBounds.\n"
        "\\subsection* {Proof\\footnote{See {the} appendix.}}\nProof.\n"
        "\\section{\\texorpdfstring{$\\alpha$ decay}{alpha decay}}\nDecay.\n"
        "\\end{document}\n"
    )
    record = _extract(source)
    assert _paths(record) == [
        ("Document",),
        ("INTRODUCTION",),
        ("Bounds on $\\mathcal{O}(n)$",),
        ("Bounds on $\\mathcal{O}(n)$", "Proof"),
        ("$\\alpha$ decay",),
    ]
    assert latex_section_rules(source) == {
        ("Document",): "default",
        ("INTRODUCTION",): "latex:section",
        ("Bounds on $\\mathcal{O}(n)$",): "latex:section",
        ("Bounds on $\\mathcal{O}(n)$", "Proof"): "latex:subsection*",
        ("$\\alpha$ decay",): "latex:section",
    }
    texts = _blocks_text(record, normalize_text(source))
    assert any(text.startswith("\nProof.") for text in texts.values())


def test_extract_latex_nests_sections_under_chapters_only_when_several() -> None:
    several = "\\chapter{First}\nA\n\\section{Inside}\nB\n\\chapter{Second}\nC\n"
    assert _paths(_extract(several)) == [("First",), ("First", "Inside"), ("Second",)]
    lone = "\\chapter{Contribution}\nA\n\\section{Intro}\nB\n\\section{End}\nC\n"
    assert _paths(_extract(lone)) == [("Contribution",), ("Intro",), ("End",)]


def test_extract_latex_falls_back_to_numbered_bold_headings() -> None:
    source = (
        "\\begin{document}\n{\\bf 1. Introduction}\n"
        + _FILLER
        + "\n\\noindent\\textbf{2 Methods}\n"
        + _FILLER
        + "\n\\textbf{1 Not a heading, a list}\n"
    )
    assert _paths(_extract(source)) == [
        ("Document",),
        ("Introduction",),
        ("Methods",),
    ]
    assert latex_section_rules(source)[("Methods",)] == "latex:bold-numbered-heading"

    # A section command wins; the fallback never mixes in.
    mixed = "\\section{Real}\n{\\bf 1. Introduction}\n" + _FILLER + "{\\bf 2. More}\n"
    assert _paths(_extract(mixed)) == [("Real",)]


def test_extract_pdf_cuts_pages_at_numbered_top_level_headings() -> None:
    pages = [
        PdfPage(1, "A Title\nAbstract text.\n1 Introduction\n" + _FILLER, False),
        PdfPage(2, "", True),
        PdfPage(
            3,
            _FILLER + "\n2 Related Work\n" + _FILLER + "\n3. Method\n" + _FILLER,
            False,
        ),
    ]
    record = _extract_pdf(pages)
    assert _paths(record) == [
        ("Body",),
        ("Introduction",),
        ("Related Work",),
        ("Method",),
    ]
    canonical = "\n".join(normalize_text(page.text) for page in pages if page.text)
    assert record.text_hash == sha256_hex(canonical.encode("utf-8"))
    texts = _blocks_text(record, canonical)
    first_text: dict[tuple[str, ...], str] = {}
    for block in record.blocks:
        first_text.setdefault(block.section_path, texts[block.block_id])
    assert first_text[("Introduction",)].startswith("1 Introduction\n")
    assert first_text[("Related Work",)].startswith("2 Related Work\n")
    assert first_text[("Method",)].startswith("3. Method\n")
    # Cutting at headings loses no readable text and keeps each page's locator.
    readable = [b for b in record.blocks if b.included_in_passages]
    assert (
        "\n".join(
            "".join(texts[b.block_id] for b in readable if b.locator.page_number == n)
            for n in (1, 3)
        )
        == canonical
    )
    assert [b.locator.page_number for b in record.blocks] == [1, 1, 2, 3, 3, 3]
    unreadable = [b for b in record.blocks if b.kind == "unreadable"]
    assert unreadable[0].section_path == ("Introduction",)
    assert pdf_section_rules(pages) == {
        ("Body",): "default",
        ("Introduction",): "pdf:numbered-heading",
        ("Related Work",): "pdf:numbered-heading",
        ("Method",): "pdf:numbered-heading",
    }


def test_extract_pdf_heading_heuristic_rejects_lists_tables_and_headers() -> None:
    text = (
        "1 We propose a method\n2 We show it works\n"  # adjacent: a list
        + _FILLER
        + "\n1 Adam 0.93\n"  # digits: a table row
        + _FILLER
        + "\n2 Running Title\n"
        + _FILLER
        + "\n2 Running Title\n"  # repeated: a running header
        + _FILLER
        + "\n1 Introduction\n"
        + _FILLER  # alone: one heading is no structure
    )
    pages = [PdfPage(1, text, False)]
    assert _paths(_extract_pdf(pages)) == [("Body",)]
    assert pdf_section_rules(pages) == {("Body",): "default"}
