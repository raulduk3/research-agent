"""SDD-MD-10: no optical character recognition among an image's pinned inputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_agent.models.manifest import MODEL_ID
from research_agent.reader.extract import PdfPage, extract_pdf
from research_agent.reader.extraction import (
    ALLOWED_EXTRACTORS,
    ExtractionPolicyError,
    ImageInputs,
    locked_packages,
    validate_extraction_policy,
)
from research_agent.reader.media import render_pages

LOCK = Path(__file__).resolve().parents[2] / "uv.lock"
PDF_HASH = "a" * 64


def _inputs(
    packages: tuple[str, ...] | None = None,
    model_ids: tuple[str, ...] = (MODEL_ID,),
    extractors: tuple[str, ...] = tuple(sorted(ALLOWED_EXTRACTORS)),
) -> ImageInputs:
    if packages is None:
        packages = locked_packages(LOCK.read_bytes())
    return ImageInputs(packages, model_ids, extractors)


def test_the_repository_image_inputs_pass() -> None:
    packages = locked_packages(LOCK.read_bytes())
    assert "torch" in packages and "transformers" in packages
    validate_extraction_policy(_inputs(packages))


def test_an_ocr_package_in_the_lock_file_is_refused() -> None:
    lock = LOCK.read_bytes() + (
        b'\n[[package]]\nname = "pytesseract"\nversion = "0.3.13"\n'
    )
    with pytest.raises(ExtractionPolicyError) as refused:
        validate_extraction_policy(_inputs(locked_packages(lock)))
    assert refused.value.findings == ("package pytesseract",)


@pytest.mark.parametrize(
    "package", ["easyocr", "paddleocr", "ocrmypdf", "tesserocr", "python-doctr"]
)
def test_each_named_recognition_engine_is_refused(package: str) -> None:
    with pytest.raises(ExtractionPolicyError):
        validate_extraction_policy(_inputs(("numpy", package)))


def test_an_ocr_model_identity_is_refused() -> None:
    with pytest.raises(ExtractionPolicyError) as refused:
        validate_extraction_policy(
            _inputs(model_ids=(MODEL_ID, "microsoft/trocr-base-printed"))
        )
    assert refused.value.findings == ("model microsoft/trocr-base-printed",)


def test_an_extractor_outside_the_allowlist_is_refused() -> None:
    with pytest.raises(ExtractionPolicyError) as refused:
        validate_extraction_policy(
            _inputs(extractors=("pdf_text_layer", "https://vision.example/read"))
        )
    assert refused.value.findings == ("extractor https://vision.example/read",)


def test_every_finding_is_reported_together() -> None:
    with pytest.raises(ExtractionPolicyError) as refused:
        validate_extraction_policy(
            _inputs(("easyocr",), ("facebook/nougat-base",), ("figure_ocr",))
        )
    assert refused.value.findings == (
        "package easyocr",
        "model facebook/nougat-base",
        "extractor figure_ocr",
    )


class _Renderer:
    def render(self, pdf_bytes: bytes, page_number: int) -> bytes:
        return b"\x89PNG-page-" + bytes([page_number])


def test_an_image_only_pdf_yields_missing_text_and_page_images() -> None:
    record = extract_pdf(
        "00000000-0000-4000-8000-000000000000",
        PDF_HASH,
        "f" * 64,
        [PdfPage(1, "", True), PdfPage(2, "", True)],
        "2026-01-01T00:00:00.000000Z",
    )
    assert record.coverage == "unavailable"
    assert record.text_codepoints == 0
    assert all(block.omission_reason == "unreadable" for block in record.blocks)
    pages = render_pages(
        pdf_bytes=b"%PDF-image-only",
        pdf_hash=PDF_HASH,
        page_numbers=(1, 2),
        renderer=_Renderer(),
    )
    assert [page.locator.page_number for page in pages] == [1, 2]
    assert all(page.untrusted for page in pages)
